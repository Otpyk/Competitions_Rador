"""Run the B-provided reference C receiver against a saved candidate batch."""

import argparse
import json
from pathlib import Path
import sys

from .return_contract import validate_return


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="检查保存的 B 回包与 C 原始候选是否关联一致；不核验网页真实性")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        candidates = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Candidates must be a nonempty array")
        result_dir = args.results.resolve()
        if not result_dir.is_dir():
            raise ValueError("Results directory does not exist")
        paths, ids = [], set()
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
                raise ValueError("Every candidate must have a text ID")
            contest_id = candidate["id"]
            if not contest_id or any(ch in contest_id for ch in '/\\:') or contest_id.casefold() in ids:
                raise ValueError("Unsafe or duplicate candidate ID")
            ids.add(contest_id.casefold())
            path = (result_dir / (contest_id + ".json")).resolve()
            if path.parent != result_dir:
                raise ValueError("Result path escapes results directory")
            paths.append(path)
        if {path.resolve() for path in result_dir.glob("*.json")} != set(paths):
            raise ValueError("Result filenames must match all candidate IDs exactly")
        receipts = []
        for candidate, path in zip(candidates, paths):
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            receipt = validate_return(payload, candidate)
            # The full payload stays in its original file; only summarize receipt.
            receipts.append({key: value for key, value in receipt.items() if key != "received_payload"})
        report = {"reference_receiver_passed": True, "candidate_count": len(receipts),
                  "c_runtime_executed": False, "web_authenticity_checked": False,
                  "notice": "这是 B 提供的参考接收检查；C 仍需运行自己项目的实际接收程序。",
                  "receipts": receipts}
        output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            target = args.output.resolve()
            if target == args.candidates.resolve() or target.is_relative_to(result_dir):
                raise ValueError("Receipt output must not overwrite candidates or result files")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(output, encoding="utf-8")
        print(output)
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(2, f"接收检查失败：{exc}\n")


if __name__ == "__main__":
    main()
