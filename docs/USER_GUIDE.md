# PDF Redact user guide

PDF Redact permanently removes text, images and graphics from PDF files, and the hidden
information that often travels with them. It runs on your own computer: documents are never
uploaded anywhere.

- [Start PDF Redact](#start-pdf-redact)
- [Open a document](#open-a-document)
- [Mark what to remove](#mark-what-to-remove)
- [Find text and personal information](#find-text-and-personal-information)
- [Choose how marks look](#choose-how-marks-look)
- [Apply the redactions](#apply-the-redactions)
- [Check the result](#check-the-result)
- [Reports](#reports)
- [Save your work, and work with Acrobat](#save-your-work-and-work-with-acrobat)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)

## Start PDF Redact

From a copy of the source code (needs Python 3.11+ and, for the first run, Node.js 20+):

```sh
python3 run.py
```

From a wheel (needs Python 3.11+ only):

```sh
pipx install pdf_redact-1.0.0-py3-none-any.whl
pdf-redact
```

PDF Redact opens in your browser. The link it prints contains a one-time key, so only that
browser tab can use this session; if you close the tab, open the link from the terminal again.
Options:

- `--port 9000` uses another port (the default is 8765).
- `--no-browser` prints the link without opening a browser.

Press `Ctrl+C` in the terminal to stop it. The temporary copies of your documents are deleted when
you close a document, and when PDF Redact stops.

## Open a document

Drop a PDF onto the window, or choose **Open…**. For a password-protected PDF you are asked for the
password; the redacted copy keeps the same protection and passwords.

A bar under the toolbar points out anything to be aware of: for example, that a document is
digitally signed (redacting it invalidates the signatures), has form fields or attachments, was
damaged and repaired, or already contains redaction marks (they are loaded as marks).

Use the page box, the thumbnails, or scroll to move around; **Fit width**, **Fit page** and the zoom
buttons change the size.

## Mark what to remove

Marks show what will be removed. Nothing changes until you [apply](#apply-the-redactions) them,
and even then only in a new copy of the file.

| Tool | How to use it |
|---|---|
| **Mark text** (`T`) | Drag over text in reading order. Double-click marks a word, triple-click a line. Dragging where there is no text draws a box instead. |
| **Mark area** (`R`) | Drag a box over anything: text, images, drawings, scanned pages. |
| **Select** (`V`) | Click a mark to select it, `Shift`-click to add more. Drag to move, drag the handles to resize, or use the arrow keys (`Shift` for bigger steps). |
| **Mark pages…** | Removes everything on whole pages. Type pages and ranges such as `1, 4-7`, or `odd`, `even`, `all`. |

The **Marks** tab lists every mark by page. Click one to go to it. `Delete` removes the selected
marks, and **Undo** and **Redo** take back any change.

## Find text and personal information

Open the **Search** tab (`⌘F` / `Ctrl+F`).

- **Text** finds words or phrases. Choose whole words, match case, or a regular expression (Python
  syntax). Matches are found across line breaks, hyphenation and typographic quotes and dashes.
- **Personal info** finds common kinds of personal information: Social Security and employer
  numbers, phone numbers, email addresses, payment cards, IBANs, IP addresses, passport and driver's
  license numbers, US street addresses and, if you choose, dates. Add your own keywords and named
  regular expressions too, and save the list to use again.

Search all pages, the current page or a range. Review the results, untick any you want to keep,
then **Mark** the rest. Long searches show their progress and can be cancelled.

> Search only sees real text. Text in scanned pages or images can't be found, so mark it with
> **Mark area**.

## Choose how marks look

With marks selected, the panel on the right sets how they look once applied; with nothing selected,
it sets the look of new marks. **Set as default** copies the look of the selection to new marks.

- **Fill**: the colour of the box, or none. Without a fill, the content is still removed but the
  space is left blank, which may show how long the removed text was.
- **Overlay text**: text to show on the box, such as "REDACTED". Choose its colour, font
  (Helvetica, Times or Courier), size (fitted to the box by default) and alignment, and whether to
  **Repeat** it to fill the box.
- **Codes**: click a redaction code, such as FOIA `(b)(6)` or Privacy Act `(k)(5)`, to add it to the
  overlay text (click again to remove it). **Manage…** creates your own code sets, and imports or
  exports them as JSON.

Hover over a mark, or turn on **Preview**, to see exactly how it will look in the output.

## Apply the redactions

Choose **Apply N redactions…** (or **Remove hidden information…** when there are no marks), check
the options, then **Apply redactions**. On long documents a progress bar is shown; **Cancel** or
`Esc` stops it.

**Images under marks**

- *Blank the covered pixels* (recommended): only the covered part of an image is removed.
- *Remove every image a mark touches*.
- *Leave images unchanged*: the image under a mark stays in the file, only hidden by the box.

**Vector graphics under marks**

- *Remove shapes inside marks* (recommended).
- *Remove every shape a mark touches*: also removes lines that cross a mark.
- *Leave vector graphics unchanged*.

**Hidden information** is removed from the whole document unless you turn it off. Each kind can be
chosen separately:

- Document properties and metadata (title, author, dates, XMP).
- Comments (removed, flattened into the page, or kept) and form fields (flattened, cleared or
  kept).
- Hidden layers, and hidden text such as white or covered text. Invisible OCR text over scanned
  images is kept by default, so scans stay searchable.
- Content outside the visible page area, attached files, links, JavaScript and automatic actions,
  and page thumbnails.
- Optionally, bookmarks (their titles may repeat redacted text) and custom page labels.

Your original file is never changed. You can keep editing the marks and apply again.

## Check the result

Every redacted copy is checked before you download it:

- No marked text, image pixels or graphics remain under any mark.
- No earlier versions of the file, which PDFs can keep inside them, remain.
- The hidden information you chose to remove is gone.
- Text marked from search results doesn't still appear anywhere else in the file, including the
  page text, bookmarks, properties, comments, links and form fields. Any leftover is reported as a
  warning, with a button to show it on the page.

If a check fails, the problems are listed, and downloading needs your confirmation. Go **Back**, fix
the marks, and apply again.

**Download** saves the copy as *name*`_redacted.pdf`.

## Reports

After applying, download:

- **Report**: a printable summary (HTML; print it to PDF if needed).
- **Audit log**: everything recorded about the redaction as JSON, including file hashes, options,
  marks, hidden information removed and checks.
- **CSV**: one row per mark, for spreadsheets.

By default the reports show only the length of each removed text. You can choose a SHA-256 hash,
or the text in full; a report with the full text is as sensitive as the original document.

## Save your work, and work with Acrobat

From the **Project** menu:

- **Save project** (`⌘S` / `Ctrl+S`) saves the marks to a `.redact.json` file. **Load project…**
  brings them back for the same PDF.
- **Export marked PDF** saves an unredacted copy with the marks as standard redaction annotations,
  to review or apply in Acrobat and other tools. When you open a PDF with such annotations, they
  become marks here.

If you close a document, or open another, while it has marks that weren't applied, you are asked
first.

## Keyboard shortcuts

`⌘` is `Ctrl` on Windows and Linux.

| Keys | Action |
|---|---|
| `T`, `R`, `V` | Mark text, Mark area, Select tool |
| `⌘F` | Search |
| `⌘S` | Save project |
| `⌘Z`, `⇧⌘Z` (`Ctrl+Y`) | Undo, redo |
| `⌘A` | Select all marks |
| `Delete` | Remove the selected marks |
| Arrow keys (`Shift` for larger steps) | Move the selected area marks |
| `Esc` | Clear the selection; close a dialog; stop applying |
| `⌘=`, `⌘-`, `⌘0` | Zoom in, zoom out, 100% |

In the **Marks** list, the arrow keys, `Home` and `End` move between marks and select them
(`Shift` adds to the selection), `Space` or `Enter` selects (`⌘` toggles), and `Delete` removes.
Everything except drawing and resizing marks works with the keyboard alone.

## Limitations

- There is no OCR: text in scanned pages and images can't be searched or marked as text. Use
  **Mark area**, which removes the covered pixels.
- Marks don't reach the data of XFA forms, which is stored outside the pages. It is removed along
  with the form field values, unless you keep the form fields or turn off the removal of hidden
  information.
- Redacting a signed document invalidates its signatures.
- The overlay fonts cover Latin characters only.

## Troubleshooting

- **"Session expired"**: open the full link printed in the terminal, including the `#token=…`
  part. Each start of PDF Redact makes a new link.
- **The port is in use**: start with another port, e.g. `python3 run.py --port 9000`.
- **"Node.js 20 or later is needed"**: install Node.js once to build the interface, or use a wheel.
- **A check failed**: the result lists what was found and where. Usually the fix is to enlarge or
  add a mark, or to choose a stricter option for images or graphics.
