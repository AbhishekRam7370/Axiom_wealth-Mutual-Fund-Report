# Fund Report — Market Capture Intelligence

A Streamlit application for comparing 2–10 mutual funds using AdvisorKhoj Market Capture Ratio figures, a configured OpenAI-compatible language model, and a generated PDF report.

## Current status

This repository started empty. The application scaffold is implemented, but the AdvisorKhoj browser interaction and live deployment have not yet been verified end to end. The source page is interactive and currently describes a comparison form that accepts up to four funds; this application attempts one fund at a time to support a report of up to ten. Do not treat the integration as production-verified until it has been tested against the live source and the current page controls.

The app deliberately fails when it cannot resolve a fund or retrieve its required capture figures. It does not substitute demo figures or a static sample report.

## Features

- Enter fund names directly or paste a list.
- Select 2–10 unique funds and a category for each fund.
- Choose a 1-, 3-, 5-, or 10-year analysis period.
- Retrieve scheme, benchmark, up-capture, down-capture, and capture-ratio figures from the AdvisorKhoj Market Capture Ratio tool.
- Calculate a deterministic ranking before requesting the LLM explanation.
- Validate the AI response for complete fund coverage and consistent ranking.
- Generate a selectable-text PDF containing figures, ranking, explanations, source provenance, retrieval timestamps, and a risk disclaimer.
- Show actionable errors instead of inventing missing data.

## Technology

- Python and Streamlit
- Playwright Chromium for the interactive AdvisorKhoj form
- pandas for table extraction and normalization
- OpenAI-compatible Chat Completions API for narrative explanations
- ReportLab for PDF generation
- pytest for automated tests

## Local setup

Use Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY`. Never commit the real key. The default model is `gpt-4o-mini`; configure a model available to your provider using `OPENAI_MODEL`. An OpenAI-compatible endpoint can be supplied through `OPENAI_BASE_URL`.

Run the application:

```powershell
streamlit run app.py
```

Run tests:

```powershell
pytest -q
```

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes for report generation | Server-side API credential for the language model |
| `OPENAI_MODEL` | No | Model identifier; defaults to `gpt-4o-mini` |
| `OPENAI_BASE_URL` | No | OpenAI-compatible API root; defaults to `https://api.openai.com/v1` |
| `ADVISORKHOJ_URL` | No | AdvisorKhoj Market Capture Ratio page URL |

The key must remain in the hosting provider's secret settings or a local, untracked `.env` file. Never place it in frontend code or commit it.

## Data retrieval and interpretation

The primary source is [AdvisorKhoj Market Capture Ratio](https://www.advisorkhoj.com/mutual-funds-research/market-capture-ratio). Its published explanation describes up-market capture as participation during rising benchmark periods, down-market capture as participation during falling benchmark periods, and capture ratio as the relationship between the two. A lower down-market capture can indicate less downside participation, while a higher up-market capture can indicate more upside participation. Benchmark differences and fund category still matter.

The source page is interactive. The scraper selects the category and period on the source page, resolves the requested fund through its suggestion list, submits the form, and validates that the returned table contains both capture columns. Page structure changes, access restrictions, or network failures are surfaced as errors. No unauthorized API or undocumented endpoint is assumed. AdvisorKhoj states on its research pages that mutual fund distributors seeking APIs may contact it; for sustained or commercial use, obtain permission or an official data interface.

## Ranking and AI safeguards

The app orders funds using the source capture ratio when available. If that ratio is missing, it uses up capture minus down capture as a transparent fallback score. This is a simple comparison heuristic, not an investment suitability model. The LLM is asked to explain the existing deterministic order rather than set or change ranks. Its response is checked for complete fund coverage and ranking consistency before the PDF is generated.

## Deployment

A Render blueprint is included in `render.yaml`. To deploy:

1. Push this repository to GitHub.
2. Create a new Render Blueprint deployment from the repository.
3. Set `OPENAI_API_KEY` in Render's environment settings.
4. Confirm the selected plan and any possible charges before deploying.
5. Open the public URL and test source retrieval, AI analysis, and PDF download with real data.

The blueprint uses Chromium installation during build. Hosting plan limits, browser dependencies, outbound requests, and request execution time must be validated in the actual deployment. No live URL is claimed by this repository until a public deployment has been completed and checked.

## Known limitations before production use

- The live AdvisorKhoj form interaction still requires real end-to-end verification.
- The current source interface's available categories and period labels may change.
- There is no official AdvisorKhoj API credential configured in this project.
- LLM availability and cost depend on the configured provider and account.
- No genuine sample report is checked in because one must be generated from live, retrieved figures.
- The app is informational and does not provide individualized financial advice.

## Financial disclaimer

Mutual fund investments are subject to market risks. Market capture figures describe historical behavior against a benchmark and do not guarantee future returns. The generated report is educational only, not investment advice. Review scheme documents and consult a qualified financial adviser before making investment decisions.
