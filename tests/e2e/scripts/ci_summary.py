"""Print the e2e results as Markdown for the GitHub job summary (stdlib only).

    python tests/e2e/scripts/ci_summary.py reports/junit.xml reports/timings.json \
        >> "$GITHUB_STEP_SUMMARY"

One row per test file (passed / failed / skipped), then the timings table. A missing file is
reported, not raised: the summary also runs when the stack never came up.
"""

import json
import sys
import xml.etree.ElementTree as ElementTree
from collections import Counter, defaultdict
from pathlib import Path


def test_file(classname: str) -> str:
    return next((part for part in classname.split(".") if part.startswith("test_")), classname)


def outcome(testcase: ElementTree.Element) -> str:
    for child in testcase:
        if child.tag in ("failure", "error"):
            return "failed"
        if child.tag == "skipped":
            return "skipped"
    return "passed"


def results_table(junit_path: Path) -> list[str]:
    if not junit_path.exists():
        return [
            "No JUnit report: the tests did not run. See the step log and the e2e-logs artifact."
        ]
    counts: dict[str, Counter] = defaultdict(Counter)
    for testcase in ElementTree.parse(junit_path).iter("testcase"):
        counts[test_file(testcase.get("classname", ""))][outcome(testcase)] += 1
    lines = ["| File | Passed | Failed | Skipped |", "|---|---|---|---|"]
    for name, count in sorted(counts.items()):
        mark = "❌" if count["failed"] else "✅"
        lines.append(
            f"| {mark} `{name}` | {count['passed']} | {count['failed']} | {count['skipped']} |"
        )
    return lines


def timings_table(timings_path: Path) -> list[str]:
    if not timings_path.exists():
        return ["No timings.json."]
    lines = ["| Measurement | Value |", "|---|---|"]
    for name, value in sorted(json.loads(timings_path.read_text()).items()):
        lines.append(f"| `{name}` | {value} |")
    return lines


def main() -> None:
    junit_path, timings_path = Path(sys.argv[1]), Path(sys.argv[2])
    print(
        "\n".join(
            [
                "### Results",
                *results_table(junit_path),
                "",
                "### Timings",
                *timings_table(timings_path),
            ]
        )
    )


if __name__ == "__main__":
    main()
