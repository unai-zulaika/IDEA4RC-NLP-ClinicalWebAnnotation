#!/usr/bin/env python3
"""Note-type filter for INT head and neck, derived from the few-shot pool only (patients outside the evaluation set).

A variable is asked of a note type when at least one pool note of that type has it annotated.
Writes {report_type: [variable, ...]} with the -int-hnc suffix stripped. No note text is written.

usage: hnc_pool_mapping.py OUT.json
"""
import json
import re
import sys
from collections import defaultdict

ph = json.load(open("sessions/int_hnc_phase2.json"))["notes"]
ev = {n["p_id"] for n in json.load(open("sessions/int_hnc_eval.json"))["notes"]}
m = defaultdict(set)
for n in ph:
    if n["p_id"] not in ev:
        m[n["report_type"]] |= set(re.findall(r"(?:^| \| )([a-z0-9_\-]+)-int-hnc: ", n["annotations"]))
assert not ({n["p_id"] for n in ph if n["p_id"] not in ev} & ev)  # pool and evaluation patients are disjoint
json.dump({t: sorted(v) for t, v in sorted(m.items())}, open(sys.argv[1], "w"), indent=1)
print({t: len(v) for t, v in m.items()})
