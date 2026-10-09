import io
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
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
)

load_dotenv()

DEFAULT_SOURCE_URL = "https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio"
SUPPORTED_PERIODS = {"1 year": "1 Year", "3 years": "3 Years", "5 years": "5 Years", "10 years": "10 Years"}
DISCLAIMER = (
    "This report is for educational and informational purposes only. It is not investment advice, "
    "a recommendation to buy or sell a security, or a guarantee of future performance. Mutual fund "
    "investments are subject to market risks. Past performance may not continue. Review scheme documents "
    "and consult a qualified financial adviser before making investment decisions."
)


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
    for column in table.columns:
        if phrase.casefold() in re.sub(r"\s+", " ", str(column)).casefold():
            return column
    return None


def source_select_options(page: Any) -> tuple[Any, Any, list[str]]:
    select_count = page.locator("select").count()
    category_control = None
    period_control = None
    categories: list[str] = []
    for index in range(select_count):
        control = page.locator("select").nth(index)
        if not control.is_visible():
            continue
        options = control.locator("option").all_text_contents()
        options = [re.sub(r"\s+", " ", option).strip() for option in options if option.strip()]
        if not options:
            continue
        normalized_options = [option.casefold() for option in options]
        if period_control is None and sum(bool(re.search(r"\b(?:1|3|5|10)\s*(?:year|yr)", option)) for option in normalized_options) >= 2:
            period_control = control
        if category_control is None and any(
            keyword in " ".join(normalized_options)
            for keyword in ("equity", "debt", "hybrid", "large cap", "small cap")
        ):
            category_control = control
            categories = options
    if category_control is None or period_control is None:
        raise ValueError("Could not identify AdvisorKhoj category and period controls. The source page may have changed.")
    return category_control, period_control, categories


def choose_option(control: Any, requested: str) -> str:
    options = control.locator("option").evaluate_all(
        "(elements) => elements.map((element) => ({label: element.textContent.trim(), value: element.value}))"
    )
    requested_normalized = normalize_name(requested)
    for option in options:
        if normalize_name(option["label"]) == requested_normalized and option["value"]:
            control.select_option(option["value"])
            return option["label"]
    for option in options:
        if requested_normalized in normalize_name(option["label"]) and option["value"]:
            control.select_option(option["value"])
            return option["label"]
    raise ValueError(f"AdvisorKhoj does not offer the requested option: {requested}")


def locate_fund_input(page: Any) -> Any:
    inputs = page.locator("input:visible")
    candidates = []
    for index in range(inputs.count()):
        candidate = inputs.nth(index)
        input_type = (candidate.get_attribute("type") or "text").casefold()
        placeholder = (candidate.get_attribute("placeholder") or "").casefold()
        name = (candidate.get_attribute("name") or "").casefold()
        if input_type in {"text", "search"} and "search funds" not in placeholder and "search" not in name:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("Could not identify the AdvisorKhoj fund search input.")
    for candidate in candidates:
        descriptor = " ".join(
            [
                candidate.get_attribute("placeholder") or "",
                candidate.get_attribute("name") or "",
                candidate.get_attribute("id") or "",
            ]
        ).casefold()
        if "fund" in descriptor or "scheme" in descriptor:
            return candidate
    return candidates[0]


def select_suggestion(page: Any, requested_name: str) -> str:
    deadline = time.monotonic() + 5
    requested_normalized = normalize_name(requested_name)
    while time.monotonic() < deadline:
        for selector in ['[role="option"]', ".ui-menu-item", ".autocomplete-suggestion", "li"]:
            items = page.locator(selector)
            for index in range(min(items.count(), 40)):
                item = items.nth(index)
                try:
                    if not item.is_visible():
                        continue
                    label = re.sub(r"\s+", " ", item.inner_text()).strip()
                    normalized_label = normalize_name(label)
                    if normalized_label and (
                        requested_normalized in normalized_label or normalized_label in requested_normalized
                    ):
                        item.click(timeout=1000)
                        return label
                except Exception:
                    continue
        page.wait_for_timeout(250)
    raise ValueError(f"AdvisorKhoj could not resolve '{requested_name}' to a listed scheme.")


def submit_source_form(page: Any) -> None:
    buttons = page.get_by_role("button", name=re.compile(r"submit", re.I))
    if buttons.count():
        buttons.first.click()
    else:
        submits = page.locator('input[type="submit"]:visible')
        if not submits.count():
            raise ValueError("Could not identify the AdvisorKhoj Submit control.")
        submits.first.click()
    page.wait_for_timeout(900)


