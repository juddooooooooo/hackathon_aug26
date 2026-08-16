# Submission package

Prepared for the Data School Hackathon 2026 submission form.

- **`one_pager_solution_summary.pdf`** — the required one-page solution summary (A4, one page, verified).
- **`presentation_slides.pdf`** — the required presentation deck (12 slides, 16:9).
- Editable sources: `one_pager_solution_summary.html` and `presentation_slides.html`. Open either
  in a browser, edit the visible text directly, then re-print to PDF (Ctrl+P → Save as PDF, or reuse the
  Playwright render scripts referenced in the session log) to regenerate.

## Before submitting

1. **Team Name is a placeholder.** Both PDFs currently show `[Insert team name]` in the header/footer.
   Find-and-replace it in the two `.html` files (search for `[Insert team name]`), then re-render to PDF.
2. **Confirm the GitHub repository is public.** As of this build, `github.com/juddooooooooo/hackathon_aug26`
   returned 404 to an unauthenticated request — that means it is currently **private**, and the judging
   panel will not be able to open the code link. Fix: repo → Settings → General → Danger Zone → Change
   visibility → Public. Takes under a minute; this blocks the "link to code" requirement entirely if left
   private.
3. Double-check the two PDFs render as exactly one page (one-pager) and 12 slides (deck) after any edits —
   both were verified at build time via `pypdf`'s page count.

## What's inside each deliverable

The one-pager and slide deck both draw their figures directly from `data/processed/*.parquet` — the same
computed pipeline output the dashboard reads. Every number was cross-checked against the source parquet
files and `reports/*.md` before being written into either document (see the session's verification pass).

`notebooks/pipeline_walkthrough.ipynb` (repo root, not this folder) is a new addition covering the
"reproducible Python notebook" deliverable named in hackathon.txt — it imports the project's own modules
and displays the actual computed output at every stage, already executed with real results.
