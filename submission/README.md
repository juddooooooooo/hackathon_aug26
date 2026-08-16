# Submission package

Prepared for the Data School Hackathon 2026 submission form.

- **`one_pager_solution_summary.pdf`** — the required one-page solution summary (A4, one page, verified).
- **`presentation_slides.pdf`** — the required presentation deck (12 slides, 16:9).
- Editable sources: `one_pager_solution_summary.html` and `presentation_slides.html`. Open either
  in a browser, edit the visible text directly, then re-print to PDF (Ctrl+P → Save as PDF, or reuse the
  Playwright render scripts referenced in the session log) to regenerate.

## Status

- **Team Name**: sudo Vinos. **Team Members**: Judd Jocum, Asher Hyde. Filled in on both documents.
- **GitHub repository**: confirmed public (`github.com/juddooooooooo/hackathon_aug26` returns 200) —
  this was private earlier in the build and was switched before this version was rendered.
- Both PDFs verified at build time (`pypdf` page count) to be exactly one page (one-pager) and 12 slides
  (deck). Re-verify this if you edit the HTML and re-render — it's easy to overflow a page with new content.

## What's inside each deliverable

The one-pager and slide deck both draw their figures directly from `data/processed/*.parquet` — the same
computed pipeline output the dashboard reads. Every number was cross-checked against the source parquet
files and `reports/*.md` before being written into either document (see the session's verification pass).

`notebooks/pipeline_walkthrough.ipynb` (repo root, not this folder) is a new addition covering the
"reproducible Python notebook" deliverable named in hackathon.txt — it imports the project's own modules
and displays the actual computed output at every stage, already executed with real results.
