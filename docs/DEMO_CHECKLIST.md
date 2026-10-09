# Five-Minute Demo Checklist

Target duration: 4 minutes 30 seconds.

## Recording outline

- 0:00–0:25 — Open the deployed application and introduce the fund comparison workflow.
- 0:25–1:15 — Enter or paste two to ten mutual fund names and select the AdvisorKhoj category for each fund.
- 1:15–1:35 — Select the analysis period: 1, 3, 5, or 10 years.
- 1:35–2:35 — Generate the report and show progress, source retrieval, and the validated comparison preview.
- 2:35–3:30 — Download and open the PDF. Show source figures, ranking, explanations, retrieval timestamps, and disclosures.
- 3:30–4:10 — Show the README, setup instructions, tests, and GitHub pull request.
- 4:10–4:30 — State any known limitations honestly.

## Before recording

- Confirm the public URL is live.
- Use only fund figures retrieved from AdvisorKhoj during the recording.
- Confirm the LLM provider is configured and available.
- Generate a new report during the recording rather than opening a fabricated sample.
- Check that the PDF opens and contains the selected funds and period.
- Hide API keys, account details, and private environment settings.
- Keep the final video under five minutes.

## Current recording status

An earlier version of the local source → AI analysis → PDF workflow was confirmed using the existing FreeLLMAPI setup. Subsequent changes have tightened ranking, AI response validation, duplicate-scheme checks, report-state handling, and PDF rendering. Pull and test the exact latest branch and generate a fresh PDF before recording. The public deployment has not been verified, so do not describe a public URL as live or record a deployment demo until it has been created and tested.