def fetch_one_fund(requested_name: str, category: str, period: str) -> FundCaptureData:
    source_url = os.getenv("ADVISORKHOJ_URL", DEFAULT_SOURCE_URL)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.set_default_timeout(8000)
            page.goto(source_url, wait_until="domcontentloaded", timeout=25000)
            category_control, period_control, _ = source_select_options(page)
            selected_category = choose_option(category_control, category)
            selected_period = choose_option(period_control, SUPPORTED_PERIODS[period])
            fund_input = locate_fund_input(page)
            fund_input.fill(requested_name)
            page.wait_for_timeout(500)
            selected_scheme = select_suggestion(page, requested_name)
            submit_source_form(page)
            tables = pd.read_html(io.StringIO(page.content()))
            capture_table = identify_capture_table(tables)
            scheme_column = column_for(capture_table, "scheme name")
            if scheme_column is None:
                scheme_column = capture_table.columns[0]
            matching_rows = capture_table[
                capture_table[scheme_column].astype(str).map(
                    lambda name: normalize_name(name) == normalize_name(selected_scheme)
                    or normalize_name(requested_name) in normalize_name(name)
                )
            ]
            if matching_rows.empty:
                raise ValueError(f"AdvisorKhoj returned no capture data for '{requested_name}'.")
            row = matching_rows.iloc[0]
            def value_for(phrase: str) -> Any:
                column = column_for(capture_table, phrase)
                return row[column] if column is not None else None
            data = FundCaptureData(
                requested_name=requested_name,
                scheme_name=str(row[scheme_column]).strip(),
                category=selected_category,
                period=selected_period,
                amc_name=str(value_for("amc name") or "Not provided"),
                benchmark_name=str(value_for("benchmark name") or "Not provided"),
                launch_date=str(value_for("launch date") or "Not provided"),
                scheme_return_percent=parse_numeric(value_for("scheme return")),
                up_capture_percent=parse_numeric(value_for("up market capture ratio")),
                down_capture_percent=parse_numeric(value_for("down market capture ratio")),
                capture_ratio=parse_numeric(value_for("capture ratio")),
                source_url=source_url,
                retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            if data.up_capture_percent is None or data.down_capture_percent is None:
                raise ValueError(f"AdvisorKhoj returned incomplete capture figures for '{requested_name}'.")
            return data
    except PlaywrightTimeoutError as error:
        raise RuntimeError(f"AdvisorKhoj timed out while retrieving '{requested_name}'. Try again later.") from error
    except (ValueError, RuntimeError):
        raise
    except Exception as error:
        raise RuntimeError(
            f"Unable to retrieve verified AdvisorKhoj data for '{requested_name}'. "
            "The source may have changed or may be temporarily unavailable."
        ) from error
    finally:
        try:
            browser.close()
        except Exception:
            pass


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
    for fund in funds:
        story.append(Paragraph(
            f"<b>{fund.scheme_name}</b><br/>AMC: {fund.amc_name} | Benchmark: {fund.benchmark_name} | "
            f"Launch date: {fund.launch_date}<br/>Scheme return: {fund.scheme_return_percent if fund.scheme_return_percent is not None else 'Not provided'}% | "
            f"Up capture: {fund.up_capture_percent}% | Down capture: {fund.down_capture_percent}% | "
            f"Capture ratio: {fund.capture_ratio if fund.capture_ratio is not None else 'Not provided'}<br/>"
            f"Retrieved: {fund.retrieved_at}<br/>Source: {fund.source_url}",
            styles["SmallBody"],
        ))
    story.extend([Paragraph("Important limitations", styles["SectionTitle"]), Paragraph(DISCLAIMER, styles["SmallBody"])])
    def add_page_number(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5B6770"))
        canvas.drawRightString(A4[0] - 17 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()
    document.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return output.getvalue()


def load_categories() -> list[str]:
    source_url = os.getenv("ADVISORKHOJ_URL", DEFAULT_SOURCE_URL)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(source_url, wait_until="domcontentloaded", timeout=25000)
            _, _, categories = source_select_options(page)
            return [category for category in categories if category and normalize_name(category) not in {"select", "select category"}]
        finally:
            browser.close()


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


def main() -> None:
    st.set_page_config(page_title="Fund Report | Market Capture Intelligence", page_icon="📊", layout="wide")
    st.markdown(
        """
        <style>
        .stApp { background: #f5f7fb; }
        .block-container { max-width: 1120px; padding-top: 2rem; }
        .hero { padding: 1.7rem 2rem; border-radius: 18px; background: linear-gradient(120deg,#14324a,#246b78); color: white; margin-bottom: 1.5rem; }
        .hero h1 { color: white; margin-bottom: .4rem; }
        .hero p { color: #e5f0f4; font-size: 1.05rem; }
        </style>
        <div class="hero">
          <h1>Fund Report</h1>
          <p>Compare mutual funds using AdvisorKhoj market capture figures and evidence-based AI explanations.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "fund_entries" not in st.session_state:
        st.session_state.fund_entries = [{"name": "", "category": ""} for _ in range(2)]

    with st.expander("How this report works", expanded=False):
        st.write("The application retrieves each fund's figures from AdvisorKhoj, calculates a deterministic comparison order, and asks the configured language model to explain the evidence. Missing source figures stop report generation instead of being invented.")
        st.caption("Market capture ratios are only one comparison lens. This report is educational and is not individualized investment advice.")

    left, right = st.columns([1.2, 0.8], gap="large")
    with left:
        st.subheader("1. Choose your funds")
        st.write("Select 2–10 unique funds. Each fund can use its own AdvisorKhoj category.")
        pasted_names = st.text_area("Paste fund names (one per line, or comma-separated)", height=100, placeholder="HDFC Large Cap Fund\nMirae Asset Large Cap Fund")
        if st.button("Fill fund fields from pasted list", use_container_width=True):
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
            categories = st.cache_data(ttl=3600, show_spinner=False)(load_categories)()
        except Exception:
            categories = []
            st.warning("AdvisorKhoj category options could not be loaded right now. Refresh later; categories are not guessed.")
        if not categories:
            categories = []
        for index, entry in enumerate(st.session_state.fund_entries):
            st.markdown(f"**Fund {index + 1}**")
            name_column, category_column = st.columns([1.5, 1])
            with name_column:
                entry["name"] = st.text_input(f"Fund name {index + 1}", value=entry["name"], key=f"fund_name_{index}", label_visibility="collapsed", placeholder="Search or enter exact fund name")
            with category_column:
                if categories:
                    options = ["Select category"] + categories
                    current = entry["category"] if entry["category"] in categories else "Select category"
                    selected_category = st.selectbox(f"Category {index + 1}", options, index=options.index(current), key=f"fund_category_{index}", label_visibility="collapsed")
                    entry["category"] = "" if selected_category == "Select category" else selected_category
                else:
                    entry["category"] = st.text_input(f"Category {index + 1}", value=entry["category"], key=f"fund_category_text_{index}", label_visibility="collapsed", placeholder="AdvisorKhoj category")
        add_column, remove_column = st.columns(2)
        with add_column:
            if st.button("＋ Add fund", disabled=len(st.session_state.fund_entries) >= 10, use_container_width=True):
                st.session_state.fund_entries.append({"name": "", "category": ""})
                st.rerun()
        with remove_column:
            if st.button("− Remove last fund", disabled=len(st.session_state.fund_entries) <= 2, use_container_width=True):
                st.session_state.fund_entries.pop()
                st.rerun()

    with right:
        st.subheader("2. Set the period")
        selected_period = st.radio("Analysis period", list(SUPPORTED_PERIODS.keys()), index=2)
        st.info("AdvisorKhoj currently displays up to four funds in its own comparison form. This app queries each selected fund separately so reports can include up to ten.")
        st.subheader("3. Generate your report")
        st.write("A configured OpenAI-compatible API key is required for the AI explanations.")
        generate = st.button("Generate report & prepare PDF", type="primary", use_container_width=True)

    if generate:
        clean_entries = [(entry["name"].strip(), entry["category"].strip()) for entry in st.session_state.fund_entries if entry["name"].strip()]
        normalized_names = [normalize_name(name) for name, _ in clean_entries]
        if not 2 <= len(clean_entries) <= 10:
            st.error("Select between 2 and 10 funds before generating a report.")
        elif len(set(normalized_names)) != len(normalized_names):
            st.error("Duplicate fund names were found. Keep only unique funds.")
        elif any(not category for _, category in clean_entries):
            st.error("Choose an AdvisorKhoj category for every selected fund.")
        elif selected_period not in SUPPORTED_PERIODS:
            st.error("Choose one of the supported periods.")
        else:
            try:
                with st.status("Generating your report…", expanded=True) as status:
                    funds, ranking, analysis, pdf_bytes = run_report(clean_entries, selected_period)
                    status.update(label="Report generated", state="complete", expanded=False)
                st.success("The report was generated using retrieved source figures and validated AI output.")
                st.subheader("Comparison preview")
                st.write(analysis["overall_summary"])
                preview = []
                analysis_by_name = {item["scheme_name"]: item for item in analysis["funds"]}
                for item in ranking:
                    explanation = analysis_by_name[item["scheme_name"]]
                    preview.append({
                        "Rank": item["rank"],
                        "Fund": item["scheme_name"],
                        "Up capture (%)": item["up_capture_percent"],
                        "Down capture (%)": item["down_capture_percent"],
                        "Capture ratio": item["capture_ratio"],
                        "Reason": explanation["reason"],
                    })
                st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)
                filename = f"mutual-fund-market-capture-{selected_period.replace(' ', '-')}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
                st.download_button("Download PDF report", data=pdf_bytes, file_name=filename, mime="application/pdf", use_container_width=True)
            except Exception as error:
                st.error(str(error))
                st.caption("No sample or fabricated report is substituted when source retrieval or AI analysis fails.")


if __name__ == "__main__":
    main()
