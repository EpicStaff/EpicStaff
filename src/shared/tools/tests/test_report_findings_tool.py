import pytest

from conftest import load_tool_main

report_findings_module = load_tool_main("report_findings_tool")
report_findings_main = report_findings_module.main
FINDINGS_MARKER_KEY = report_findings_module.FINDINGS_MARKER_KEY
MAX_FINDINGS = report_findings_module.MAX_FINDINGS


class TestReportFindingsToolHappyPath:
    def test_basic_findings_reported(self):
        result = report_findings_main(
            findings=[
                {
                    "title": "SQL injection risk",
                    "severity": "high",
                    "file": "a.py",
                    "line": 12,
                },
                {"title": "Missing docstring", "severity": "low"},
            ],
            title="Security Review",
            summary="Two issues found",
        )

        assert isinstance(result, dict)
        assert result[FINDINGS_MARKER_KEY] == "findings"
        assert result["title"] == "Security Review"
        assert result["summary"] == "Two issues found"
        assert result["total_submitted"] == 2
        assert result["total_returned"] == 2
        assert result["truncated"] is False
        assert len(result["findings"]) == 2
        assert result["findings"][0] == {
            "title": "SQL injection risk",
            "severity": "high",
            "category": None,
            "file": "a.py",
            "line": 12,
            "detail": None,
        }
        assert "Reported 2 finding(s)" in result["message"]

    def test_severity_defaults_to_info_when_omitted(self):
        result = report_findings_main(findings=[{"title": "Note"}])

        assert result["findings"][0]["severity"] == "info"

    def test_optional_fields_default_to_none(self):
        result = report_findings_main(findings=[{"title": "Just a title"}])

        finding = result["findings"][0]
        assert finding["category"] is None
        assert finding["file"] is None
        assert finding["line"] is None
        assert finding["detail"] is None

    def test_title_and_summary_are_optional(self):
        result = report_findings_main(findings=[{"title": "x"}])

        assert result["title"] is None
        assert result["summary"] is None


class TestReportFindingsToolSeverityValidation:
    def test_invalid_severity_defaults_to_info_and_warns(self):
        result = report_findings_main(
            findings=[{"title": "Weird", "severity": "catastrophic"}]
        )

        assert result["findings"][0]["severity"] == "info"
        assert "Warnings:" in result["message"]
        assert "invalid severity" in result["message"]

    def test_all_valid_severities_accepted(self):
        severities = ["info", "low", "medium", "high", "critical"]
        result = report_findings_main(
            findings=[
                {"title": f"f{i}", "severity": s} for i, s in enumerate(severities)
            ]
        )

        assert [f["severity"] for f in result["findings"]] == severities
        assert "Warnings:" not in result["message"]

    def test_severity_case_insensitive(self):
        result = report_findings_main(findings=[{"title": "x", "severity": "HIGH"}])

        assert result["findings"][0]["severity"] == "high"


class TestReportFindingsToolTruncation:
    def test_findings_list_capped_and_announced(self):
        findings = [{"title": f"finding {i}"} for i in range(MAX_FINDINGS + 10)]

        result = report_findings_main(findings=findings)

        assert result["total_submitted"] == MAX_FINDINGS + 10
        assert result["total_returned"] == MAX_FINDINGS
        assert result["truncated"] is True
        assert "truncated" in result["message"]

    def test_long_detail_field_is_truncated(self):
        long_detail = "x" * 5000
        result = report_findings_main(findings=[{"title": "t", "detail": long_detail}])

        detail = result["findings"][0]["detail"]
        assert len(detail) < len(long_detail)
        assert detail.endswith("(truncated)")

    def test_long_title_is_truncated(self):
        long_title = "t" * 500
        result = report_findings_main(findings=[{"title": long_title}])

        title = result["findings"][0]["title"]
        assert len(title) < len(long_title)
        assert title.endswith("(truncated)")


class TestReportFindingsToolErrorPaths:
    def test_missing_findings_returns_error_string(self):
        result = report_findings_main()

        assert isinstance(result, str)
        assert result.startswith("Error:")
        assert "required" in result

    def test_findings_not_a_list_returns_error_string(self):
        result = report_findings_main(findings="not a list")

        assert isinstance(result, str)
        assert result.startswith("Error:")

    def test_empty_findings_list_returns_error_string(self):
        result = report_findings_main(findings=[])

        assert isinstance(result, str)
        assert result.startswith("Error:")

    def test_finding_missing_title_is_skipped_with_warning(self):
        result = report_findings_main(
            findings=[{"severity": "high"}, {"title": "valid one"}]
        )

        assert isinstance(result, dict)
        assert result["total_returned"] == 1
        assert "missing required 'title'" in result["message"]

    def test_all_findings_invalid_returns_error_string(self):
        result = report_findings_main(
            findings=[{"severity": "high"}, {"no_title": True}]
        )

        assert isinstance(result, str)
        assert result.startswith("Error:")
        assert "no valid findings" in result

    def test_non_integer_line_is_dropped_with_warning(self):
        result = report_findings_main(findings=[{"title": "x", "line": "not-a-number"}])

        assert result["findings"][0]["line"] is None
        assert "non-integer" in result["message"]

    def test_never_raises_on_unexpected_shape(self):
        # A finding entry that's a list instead of a dict should be skipped,
        # not raise.
        result = report_findings_main(findings=[["not", "a", "dict"], {"title": "ok"}])

        assert isinstance(result, dict)
        assert result["total_returned"] == 1
