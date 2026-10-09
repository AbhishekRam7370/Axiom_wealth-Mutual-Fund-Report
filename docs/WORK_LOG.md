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

## Time accounting

Active implementation time was not measured by a reliable timer. No numerical hours total is claimed. Record the actual active work time in the assignment submission once it has been measured.

- Follow-up mapping check: the local live retrieval returned the correct 77% up capture and 58% down capture but initially mapped `capture_ratio` to the up-capture column because column matching used a substring. The latest branch now prefers exact normalized column headers and adds a regression test expecting the source's separate `Capture Ratio` value (1.33). The updated 25-case suite and retrieval result must be verified after the user pulls the latest commit.
