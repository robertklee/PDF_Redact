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
  Review the hits, then mark the selected ones in one step. Long searches show their progress and
  can be cancelled.
- **Personal info**: detect SSNs, EINs, phone numbers, emails, payment cards (Luhn-checked), IBANs,
  IP addresses, passport and driver's license numbers, US street addresses and (opt-in) dates, plus
  your own keywords and named regular expressions. Pattern lists can be saved and loaded as JSON.
- Appearance: fill colour (or none), overlay text, text colour, font (Helvetica, Times or Courier),
  size (auto-fit by default), alignment, and repeating the text to fill the box. Hover over a mark, or
  turn on **Preview**, to see exactly how it will look in the output. Set the defaults for new marks
  with nothing selected.
- **Redaction codes**: click codes such as FOIA `(b)(6)` or Privacy Act `(k)(5)` to add them to the
  overlay text of the selected marks. Create your own code sets, and import or export them as JSON.
- **Apply**: choose how images and vector graphics under marks are handled, then download a redacted
  copy (with progress, and Cancel or `Esc`, on long documents). The original file is never modified.
  Each result is verified (no text, image pixels or earlier file revisions left under any mark);
  downloading a file that fails verification needs
  explicit confirmation. Text marked from search results is also searched for across the whole
  output (page text, bookmarks, properties, comments, links and form fields), with a warning for
  any occurrence that was left unmarked.
- **Hidden information**: applying also removes metadata, comments, form data (flattened by
  default), attachments, links, JavaScript, thumbnails, hidden layers, hidden text (keeping OCR text
  over scans), and content outside the visible page area. Each option can be turned off; bookmarks
  and page labels can be removed too. With no marks, **Remove hidden information…** does this on
  its own. Replacement and alternate text (`ActualText`, `Alt`) is always removed from redacted pages.
- **Reports**: after applying, download a printable HTML report, the full audit log (JSON) or the
  marks as CSV, with file hashes, options, hidden information removed and verification results.
  Removed text appears as its length by default, or as a SHA-256 hash or in full if you choose.
- **Projects** (`⌘S`/`Ctrl+S`): save the marks to a `.redact.json` file and load them later to carry on.
- **Acrobat interop**: **Export marked PDF** writes an unredacted copy with the marks as standard
  redaction annotations, to review or apply in Acrobat and other tools. Redaction annotations already
  in a PDF become marks when you open it.
- **Keyboard and screen readers**: everything except drawing marks works from the keyboard. Dialogs
  keep the focus inside them, close with `Esc` and return the focus to where it was. In the marks
  list, the arrow keys, `Home` and `End` move and select (`Shift` adds to the selection), and `Del`
  removes the selected marks. The page view scrolls with the arrow and page keys once focused.
  Every screen is checked with axe (WCAG 2.1 AA) in the end-to-end tests.

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
