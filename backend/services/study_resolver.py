"""
Study-level review resolver.

Collapses per-note LLM annotations into ONE value per patient per study
variable, computes cohort eligibility, and (optionally) auto-resolves
conflicts using a user-defined per-variable strategy.

Design mirrors ``services.diagnosis_resolver.DiagnosisResolver``:
  * grouped by patient (``p_id``)
  * pure/deterministic, returns plain dicts (no Pydantic at this layer)
  * human-confirmed state is preserved on recompute

The diagnosis variable (site + histology -> ICD-O-3 code) is NOT re-derived
here; it reads the existing ``session['patient_diagnoses']`` produced by the
diagnosis resolver, optionally applying the date strategy to settle conflicts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# small helpers (lazily reuse the export helpers so formatting stays identical)
# --------------------------------------------------------------------------

def _export_helpers():
    from routes.sessions import (
        _extract_value_from_annotation,
        _classify_absence,
        _normalize_date,
    )
    return _extract_value_from_annotation, _classify_absence, _normalize_date


def _pt_matches(session_pt: str, base: str) -> bool:
    """True if a session prompt_type key corresponds to a study base key.

    Tolerant of center suffixes: ``gender`` matches ``gender-int-sarc``,
    ``stage_at_diagnosis`` matches ``stage_at_diagnosis-int``.
    """
    s = (session_pt or "").lower()
    b = (base or "").lower()
    return bool(b) and (s == b or s.startswith(b + "-") or s.startswith(b + "_"))


def _ann_extracted_date(ann: dict) -> str:
    d = ann.get("extracted_date")
    if d:
        return d
    di = ann.get("date_info") or ann.get("date")
    if isinstance(di, dict):
        return di.get("date_value") or di.get("csv_date") or ""
    if isinstance(di, str):
        return di
    return ""


_LABEL_CODE_TAIL = re.compile(
    r"\s*\((?:ICD-O-3[:\- ].*?|\d{4}/\d[^)]*|C\d{2}(?:\.\d)?[^)]*)\)\s*\.?\s*$", re.I)


def _extract_llm_label(text: str) -> str:
    """Pull the descriptive label the LLM wrote, dropping the (often fake) code.

    "Histological type: Liposarcoma (8850/3)." -> "Liposarcoma"
    "Tumor site (Retroperitoneum): Retroperitoneum (C48.0)." -> "Retroperitoneum"
    """
    if not text:
        return ""
    t = str(text).strip()
    t = _LABEL_CODE_TAIL.sub("", t).strip()
    if ":" in t:
        t = t.split(":")[-1].strip()
    t = re.sub(r"\s*\(?\d{4}/\d\)?\.?$", "", t).strip()
    t = re.sub(r"\s*\(?C\d{2}(?:\.\d)?\)?\.?$", "", t).strip()
    return t.rstrip(".").strip()


# Negation cues (EN/IT/PL/SV) used to reject "no/without recurrence/progression"
# statements in the longitudinal event aggregate.
_EVENT_NEGATION = re.compile(
    r"\b(no|not|without|negativ\w*|nessun\w*|senza|assenza|brak|bez|ingen|inga|utan)\b",
    re.IGNORECASE)

# recurrencetype output-token -> DiseaseExtent field name (matches the recurrencetype
# entity_mapping the export already uses). "local" is the localised flag; the rest
# are distant metastatic sites. Order longest-first so "soft tissue" wins over none.
_DISEASE_EXTENT_SITES = [
    ("soft tissue", "softTissue"),
    ("lung", "lung"),
    ("bone", "metastasisatbone"),
    ("liver", "liver"),
    ("brain", "brain"),
    ("other", "otherViscera"),
]


def _sites_from_recurrencetype(value: str) -> List[str]:
    """Map a recurrencetype value ('metastatic lung, bone' / 'local') to the
    DiseaseExtent field names that are true."""
    v = (value or "").lower()
    sites = [field for token, field in _DISEASE_EXTENT_SITES if token in v]
    if not sites and re.search(r"\blocal\b", v):
        return ["localised"]
    return sites


def _episode_status(value: str) -> str:
    """recur_or_prog / recurrencetype value -> EpisodeEvent.diseaseStatus."""
    return "progression" if "progression" in (value or "").lower() else "recurrence"


def _ann_has_flags(ann: dict) -> bool:
    flags = ann.get("hallucination_flags")
    if isinstance(flags, list) and flags:
        return True
    icd = ann.get("icdo3_code")
    if isinstance(icd, dict) and icd.get("low_confidence"):
        return True
    return False


def _parse_ddmmyyyy(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", date_str.strip())
    if not m:
        return None
    day, month, year = (int(x) for x in m.groups())
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StudyResolver:
    """Resolve + validate study variables at the patient level."""

    def resolve_session(
        self,
        session: Dict[str, Any],
        study: Dict[str, Any],
        variables: List[Dict[str, Any]],
        conflict_config: Optional[Dict[str, Any]] = None,
        patient_diagnoses: Optional[Dict[str, Any]] = None,
        existing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        notes = session.get("notes", [])
        annotations = session.get("annotations", {})
        patient_diagnoses = patient_diagnoses or session.get("patient_diagnoses", {}) or {}
        existing = existing or {}
        conflict_config = conflict_config or {"enabled": False, "per_variable": {}}
        notes_by_id = {n.get("note_id", ""): n for n in notes}

        patient_notes: Dict[str, List[Dict]] = {}
        for note in notes:
            pid = note.get("p_id", "")
            if not pid:
                continue
            patient_notes.setdefault(pid, []).append(note)

        results: Dict[str, Dict[str, Any]] = {}
        for pid, p_notes in patient_notes.items():
            prev = existing.get(pid, {}) if isinstance(existing, dict) else {}
            prev_vars = prev.get("variables", {}) if isinstance(prev, dict) else {}

            var_reviews: Dict[str, Dict[str, Any]] = {}
            for var in variables:
                key = var["key"]
                prev_var = prev_vars.get(key, {})
                source = var.get("source")
                if source == "diagnosis":
                    review = self._resolve_diagnosis_variable(
                        var, pid, patient_diagnoses, notes_by_id, annotations, conflict_config
                    )
                    # Diagnosis PARTS are driven by the reviewer's picked codes in
                    # patient_diagnoses (authoritative); only the combination's
                    # confirm/reject lives in the study store.
                    if var.get("diagnosis_part") == "combination":
                        review = self._merge_previous(review, prev_var)
                elif source == "presence":
                    review = self._merge_previous(
                        self._resolve_presence_variable(var, p_notes, annotations), prev_var)
                elif source == "event_any":
                    review = self._merge_previous(
                        self._resolve_event_variable(var, p_notes, annotations), prev_var)
                else:
                    review = self._merge_previous(
                        self._resolve_annotation_variable(var, p_notes, annotations, conflict_config), prev_var)
                # Preserve any LLM baseline captured on a prior human confirm (the
                # confirm endpoint overwrites proposed_value), then stamp the
                # baseline + derived accept/edit/reject.
                if isinstance(prev_var, dict) and prev_var.get("llm_value") is not None:
                    review["llm_value"] = prev_var["llm_value"]
                self.annotate_review_action(review)
                var_reviews[key] = review

            eligibility = self._compute_eligibility(
                study, pid, p_notes, annotations, patient_diagnoses, notes_by_id
            )
            eligibility = self._merge_previous_eligibility(
                eligibility, prev.get("eligibility", {}) if isinstance(prev, dict) else {}
            )

            prev_events = prev.get("events") if isinstance(prev, dict) else None
            results[pid] = {
                "patient_id": pid,
                "eligibility": eligibility,
                "variables": var_reviews,
                "events": self.build_events(var_reviews, variables, prev_events),
                "timeline": self.build_timeline(var_reviews, variables),
                "overall_status": self._overall_status(eligibility, var_reviews, variables),
            }

        return results

    # ------------------------------------------------------------------
    # annotation-source variables
    # ------------------------------------------------------------------
    def _gather_candidates(self, var, p_notes, annotations) -> List[Dict[str, Any]]:
        extract_value, classify_absence, normalize_date = _export_helpers()
        bases = var.get("prompt_types") or ([var["prompt_type"]] if var.get("prompt_type") else [])
        cands: List[Dict[str, Any]] = []
        for note in p_notes:
            nid = note.get("note_id", "")
            if not nid:
                continue
            rtype = note.get("report_type", "") or ""
            ndate = note.get("date", "") or ""
            nanns = annotations.get(nid, {})
            if not isinstance(nanns, dict):
                continue
            for pt, ann in nanns.items():
                if not isinstance(ann, dict) or not any(_pt_matches(pt, b) for b in bases):
                    continue
                atext = ann.get("annotation_text", "") or ""
                if not atext.strip():
                    continue
                value = extract_value(atext, pt)
                if classify_absence(value):
                    continue
                # A negated annotation asserts the value is NOT present; treating
                # it as a positive value would fabricate conflicts or pick a wrong
                # value, so exclude it (mirrors _treatment_present).
                if ann.get("is_negated"):
                    continue
                edate = _ann_extracted_date(ann)
                if edate:
                    date, date_from = normalize_date(edate), "event"
                else:
                    date = normalize_date(ndate)
                    date_from = "note" if date else "none"
                cands.append({
                    "value": value,
                    "note_id": nid,
                    "prompt_type": pt,
                    "report_type": rtype,
                    "date": date,
                    "date_from": date_from,
                    "is_negated": ann.get("is_negated"),
                    "has_flags": _ann_has_flags(ann),
                    "reasoning": ann.get("reasoning"),
                    "annotation_text": atext.strip()[:1000],
                    "evidence_spans": ann.get("evidence_spans") or [],
                    "snippet": atext.strip()[:400],
                })
        return cands

    def _resolve_annotation_variable(self, var, p_notes, annotations, conflict_config) -> Dict[str, Any]:
        cands = self._gather_candidates(var, p_notes, annotations)
        review = {
            "key": var["key"],
            "label": var.get("label", var["key"]),
            "source": "annotation",
            "proposed_value": None,
            "value": None,
            "status": "needs_review",
            "conflict": False,
            "candidates": cands,
            "source_note_ids": sorted({c["note_id"] for c in cands}),
            "source_prompt_type": cands[0]["prompt_type"] if cands else var.get("prompt_type"),
            "evidence_snippet": cands[0]["snippet"] if cands else None,
            "reasoning": cands[0].get("reasoning") if cands else None,
            "auto_resolved": False,
            "resolution_rule": None,
            "review_reasons": [],
            "reviewed_by": None,
            "reviewed_at": None,
            "note": None,
        }

        if not cands:
            review["review_reasons"] = ["No value extracted from any note"]
            return review

        distinct = sorted({c["value"].strip().lower() for c in cands})
        if len(distinct) == 1:
            review["proposed_value"] = cands[0]["value"]
            review["status"] = "auto"
            return review

        # --- conflict ---
        review["conflict"] = True
        review["review_reasons"] = [
            f"{len(distinct)} different values across notes: "
            + ", ".join(sorted({c['value'] for c in cands}))
        ]
        # default suggestion shown to the human = most recent note value;
        # when no candidate has a parseable date, fall back to the most frequent
        # value (then first) rather than an arbitrary note-iteration-order pick.
        suggested = self._pick_by_date(cands, "latest") or self._most_common(cands)
        review["proposed_value"] = suggested["value"]

        chosen, rule, reason = self._auto_resolve(var, cands, conflict_config)
        if chosen is not None:
            review["value"] = chosen["value"]
            review["proposed_value"] = chosen["value"]
            review["status"] = "confirmed"
            review["auto_resolved"] = True
            review["resolution_rule"] = rule
            review["reviewed_by"] = "rule"
            review["reviewed_at"] = _now()
            review["review_reasons"].append(reason)
        return review

    # ------------------------------------------------------------------
    # presence (yes/no + timing) and longitudinal (any-event) variables
    # ------------------------------------------------------------------
    @staticmethod
    def _blank_review(var, source, cands):
        return {
            "key": var["key"], "label": var.get("label", var["key"]), "source": source,
            "proposed_value": None, "value": None, "status": "needs_review", "conflict": False,
            "candidates": cands, "source_note_ids": sorted({c["note_id"] for c in cands if c.get("note_id")}),
            "source_prompt_type": cands[0]["prompt_type"] if cands else var.get("prompt_type"),
            "evidence_snippet": cands[0]["snippet"] if cands else None,
            "reasoning": cands[0].get("reasoning") if cands else None,
            "auto_resolved": False, "resolution_rule": None, "review_reasons": [],
            "reviewed_by": None, "reviewed_at": None, "note": None,
            "llm_label": None, "llm_code": None, "selected_code": None, "combination_valid": None,
        }

    @staticmethod
    def _detect_timing(cands):
        text = " ".join(((c.get("annotation_text") or "") + " " + (c.get("value") or "")) for c in cands).lower()
        if any(w in text for w in ["neoadjuvant", "neo-adjuvant", "pre-operative", "preoperative",
                                    "before surgery", "prima dell", "przedoperacyjn", "neoadjuwant", "neoadjuvant"]):
            return "neoadjuvant"
        if any(w in text for w in ["adjuvant", "post-operative", "postoperative", "after surgery",
                                   "dopo l", "pooperacyjn", "adjuwant"]):
            return "adjuvant"
        return ""

    def _resolve_presence_variable(self, var, p_notes, annotations) -> Dict[str, Any]:
        """Yes/No from the presence of any non-absent, non-negated annotation for
        the prompt (optionally with neoadjuvant/adjuvant timing)."""
        cands = self._gather_candidates(var, p_notes, annotations)
        review = self._blank_review(var, "presence", cands)
        review["status"] = "auto"
        if cands:
            timing = self._detect_timing(cands) if var.get("timing") else ""
            review["proposed_value"] = "Yes" + (f" ({timing})" if timing else "")
            review["review_reasons"] = [f"{len(cands)} matching annotation(s) found"]
        else:
            review["proposed_value"] = "No"
            review["review_reasons"] = ["No matching annotation found"]
        return review

    def _resolve_event_variable(self, var, p_notes, annotations) -> Dict[str, Any]:
        """Longitudinal any-event aggregate (e.g. metastasis/recurrence over time):
        Yes if any annotation matches a positive value; reports first date + kinds."""
        cands = self._gather_candidates(var, p_notes, annotations)
        review = self._blank_review(var, "event_any", cands)
        review["status"] = "auto"
        positives = [p.lower() for p in (var.get("positive_values") or [])]

        def _is_positive(c):
            text = (c.get("value") or "")
            tl = text.lower()
            if positives and not any(p in tl for p in positives):
                return False
            # reject explicit negations of the event ("no/without progression", multilingual)
            if _EVENT_NEGATION.search(text):
                return False
            return True

        hits = [c for c in cands if _is_positive(c)]
        if hits:
            dated = [c for c in hits if _parse_ddmmyyyy(c.get("date", ""))]
            first = min(dated, key=lambda c: _parse_ddmmyyyy(c["date"]))["date"] if dated else None
            kinds = "; ".join(sorted({c["value"] for c in hits}))
            review["proposed_value"] = "Yes" + (f" — first {first}" if first else "") + (f" ({kinds})" if kinds else "")
            review["candidates"] = hits + [c for c in cands if c not in hits]
            review["review_reasons"] = [f"{len(hits)} event(s) over time"]
        else:
            review["proposed_value"] = "No"
            review["review_reasons"] = ["No recurrence/metastasis event found"]
        return review

    # ------------------------------------------------------------------
    # patient clinical timeline (diagnosis -> status / metastasis / treatments)
    # ------------------------------------------------------------------
    @staticmethod
    def _earliest_candidate(cands):
        dated = [c for c in cands if _parse_ddmmyyyy(c.get("date") or "")]
        if dated:
            return min(dated, key=lambda c: _parse_ddmmyyyy(c["date"]))
        return cands[0] if cands else None

    @staticmethod
    def _first_contact_candidate(variables_state, variables_cfg):
        """Earliest dated candidate across all NON-event variables ≈ first documented
        clinical contact — the diagnosis anchor. Event variables (recur/metastasis)
        are excluded because they can carry historical/over-derived dates that
        predate the first contact and must not pull the anchor backwards."""
        event_keys = {v["key"] for v in variables_cfg
                      if (v.get("timeline") or {}).get("category") in ("status", "metastasis")}
        pool = [c for k, vr in variables_state.items() if k not in event_keys
                for c in ((vr or {}).get("candidates") or [])]
        return StudyResolver._earliest_candidate(pool)

    @staticmethod
    def _event_label_detail(category, value):
        """Map a status/metastasis candidate value -> (label, short detail)."""
        v = (value or "").strip()
        if category == "metastasis":
            m = re.search(r"metastatic\s+(.+)", v, re.I)
            detail = (m.group(1).strip().rstrip(".") if m else None) or None
            return "Metastasis", detail
        vl = v.lower()
        if "progression" in vl:
            return "Progression", None
        if "recurrence" in vl or "recurred" in vl or "relapse" in vl:
            return "Recurrence", None
        return (v[:40] or "Event"), None

    @staticmethod
    def build_timeline(variables_state: Dict[str, Any], variables_cfg: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Assemble a patient's chronological clinical timeline from the resolved
        study variables. Only variables carrying a ``timeline`` config block
        contribute; category drives how the event(s) are extracted:

          diagnosis   -> one anchor event (earliest dated candidate)
          status      -> one event per positive candidate (recurrence/progression)
          metastasis  -> one event per positive candidate (metastatic site set)
          treatment   -> one event when the treatment is present

        ``confirmed`` is variable-level: an event is confirmed only when a human
        (not a rule) confirmed its underlying variable.
        """
        cfg_by_key = {v["key"]: v for v in variables_cfg}
        events: List[Dict[str, Any]] = []
        for key, vr in variables_state.items():
            vcfg = cfg_by_key.get(key) or {}
            tcfg = vcfg.get("timeline")
            if not tcfg:
                continue
            category = tcfg.get("category")
            if not category:
                continue
            confirmed = (vr.get("status") == "confirmed") and not vr.get("auto_resolved")
            reviewed_by = vr.get("reviewed_by") if confirmed else None
            cands = vr.get("candidates") or []

            if category in ("status", "metastasis"):
                positives = [p.lower() for p in (vcfg.get("positive_values") or [])]
                seen = set()
                for c in cands:
                    val = (c.get("value") or "").strip()
                    if not val:
                        continue
                    tl = val.lower()
                    if positives and not any(p in tl for p in positives):
                        continue
                    if _EVENT_NEGATION.search(val):
                        continue
                    label, detail = StudyResolver._event_label_detail(category, val)
                    dedup = (c.get("date"), label, detail)
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    events.append({
                        "date": c.get("date"), "date_from": c.get("date_from", "event"),
                        "category": category, "label": label, "detail": detail,
                        "confirmed": confirmed, "reviewed_by": reviewed_by, "variable_key": key,
                    })
            elif category == "treatment":
                present = bool(vr.get("value")) or str(vr.get("proposed_value") or "").strip().lower().startswith("yes")
                if not present:
                    continue
                c = StudyResolver._earliest_candidate(cands) or {}
                pv = str(vr.get("value") or vr.get("proposed_value") or "")
                m = re.search(r"\((neoadjuvant|adjuvant)\)", pv, re.I)
                # Timeline nodes show the plain treatment TYPE, not the study
                # variable's "... at diagnosis" wording — that is wrong for a
                # treatment dated after a relapse (relabelled post-loop below).
                label = re.sub(r"\s+at diagnosis$", "", vcfg.get("label", key), flags=re.I)
                events.append({
                    "date": c.get("date"), "date_from": c.get("date_from", "none"),
                    "category": "treatment", "label": label,
                    "detail": m.group(1).lower() if m else None,
                    "confirmed": confirmed, "reviewed_by": reviewed_by, "variable_key": key,
                })
            elif category == "diagnosis":
                # Anchor the diagnosis at first documented contact (earliest non-event
                # note), not the histology-resolution note — the latter can be a much
                # later pathology note, which would falsely flag legitimate events.
                # Fall back to the earliest diagnosis-part candidate if needed.
                fc = StudyResolver._first_contact_candidate(variables_state, variables_cfg)
                if fc is None:
                    pool = list(cands)
                    for dv in variables_cfg:
                        if dv.get("source") == "diagnosis" and dv["key"] != key:
                            pool.extend((variables_state.get(dv["key"]) or {}).get("candidates") or [])
                    fc = StudyResolver._earliest_candidate(pool) or {}
                events.append({
                    "date": fc.get("date"), "date_from": fc.get("date_from", "none"),
                    "category": "diagnosis", "label": tcfg.get("label", "Diagnosis"),
                    "detail": vr.get("value") or vr.get("proposed_value"),
                    "confirmed": confirmed, "reviewed_by": reviewed_by, "variable_key": key,
                })

        # A treatment dated AFTER the first GENUINE recurrence/progression is not
        # initial ("at diagnosis") treatment — mark it as given for relapsed/
        # progressive disease. Count only relapses strictly AFTER first contact:
        # an event at/before the diagnosis is anomalous (a pre-diagnosis mention or
        # the initial presentation mislabelled) and must not shift the threshold.
        _fc = StudyResolver._first_contact_candidate(variables_state, variables_cfg)
        _fc_date = _parse_ddmmyyyy((_fc or {}).get("date") or "")
        relapse = [d for e in events
                   if e["category"] in ("status", "metastasis")
                   for d in [_parse_ddmmyyyy(e.get("date") or "")]
                   if d and (not _fc_date or d > _fc_date)]
        first_relapse = min(relapse) if relapse else None
        if first_relapse:
            for e in events:
                if e["category"] == "treatment":
                    ed = _parse_ddmmyyyy(e.get("date") or "")
                    if ed and ed > first_relapse:
                        e["label"] = e["label"] + " (post-relapse)"
                        e["detail"] = "for relapsed/progressive disease" if not e.get("detail") \
                            else f"{e['detail']} · post-relapse"

        # The diagnosis keeps its real date (earliest histology/topography note ≈
        # first documented contact). We deliberately DO NOT move it onto an event's
        # date: an event that predates the diagnosis is anomalous (an over-derived
        # recurrence or a historical mention), so it is flagged on the event itself
        # (see build_events + resolve_session) rather than corrupting the anchor.
        def _sort_key(e):
            return (0 if e["category"] == "diagnosis" else 1,
                    _parse_ddmmyyyy(e.get("date") or "") or datetime.max)
        events.sort(key=_sort_key)
        return events

    # ------------------------------------------------------------------
    # diagnosis-source variable (reads patient_diagnoses)
    # ------------------------------------------------------------------
    def _resolve_diagnosis_variable(self, var, pid, patient_diagnoses, notes_by_id, annotations, conflict_config) -> Dict[str, Any]:
        """Build one of the three diagnosis parts (histology / topography /
        combination) from the resolved patient diagnosis."""
        part = var.get("diagnosis_part", "combination")
        diag = patient_diagnoses.get(pid, {}) if isinstance(patient_diagnoses, dict) else {}
        status = diag.get("status", "skipped")
        resolved = diag.get("resolved_code") or {}

        def _code_cands(codes, kind):
            out = []
            for c in codes:
                nid = c.get("note_id", "")
                note = notes_by_id.get(nid, {})
                pt = c.get("prompt_type", kind)
                ann = (annotations.get(nid, {}) or {}).get(pt, {}) if isinstance(annotations, dict) else {}
                if not isinstance(ann, dict):
                    ann = {}
                out.append({
                    "value": f"{c.get('code', '')} {c.get('description', '')}".strip(),
                    "note_id": nid,
                    "prompt_type": pt,
                    "report_type": note.get("report_type", "") if note else "",
                    "date": self._note_date(note),
                    "date_from": "note" if self._note_date(note) else "none",
                    "code": c.get("code", ""),
                    "reasoning": ann.get("reasoning"),
                    "annotation_text": (ann.get("annotation_text") or "").strip()[:1000] or None,
                    "evidence_spans": ann.get("evidence_spans") or [],
                })
            return out

        review = {
            "key": var["key"], "label": var.get("label", var["key"]), "source": "diagnosis",
            "proposed_value": None, "value": None, "status": "needs_review", "conflict": False,
            "candidates": [], "source_note_ids": [], "source_prompt_type": "diagnosis",
            "evidence_snippet": None, "reasoning": None, "auto_resolved": False,
            "resolution_rule": None, "review_reasons": [], "reviewed_by": None,
            "reviewed_at": None, "note": None,
        }

        if part in ("histology", "topography"):
            codes = diag.get("histology_codes" if part == "histology" else "topography_codes", []) or []
            candidates = _code_cands(codes, part)
            review["candidates"] = candidates
            review["source_note_ids"] = sorted({c["note_id"] for c in candidates if c["note_id"]})
            # The LLM's descriptive LABEL is trusted (drives the condition-file search);
            # its CODE is not — reviewers pick a real code.
            review["llm_label"] = next(
                (_extract_llm_label(c.get("annotation_text")) for c in candidates
                 if _extract_llm_label(c.get("annotation_text"))), None)
            review["llm_code"] = next((c["code"] for c in candidates if c.get("code")), None)

            # Reviewer's chosen real code (or explicit rejection) is authoritative.
            ud = (diag.get("user_diagnosis") or {}).get(part) or {}
            if ud.get("rejected"):
                review.update({"status": "rejected", "reviewed_by": ud.get("reviewer") or "user",
                               "reviewed_at": ud.get("at")})
                return review
            if ud.get("code"):
                disp = f"{ud['code']} — {ud.get('label', '')}".strip(" —")
                review.update({"proposed_value": disp, "value": disp, "status": "confirmed",
                               "selected_code": ud["code"], "reviewed_by": ud.get("reviewer") or "user",
                               "reviewed_at": ud.get("at")})
                return review

            # Not yet corrected: surface the LLM code candidates so the reviewer has
            # a starting point (the card will auto-search the label for real codes).
            distinct = {c.get("code") for c in candidates if c.get("code")}
            if len(distinct) == 1:
                review["proposed_value"] = candidates[0]["value"]
            elif len(distinct) > 1:
                review["proposed_value"] = candidates[0]["value"]
                review["conflict"] = True
                review["review_reasons"] = [f"Multiple {part} codes from the LLM: " + ", ".join(sorted(distinct))]
            elif review["llm_label"]:
                review["review_reasons"] = [f"Pick the real {part} code for '{review['llm_label']}'"]
            else:
                review["review_reasons"] = [f"No {part} extracted"]
            return review

        # combination: the final morphology-topography ICD-O-3 diagnosis code
        query = resolved.get("query_code")
        disp = (f"{query} — {resolved.get('name', '')}".strip(" —") or query) if query else None
        review["proposed_value"] = disp
        review["combination_valid"] = (resolved.get("validation") or {}).get("combination_valid")
        if query:
            # Assembled from the parts, but shown as a proposal — the reviewer must
            # eyeball the combined diagnosis and Validate it (a human confirm is
            # preserved via _merge_previous).
            review["status"] = "auto"
        else:
            review["review_reasons"] = ["Confirm histology & topography codes to assemble the diagnosis code"]
        return review

    # ------------------------------------------------------------------
    # conflict auto-resolution strategies
    # ------------------------------------------------------------------
    def _auto_resolve(self, var, cands, conflict_config):
        """Return (chosen_candidate | None, rule_name | None, reason)."""
        if not conflict_config or not conflict_config.get("enabled"):
            return None, None, "Auto-resolution disabled"
        per_var = (conflict_config.get("per_variable") or {}).get(var["key"], {})
        strategy = per_var.get("strategy", "none")

        if strategy == "report_type_ranking":
            ranking = per_var.get("ranking", []) or []
            chosen = self._resolve_by_ranking(cands, ranking)
            if chosen is not None:
                return chosen, "report_type_ranking", (
                    f"Auto-resolved to '{chosen['value']}' from report type "
                    f"'{chosen['report_type']}' (ranking)"
                )
            return None, None, "Ranking could not decide — sent to manual review"

        if strategy == "date":
            pref = per_var.get("date_pref", "earliest")
            chosen = self._resolve_by_date_strict(cands, pref)
            if chosen is not None:
                return chosen, f"date_{pref}", (
                    f"Auto-resolved to '{chosen['value']}' from the {pref} note "
                    f"({chosen['date']})"
                )
            return None, None, "Date rule could not decide — sent to manual review"

        return None, None, "No strategy configured"

    @staticmethod
    def _resolve_by_ranking(cands, ranking):
        """Walk the ranking; first present report type with a single distinct
        value wins. Otherwise None (straight to manual)."""
        by_type: Dict[str, List[dict]] = {}
        for c in cands:
            by_type.setdefault((c.get("report_type") or "").lower(), []).append(c)
        for rt in ranking:
            group = by_type.get((rt or "").lower())
            if not group:
                continue
            distinct = {c["value"].strip().lower() for c in group}
            if len(distinct) == 1:
                return group[0]
            return None  # top present type disagrees -> manual
        return None  # no ranked type present -> manual

    def _resolve_by_date_strict(self, cands, pref):
        """Pick the earliest/latest-dated value only if that extreme is
        unambiguous; otherwise None (manual). Tie-detection compares parsed
        dates, so different formatting of the same day (1/1/2020 vs 01/01/2020)
        is still recognised as the same date."""
        dated = [c for c in cands if _parse_ddmmyyyy(c.get("date", ""))]
        if not dated:
            return None
        dated.sort(key=lambda c: _parse_ddmmyyyy(c["date"]))
        extreme = dated[0] if pref == "earliest" else dated[-1]
        extreme_dt = _parse_ddmmyyyy(extreme["date"])
        same_date = [c for c in dated if _parse_ddmmyyyy(c["date"]) == extreme_dt]
        if len({c["value"].strip().lower() for c in same_date}) == 1:
            return extreme
        return None  # tie on the extreme date -> manual

    @staticmethod
    def _pick_by_date(cands, pref):
        dated = [c for c in cands if _parse_ddmmyyyy(c.get("date", ""))]
        if not dated:
            return None
        dated.sort(key=lambda c: _parse_ddmmyyyy(c["date"]))
        return dated[0] if pref == "earliest" else dated[-1]

    @staticmethod
    def _most_common(cands):
        """Return the candidate whose value is most frequent (ties -> first)."""
        from collections import Counter
        counts = Counter(c["value"].strip().lower() for c in cands)
        best = counts.most_common(1)[0][0] if counts else None
        for c in cands:
            if c["value"].strip().lower() == best:
                return c
        return cands[0]

    @staticmethod
    def _note_date(note):
        if not note:
            return None
        from routes.sessions import _normalize_date
        d = note.get("date", "")
        return _normalize_date(d) if d else None

    # ------------------------------------------------------------------
    # optional date-based resolution of conflicting diagnosis codes
    # ------------------------------------------------------------------
    def apply_diagnosis_date_strategy(
        self, patient_diagnoses: Dict[str, Any], notes_by_id: Dict[str, Any], pref: str = "earliest"
    ) -> Dict[str, Any]:
        """Settle ``needs_review`` diagnoses by picking the earliest/latest dated
        histology + topography code and validating the combination. Manual and
        already-resolved entries are left untouched."""
        try:
            from lib.icdo3_csv_indexer import get_csv_indexer
            indexer = get_csv_indexer()
        except Exception:
            indexer = None
        if indexer is None:
            return patient_diagnoses

        for pid, diag in patient_diagnoses.items():
            if not isinstance(diag, dict) or diag.get("status") != "needs_review":
                continue
            h = self._pick_code_by_date(diag.get("histology_codes", []) or [], notes_by_id, pref)
            t = self._pick_code_by_date(diag.get("topography_codes", []) or [], notes_by_id, pref)
            if not h or not t:
                continue
            validation = indexer.validate_combination(h["code"], t["code"])
            if not validation.get("valid"):
                continue
            row = validation.get("row_data", {}) or {}
            diag.update({
                "status": "auto_resolved",
                "review_reasons": [f"Auto-resolved by {pref}-date rule"],
                "resolved_code": {
                    "query_code": validation["query_code"],
                    "morphology_code": h["code"],
                    "topography_code": t["code"],
                    "name": validation.get("name", ""),
                    "source": "auto",
                    "user_selected": False,
                    "validation": {
                        "morphology_valid": True,
                        "topography_valid": True,
                        "combination_valid": True,
                    },
                    "created_at": _now(),
                },
                "csv_id": str(row.get("ID", "")) if row else None,
                "resolved_at": _now(),
                "resolved_by": f"rule:date_{pref}",
            })
        return patient_diagnoses

    def _pick_code_by_date(self, codes, notes_by_id, pref):
        dated = []
        for c in codes:
            note = notes_by_id.get(c.get("note_id", ""), {})
            d = self._note_date(note)
            if _parse_ddmmyyyy(d or ""):
                dated.append((d, c))
        if not dated:
            return None
        dated.sort(key=lambda x: _parse_ddmmyyyy(x[0]))
        extreme_dt = _parse_ddmmyyyy((dated[0] if pref == "earliest" else dated[-1])[0])
        same = [c for (d, c) in dated if _parse_ddmmyyyy(d) == extreme_dt]
        if len({c["code"] for c in same}) == 1:
            return same[0]
        return None

    # ------------------------------------------------------------------
    # cohort eligibility
    # ------------------------------------------------------------------
    def _compute_eligibility(self, study, pid, p_notes, annotations, patient_diagnoses, notes_by_id) -> Dict[str, Any]:
        cohort = study.get("cohort", {})
        diag = patient_diagnoses.get(pid, {}) if isinstance(patient_diagnoses, dict) else {}
        resolved = diag.get("resolved_code") or {}
        # The histology/topography criteria are decided from the RESOLVED diagnosis
        # code only. An unresolved (needs_review/skipped) diagnosis leaves the
        # criterion unknown (None) -> the patient needs review, rather than being
        # auto-included off one matching code among conflicting candidates.
        is_resolved = diag.get("status") in ("auto_resolved", "manually_resolved") and bool(resolved)

        # ---- histology criterion (3-state: True=auto-include / None=review / False=exclude) ----
        hist_cfg = cohort.get("histology", {})
        auto_prefixes = set(hist_cfg.get("morphology_prefixes", []))
        review_prefixes = set(hist_cfg.get("review_prefixes", []))
        morph_codes = [resolved["morphology_code"]] if resolved.get("morphology_code") else \
            [c["code"] for c in (diag.get("histology_codes") or []) if c.get("code")]
        hist_ok, hist_extra = None, ""
        if is_resolved and resolved.get("morphology_code"):
            p = resolved["morphology_code"].split("/")[0]
            if p in auto_prefixes:
                hist_ok = True
            elif p in review_prefixes:
                hist_ok, hist_extra = None, " — other liposarcoma variant, confirm eligibility"
            else:
                hist_ok = False

        # ---- topography criterion (3-state) ----
        topo_cfg = cohort.get("topography", {})
        auto_topo = set(topo_cfg.get("codes", []))
        review_topo = set(topo_cfg.get("review_codes", []))
        topo_codes = [resolved["topography_code"]] if resolved.get("topography_code") else \
            [c["code"] for c in (diag.get("topography_codes") or []) if c.get("code")]
        topo_ok, topo_extra = None, ""
        if is_resolved and resolved.get("topography_code"):
            tc = resolved["topography_code"]
            if tc in auto_topo:
                topo_ok = True
            elif tc in review_topo:
                topo_ok, topo_extra = None, " — C49.x can be non-retroperitoneal, confirm site"
            else:
                topo_ok = False

        # ---- treatment criterion ----
        treat_cfg = cohort.get("treatment", {})
        treat_pt = treat_cfg.get("prompt_type", "")
        treat_ok = self._treatment_present(treat_pt, p_notes, annotations)

        reasons = []
        reasons.append(self._criterion_reason("Histology", hist_cfg.get("label", "match"), hist_ok, morph_codes) + hist_extra)
        reasons.append(self._criterion_reason("Topography", topo_cfg.get("label", "match"), topo_ok, topo_codes) + topo_extra)
        reasons.append(self._treatment_reason(treat_cfg.get("label", "Treatment"), treat_ok))

        criteria = {"histology": hist_ok, "topography": topo_ok, "treatment": treat_ok}
        if hist_ok is False or topo_ok is False or treat_ok is False:
            auto = "excluded"
        elif hist_ok and topo_ok and treat_ok:
            auto = "included"
        else:
            auto = "needs_review"

        return {
            "decision": auto,
            "auto_decision": auto,
            "confirmed": False,
            "reasons": reasons,
            "criteria": criteria,
            "decided_by": None,
            "decided_at": None,
        }

    @staticmethod
    def _treatment_present(treat_pt, p_notes, annotations) -> Optional[bool]:
        if not treat_pt:
            return None
        extract_value, classify_absence, _ = _export_helpers()
        found_any = False
        found_present = False
        for note in p_notes:
            nid = note.get("note_id", "")
            nanns = annotations.get(nid, {})
            if not isinstance(nanns, dict):
                continue
            for pt, ann in nanns.items():
                if not isinstance(ann, dict) or not _pt_matches(pt, treat_pt):
                    continue
                found_any = True
                atext = ann.get("annotation_text", "") or ""
                if not atext.strip():
                    continue
                # Classify absence on the EXTRACTED value (mirrors _gather_candidates):
                # classifying the raw template text both misses prefixed absences
                # ("Surgery type: None.") and false-matches absence phrases that
                # only appear inside the label.
                value = extract_value(atext, pt)
                if value.strip() and not classify_absence(value) and not ann.get("is_negated"):
                    found_present = True
        if found_present:
            return True
        if found_any:
            return False
        return None

    @staticmethod
    def _criterion_reason(name, label, ok, codes):
        codes_str = (" [" + ", ".join(codes) + "]") if codes else ""
        if ok is True:
            return f"{name}: {label} ✓{codes_str}"
        if ok is False:
            return f"{name}: not {label} ✗{codes_str}"
        return f"{name}: unknown (no resolved code){codes_str}"

    @staticmethod
    def _treatment_reason(label, ok):
        if ok is True:
            return f"{label}: found ✓"
        if ok is False:
            return f"{label}: not found ✗"
        return f"{label}: unknown (not annotated)"

    # ------------------------------------------------------------------
    # preservation of human decisions
    # ------------------------------------------------------------------
    @staticmethod
    def _is_human(var_dict) -> bool:
        return bool(var_dict.get("reviewed_by")) and var_dict.get("reviewed_by") != "rule" \
            and not var_dict.get("auto_resolved")

    # ------------------------------------------------------------------
    # LLM-vs-human evaluation (accept / edit / reject of the model's proposals)
    # ------------------------------------------------------------------
    @staticmethod
    def _norm_val(s) -> str:
        return (str(s) if s is not None else "").strip().casefold()

    @staticmethod
    def classify_review_action(var: Dict[str, Any]) -> Optional[str]:
        """How a HUMAN reviewer acted on the LLM's proposal for one variable:
          'accept' -> confirmed the LLM's value unchanged
          'edit'   -> confirmed a value different from the LLM's (correction)
          'reject' -> marked the LLM's value not usable
        Returns None when the decision was not made by a human (pending / auto /
        rule-resolved), so only genuine human judgements are measured."""
        status = var.get("status")
        if status not in ("confirmed", "rejected") or not StudyResolver._is_human(var):
            return None
        if status == "rejected":
            return "reject"
        # diagnosis parts: the LLM's CODE is what is validated (its label is trusted,
        # its code usually hallucinated) -> accept only if the picked code == LLM code
        if var.get("source") == "diagnosis" and var.get("selected_code"):
            return "accept" if StudyResolver._norm_val(var.get("selected_code")) == \
                StudyResolver._norm_val(var.get("llm_code")) else "edit"
        # the LLM proposed nothing but the human supplied a value -> a miss (false negative)
        if not StudyResolver._norm_val(var.get("llm_value")) and StudyResolver._norm_val(var.get("value")):
            return "missed"
        return "accept" if StudyResolver._norm_val(var.get("value")) == \
            StudyResolver._norm_val(var.get("llm_value")) else "edit"

    @staticmethod
    def annotate_review_action(var: Dict[str, Any]) -> Dict[str, Any]:
        """Stamp llm_value baseline (once) + the derived review_action on a variable."""
        if var.get("llm_value") is None:
            var["llm_value"] = var.get("proposed_value")
        var["review_action"] = StudyResolver.classify_review_action(var)
        return var

    @staticmethod
    def evaluation_summary(patients: Dict[str, Any], variables: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate human accept/edit/reject decisions across all patients into an
        LLM-evaluation report (overall + per variable)."""
        order = [v["key"] for v in variables]
        meta = {
            v["key"]: {
                "label": v.get("label", v["key"]),
                "prompt_type": v.get("prompt_type") or (v.get("prompt_types") or [None])[0] or v.get("source"),
                "group": v.get("group", "Other"),
            }
            for v in variables
        }
        EVENTS_KEY = "__events__"
        meta[EVENTS_KEY] = {"label": "Outcome events (recurrence/progression/metastasis)",
                            "prompt_type": "recur_or_prog+recurrencetype", "group": "Outcome"}
        BUCKETS = ("accept", "edit", "reject", "missed")

        def _blank():
            return {b: 0 for b in BUCKETS}

        per_var: Dict[str, Dict[str, int]] = {}
        overall = _blank()
        reviewed_patients = 0
        for p in (patients or {}).values():
            touched = False
            for key, var in (p.get("variables") or {}).items():
                action = StudyResolver.classify_review_action(var)
                if not action:
                    continue
                touched = True
                per_var.setdefault(key, _blank())[action] += 1
                overall[action] += 1
            # outcome events (decision: measured too; a manual-added event = 'missed')
            for ev in (p.get("events") or []):
                action = StudyResolver.classify_event_action(ev)
                if not action:
                    continue
                touched = True
                per_var.setdefault(EVENTS_KEY, _blank())[action] += 1
                overall[action] += 1
            if touched:
                reviewed_patients += 1

        def _stat(key: str, counts: Dict[str, int], m: Dict[str, Any]) -> Dict[str, Any]:
            reviewed = sum(counts[b] for b in BUCKETS)
            r = (lambda n: round(n / reviewed, 4) if reviewed else 0.0)
            out = {"key": key, "label": m.get("label", key), "prompt_type": m.get("prompt_type"),
                   "group": m.get("group", ""), "reviewed": reviewed}
            for b in BUCKETS:
                out[b] = counts[b]
                out[f"{b}_rate"] = r(counts[b])
            return out

        rows = [_stat(k, per_var[k], meta.get(k, {})) for k in order if k in per_var]
        if EVENTS_KEY in per_var:
            rows.append(_stat(EVENTS_KEY, per_var[EVENTS_KEY], meta[EVENTS_KEY]))
        rows += [_stat(k, per_var[k], meta.get(k, {})) for k in per_var
                 if k not in order and k != EVENTS_KEY]
        return {
            "overall": _stat("__overall__", overall, {"label": "All variables", "group": ""}),
            "per_variable": rows,
            "reviewed_patients": reviewed_patients,
        }

    @staticmethod
    def finalize_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Re-derive each event's review_action and re-sort by date. Used after an
        in-place mutation (confirm / drop / edit / add) so the stored list stays consistent."""
        for e in events:
            e["review_action"] = StudyResolver.classify_event_action(e)
        events.sort(key=lambda e: (_parse_ddmmyyyy(e.get("date") or "") or datetime.max))
        return events

    # ------------------------------------------------------------------
    # longitudinal outcome events (EpisodeEvent + linked DiseaseExtent)
    # ------------------------------------------------------------------
    @staticmethod
    def _event_key(date: Optional[str], note_id: str) -> str:
        """Stable key for matching an assembled event to a prior human decision
        across recomputes: dated events merge by date (across both prompts and all
        notes); undated events stay distinct per note so they are not collapsed.
        Derived from the LLM annotation only, so a human edit never changes it."""
        return date if date else f"note:{note_id}"

    @staticmethod
    def _event_signature(ev: Dict[str, Any]) -> str:
        return f"{ev.get('disease_status')}|{ev.get('date')}|{','.join(sorted(ev.get('sites') or []))}"

    @staticmethod
    def _assemble_llm_events(variables_state: Dict[str, Any], variables_cfg: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Assemble the LLM's outcome-event list from the status (recur_or_prog)
        and metastasis (recurrencetype) variables: one EpisodeEvent per date, its
        diseaseStatus taken from recur_or_prog and its DiseaseExtent sites from
        recurrencetype (both are prompts on the same note describing one event)."""
        status_keys = [v["key"] for v in variables_cfg if (v.get("timeline") or {}).get("category") == "status"]
        met_keys = [v["key"] for v in variables_cfg if (v.get("timeline") or {}).get("category") == "metastasis"]

        merged: Dict[str, Dict[str, Any]] = {}
        note_to_key: Dict[str, str] = {}   # note_id -> event key, for recurrencetype enrichment

        def _add_evidence(ev, c):
            ev["evidence"].append({
                "note_id": c.get("note_id") or "", "prompt_type": c.get("prompt_type", ""),
                "value": c.get("value", ""), "date": c.get("date"),
                "report_type": c.get("report_type", ""),
                "annotation_text": c.get("annotation_text"), "reasoning": c.get("reasoning"),
                "evidence_spans": c.get("evidence_spans") or [],
            })

        # recur_or_prog is AUTHORITATIVE for whether an event exists + its diseaseStatus.
        for k in status_keys:
            for c in (variables_state.get(k) or {}).get("candidates") or []:
                val = (c.get("value") or "").strip()
                if not val or _EVENT_NEGATION.search(val):
                    continue
                key = StudyResolver._event_key(c.get("date"), c.get("note_id", ""))
                ev = merged.get(key)
                if ev is None:
                    ev = {
                        "key": key, "disease_status": "recurrence", "date": c.get("date"),
                        "date_from": c.get("date_from", "event"), "sites": [],
                        "source_note_ids": [], "origin": "llm", "status": "proposed",
                        "reviewed_by": None, "reviewed_at": None, "evidence_changed": False,
                        "edited": False, "evidence": [],
                    }
                    merged[key] = ev
                nid = c.get("note_id")
                if nid and nid not in ev["source_note_ids"]:
                    ev["source_note_ids"].append(nid)
                if nid:
                    note_to_key[nid] = key
                if _episode_status(val) == "progression":
                    ev["disease_status"] = "progression"  # more advanced state wins on a shared date
                _add_evidence(ev, c)

        # recurrencetype only ENRICHES an event recur_or_prog already established on the
        # SAME note with its metastatic sites — it must NOT fabricate an episode on its
        # own (a recurrence type asserted where recur_or_prog found no event is an
        # over-derivation from e.g. a bare lesion description).
        for k in met_keys:
            for c in (variables_state.get(k) or {}).get("candidates") or []:
                val = (c.get("value") or "").strip().lower()
                if not val or ("metastatic" not in val and not re.search(r"\blocal\b", val)):
                    continue
                if _EVENT_NEGATION.search(val):
                    continue
                key = note_to_key.get(c.get("note_id"))
                if key is None:
                    continue   # no recur_or_prog event on this note -> ignore
                ev = merged[key]
                for s in _sites_from_recurrencetype(val):
                    if s not in ev["sites"]:
                        ev["sites"].append(s)
                _add_evidence(ev, c)

        return sorted(merged.values(), key=lambda e: (_parse_ddmmyyyy(e.get("date") or "") or datetime.max))

    @staticmethod
    def build_events(variables_state: Dict[str, Any], variables_cfg: List[Dict[str, Any]],
                     prev_events: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Effective outcome-event list = freshly-assembled LLM events merged with
        the reviewer's prior decisions (confirm / drop / fix / manual-add), matched
        by stable key. A confirmed LLM event whose fresh assembly changed or vanished
        is KEPT but flagged evidence_changed (decision: keep + flag)."""
        fresh = StudyResolver._assemble_llm_events(variables_state, variables_cfg)
        prev_by = {e.get("key"): e for e in (prev_events or []) if e.get("key")}
        out: List[Dict[str, Any]] = []
        matched = set()

        for ev in fresh:
            prev = prev_by.get(ev["key"])
            if prev and (prev.get("reviewed_by") or prev.get("status") in ("confirmed", "dropped") or prev.get("origin") == "manual"):
                # a human acted on this event -> their decision + edits win; refresh
                # evidence_changed by comparing the human-facing content to the fresh LLM basis
                changed = prev.get("status") == "confirmed" and \
                    StudyResolver._event_signature(prev) != StudyResolver._event_signature(ev) and not prev.get("edited")
                merged = {**prev, "source_note_ids": ev["source_note_ids"],
                          "evidence": ev.get("evidence", []), "evidence_changed": bool(changed)}
                out.append(merged)
            else:
                out.append(ev)
            matched.add(ev["key"])

        # prior events with no fresh counterpart: keep manual events always, and
        # keep confirmed LLM events (basis vanished) with an evidence_changed flag.
        for key, prev in prev_by.items():
            if key in matched:
                continue
            if prev.get("origin") == "manual":
                out.append({**prev, "evidence_changed": False})
            elif prev.get("status") == "confirmed":
                out.append({**prev, "evidence_changed": True})
            # untouched 'proposed' LLM events that vanished are simply dropped

        # Flag events whose date precedes first documented contact (the diagnosis
        # anchor): an event cannot occur before diagnosis, so such a date is anomalous
        # — an over-derived recurrence or a historical mention — and the reviewer
        # should verify it.
        fc = StudyResolver._first_contact_candidate(variables_state, variables_cfg)
        diag_date = _parse_ddmmyyyy((fc or {}).get("date") or "")
        for ev in out:
            ed = _parse_ddmmyyyy(ev.get("date") or "")
            ev["before_diagnosis"] = bool(diag_date and ed and ed < diag_date and ev.get("origin") == "llm")
            ev["review_action"] = StudyResolver.classify_event_action(ev)
        out.sort(key=lambda e: (_parse_ddmmyyyy(e.get("date") or "") or datetime.max))
        return out

    @staticmethod
    def classify_event_action(ev: Dict[str, Any]) -> Optional[str]:
        """accept (confirmed LLM event kept as-is), edit (confirmed + human-edited),
        reject (dropped), missed (human-added event the LLM never proposed)."""
        if ev.get("origin") == "manual":
            return "missed"
        status = ev.get("status")
        if status == "dropped":
            return "reject"
        if status == "confirmed":
            return "edit" if ev.get("edited") else "accept"
        return None

    def _merge_previous(self, review, prev_var):
        """Keep a human's confirm/reject/edit; refresh everything else."""
        if not isinstance(prev_var, dict):
            return review
        if prev_var.get("status") in ("confirmed", "rejected") and self._is_human(prev_var):
            review["value"] = prev_var.get("value")
            review["status"] = prev_var["status"]
            review["auto_resolved"] = False
            review["resolution_rule"] = None
            review["reviewed_by"] = prev_var.get("reviewed_by")
            review["reviewed_at"] = prev_var.get("reviewed_at")
            review["note"] = prev_var.get("note")
        return review

    @staticmethod
    def _merge_previous_eligibility(eligibility, prev):
        if isinstance(prev, dict) and prev.get("confirmed"):
            eligibility["decision"] = prev.get("decision", eligibility["decision"])
            eligibility["confirmed"] = True
            eligibility["decided_by"] = prev.get("decided_by")
            eligibility["decided_at"] = prev.get("decided_at")
        return eligibility

    @staticmethod
    def _overall_status(eligibility, var_reviews, variables) -> str:
        if eligibility.get("decision") == "excluded":
            return "excluded"
        keys = [v["key"] for v in variables]
        statuses = [var_reviews.get(k, {}).get("status") for k in keys]
        all_done = all(s in ("confirmed", "rejected") for s in statuses) and eligibility.get("confirmed")
        any_done = eligibility.get("confirmed") or any(
            var_reviews.get(k, {}).get("status") in ("confirmed", "rejected") for k in keys
        )
        if all_done:
            return "completed"
        if any_done:
            return "in_progress"
        return "pending"
