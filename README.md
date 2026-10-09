# Fund Report — Market Capture Intelligence

A Streamlit application for comparing 2–10 mutual funds using AdvisorKhoj Market Capture Ratio figures, a configured OpenAI-compatible language model, and a generated PDF report.

## Current status

This repository started empty. The app now uses AdvisorKhoj's page-referenced scheme suggestion endpoint and a direct request to the public Market Capture Ratio results page, one scheme at a time. The live lookup has been manually verified for the canonical Parag Parikh Flexi Cap Direct Growth and Regular Growth labels; the full multi-fund-to-AI-to-PDF workflow and deployment still require end-to-end verification.

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
- requests and lxml for AdvisorKhoj scheme suggestions, category options, and results-page parsing
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
Copy-Item .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY`. Never commit the real key. The default model is `gpt-4o-mini`; configure a model available to your provider using `OPENAI_MODEL`. An OpenAI-compatible endpoint can be supplied through `OPENAI_BASE_URL`.

Run the application:

```powershell
streamlit run app.py
```

Run tests:

```powershell
python -m pytest -q
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

The source page is interactive. The scraper queries the scheme-suggestion endpoint referenced by the page's own JavaScript, then requests the public results page for the resolved canonical scheme label, category, and period. It validates that exactly one matching row contains both capture columns. When a generic name maps to multiple variants (for example, Direct and Regular Growth), it asks the user to enter a distinguishing/exact scheme label rather than silently choosing. Page changes, access restrictions, and network failures are surfaced as errors. For sustained or commercial use, obtain permission or an official data interface from AdvisorKhoj.

## Ranking and AI safeguards

The app orders funds using the source capture ratio when available. If that ratio is missing, it uses up capture minus down capture as a transparent fallback score. This is a simple comparison heuristic, not an investment suitability model. The LLM is asked to explain the existing deterministic order rather than set or change ranks. Its response is checked for complete fund coverage and ranking consistency before the PDF is generated.

## Deployment

A Render blueprint is included in `render.yaml`. To deploy:

1. Push this repository to GitHub.
2. Create a new Render Blueprint deployment from the repository.
3. Set `OPENAI_API_KEY` in Render's environment settings.
4. Confirm the selected plan and any possible charges before deploying.
5. Open the public URL and test source retrieval, AI analysis, and PDF download with real data.

The blueprint installs Python dependencies without a browser binary. Hosting plan limits, outbound requests, source availability, and request execution time must still be validated in the actual deployment. No live URL is claimed by this repository until a public deployment has been completed and checked.

## Known limitations before production use

- Live single-scheme retrieval has been manually tested, but the full 2–10 scheme, AI, and PDF workflow still requires end-to-end verification.
- Generic names that match multiple source variants must be made explicit (for example, Direct Growth vs Regular Growth).
- The current source interface's available categories and period labels may change.
- There is no official AdvisorKhoj API credential configured in this project.
- LLM availability and cost depend on the configured provider and account.
- No genuine sample report is checked in because one must be generated from live, retrieved figures.
- The app is informational and does not provide individualized financial advice.

## Financial disclaimer

Mutual fund investments are subject to market risks. Market capture figures describe historical behavior against a benchmark and do not guarantee future returns. The generated report is educational only, not investment advice. Review scheme documents and consult a qualified financial adviser before making investment decisions.
