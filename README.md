# Fund Report — Mutual Fund Market Capture Intelligence

A Python/Streamlit application for comparing mutual fund schemes using market-capture figures, generating an explainable ranking, requesting an AI-written interpretation, and exporting the results as a PDF.

## Project status

- **Automated tests:** 36 passed in 5.47 seconds in the latest local run reported on October 9, 2026.
- **Manual verification:** The latest Streamlit UI and a freshly generated PDF were confirmed by the project owner.
- **GitHub workflow:** Development is on `feature/fund-report-app`; pull request #1 is open as a draft and has not been merged.
- **Public deployment:** Not verified. The app is currently run locally.
- **Data-source authorization:** Confirm permission or an appropriate official data interface with AdvisorKhoj before sustained or commercial use.

## Features

- Compare 2–10 unique mutual fund schemes.
- Enter scheme names directly or paste a list, and select a category for each fund.
- Choose a 1-, 3-, 5-, or 10-year period.
- Retrieve scheme, benchmark, up-capture, down-capture, and capture-ratio data from the AdvisorKhoj Market Capture Ratio tool.
- Rank funds deterministically using source capture-ratio data and a documented treatment of negative ratios.
- Ask an OpenAI-compatible language model to explain the precomputed ranking; validate the response and do not let the model change the ranks.
- Review a comparison table, a chart based on retrieved values, and per-fund AI explanations.
- Generate a selectable-text PDF with figures, ranking, explanations, source provenance and links, retrieval timestamps, and a financial-risk disclaimer.
- Show actionable errors rather than substituting fabricated or static fund data.

## Architecture

This is a **single-page Streamlit application**. Retrieval, normalization, deterministic ranking, AI-provider integration, report rendering, and PDF creation are implemented in `app.py`. Automated regression tests are in `tests/test_core.py`.

The main data flow is:

1. Resolve the entered scheme name against the source's scheme suggestions.
2. Retrieve and validate the matching source result for the selected category and period.
3. Calculate the deterministic order using the reported capture ratio.
4. Request AI explanations for that order and validate the returned JSON.
5. Display the comparison and generate the PDF.

## Technology

- Python and Streamlit
- requests and lxml for source retrieval and HTML parsing
- pandas for table extraction and data normalization
- An OpenAI-compatible Chat Completions endpoint for AI explanations
- ReportLab for PDF generation
- pytest for automated tests

## Requirements

- Python 3.11 or newer
- Network access to the configured data source
- A reachable OpenAI-compatible AI endpoint and valid API key for AI report generation

## Local setup (Windows PowerShell)

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit the local `.env` file and configure the AI provider values. Do not commit real API keys.

Start the application:

```powershell
streamlit run app.py
```

Open the local URL printed by Streamlit, typically:

```text
http://localhost:8501
```

Run the automated tests:

```powershell
python -m pytest -q
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | API credential for the configured AI endpoint; required for AI report generation |
| `OPENAI_MODEL` | Model identifier supported by the provider; defaults to `gpt-4o-mini` |
| `OPENAI_BASE_URL` | OpenAI-compatible API root; defaults to `https://api.openai.com/v1` |
| `ADVISORKHOJ_URL` | AdvisorKhoj Market Capture Ratio page URL |

Keep credentials in an untracked local `.env` file or the hosting provider's secret settings. Never hard-code credentials in source code or commit them to GitHub.

## Data source and interpretation

The application uses the [AdvisorKhoj Market Capture Ratio tool](https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio). Its retrieval adapter uses the page-referenced scheme-suggestion endpoint and parses the results page. Because this depends on a website interface rather than a configured official API, changes to the page, access restrictions, or network failures may stop retrieval. Scheme names, category labels, and periods must match the options supported by the source.

The app requires a valid source capture ratio for each fund and stops with an actionable error if required data is unavailable. It does not substitute an up-minus-down fallback score or invent missing data. Ranking is a simple disclosed comparison heuristic, not an investment-suitability model or a return forecast. Different categories and benchmarks can limit the direct comparability of funds.

**Before sustained or commercial use, confirm authorization or obtain an appropriate official data interface from AdvisorKhoj.**

## AI and PDF safeguards

- Deterministic ranking is calculated before AI explanation.
- AI output is checked for valid JSON shape, complete fund coverage, and rank consistency.
- Model-generated text is escaped before being rendered into PDF paragraphs.
- Duplicate schemes are checked after canonical source resolution.
- PDF provenance includes source references and clickable links.
- The latest reported local test suite contains 36 passing cases; the project owner also confirmed the latest UI and PDF review.

## Deployment notes

A Render blueprint is included in `render.yaml`, but a public deployment has not been verified. Before hosting, configure an AI endpoint reachable from the hosting environment, add credentials through secret settings, review provider costs/quotas, and protect public access so the endpoint cannot be abused.

A local URL such as `http://localhost:3002` for FreeLLMAPI will point to the hosted container itself—not to a service running on the developer's PC—when deployed remotely. Configure a reachable, securely protected endpoint for the hosted app.

## Financial disclaimer

Mutual fund investments are subject to market risks. Market-capture figures describe historical behavior relative to a benchmark and do not guarantee future performance. This app provides informational research only and does not provide individualized financial advice. Review scheme documents and consult a qualified financial adviser before making investment decisions.
