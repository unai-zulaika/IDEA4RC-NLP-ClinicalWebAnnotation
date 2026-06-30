#!/usr/bin/env python3
"""Run the full filtered + unfiltered MSCI evaluation pipeline against a running
backend, including report generation. Safe to launch via nohup.

Steps:
  1. Upload the sample CSV → parsed rows
  2. Create Session A (no report_type mapping) → batch annotate → report A
  3. Save the report_type mapping for the center
  4. Create Session B (with mapping) → batch annotate → report B

Outputs two Markdown files in the current working directory:
  report_<center>_unfiltered.md
  report_<center>_filtered.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_DEFAULT = "http://localhost:8001/api"


def log(msg: str) -> None:
    """Print with a timestamp + flush so nohup tailing stays current."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def http_post(url: str, body: dict, timeout: float = 86400.0) -> dict:
    """POST JSON; return parsed JSON. Long timeout for the batch endpoint."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def upload_csv(api: str, csv_path: Path) -> dict:
    """POST the CSV as multipart/form-data. Uses curl for simplicity (urllib's
    multipart support is verbose). Returns the parsed CSVUploadResponse.
    """
    out = subprocess.run(
        ["curl", "-sS", "-X", "POST", f"{api}/upload/csv",
         "-F", f"file=@{csv_path}"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def load_msci_prompts(prompts_path: Path, center: str) -> list[str]:
    """Build the list of fully-suffixed prompt types for the center."""
    data = json.loads(prompts_path.read_text(encoding="utf-8"))
    center_section = data.get(center)
    if not center_section:
        raise SystemExit(f"Center {center!r} not found in {prompts_path}")
    suffix = f"-{center.lower()}"
    return [p + suffix for p in center_section.keys()]


def create_session(
    api: str,
    name: str,
    csv_data: list[dict],
    prompt_types: list[str],
    center: str,
    report_type_mapping: dict | None,
) -> str:
    body = {
        "name": name,
        "csv_data": csv_data,
        "prompt_types": prompt_types,
        "center": center,
    }
    if report_type_mapping is not None:
        body["report_type_mapping"] = report_type_mapping
    info = http_post(f"{api}/sessions", body, timeout=120)
    return info["session_id"]


def batch_annotate(api: str, session_id: str, sessions_dir: Path) -> dict:
    """Drive the annotation endpoint for every note × prompt_type in the session.

    Uses /annotate/sequential (NOT /annotate/batch). Sequential is slower (no
    parallelism) but persists per-note to the session JSON. /annotate/batch
    returns results in the response without writing to disk; if the caller
    discards the response, the work is lost — which is what happens here.
    """
    session_path = sessions_dir / f"{session_id}.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    note_count = len(session["notes"])
    prompt_count = len(session["prompt_types"])
    body = {
        # Both None → process every note × every prompt_type currently in the session
        "note_ids": None,
        "prompt_types": None,
        "fast_mode": False,
        "skip_annotated": True,  # makes the run resumable if it crashes mid-way
    }
    log(f"  sequential: {note_count} notes × {prompt_count} prompts (timeout=24h, persists per-note)")
    return http_post(f"{api}/annotate/sequential?session_id={session_id}", body, timeout=86400)


def save_mapping(api: str, mapping_path: Path, center: str) -> None:
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    http_post(
        f"{api}/upload/report-type-mappings?center={center}",
        mapping,
        timeout=60,
    )


def generate_report(
    py: Path,
    session_id: str,
    center: str,
    out_path: Path,
    sessions_dir: Path,
) -> None:
    cmd = [
        str(py),
        "tools/evaluation_report/generate_report.py",
        "--session", str(sessions_dir / f"{session_id}.json"),
        "--center", center,
        "--out", str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True, help="Sample CSV to upload (Path A schema)")
    ap.add_argument("--mapping", required=True, help="report_type_mapping JSON")
    ap.add_argument("--center", default="MSCI")
    ap.add_argument("--api", default=API_DEFAULT, help="Backend API root (default: http://localhost:8001/api)")
    ap.add_argument("--prompts", default="backend/data/prompts/prompts.json")
    ap.add_argument("--sessions-dir", default="backend/sessions")
    ap.add_argument("--python", default="backend/.venv/bin/python")
    ap.add_argument("--out-unfiltered", default=None,
                    help="Default: report_<center>_unfiltered.md")
    ap.add_argument("--out-filtered", default=None,
                    help="Default: report_<center>_filtered.md")
    ap.add_argument("--skip-unfiltered", action="store_true")
    ap.add_argument("--skip-filtered", action="store_true")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    mapping_path = Path(args.mapping)
    prompts_path = Path(args.prompts)
    sessions_dir = Path(args.sessions_dir)
    py = Path(args.python)

    for p, label in [(csv_path, "--csv"), (mapping_path, "--mapping"),
                     (prompts_path, "--prompts"), (sessions_dir, "--sessions-dir"),
                     (py, "--python")]:
        if not p.exists():
            print(f"ERROR: {label} path not found: {p}", file=sys.stderr)
            return 1

    out_unf = Path(args.out_unfiltered or f"report_{args.center.lower()}_unfiltered.md")
    out_fil = Path(args.out_filtered or f"report_{args.center.lower()}_filtered.md")

    log(f"Center: {args.center}")
    log(f"API: {args.api}")
    log(f"Sample CSV: {csv_path}")

    log("Uploading CSV …")
    upload_resp = upload_csv(args.api, csv_path)
    rows = upload_resp.get("all_rows") or []
    if not rows:
        log("ERROR: upload returned no rows. Aborting.")
        return 1
    log(f"  parsed {len(rows)} rows")

    prompt_types = load_msci_prompts(prompts_path, args.center)
    log(f"  prompt_types: {len(prompt_types)} ({', '.join(prompt_types[:3])}, …)")

    # ────────── RUN A: unfiltered ──────────
    if not args.skip_unfiltered:
        log("RUN A — unfiltered (no report-type mapping)")
        sid_a = create_session(
            args.api, name=f"{args.center} eval — unfiltered",
            csv_data=rows, prompt_types=prompt_types,
            center=args.center, report_type_mapping=None,
        )
        log(f"  session A = {sid_a}")
        t0 = time.time()
        batch_annotate(args.api, sid_a, sessions_dir)
        log(f"  batch A done in {time.time() - t0:.0f}s")
        generate_report(py, sid_a, args.center, out_unf, sessions_dir)
        log(f"  wrote {out_unf}")

    # ────────── RUN B: filtered ──────────
    if not args.skip_filtered:
        log("Saving report-type mapping …")
        save_mapping(args.api, mapping_path, args.center)

        log("RUN B — filtered (with report-type mapping)")
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        sid_b = create_session(
            args.api, name=f"{args.center} eval — filtered",
            csv_data=rows, prompt_types=prompt_types,
            center=args.center, report_type_mapping=mapping,
        )
        log(f"  session B = {sid_b}")
        t0 = time.time()
        batch_annotate(args.api, sid_b, sessions_dir)
        log(f"  batch B done in {time.time() - t0:.0f}s")
        generate_report(py, sid_b, args.center, out_fil, sessions_dir)
        log(f"  wrote {out_fil}")

    log("Done.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        log(f"HTTP {e.code} from {e.url}: {body[:500]}")
        sys.exit(1)
    except KeyboardInterrupt:
        log("Interrupted")
        sys.exit(130)
