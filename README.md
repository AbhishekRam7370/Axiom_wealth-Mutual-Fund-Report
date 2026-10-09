# Fund Report — Market Capture Intelligence

A Streamlit application for comparing 2–10 mutual funds using AdvisorKhoj Market Capture Ratio figures, a configured OpenAI-compatible language model, and a generated PDF report.

## Current status

The developer confirmed the local source → AI analysis → PDF workflow is working with AdvisorKhoj retrieval and the existing FreeLLMAPI OpenAI-compatible endpoint. Live source retrieval was checked for Parag Parikh Flexi Cap Direct Growth and Mirae Asset Large Cap Direct Growth for 1-, 3-, 5-, and 10-year periods. The 5-year capture ratios were verified as 1.33 and 1.01 respectively. Twenty-five tests passed before the latest provenance/UI redesign commits.

The current feature branch refreshes the Streamlit reporting workspace, persists a generated report across Streamlit reruns, adds a benchmark-aware table and source-based capture chart, and improves the PDF provenance section. **The updated suite and fresh PDF layout must still be verified locally after pulling the latest commit.** Public deployment and the demo recording are not yet verified.

The app deliberately fails when it cannot resolve a fund or retrieve its required capture figures. It does not substitute demo figures or a static sample report.

## Application architecture

This repository is a **single-page Streamlit application**. The UI, AdvisorKhoj retrieval adapter, deterministic ranking, AI provider client, and ReportLab PDF builder live in `app.py`; regression tests are in `tests/test_core.py`. The project currently has no separate frontend/backend service split, database, authentication screens, or multi-route page set to redesign. The presentation work intentionally keeps the existing Streamlit stack and retrieval/report functions.

The UI is organized as three working areas: build a comparison (2–10 unique schemes and category per scheme), set report settings (1/3/5/10 years and AI configuration status), and review the generated report (summary, ranked figures, benchmark-aware table, source-derived chart, per-fund AI notes, provenance, and PDF download). Generated results are stored in Streamlit session state so clicking download or interacting with the page does not immediately discard the report.

## Features

- Enter fund names directly or paste a list.
- Select 2–10 unique funds and a category for each fund.
- Choose a 1-, 3-, 5-, or 10-year analysis period.
- Retrieve scheme, benchmark, up-capture, down-capture, and capture-ratio figures from the AdvisorKhoj Market Capture Ratio tool.
- Calculate a deterministic ranking before requesting the LLM explanation.
- Validate the AI response for complete fund coverage and consistent ranking.
- Review a benchmark-aware comparison table and a chart built from the retrieved up/down capture values.
- Expand per-scheme AI explanations to read ranking rationale, strengths, and limitations.
- Keep a generated result visible across normal Streamlit reruns, including PDF download interactions.
- Generate a selectable-text PDF containing figures, ranking, explanations, clickable source provenance, retrieval timestamps, and a risk disclaimer.
- Use responsive layouts, high-contrast form controls, loading/status messages, an empty state, and actionable errors instead of invented data.

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

The app requires the source's Capture Ratio for every selected fund; it does not mix that ratio with a fallback score on a different scale. If a ratio is missing, report generation stops with an actionable error. Ranking uses the reported Capture Ratio with the following explicit ordering: negative ratios are placed first only when the source up-capture is non-negative and down-capture is negative (the source identifies that case as potentially favourable); other non-negative ratios follow from high to low; other negative ratios follow them. This is a simple, disclosed comparison heuristic, not an investment suitability model or return forecast. Benchmark/category differences can still make cross-fund comparisons less direct.

The LLM is asked to explain the existing deterministic order rather than set or change ranks. The response validator checks the top-level JSON shape, fund coverage, item structure, and rank consistency before the PDF is generated. Model-generated strings are HTML-escaped before being rendered into ReportLab paragraphs. Canonical schemes are checked for duplicates after resolution as well as validating the names entered in the form.

## Deployment

A Render blueprint is included in `render.yaml`. To deploy:

1. Push this repository to GitHub.
2. Create a new Render Blueprint deployment from the repository.
3. Set `OPENAI_API_KEY` and the intended `OPENAI_MODEL` in Render's environment settings.
4. Set `OPENAI_BASE_URL` to an AI endpoint reachable from Render. Do not use a local-only `localhost` URL for FreeLLMAPI; from a hosted container it would point back to that container, not your PC.
5. Confirm the selected plan and any possible charges before deploying.
6. Confirm whether the source retrieval arrangement is authorized for the intended use, then open the public URL and test source retrieval, AI analysis, access controls, and PDF download with real data. Do not expose a provider key through an unrestricted public endpoint.

The blueprint installs Python dependencies without a browser binary. Hosting plan limits, outbound requests, source availability, and request execution time must still be validated in the actual deployment. No live URL is claimed by this repository until a public deployment has been completed and checked.

## Known limitations before production use

- The financial ranking policy, AI output escaping, duplicate canonical scheme check, and report-result state safeguards were recently tightened; run the newest tests and generate a fresh PDF before accepting those changes.
- Live source retrieval depends on an undocumented website page/endpoint and HTML table structure. The site's current terms state that use of its service is subject to the terms and that website elements are copyrighted; permission or a suitable official interface should be confirmed before sustained/commercial use.
- Generic names that match multiple source variants must be made explicit (for example, Direct Growth vs Regular Growth).
- The current source interface's available categories and period labels may change.
- There is no official AdvisorKhoj API credential configured in this project.
- A free/public AI endpoint may have quotas and limitations; hosted inference must be reachable from the deployment environment.
- No genuine sample report is checked in because one must be generated from live, retrieved figures.
- The app is informational and does not provide individualized financial advice.
- The latest full test and visual regression run is still pending.

## Financial disclaimer

Mutual fund investments are subject to market risks. Market capture figures describe historical behavior against a benchmark and do not guarantee future returns. The generated report is educational only, not investment advice. Review scheme documents and consult a qualified financial adviser before making investment decisions.
