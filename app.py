import io
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.sax.saxutils import escape

import pandas as pd
from lxml import html as lxml_html
import requests
import streamlit as st
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)

load_dotenv()

DEFAULT_SOURCE_URL = "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio"
SUPPORTED_PERIODS = {"1 year": "1 Year", "3 years": "3 Years", "5 years": "5 Years", "10 years": "10 Years"}
PERIOD_CODES = {"1 year": "1", "3 years": "3", "5 years": "5", "10 years": "10"}
DISCLAIMER = (
    "This report is for educational and informational purposes only. It is not investment advice, "
    "a recommendation to buy or sell a security, or a guarantee of future performance. Mutual fund "
    "investments are subject to market risks. Past performance may not continue. Review scheme documents "
    "and consult a qualified financial adviser before making investment decisions."
)


def resolve_advisorkhoj_url(url: str | None = None) -> str:
    """Ensure AdvisorKhoj uses its lightweight HTML mode for HTTP retrieval."""
    configured_url = (url or os.getenv("ADVISORKHOJ_URL") or DEFAULT_SOURCE_URL).strip()
    parts = urlsplit(configured_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key.casefold() == "pagespeed" for key, _ in query):
        query.append(("PageSpeed", "noscript"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass(frozen=True)
class FundCaptureData:
    requested_name: str
    scheme_name: str
    category: str
    period: str
    amc_name: str
    benchmark_name: str
    launch_date: str
    scheme_return_percent: float | None
    up_capture_percent: float | None
    down_capture_percent: float | None
    capture_ratio: float | None
    source_url: str
    retrieved_at: str


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def parse_fund_names(text: str) -> list[str]:
    names = [re.sub(r"\s+", " ", line).strip(" \t,;") for line in re.split(r"[\n,;]+", text)]
    unique_names: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = normalize_name(name)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_names.append(name)
    if not 2 <= len(unique_names) <= 10:
        raise ValueError("Enter between 2 and 10 unique mutual fund names.")
    return unique_names


def parse_numeric(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "—", "N/A", "NA"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group())


def identify_capture_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    for table in tables:
        columns = [re.sub(r"\s+", " ", str(column)).strip().casefold() for column in table.columns]
        if any("up market capture ratio" in column for column in columns) and any(
            "down market capture ratio" in column for column in columns
        ):
            return table
    raise ValueError("AdvisorKhoj did not return a recognizable Market Capture Ratio table.")


def column_for(table: pd.DataFrame, phrase: str) -> Any:
    """Prefer an exact normalized header before falling back to substring matching."""
    requested = normalize_name(phrase)
    for column in table.columns:
        if normalize_name(str(column)) == requested:
            return column
    for column in table.columns:
        if requested in normalize_name(str(column)):
            return column
    return None

def select_scheme_suggestion(requested_name: str, suggestions: list[str]) -> str:
    """Resolve one scheme conservatively; never silently choose among variants."""
    cleaned = [re.sub(r"\s+", " ", str(item)).strip() for item in suggestions]
    cleaned = list(dict.fromkeys(item for item in cleaned if item))
    if not cleaned:
        raise ValueError(f"AdvisorKhoj returned no scheme suggestions for '{requested_name}'.")

    requested_normalized = normalize_name(requested_name)
    exact = [item for item in cleaned if normalize_name(item) == requested_normalized]
    if len(exact) == 1:
        return exact[0]

    requested_tokens = set(requested_normalized.split())
    direct_words = {"direct", "dir"}
    regular_words = {"regular", "reg"}
    if requested_tokens & direct_words:
        variants = [item for item in cleaned if set(normalize_name(item).split()) & direct_words]
        if len(variants) == 1:
            return variants[0]
    if requested_tokens & regular_words:
        variants = [item for item in cleaned if set(normalize_name(item).split()) & regular_words]
        if len(variants) == 1:
            return variants[0]

    if len(cleaned) == 1:
        return cleaned[0]

    generic_words = {"fund", "mutual", "scheme", "growth", "gr", "plan"}
    meaningful_tokens = requested_tokens - generic_words - direct_words - regular_words
    scores = {
        item: len(meaningful_tokens & set(normalize_name(item).split())) /
        max(1, len(meaningful_tokens))
        for item in cleaned
    }
    best_score = max(scores.values())
    winners = [item for item, score in scores.items() if score == best_score]
    second_score = max((score for score in scores.values() if score < best_score), default=-1.0)
    if len(winners) == 1 and best_score >= 0.75 and best_score - second_score >= 0.15:
        return winners[0]

    choices = "; ".join(cleaned[:8])
    raise ValueError(
        f"'{requested_name}' matches multiple AdvisorKhoj schemes. "
        f"Enter one exact scheme name, for example: {choices}"
    )


def fetch_advisorkhoj_suggestions(
    requested_name: str,
    category: str,
    source_url: str,
    session: Any = None,
) -> str:
    """Resolve a typed fund name through AdvisorKhoj's page-referenced typeahead endpoint."""
    from contextlib import nullcontext

    owns_session = session is None
    client_context = requests.Session() if owns_session else nullcontext(session)
    with client_context as client:
        parts = urlsplit(source_url)
        endpoint = f"{parts.scheme}://{parts.netloc}/mutual-funds-research/autoSuggestAllMfSchemesShortNames"
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; FundReportResearch/1.0)",
            "Referer": source_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        tokens = re.sub(r"\s+", " ", requested_name).strip().split()
        if not tokens:
            raise ValueError("Enter a mutual-fund scheme name.")

        # The source endpoint is prefix-oriented; dropping trailing generic words
        # such as 'Fund' can reveal the canonical scheme labels.
        tried: set[str] = set()
        for width in range(len(tokens), 0, -1):
            query = " ".join(tokens[:width])
            if query.casefold() in tried:
                continue
            tried.add(query.casefold())
            response = client.post(
                endpoint,
                data={"query": query, "category": category},
                headers=headers,
                timeout=(10, 30),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError("AdvisorKhoj returned an unexpected scheme-suggestion response.")
            suggestions = [str(item) for item in payload if isinstance(item, str) and item.strip()]
            if suggestions:
                return select_scheme_suggestion(requested_name, suggestions)

    raise ValueError(
        f"AdvisorKhoj found no scheme matching '{requested_name}' in category '{category}'. "
        "Check the name and category, then try again."
    )


def fetch_one_fund(requested_name: str, category: str, period: str) -> FundCaptureData:
    source_url = resolve_advisorkhoj_url(os.getenv("ADVISORKHOJ_URL", DEFAULT_SOURCE_URL))
    period_key = period.casefold().strip()
    if period_key not in SUPPORTED_PERIODS or period_key not in PERIOD_CODES:
        raise ValueError(f"Unsupported analysis period: {period}")

    try:
        with requests.Session() as session:
            selected_scheme = fetch_advisorkhoj_suggestions(
                requested_name, category, source_url, session=session
            )
            response = session.get(
                source_url,
                params={
                    "category": category,
                    "schemes": selected_scheme,
                    "period": PERIOD_CODES[period_key],
                },
                headers={"User-Agent": "Mozilla/5.0 (compatible; FundReportResearch/1.0)"},
                timeout=(10, 45),
            )
            response.raise_for_status()
            tables = pd.read_html(io.StringIO(response.text))
            capture_table = identify_capture_table(tables)
            scheme_column = column_for(capture_table, "scheme name")
            if scheme_column is None:
                scheme_column = capture_table.columns[0]

            matching_rows = capture_table[
                capture_table[scheme_column].astype(str).map(
                    lambda name: normalize_name(name) == normalize_name(selected_scheme)
                )
            ]
            if len(matching_rows) != 1:
                raise ValueError(
                    f"AdvisorKhoj did not return exactly one result for '{selected_scheme}'. "
                    "No report was generated from ambiguous or missing data."
                )

            row = matching_rows.iloc[0]

            def value_for(phrase: str) -> Any:
                column = column_for(capture_table, phrase)
                return row[column] if column is not None else None

            data = FundCaptureData(
                requested_name=requested_name,
                scheme_name=str(row[scheme_column]).strip(),
                category=category,
                period=SUPPORTED_PERIODS[period_key],
                amc_name=str(value_for("amc name") or "Not provided"),
                benchmark_name=str(value_for("benchmark name") or "Not provided"),
                launch_date=str(value_for("launch date") or "Not provided"),
                scheme_return_percent=parse_numeric(value_for("scheme return")),
                up_capture_percent=parse_numeric(value_for("up market capture ratio")),
                down_capture_percent=parse_numeric(value_for("down market capture ratio")),
                capture_ratio=parse_numeric(value_for("capture ratio")),
                source_url=response.url,
                retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            if data.up_capture_percent is None or data.down_capture_percent is None:
                raise ValueError(f"AdvisorKhoj returned incomplete capture figures for '{requested_name}'.")
            return data
    except (ValueError, RuntimeError):
        raise
    except requests.RequestException as error:
        raise RuntimeError(
            f"Unable to contact AdvisorKhoj while retrieving '{requested_name}'. Try again later."
        ) from error
    except Exception as error:
        raise RuntimeError(
            f"Unable to retrieve verified AdvisorKhoj data for '{requested_name}'. "
            "The source may have changed or may be temporarily unavailable."
        ) from error


def deterministic_score(fund: FundCaptureData) -> float:
    if fund.capture_ratio is not None:
        return fund.capture_ratio
    return (fund.up_capture_percent or 0.0) - (fund.down_capture_percent or 0.0)


def rank_funds(funds: list[FundCaptureData]) -> list[dict[str, Any]]:
    ranked = sorted(funds, key=deterministic_score, reverse=True)
    return [
        {
            "rank": index,
            "scheme_name": fund.scheme_name,
            "score": round(deterministic_score(fund), 4),
            "up_capture_percent": fund.up_capture_percent,
            "down_capture_percent": fund.down_capture_percent,
            "capture_ratio": fund.capture_ratio,
        }
        for index, fund in enumerate(ranked, start=1)
    ]


def request_ai_analysis(funds: list[FundCaptureData], ranking: list[dict[str, Any]], period: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AI analysis is not configured. Add OPENAI_API_KEY in the hosting environment.")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    payload = {
        "period": period,
        "funds": [asdict(fund) for fund in funds],
        "deterministic_ranking": ranking,
    }
    system_prompt = (
        "You are a careful mutual-fund data explainer. Use only supplied figures. Do not invent facts, "
        "returns, dates, benchmarks, or risk metrics. Explain that a higher up-capture can indicate more "
        "participation in rising markets and a lower down-capture can indicate less participation in falling "
        "markets, while noting benchmark and category differences. The deterministic ranking is authoritative; "
        "do not reorder funds. Return valid JSON with keys overall_summary and funds. funds must contain each "
        "scheme_name exactly once with rank, reason, strengths, limitations. Keep explanations concise and "
        "balanced. Do not provide individualized investment advice."
    )
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        },
        timeout=(10, 60),
    )
    if response.status_code == 429:
        raise RuntimeError("The AI provider rate limit or quota was reached. Try again later.")
    if response.status_code >= 400:
        raise RuntimeError(f"The AI provider returned HTTP {response.status_code}. Check provider configuration.")
    try:
        result = json.loads(response.json()["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise RuntimeError("The AI provider returned an invalid analysis response.") from error
    expected = {fund.scheme_name for fund in funds}
    actual_funds = result.get("funds")
    if not isinstance(actual_funds, list):
        raise RuntimeError("The AI response did not contain a valid fund analysis list.")
    actual_names = [item.get("scheme_name") for item in actual_funds if isinstance(item, dict)]
    if len(actual_names) != len(expected) or set(actual_names) != expected:
        raise RuntimeError("The AI response omitted, duplicated, or changed a selected fund.")
    expected_ranks = {item["scheme_name"]: item["rank"] for item in ranking}
    for item in actual_funds:
        if item.get("rank") != expected_ranks[item["scheme_name"]]:
            raise RuntimeError("The AI response changed the validated deterministic ranking.")
        for key in ("reason", "strengths", "limitations"):
            if not isinstance(item.get(key), (str, list)) or not item.get(key):
                raise RuntimeError("The AI response contained an incomplete explanation.")
    if not isinstance(result.get("overall_summary"), str) or not result["overall_summary"].strip():
        raise RuntimeError("The AI response did not contain an overall summary.")
    return result


def build_pdf(funds: list[FundCaptureData], ranking: list[dict[str, Any]], analysis: dict[str, Any], period: str) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Mutual Fund Market Capture Report - {period}",
        author="Fund Report Web Scraping",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontSize=23, leading=28, textColor=colors.HexColor("#14324A"), alignment=TA_CENTER, spaceAfter=8 * mm))
    styles.add(ParagraphStyle(name="SectionTitle", parent=styles["Heading2"], fontSize=14, leading=18, textColor=colors.HexColor("#14324A"), spaceBefore=5 * mm, spaceAfter=3 * mm))
    styles.add(ParagraphStyle(name="SmallBody", parent=styles["BodyText"], fontSize=8.5, leading=12, spaceAfter=2 * mm))
    styles.add(ParagraphStyle(name="SourceFundTitle", parent=styles["Heading3"], fontSize=10.5, leading=13, textColor=colors.HexColor("#14324A"), spaceBefore=1 * mm, spaceAfter=0))
    styles.add(ParagraphStyle(name="SourceLabel", parent=styles["SmallBody"], fontSize=8, leading=10, textColor=colors.HexColor("#344054"), wordWrap="CJK", spaceAfter=0))
    styles.add(ParagraphStyle(name="SourceValue", parent=styles["SmallBody"], fontSize=8, leading=10, textColor=colors.HexColor("#344054"), wordWrap="CJK", splitLongWords=1, spaceAfter=0))
    story: list[Any] = [
        Spacer(1, 20 * mm),
        Paragraph("MUTUAL FUND REPORT", styles["ReportTitle"]),
        Paragraph("Market Capture Ratio Comparison", styles["Heading2"]),
        Spacer(1, 4 * mm),
        Paragraph(f"Analysis period: {period}", styles["BodyText"]),
        Paragraph(f"Generated: {datetime.now().astimezone().strftime('%d %b %Y, %H:%M %Z')}", styles["BodyText"]),
        Paragraph("Primary source: AdvisorKhoj Market Capture Ratio", styles["BodyText"]),
        Spacer(1, 8 * mm),
        Paragraph("Funds analyzed", styles["SectionTitle"]),
    ]
    for fund in funds:
        story.append(Paragraph(f"• {fund.scheme_name} — {fund.category}", styles["BodyText"]))
    story.extend([Spacer(1, 5 * mm), Paragraph("Ranking overview", styles["SectionTitle"])])
    table_rows = [["Rank", "Fund", "Up capture", "Down capture", "Capture ratio"]]
    for item in ranking:
        table_rows.append([
            str(item["rank"]),
            Paragraph(str(item["scheme_name"]), styles["SmallBody"]),
            "—" if item["up_capture_percent"] is None else f'{item["up_capture_percent"]:.2f}%',
            "—" if item["down_capture_percent"] is None else f'{item["down_capture_percent"]:.2f}%',
            "—" if item["capture_ratio"] is None else f'{item["capture_ratio"]:.2f}',
        ])
    ranking_table = Table(table_rows, colWidths=[13 * mm, 77 * mm, 28 * mm, 30 * mm, 25 * mm], repeatRows=1, hAlign="LEFT")
    ranking_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14324A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E0E7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7FA")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([ranking_table, Paragraph("Overall summary", styles["SectionTitle"]), Paragraph(analysis["overall_summary"], styles["BodyText"])])
    analysis_by_name = {item["scheme_name"]: item for item in analysis["funds"]}
    for item in ranking:
        explanation = analysis_by_name[item["scheme_name"]]
        story.append(Paragraph(f"Rank {item['rank']}: {item['scheme_name']}", styles["SectionTitle"]))
        story.append(Paragraph(f"<b>Reason:</b> {str(explanation['reason'])}", styles["BodyText"]))
        strengths = explanation["strengths"]
        limitations = explanation["limitations"]
        if isinstance(strengths, list):
            strengths = "; ".join(str(item) for item in strengths)
        if isinstance(limitations, list):
            limitations = "; ".join(str(item) for item in limitations)
        story.append(Paragraph(f"<b>Strengths:</b> {str(strengths)}", styles["BodyText"]))
        story.append(Paragraph(f"<b>Limitations:</b> {str(limitations)}", styles["BodyText"]))
    story.append(Paragraph("Source figures and provenance", styles["SectionTitle"]))
    for index, fund in enumerate(funds, start=1):
        scheme_title = Paragraph(
            f"{index}. {safe_paragraph(fund.scheme_name)}",
            styles["SourceFundTitle"],
        )

        def percentage_text(value: float | None) -> str:
            return "Not provided" if value is None else f"{value:.2f}%"

        def ratio_text(value: float | None) -> str:
            return "Not provided" if value is None else f"{value:.2f}"

        source_href = escape(str(fund.source_url), {'"': "&quot;"})
        source_value = Paragraph(
            '<link href="' + source_href + '" color="#1d5d8c">'
            "Open AdvisorKhoj source page</link><br/>"
            '<font size="6" color="#64748b">' + safe_paragraph(fund.source_url) + "</font>",
            styles["SourceValue"],
        )

        provenance_rows = [
            ("AMC", fund.amc_name or "Not provided"),
            ("Benchmark", fund.benchmark_name or "Not provided"),
            ("Launch date", fund.launch_date or "Not provided"),
            ("Analysis period", fund.period or "Not provided"),
            ("Scheme return", percentage_text(fund.scheme_return_percent)),
            ("Up-market capture", percentage_text(fund.up_capture_percent)),
            ("Down-market capture", percentage_text(fund.down_capture_percent)),
            ("Capture ratio", ratio_text(fund.capture_ratio)),
            ("Retrieved at (UTC)", fund.retrieved_at or "Not provided"),
            ("Source URL", source_value),
        ]
        provenance_table_rows = []
        for label, value in provenance_rows:
            label_cell = Paragraph(f"<b>{safe_paragraph(label)}</b>", styles["SourceLabel"])
            value_cell = value if isinstance(value, Paragraph) else Paragraph(
                safe_paragraph(value), styles["SourceValue"]
            )
            provenance_table_rows.append([label_cell, value_cell])

        provenance_table = Table(
            provenance_table_rows,
            colWidths=[37 * mm, 139 * mm],
            hAlign="LEFT",
        )
        provenance_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F8")),
            ("BACKGROUND", (1, 0), (1, -1), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D5DEE8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(KeepTogether([
            Spacer(1, 2 * mm),
            scheme_title,
            Spacer(1, 1 * mm),
            provenance_table,
            Spacer(1, 4 * mm),
        ]))
    story.extend([Paragraph("Important limitations", styles["SectionTitle"]), Paragraph(DISCLAIMER, styles["SmallBody"])])
    def add_page_number(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5B6770"))
        canvas.drawRightString(A4[0] - 17 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()
    document.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return output.getvalue()


@st.cache_data(ttl=3600, show_spinner=False)
def load_categories() -> list[str]:
    source_url = resolve_advisorkhoj_url(os.getenv("ADVISORKHOJ_URL", DEFAULT_SOURCE_URL))
    try:
        response = requests.get(
            source_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FundReportResearch/1.0)"},
            timeout=(10, 30),
        )
        response.raise_for_status()
        document = lxml_html.fromstring(response.content)
        categories = [
            re.sub(r"\s+", " ", value).strip()
            for value in document.xpath('//select[@id="sel_schemeCategories"]/option/text()')
        ]
        categories = [
            category for category in categories
            if category and normalize_name(category) not in {"select", "select category"}
        ]
        if not categories:
            raise ValueError("AdvisorKhoj did not expose any category options.")
        return categories
    except requests.RequestException as error:
        raise RuntimeError("Unable to load AdvisorKhoj categories. Try again later.") from error


def run_report(requested_funds: list[tuple[str, str]], period: str) -> tuple[list[FundCaptureData], list[dict[str, Any]], dict[str, Any], bytes]:
    funds: list[FundCaptureData] = []
    for index, (name, category) in enumerate(requested_funds, start=1):
        st.write(f"Retrieving AdvisorKhoj figures for {index} of {len(requested_funds)}: {name}")
        funds.append(fetch_one_fund(name, category, period))
    ranking = rank_funds(funds)
    analysis = request_ai_analysis(funds, ranking, period)
    pdf_bytes = build_pdf(funds, ranking, analysis, period)
    return funds, ranking, analysis, pdf_bytes



def safe_paragraph(value: Any) -> str:
    return escape(str(value))



def build_comparison_preview(
    funds: list[FundCaptureData],
    ranking: list[dict[str, Any]],
) -> pd.DataFrame:
    """Build a real-data preview in the same deterministic order as the report ranking."""
    funds_by_name = {fund.scheme_name: fund for fund in funds}
    rows: list[dict[str, Any]] = []
    for item in ranking:
        fund = funds_by_name[item["scheme_name"]]
        rows.append({
            "Rank": item["rank"],
            "Fund": fund.scheme_name,
            "Category": fund.category,
            "Benchmark": fund.benchmark_name,
            "Up-market capture (%)": fund.up_capture_percent,
            "Down-market capture (%)": fund.down_capture_percent,
            "Capture ratio": fund.capture_ratio,
        })
    return pd.DataFrame(rows)


def display_metric(value: float | None, suffix: str = "") -> str:
    """Format a retrieved metric for a compact visual summary without inventing missing data."""
    return "—" if value is None else f"{value:.2f}{suffix}"


def main() -> None:
    st.set_page_config(
        page_title="Fund Report | Market Capture Intelligence",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(
        """
        <style>
        :root { color-scheme: light; }
        .stApp, [data-testid="stAppViewContainer"] {
            background: #f3f6fa !important;
            color: #1d2939 !important;
        }
        [data-testid="stHeader"] {
            background: rgba(243, 246, 250, .92) !important;
        }
        .block-container {
            max-width: 1380px;
            padding: 1.5rem clamp(1rem, 3vw, 2.5rem) 3rem;
        }
        .stApp p, .stApp li, .stApp label, .stApp legend,
        .stApp [data-testid="stMarkdownContainer"],
        .stApp [data-testid="stWidgetLabel"] { color: #344054 !important; }
        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5 {
            color: #102a43 !important;
            letter-spacing: -.025em;
        }
        .stApp h1 { letter-spacing: -.04em; }
        [data-testid="stCaptionContainer"], .stCaption { color: #667085 !important; }
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #ffffff;
            border: 1px solid #e2e8f0 !important;
            border-radius: 16px !important;
            box-shadow: 0 2px 7px rgba(16, 42, 67, .035);
        }
        .stTextInput input, .stTextArea textarea, [data-baseweb="input"] input {
            background: #ffffff !important;
            color: #172b4d !important;
            -webkit-text-fill-color: #172b4d !important;
            border-color: #cbd5e1 !important;
            border-radius: 9px !important;
        }
        .stTextInput input::placeholder, .stTextArea textarea::placeholder {
            color: #7b8794 !important;
            -webkit-text-fill-color: #7b8794 !important;
            opacity: 1 !important;
        }
        [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        [data-baseweb="popover"], [role="listbox"], [role="option"] {
            background: #ffffff !important;
            color: #172b4d !important;
        }
        [data-testid="stSelectbox"] [data-baseweb="select"] *,
        [data-baseweb="popover"] *, [role="listbox"] *, [role="option"] * {
            color: #172b4d !important;
        }
        [data-testid="stRadio"] label, [data-testid="stRadio"] label p,
        [data-testid="stCheckbox"] label, [data-testid="stCheckbox"] label p {
            color: #344054 !important;
        }
        [data-testid="stAlert"] * { color: #344054 !important; }
        [data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
            min-height: 2.6rem;
            border-radius: 9px !important;
            font-weight: 650 !important;
            transition: background-color .15s ease, border-color .15s ease;
        }
        [data-testid="stButton"] button[kind="primary"],
        [data-testid="stDownloadButton"] button[kind="primary"] {
            background: #145c63 !important;
            border-color: #145c63 !important;
            color: #ffffff !important;
        }
        [data-testid="stButton"] button[kind="primary"]:hover,
        [data-testid="stDownloadButton"] button:hover {
            background: #0e464c !important;
            border-color: #0e464c !important;
            color: #ffffff !important;
        }
        [data-testid="stButton"] button[kind="secondary"] {
            background: #ffffff !important;
            color: #174c56 !important;
            border: 1px solid #bfd1d7 !important;
        }
        [data-testid="stButton"] button[kind="secondary"] * { color: #174c56 !important; }
        .fr-brand {
            display: flex; align-items: center; gap: 12px; margin-bottom: 1.1rem;
        }
        .fr-mark {
            display: flex; align-items: center; justify-content: center;
            width: 44px; height: 44px; border-radius: 12px;
            background: #123a4a; color: white; font-size: 20px; font-weight: 800;
            letter-spacing: -.04em;
        }
        .fr-brand-name { font-size: 1rem; font-weight: 750; color: #102a43; line-height: 1.25; }
        .fr-brand-sub { margin-top: 3px; font-size: .77rem; color: #667085; letter-spacing: .08em; text-transform: uppercase; }
        .fr-hero {
            padding: clamp(1.25rem, 3vw, 2rem);
            border-radius: 18px;
            background: #123a4a;
            color: #ffffff;
            margin-bottom: 1rem;
        }
        .fr-eyebrow { color: #b5dadd; font-size: .76rem; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
        .fr-hero h1 { color: #ffffff !important; margin: .45rem 0 .45rem; font-size: clamp(1.8rem, 4vw, 2.65rem); }
        .fr-hero p { color: #dcebed !important; max-width: 750px; margin: 0; font-size: 1rem; line-height: 1.65; }
        .fr-chip-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 1rem 0 1.4rem; }
        .fr-chip {
            background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
            padding: 14px 16px; min-width: 0;
        }
        .fr-chip-label { color: #667085; font-size: .76rem; font-weight: 650; text-transform: uppercase; letter-spacing: .06em; }
        .fr-chip-value { color: #123a4a; font-size: 1.08rem; font-weight: 750; margin-top: 5px; }
        .fr-chip-note { color: #667085; font-size: .8rem; margin-top: 3px; line-height: 1.4; }
        .fr-section-kicker { color: #14717a; text-transform: uppercase; letter-spacing: .1em; font-size: .73rem; font-weight: 750; }
        .fr-card-title { color: #102a43; font-weight: 750; font-size: 1.08rem; margin: .25rem 0 .2rem; }
        .fr-muted { color: #667085; font-size: .88rem; line-height: 1.5; }
        .fr-footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #dce4ec; color: #667085; font-size: .78rem; line-height: 1.6; }
        @media (max-width: 700px) {
            .block-container { padding: 1rem .75rem 2rem; }
            .fr-chip-row { grid-template-columns: 1fr; gap: 8px; }
            .fr-chip { padding: 11px 13px; }
            .fr-brand { margin-bottom: .8rem; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { transition: none !important; animation: none !important; }
        }
        </style>
        <div class="fr-brand">
          <div class="fr-mark">FR</div>
          <div>
            <div class="fr-brand-name">Fund Report</div>
            <div class="fr-brand-sub">Market Capture Intelligence</div>
          </div>
        </div>
        <section class="fr-hero">
          <div class="fr-eyebrow">Research workspace · Mutual funds</div>
          <h1>Compare how funds participate in markets.</h1>
          <p>Build a source-backed comparison with AdvisorKhoj market-capture figures, a transparent ranking rule, concise AI explanations, and a downloadable PDF. No portfolio balances or unsupported performance statistics are inferred.</p>
        </section>
        <div class="fr-chip-row">
          <div class="fr-chip"><div class="fr-chip-label">Comparison size</div><div class="fr-chip-value">2–10 schemes</div><div class="fr-chip-note">Choose between two and ten unique schemes.</div></div>
          <div class="fr-chip"><div class="fr-chip-label">Reporting windows</div><div class="fr-chip-value">1 · 3 · 5 · 10 years</div><div class="fr-chip-note">Use the same source period for every selected fund.</div></div>
          <div class="fr-chip"><div class="fr-chip-label">Primary data source</div><div class="fr-chip-value">AdvisorKhoj</div><div class="fr-chip-note">Scheme-level figures, benchmark and source URL.</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "fund_entries" not in st.session_state:
        st.session_state.fund_entries = [{"name": "", "category": ""} for _ in range(2)]
    if "last_report" not in st.session_state:
        st.session_state.last_report = None

    config_column, settings_column = st.columns([1.55, 0.85], gap="large")
    with config_column:
        with st.container(border=True):
            st.markdown('<div class="fr-section-kicker">Step 01</div>', unsafe_allow_html=True)
            st.subheader("Build your comparison")
            st.caption("Enter two to ten unique schemes. Each scheme uses its own AdvisorKhoj category.")
            with st.expander("Paste a list of fund names", expanded=False):
                pasted_names = st.text_area(
                    "Scheme names",
                    height=105,
                    placeholder="HDFC Large Cap Fund\nMirae Asset Large Cap Fund",
                    help="One scheme per line, or separate names with commas or semicolons.",
                    key="pasted_fund_names",
                )
                if st.button("Apply names to the form", use_container_width=True):
                    try:
                        names = parse_fund_names(pasted_names)
                        st.session_state.fund_entries = [{"name": name, "category": ""} for name in names]
                        for index in range(10):
                            st.session_state[f"fund_name_{index}"] = names[index] if index < len(names) else ""
                            st.session_state[f"fund_category_{index}"] = "Select category"
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))

            try:
                categories = load_categories()
                category_load_error = None
            except Exception as error:
                categories = []
                category_load_error = str(error)
                st.warning("AdvisorKhoj category choices are temporarily unavailable. You can enter the exact category label manually below.")

            for index, entry in enumerate(st.session_state.fund_entries):
                with st.container(border=True):
                    st.markdown(f'<div class="fr-section-kicker">Scheme {index + 1:02d}</div>', unsafe_allow_html=True)
                    name_column, category_column = st.columns([1.25, 1], gap="medium")
                    with name_column:
                        entry["name"] = st.text_input(
                            "Fund / scheme name",
                            value=entry["name"],
                            key=f"fund_name_{index}",
                            placeholder="e.g. HDFC Large Cap Fund Dir Gr",
                            help="Use Direct/Dir or Regular/Reg when multiple scheme variants exist.",
                        ).strip()
                    with category_column:
                        if categories:
                            options = ["Select category"] + categories
                            current = entry["category"] if entry["category"] in categories else "Select category"
                            selected_category = st.selectbox(
                                "AdvisorKhoj category",
                                options,
                                index=options.index(current),
                                key=f"fund_category_{index}",
                                help="Choose the source category that contains this scheme.",
                            )
                            entry["category"] = "" if selected_category == "Select category" else selected_category
                        else:
                            entry["category"] = st.text_input(
                                "AdvisorKhoj category",
                                value=entry["category"],
                                key=f"fund_category_text_{index}",
                                placeholder="Exact category label",
                            ).strip()

            count_column, action_column = st.columns([1, 1], gap="small")
            with count_column:
                st.caption(f"{len(st.session_state.fund_entries)} scheme slots · maximum 10")
            with action_column:
                add_column, remove_column = st.columns(2, gap="small")
                with add_column:
                    if st.button("＋ Add scheme", disabled=len(st.session_state.fund_entries) >= 10, use_container_width=True):
                        st.session_state.fund_entries.append({"name": "", "category": ""})
                        st.rerun()
                with remove_column:
                    if st.button("− Remove last", disabled=len(st.session_state.fund_entries) <= 2, use_container_width=True):
                        st.session_state.fund_entries.pop()
                        st.rerun()

    with settings_column:
        with st.container(border=True):
            st.markdown('<div class="fr-section-kicker">Step 02</div>', unsafe_allow_html=True)
            st.subheader("Report settings")
            selected_period = st.radio(
                "Analysis period",
                list(SUPPORTED_PERIODS.keys()),
                index=2,
                horizontal=True,
                help="Every selected scheme is retrieved for the same period.",
            )
            st.divider()
            st.markdown("**What the report includes**")
            st.markdown(
                "- Market-capture figures and each scheme's benchmark\n"
                "- A deterministic order using capture ratio when available\n"
                "- AI explanations validated against the selected schemes and ranks\n"
                "- PDF with source links, retrieval timestamps and disclosures"
            )
            st.info("Benchmark and category differences matter. This report is a research aid, not personalized investment advice.")
            st.markdown("**Required configuration**")
            if os.getenv("OPENAI_API_KEY", "").strip():
                st.markdown("✓ AI provider key detected in the local/hosting environment.")
            else:
                st.warning("AI analysis is not configured. Add OPENAI_API_KEY to the environment or local .env file.")
            if st.button("Generate report & prepare PDF", type="primary", use_container_width=True):
                clean_entries = [
                    (entry["name"].strip(), entry["category"].strip())
                    for entry in st.session_state.fund_entries
                    if entry["name"].strip()
                ]
                normalized_names = [normalize_name(name) for name, _ in clean_entries]
                if not 2 <= len(clean_entries) <= 10:
                    st.error("Select between 2 and 10 funds before generating a report.")
                elif len(set(normalized_names)) != len(normalized_names):
                    st.error("Duplicate fund names were found. Keep only unique funds.")
                elif any(not category for _, category in clean_entries):
                    st.error("Choose an AdvisorKhoj category for every selected fund.")
                elif len(clean_entries) != len(st.session_state.fund_entries):
                    st.error("Fill in every scheme slot or remove unused slots before generating.")
                elif selected_period not in SUPPORTED_PERIODS:
                    st.error("Choose one of the supported periods.")
                else:
                    try:
                        with st.status("Generating your report…", expanded=True) as status:
                            funds, ranking, analysis, pdf_bytes = run_report(clean_entries, selected_period)
                            status.update(label="Report generated", state="complete", expanded=False)
                        st.session_state.last_report = {
                            "funds": funds,
                            "ranking": ranking,
                            "analysis": analysis,
                            "pdf_bytes": pdf_bytes,
                            "period": selected_period,
                            "generated_at": datetime.now().astimezone().strftime("%d %b %Y, %H:%M %Z"),
                        }
                        st.success("Report generated from retrieved source figures and validated AI output.")
                    except Exception as error:
                        st.error(str(error))
                        st.caption("No sample or fabricated report is substituted when source retrieval or AI analysis fails.")

    report = st.session_state.last_report
    st.markdown("")
    if report:
        toolbar_left, toolbar_right = st.columns([0.72, 0.28], gap="medium")
        with toolbar_left:
            st.markdown('<div class="fr-section-kicker">Step 03 · Results</div>', unsafe_allow_html=True)
            st.header("Comparison report")
            st.caption(f"Last generated: {report['generated_at']} · Period: {report['period']} · {len(report['funds'])} schemes")
        with toolbar_right:
            st.markdown("<div style='height:1.65rem'></div>", unsafe_allow_html=True)
            if st.button("Clear report", use_container_width=True):
                st.session_state.last_report = None
                st.rerun()

        funds = report["funds"]
        ranking = report["ranking"]
        analysis = report["analysis"]
        metric_columns = st.columns(4, gap="medium")
        top_fund = ranking[0]["scheme_name"] if ranking else "—"
        metric_values = [
            ("Schemes compared", str(len(funds))),
            ("Analysis period", report["period"]),
            ("Highest-ranked scheme", top_fund),
            ("Verified source rows", f"{len(funds)} of {len(funds)}"),
        ]
        for column, (label, value) in zip(metric_columns, metric_values):
            with column:
                with st.container(border=True):
                    st.caption(label)
                    st.markdown(f"<div style='font-size:1.05rem;font-weight:750;color:#123a4a;overflow-wrap:anywhere'>{safe_paragraph(value)}</div>", unsafe_allow_html=True)

        st.markdown("")
        with st.container(border=True):
            st.subheader("Executive summary")
            st.write(analysis["overall_summary"])
            st.caption("Ranks are calculated by the application. AI explanations describe the retrieved data and are not allowed to change the rank order.")

        st.subheader("Ranking and market-capture metrics")
        preview = build_comparison_preview(funds, ranking)
        st.dataframe(
            preview,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", format="%d"),
                "Up-market capture (%)": st.column_config.NumberColumn("Up-market capture (%)", format="%.2f"),
                "Down-market capture (%)": st.column_config.NumberColumn("Down-market capture (%)", format="%.2f"),
                "Capture ratio": st.column_config.NumberColumn("Capture ratio", format="%.2f"),
            },
        )
        st.caption("Rows are ordered by capture ratio where available; if unavailable, the documented fallback score is up-capture minus down-capture. Benchmark differences can limit direct comparability.")

        chart_column, notes_column = st.columns([1.15, 0.85], gap="large")
        with chart_column:
            with st.container(border=True):
                st.subheader("Upside and downside participation")
                chart_data = preview.set_index("Fund")[["Up-market capture (%)", "Down-market capture (%)"]]
                st.bar_chart(chart_data, use_container_width=True, height=320)
                st.caption("Percentages are source-reported market-capture metrics, not fund returns.")
        with notes_column:
            with st.container(border=True):
                st.subheader("How to read these figures")
                st.markdown(
                    "- **Up-market capture:** participation in rising benchmark periods.\n"
                    "- **Down-market capture:** participation in falling benchmark periods.\n"
                    "- **Capture ratio:** AdvisorKhoj’s reported ratio; the app uses this for the primary ranking when available."
                )
                st.caption("This ranking is one comparison lens, not an investment suitability model.")

        st.subheader("AI analysis by scheme")
        analyses_by_name = {item["scheme_name"]: item for item in analysis["funds"]}
        for item in ranking:
            fund_analysis = analyses_by_name[item["scheme_name"]]
            fund = next(fund for fund in funds if fund.scheme_name == item["scheme_name"])
            with st.expander(f"Rank {item['rank']} · {item['scheme_name']}", expanded=(item["rank"] == 1)):
                st.caption(f"{fund.category} · Benchmark: {fund.benchmark_name} · {report['period']}")
                st.markdown("**Why this rank**")
                st.write(fund_analysis["reason"])
                strengths = fund_analysis["strengths"]
                limitations = fund_analysis["limitations"]
                if isinstance(strengths, list):
                    strengths = "; ".join(str(value) for value in strengths)
                if isinstance(limitations, list):
                    limitations = "; ".join(str(value) for value in limitations)
                strength_column, limitation_column = st.columns(2, gap="medium")
                with strength_column:
                    st.markdown("**Strengths noted**")
                    st.write(strengths)
                with limitation_column:
                    st.markdown("**Limitations to keep in mind**")
                    st.write(limitations)

        st.markdown("")
        download_column, provenance_column = st.columns([1, 1.25], gap="large")
        with download_column:
            with st.container(border=True):
                st.subheader("Download report")
                st.write("PDF includes the comparison, AI explanations, source links, retrieval timestamps and disclaimer.")
                filename = f"mutual-fund-market-capture-{report['period'].replace(' ', '-')}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
                st.download_button(
                    "↓ Download PDF report",
                    data=report["pdf_bytes"],
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                )
        with provenance_column:
            with st.container(border=True):
                st.subheader("Data provenance")
                st.caption("Figures are retrieved live for this report. Open each source page to review the captured row.")
                for fund in funds:
                    st.markdown(f"**{safe_paragraph(fund.scheme_name)}**")
                    st.markdown(f"[Open AdvisorKhoj source page]({fund.source_url})")
                    st.caption(f"Benchmark: {fund.benchmark_name} · Retrieved at {fund.retrieved_at}")
    else:
        with st.container(border=True):
            st.markdown('<div class="fr-section-kicker">Step 03 · Results</div>', unsafe_allow_html=True)
            st.subheader("Your comparison will appear here")
            st.markdown(
                "After you generate a report, this area shows the verified source figures, "
                "deterministic ranking, AI notes, comparison chart and PDF download."
            )
            st.caption("No sample fund values are shown in the empty state.")

    st.markdown(
        """
        <div class="fr-footer">
          <strong>Data and risk note</strong><br/>
          Market-capture metrics describe historical participation relative to a benchmark. They are not fund returns and do not guarantee future outcomes. This tool provides educational information, not individualized investment advice.
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
