import pandas as pd
import pytest

from app import (
    FundCaptureData,
    build_pdf,
    deterministic_score,
    identify_capture_table,
    parse_fund_names,
    parse_numeric,
    rank_funds,
)


def make_fund(name: str, up: float, down: float, capture: float) -> FundCaptureData:
    return FundCaptureData(
        requested_name=name,
        scheme_name=name,
        category="Equity: Large Cap",
        period="5 Years",
        amc_name="Example AMC",
        benchmark_name="Example Benchmark",
        launch_date="01-01-2000",
        scheme_return_percent=10.0,
        up_capture_percent=up,
        down_capture_percent=down,
        capture_ratio=capture,
        source_url="https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio",
        retrieved_at="2026-10-09T00:00:00+00:00",
    )


def test_parse_fund_names_deduplicates_and_normalizes_whitespace():
    assert parse_fund_names("  Fund One  \nFund Two, Fund One; Fund Three") == [
        "Fund One",
        "Fund Two",
        "Fund Three",
    ]


@pytest.mark.parametrize("value", ["Fund One", "Fund One\\nFund One", "\\n".join(f"Fund {i}" for i in range(11))])
def test_parse_fund_names_rejects_invalid_count(value):
    with pytest.raises(ValueError):
        parse_fund_names(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("97.00%", 97.0), ("1,200.5", 1200.5), ("-", None), ("Not available", None), (None, None)],
)
def test_parse_numeric(value, expected):
    assert parse_numeric(value) == expected


def test_identify_capture_table_requires_both_capture_columns():
    valid_table = pd.DataFrame(
        {
            "Scheme Name": ["Fund One"],
            "Up Market Capture Ratio (%)": [105],
            "Down Market Capture Ratio (%)": [85],
        }
    )
    assert identify_capture_table([pd.DataFrame({"Unrelated": [1]}), valid_table]).equals(valid_table)


def test_identify_capture_table_rejects_unrelated_table():
    with pytest.raises(ValueError):
        identify_capture_table([pd.DataFrame({"Scheme Name": ["Fund One"], "Return": [10]})])


def test_rank_funds_uses_capture_ratio_and_preserves_unique_funds():
    funds = [make_fund("Fund One", 105, 90, 1.16), make_fund("Fund Two", 98, 95, 1.03)]
    ranking = rank_funds(funds)
    assert [item["scheme_name"] for item in ranking] == ["Fund One", "Fund Two"]
    assert [item["rank"] for item in ranking] == [1, 2]


def test_build_pdf_returns_pdf_bytes_with_source_data():
    funds = [make_fund("Fund One", 105, 90, 1.16), make_fund("Fund Two", 98, 95, 1.03)]
    ranking = rank_funds(funds)
    analysis = {
        "overall_summary": "The funds differ in their market capture behavior.",
        "funds": [
            {"scheme_name": "Fund One", "rank": 1, "reason": "Higher capture ratio.", "strengths": ["Higher ratio"], "limitations": ["Limited metric"]},
            {"scheme_name": "Fund Two", "rank": 2, "reason": "Lower capture ratio.", "strengths": ["Lower downside capture"], "limitations": ["Lower ratio"]},
        ],
    }
    result = build_pdf(funds, ranking, analysis, "5 years")
    assert result.startswith(b"%PDF")
    assert len(result) > 1000
