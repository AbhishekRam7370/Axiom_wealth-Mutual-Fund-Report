# Work Log

## 2026-10-09

- Inspected repository metadata through the connected GitHub integration.
- Confirmed the repository was initially empty and had no README, application files, branches, or commits.
- Created an initial ignore-rules commit on `main` and a separate implementation branch, `feature/fund-report-app`.
- Added the Streamlit application, deterministic ranking, OpenAI-compatible analysis, PDF generation, tests, setup documentation, environment template, and Render blueprint. The AdvisorKhoj retrieval adapter was subsequently changed from Playwright form automation to the source page's own suggestion endpoint plus direct results-page requests.
- Inspected the public AdvisorKhoj Market Capture Ratio page and its published metric definitions.
- Created draft pull request #1 for review.
- The local Windows environment successfully installed dependencies and Chromium after a transient network failure. The contributor ran `python -m pytest -q`: 16 tests passed before the latest scheme-resolution adapter changes.
- Live manual verification confirmed AdvisorKhoj's suggestion endpoint returns canonical labels `Parag Parikh Flexi Cap Dir Gr` and `Parag Parikh Flexi Cap Reg Gr`; direct results-page requests returned capture rows for both. Current application code now resolves canonical labels and rejects ambiguous generic names; the user still needs to pull the latest commit and run tests plus `fetch_one_fund` end to end.
- The latest branch patch removes the Playwright runtime requirement, fetches categories with lxml, resolves source scheme names using the endpoint's prefix behavior, requests the actual results page by category/scheme/period, rejects ambiguous variants, and adds six scheme-resolution tests plus two mocked endpoint tests. There are now 24 test cases defined; execution against this latest commit is pending.

- Follow-up PDF layout fix: the `Source figures and provenance` section now uses a labeled two-column table for each fund, displays capture values consistently, wraps long source URLs, provides a clickable AdvisorKhoj source link, and HTML-escapes source metadata. Added a regression test for ampersands and long query-string URLs; the updated test suite and rendered PDF still need verification after pull.

## Frontend redesign — 9 October 2026

- Inspected the repository tree. The project has a single Streamlit entry point (`app.py`), one pytest module (`tests/test_core.py`), dependency manifest, README, work log, demo checklist, environment template, and Render blueprint. It does not currently contain separate frontend routes, a distinct backend API service, database, or authentication/profile/admin screens.
- Reworked the actual Streamlit workspace to a finance-oriented, high-contrast design with an application identity/header, clear comparison/setup/results steps, responsive layout rules, consistent bordered panels, clearer form labels, helper text, and accessible reduced-motion styling.
- Retained the live AdvisorKhoj category/name retrieval workflow, input bounds (2–10), period choices, deterministic rank calculation, guarded AI request/response validation, and ReportLab output.
- Added a benchmark-aware comparison preview built from retrieved fund records, a source-derived up/down-capture chart, per-scheme AI explanation panels, report summary cards derived from the current result, source links, and an explicit no-sample empty state.
- Fixed result persistence by storing the successful report in Streamlit session state, so normal reruns (including clicking the download control) do not immediately clear the results.
- Cached category retrieval using a stable Streamlit cache decorator, and added a regression test for comparison-table rank order and benchmark/category fidelity.
- Improved PDF source provenance layout in the previous commit: per-fund key/value tables, escaped metadata, wrapped long source URLs, and clickable AdvisorKhoj source links; the matching regression test covers ampersands and query strings.
- Updated the README architecture and current verification notes. The current UI/PDF commit has **not yet been locally tested**. The user should pull the branch, run the full test suite (expected 27 cases), launch Streamlit, regenerate a fresh PDF, and visually inspect it. No public deployment or demo recording is claimed complete.

## Time accounting

Active implementation time was not measured by a reliable timer. No numerical hours total is claimed. Record the actual active work time in the assignment submission once it has been measured.

- Follow-up mapping check: the local live retrieval returned the correct 77% up capture and 58% down capture but initially mapped `capture_ratio` to the up-capture column because column matching used a substring. The latest branch now prefers exact normalized column headers and adds a regression test expecting the source's separate `Capture Ratio` value (1.33). The updated 25-case suite and retrieval result must be verified after the user pulls the latest commit.
