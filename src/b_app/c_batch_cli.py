"""Run C's real-candidate batch through B without source trust shortcuts."""

import argparse
import json
from pathlib import Path
import sys

from .c_batch import run_batch


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="C批次接入B：校验追溯关系并输出核验回包，不联网")
    parser.add_argument("package_root", type=Path, help="解压后的C交接包目录")
    parser.add_argument("--output-dir", type=Path, required=True, help="新的输出目录，必须在C交接包外")
    parser.add_argument("--approved-sources", type=Path, help="B单独维护的来源批准JSON；省略时不批准任何来源")
    parser.add_argument("--context-holds", type=Path, help="B单独维护的范围待确认清单，阻止方向不明的搜索")
    args = parser.parse_args()
    try:
        report = run_batch(args.package_root, args.output_dir, args.approved_sources, args.context_holds)
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(2, f"批次处理失败：{exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
