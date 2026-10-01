from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import ROOT, hard_gate_reasons, normalize_candidate, run_cycle, write_report


def calibrate() -> int:
    fixture = json.loads((ROOT / "tests" / "fixtures" / "calibration.json").read_text(encoding="utf-8"))
    failures = []
    for case in fixture["cases"]:
        op = normalize_candidate(case["candidate"])
        passed = not hard_gate_reasons(op)
        bad = passed != case["expected_hard_gate_pass"]
        if case.get("expected_vertical") and op.vertical != case["expected_vertical"]:
            bad = True
        if bad:
            failures.append(case["name"])
    print(json.dumps({"cases": len(fixture["cases"]), "failures": failures}, indent=2))
    return 1 if failures else 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["cycle", "report", "calibrate"])
    args = p.parse_args()
    if args.mode == "cycle":
        print(run_cycle().model_dump_json(indent=2))
    elif args.mode == "report":
        print(write_report())
    else:
        raise SystemExit(calibrate())

if __name__ == "__main__":
    main()
