from dataclasses import replace
from unittest.mock import Mock

import pandas as pd
import pytest

from app import (
    FundCaptureData,
    build_pdf,
    build_comparison_preview,
    column_for,
    fetch_advisorkhoj_suggestions,
    deterministic_score,
    identify_capture_table,
    parse_fund_names,
    parse_numeric,
    rank_funds,
    resolve_advisorkhoj_url,
    select_scheme_suggestion,
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


@pytest.mark.parametrize("value", ["Fund One", "Fund One\nFund One", "\n".join(f"Fund {i}" for i in range(11))])
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


def test_build_comparison_preview_keeps_rank_order_and_benchmarks():
    fund_one = make_fund("Fund One", 105, 90, 1.16)
    fund_two = replace(
        make_fund("Fund Two", 98, 95, 1.03),
        category="Equity: Flexi Cap",
        benchmark_name="Nifty 500 TRI",
    )
    ranking = rank_funds([fund_two, fund_one])

    preview = build_comparison_preview([fund_one, fund_two], ranking)

    assert preview["Fund"].tolist() == ["Fund One", "Fund Two"]
    assert preview["Rank"].tolist() == [1, 2]
    assert preview["Benchmark"].tolist() == ["Example Benchmark", "Nifty 500 TRI"]
    assert preview["Category"].tolist() == ["Equity: Large Cap", "Equity: Flexi Cap"]
    assert preview.iloc[0]["Capture ratio"] == 1.16


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


def test_build_pdf_handles_provenance_ampersands_and_long_source_url():
    fund = replace(
        make_fund("Fund One", 105, 90, 1.16),
        amc_name="Example & Associates",
        benchmark_name="Example Benchmark",
        source_url=(
            "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio"
            "?PageSpeed=noscript&category=Equity%3A+Large+Cap&schemes=Fund+One&period=5"
        ),
    )
    ranking = rank_funds([fund])
    analysis = {
        "overall_summary": "The fund has a source record.",
        "funds": [
            {"scheme_name": "Fund One", "rank": 1, "reason": "Example reason.", "strengths": ["Example strength"], "limitations": ["Example limitation"]},
        ],
    }

    result = build_pdf([fund], ranking, analysis, "5 years")

    assert result.startswith(b"%PDF")
    assert len(result) > 1000


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio",
            "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio?PageSpeed=noscript",
        ),
        (
            "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio?campaign=test",
            "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio?campaign=test&PageSpeed=noscript",
        ),
        (
            "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio?PageSpeed=noscript",
            "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio?PageSpeed=noscript",
        ),
    ],
)
def test_resolve_advisorkhoj_url_uses_noscript_mode(url, expected):
    assert resolve_advisorkhoj_url(url) == expected


def test_select_scheme_suggestion_matches_exact_canonical_label():
    choices = ["Parag Parikh Flexi Cap Dir Gr", "Parag Parikh Flexi Cap Reg Gr"]
    assert select_scheme_suggestion("Parag Parikh Flexi Cap Dir Gr", choices) == choices[0]
    assert select_scheme_suggestion("Parag Parikh Flexi Cap Reg Gr", choices) == choices[1]


def test_select_scheme_suggestion_uses_unique_result():
    assert select_scheme_suggestion("Mirae Asset Large Cap Fund", ["Mirae Asset Large Cap Gr"]) == "Mirae Asset Large Cap Gr"


def test_select_scheme_suggestion_resolves_explicit_direct_alias():
    choices = ["Parag Parikh Flexi Cap Dir Gr", "Parag Parikh Flexi Cap Reg Gr"]
    assert select_scheme_suggestion("Parag Parikh Flexi Cap Direct Growth", choices) == choices[0]


def test_select_scheme_suggestion_resolves_explicit_regular_alias():
    choices = ["Parag Parikh Flexi Cap Dir Gr", "Parag Parikh Flexi Cap Reg Gr"]
    assert select_scheme_suggestion("Parag Parikh Flexi Cap Regular Growth", choices) == choices[1]


def test_select_scheme_suggestion_rejects_ambiguous_generic_name():
    choices = ["Parag Parikh Flexi Cap Dir Gr", "Parag Parikh Flexi Cap Reg Gr"]
    with pytest.raises(ValueError, match="multiple AdvisorKhoj schemes"):
        select_scheme_suggestion("Parag Parikh Flexi Cap Fund", choices)


def test_select_scheme_suggestion_rejects_no_suggestions():
    with pytest.raises(ValueError, match="no scheme suggestions"):
        select_scheme_suggestion("Unknown Fund", [])


def test_fetch_advisorkhoj_suggestions_shortens_query_and_selects_direct_variant():
    empty_response = Mock()
    empty_response.json.return_value = []
    empty_response.raise_for_status.return_value = None
    found_response = Mock()
    found_response.json.return_value = [
        "Parag Parikh Flexi Cap Dir Gr",
        "Parag Parikh Flexi Cap Reg Gr",
    ]
    found_response.raise_for_status.return_value = None
    session = Mock()
    session.post.side_effect = [empty_response, found_response]

    result = fetch_advisorkhoj_suggestions(
        "Parag Parikh Flexi Cap Dir Gr",
        "Equity: Flexi Cap",
        "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio?PageSpeed=noscript",
        session=session,
    )

    assert result == "Parag Parikh Flexi Cap Dir Gr"
    assert session.post.call_count == 2
    assert session.post.call_args_list[0].kwargs["data"]["query"] == "Parag Parikh Flexi Cap Dir Gr"
    assert session.post.call_args_list[1].kwargs["data"]["query"] == "Parag Parikh Flexi Cap Dir"


def test_fetch_advisorkhoj_suggestions_rejects_no_search_results():
    empty_response = Mock()
    empty_response.json.return_value = []
    empty_response.raise_for_status.return_value = None
    session = Mock()
    session.post.return_value = empty_response

    with pytest.raises(ValueError, match="found no scheme matching"):
        fetch_advisorkhoj_suggestions(
            "Unknown Fund",
            "Equity: Flexi Cap",
            "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio?PageSpeed=noscript",
            session=session,
        )


def test_column_for_prefers_exact_capture_ratio_header():
    table = pd.DataFrame(
        {
            "Scheme Name": ["Parag Parikh Flexi Cap Dir Gr"],
            "Up Market Capture Ratio (%)": [77.0],
            "Down Market Capture Ratio (%)": [58.0],
            "Capture Ratio": [1.33],
        }
    )

    assert column_for(table, "up market capture ratio") == "Up Market Capture Ratio (%)"
    assert column_for(table, "down market capture ratio") == "Down Market Capture Ratio (%)"
    assert column_for(table, "capture ratio") == "Capture Ratio"
    assert table.iloc[0][column_for(table, "capture ratio")] == 1.33
