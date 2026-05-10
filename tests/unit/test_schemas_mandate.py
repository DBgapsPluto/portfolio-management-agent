from tradingagents.schemas.mandate import Violation, ValidationReport


def test_violation_with_details():
    v = Violation(
        rule="single_etf_cap",
        description="A381180 weight 0.22 exceeds 0.20 cap",
        severity="hard",
        suggested_fix="Reduce A381180 to 0.20",
    )
    assert v.severity == "hard"


def test_validation_report_passed():
    r = ValidationReport(passed=True, violations=[], suggestions=[])
    assert r.passed is True
    assert len(r.violations) == 0


def test_validation_report_failed_blocks():
    r = ValidationReport(
        passed=False,
        violations=[
            Violation(
                rule="risk_asset_cap",
                description="Risk weight 0.73 > 0.70",
                severity="hard",
                suggested_fix="Reduce equity exposure by 3%",
            )
        ],
        suggestions=["Consider increasing 안전자산"],
    )
    assert r.has_hard_violations is True
