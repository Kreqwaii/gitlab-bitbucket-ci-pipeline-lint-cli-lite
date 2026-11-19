"""CLI entrypoint for gitlab-bitbucket-ci-pipeline-lint-cli-lite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .rules import SEVERITY_ORDER, Finding, lint_content
from .yaml_subset import YamlParseError


def format_table(findings: Sequence[Finding], file_label: str = "") -> str:
    if not findings:
        prefix = f"{file_label}: " if file_label else ""
        return f"{prefix}No issues found."

    headers = ("RULE", "SEVERITY", "LINE", "LOCATION", "MESSAGE")
    rows = [
        (
            f.rule_id,
            f.severity.upper(),
            str(f.line if f.line is not None else "-"),
            f.location,
            f.message,
        )
        for f in findings
    ]
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))
    ]

    def _fmt_row(cols: Sequence[str]) -> str:
        return " | ".join(col.ljust(widths[i]) for i, col in enumerate(cols))

    sep = "-+-".join("-" * w for w in widths)
    lines = []
    if file_label:
        lines.append(f"File: {file_label}")
    lines.append(_fmt_row(headers))
    lines.append(sep)
    for row in rows:
        lines.append(_fmt_row(row))
    return "\n".join(lines)


def format_json(findings: Sequence[Finding], file_label: str = "") -> str:
    payload = {
        "file": file_label or None,
        "count": len(findings),
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(payload, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci-lint",
        description="Offline linter for .gitlab-ci.yml and bitbucket-pipelines.yml",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Path(s) to CI/CD YAML file(s) to lint",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--platform",
        choices=("auto", "gitlab", "bitbucket"),
        default="auto",
        help="Target CI platform (default: auto)",
    )
    parser.add_argument(
        "--fail-on",
        choices=("error", "warning", "info", "none"),
        default="error",
        help="Minimum severity that triggers non-zero exit code (default: error)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    all_outputs: List[str] = []
    should_fail = False
    threshold = SEVERITY_ORDER.get(args.fail_on, 999)

    for file_str in args.files:
        path = Path(file_str)
        if not path.is_file():
            print(f"Error: file not found: {file_str}", file=sys.stderr)
            return 2

        content = path.read_text(encoding="utf-8")
        try:
            findings = lint_content(content, file_path=str(path), platform=args.platform)
        except YamlParseError as exc:
            print(f"Parse error in {file_str}: {exc}", file=sys.stderr)
            return 2

        for f in findings:
            if SEVERITY_ORDER.get(f.severity, 0) >= threshold:
                should_fail = True

        if args.format == "json":
            all_outputs.append(format_json(findings, file_label=file_str))
        else:
            all_outputs.append(format_table(findings, file_label=file_str))

    print("\n\n".join(all_outputs))
    return 1 if should_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
