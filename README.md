# PDF Redact

A local, Acrobat-style PDF redaction tool. Mark text or regions in a browser UI; a local Python engine
(PyMuPDF) **permanently removes** the underlying text, image pixels and vector graphics, then verifies the result.

Everything runs on your machine: the server listens on `127.0.0.1` only, and every API call needs a
per-session token that is handed to the browser in the link the server prints.

See [PLAN.md](PLAN.md) for the feature specification and milestones.

## Features so far

- Viewer: virtualized pages, thumbnails, zoom and fit modes, rotated pages, password-protected PDFs.
- Marking:
  - **Mark text** (`T`): drag over text, double-click a word, triple-click a line; dragging away from text draws a box.
  - **Mark area** (`R`): draw a box over anything, including images and graphics.
  - **Select** (`V`): select, move, resize and nudge marks with the arrow keys.
  - **Mark pages…**: redact whole pages by range, e.g. `1, 4-7, odd`.
  - Undo and redo (`⌘Z`/`Ctrl+Z`, `⇧⌘Z`/`Ctrl+Y`), delete (`Del`), select all (`⌘A`/`Ctrl+A`).
- **Search** (`⌘F`/`Ctrl+F`): find text (whole words, match case, regular expressions) on all pages,
  the current page or a range. Matches survive line-break hyphenation and typographic quotes/dashes.
  Review the hits, then mark the selected ones in one step.
- **Personal info**: detect SSNs, EINs, phone numbers, emails, payment cards (Luhn-checked), IBANs,
  IP addresses, passport and driver's license numbers, US street addresses and (opt-in) dates, plus
  your own keywords and named regular expressions. Pattern lists can be saved and loaded as JSON.
- Appearance: fill colour (or none), overlay text such as `(b)(6)`, text colour, size and alignment.
  Hover over a mark, or turn on **Preview**, to see how it will look.
- **Apply**: choose how images and vector graphics under marks are handled, then download a redacted
  copy. The original file is never modified. Each result is verified (no text, image pixels or
  earlier file revisions left under any mark); downloading a file that fails verification needs
  explicit confirmation. Text marked from search results is also searched for across the whole
  output, with a warning for any occurrence that was left unmarked.

## Requirements

- Python 3.11+
- Node.js 20+ (only to build the UI)

## Run

```sh
cd frontend && npm ci && npm run build && cd ..
cd backend && python -m venv .venv && .venv/bin/pip install -e . && .venv/bin/pdf-redact
```

The server opens the UI in your browser. Use `--port` to change the port and `--no-browser` to
just print the link.

## Develop

Run the backend with a fixed token and the Vite dev server, which proxies `/api` to it:

```sh
cd backend && .venv/bin/pip install -e '.[dev]'
PDF_REDACT_TOKEN=dev .venv/bin/pdf-redact --no-browser   # terminal 1
cd frontend && npm run dev                               # terminal 2, http://127.0.0.1:5173
```

Sample PDFs covering the tricky cases (rotated pages, images, vector graphics, encryption with
user password `user-pw`, …) can be generated with:

```sh
cd backend && .venv/bin/python -m tests.corpus /tmp/pdfr-corpus
```

### Tests

```sh
cd backend && .venv/bin/pytest && .venv/bin/ruff check && .venv/bin/ruff format --check
cd frontend && npm run typecheck && npm run lint && npm test
cd frontend && npx playwright install chromium && npm run e2e   # end-to-end, needs the backend venv
```

## License

PDF Redact uses [PyMuPDF](https://pymupdf.readthedocs.io/), which is licensed under the AGPL-3.0.
