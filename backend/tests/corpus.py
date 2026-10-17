"""Synthetic PDF fixtures that exercise redaction edge cases.

Each builder returns PDF bytes containing ``SECRET`` somewhere it must be removable from.
Run ``python -m tests.corpus OUTDIR`` (from backend/) to write them all to disk for manual testing.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pymupdf

SECRET = "TOPSECRET-4471"
ABOVE = "Visible line above"
BELOW = "Visible line below"
SECRET_LINE = f"Account number {SECRET} is confidential."
USER_PASSWORD = "user-pw"
OWNER_PASSWORD = "owner-pw"


def _three_lines(
    page: pymupdf.Page,
    x: float = 72,
    y: float = 120,
    leading: float = 14,
    size: float = 12,
    **kwargs,
) -> None:
    for i, text in enumerate([ABOVE, SECRET_LINE, BELOW]):
        page.insert_text((x, y + i * leading), text, fontsize=size, **kwargs)


def _pattern_pixmap(width: int = 240, height: int = 120) -> pymupdf.Pixmap:
    """A noisy image so that 'blanked' regions are distinguishable from untouched ones."""
    samples = bytearray()
    for y in range(height):
        for x in range(width):
            samples += bytes(((x * 7) % 256, (y * 11) % 256, ((x + y) * 3) % 256))
    return pymupdf.Pixmap(pymupdf.csRGB, width, height, bytes(samples), False)


def text_basic() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Quarterly report", fontsize=18)
    _three_lines(page)
    return doc.tobytes()


def tight_leading(ratio: float = 1.0) -> bytes:
    """Lines spaced at `ratio` × font size, so font boxes of neighbouring lines overlap."""
    doc = pymupdf.open()
    _three_lines(doc.new_page(), leading=12 * ratio)
    return doc.tobytes()


def rotated(rotation: int = 90) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    _three_lines(page)
    page.set_rotation(rotation)
    return doc.tobytes()


def vertical_text() -> bytes:
    """Text drawn rotated within an unrotated page (writing direction bottom-to-top)."""
    doc = pymupdf.open()
    page = doc.new_page()
    for i, text in enumerate([ABOVE, SECRET_LINE, BELOW]):
        page.insert_text((100 + i * 14, 500), text, fontsize=12, rotate=90)
    return doc.tobytes()


def cropbox_offset() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    _three_lines(page, x=150, y=250)
    page.insert_text((20, 30), f"Outside crop {SECRET}", fontsize=10)
    page.set_cropbox(pymupdf.Rect(100, 150, 500, 600))
    return doc.tobytes()


def outside_crop() -> bytes:
    """Text, images and graphics placed where the CropBox hides them, on a rotated page."""
    doc = pymupdf.open()
    page = doc.new_page()
    _three_lines(page, x=150, y=250)
    page.insert_text((20, 30), f"Outside crop {SECRET}", fontsize=10)
    page.insert_text((700, 400), f"Off the page {SECRET}", fontsize=10)
    pix = _pattern_pixmap()
    page.insert_image(pymupdf.Rect(10, 400, 90, 480), pixmap=pix, keep_proportion=False)
    page.insert_image(pymupdf.Rect(400, 300, 560, 380), pixmap=pix, keep_proportion=False)
    page.draw_rect(pymupdf.Rect(20, 650, 80, 700), color=(1, 0, 0), fill=(0, 1, 0))
    page.draw_rect(pymupdf.Rect(20, 100, 80, 200), color=(1, 0, 0), fill=(0, 1, 0))
    page.draw_rect(pymupdf.Rect(300, 500, 350, 520), color=(1, 0, 0), fill=(0, 1, 0))  # visible
    page.set_cropbox(pymupdf.Rect(100, 150, 500, 600))
    page.set_rotation(90)
    return doc.tobytes()


def off_page_text() -> bytes:
    """Text drawn outside the MediaBox: no viewer shows it, but it is in the content stream."""
    doc = pymupdf.open()
    page = doc.new_page()
    _three_lines(page)
    page.insert_text((72, -300), f"Above the page {SECRET}", fontsize=12)
    page.insert_text((700, 400), f"Right of the page {SECRET}", fontsize=12)
    return doc.tobytes()


def field_with_kids() -> bytes:
    """One form field (holding the value) shown by two widgets that are its kids."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "SSN:", fontsize=12)
    page.insert_text((72, 300), "SSN again:", fontsize=12)
    field = doc.get_new_xref()
    kids = []
    for y in (742, 542):
        xref = doc.get_new_xref()
        doc.update_object(
            xref,
            f"<</Type/Annot/Subtype/Widget/Rect[150 {y - 6} 340 {y + 12}]/F 4"
            f"/Parent {field} 0 R/P {page.xref} 0 R>>",
        )
        kids.append(xref)
    kid_refs = " ".join(f"{k} 0 R" for k in kids)
    doc.update_object(field, f"<</FT/Tx/T(ssn)/V({SECRET})/DA(0 g /Helv 12 Tf)/Kids[{kid_refs}]>>")
    doc.xref_set_key(page.xref, "Annots", f"[{kid_refs}]")
    doc.xref_set_key(
        doc.pdf_catalog(), "AcroForm", f"<</Fields[{field} 0 R]/NeedAppearances true>>"
    )
    return doc.tobytes()


def image_with_ocr_text() -> bytes:
    """Like an OCR'd scan: a picture of the page with invisible text on top."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(
        pymupdf.Rect(60, 100, 420, 160), pixmap=_pattern_pixmap(), keep_proportion=False
    )
    _three_lines(page, render_mode=3)
    return doc.tobytes()


def scanned_image() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(72, 72, 372, 222), pixmap=_pattern_pixmap())
    return doc.tobytes()


def vector_graphics() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_line((50, 200), (550, 200), color=(0, 0, 1), width=2)  # crosses the target box
    page.draw_rect(pymupdf.Rect(220, 180, 260, 220), color=None, fill=(1, 0, 0))  # inside it
    page.draw_rect(pymupdf.Rect(400, 400, 500, 500), color=(0, 0.5, 0), width=1)  # far away
    return doc.tobytes()


def annotations() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    _three_lines(page)
    hit = page.search_for(SECRET)[0]
    page.add_text_annot(hit.tl, f"Note about {SECRET}")
    page.add_freetext_annot(pymupdf.Rect(300, 300, 500, 340), f"Comment {SECRET}")
    return doc.tobytes()


def existing_redaction() -> bytes:
    """A file that already carries an unapplied /Redact annotation (e.g. from Acrobat)."""
    doc = pymupdf.open()
    page = doc.new_page()
    _three_lines(page)
    page.add_redact_annot(page.search_for(ABOVE)[0])
    return doc.tobytes()


def form_fields() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "SSN:", fontsize=12)
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "ssn"
    widget.field_value = SECRET
    widget.rect = pymupdf.Rect(110, 86, 300, 104)
    page.add_widget(widget)
    return doc.tobytes()


def attachments() -> bytes:
    doc = pymupdf.open()
    _three_lines(doc.new_page())
    doc.embfile_add("secret.txt", SECRET.encode(), filename="secret.txt", desc=SECRET)
    return doc.tobytes()


def javascript() -> bytes:
    doc = pymupdf.open()
    _three_lines(doc.new_page())
    xref = doc.get_new_xref()
    doc.update_object(xref, f"<</S/JavaScript/JS(app.alert('{SECRET}'))>>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{xref} 0 R")
    return doc.tobytes()


def metadata() -> bytes:
    doc = pymupdf.open()
    _three_lines(doc.new_page())
    doc.set_metadata({"author": SECRET, "title": "Report", "subject": SECRET, "keywords": SECRET})
    doc.set_xml_metadata(
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f'<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{SECRET}</dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
    )
    return doc.tobytes()


def hidden_text() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    _three_lines(page)
    page.insert_text((72, 300), f"Invisible {SECRET}", fontsize=12, render_mode=3)
    page.insert_text((72, 330), f"White {SECRET}", fontsize=12, color=(1, 1, 1))
    page.insert_text((72, 360), f"Covered {SECRET}", fontsize=12)
    page.draw_rect(pymupdf.Rect(60, 345, 300, 366), color=None, fill=(0.2, 0.4, 0.6))
    return doc.tobytes()


def actual_text() -> bytes:
    """Marked content whose /ActualText repeats the secret: inline, through a named property
    list, and inside a form XObject."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), ABOVE, fontsize=12)
    props = doc.get_new_xref()
    doc.update_object(props, f"<</ActualText({SECRET}-NAMED)/MCID 0>>")
    form = doc.get_new_xref()
    doc.update_object(form, "<</Type/XObject/Subtype/Form/BBox[0 0 612 792]/Resources<<>>>>")
    doc.update_stream(
        form,
        f"/Span <</ActualText({SECRET}-FORM)>> BDC BT /helv 12 Tf 72 620 Td "
        f"({SECRET}) Tj ET EMC".encode(),
    )
    doc.xref_set_key(form, "Resources/Font/helv", f"{page.get_fonts()[0][0]} 0 R")
    resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    doc.xref_set_key(resources, "Properties", f"<</P0 {props} 0 R>>")
    doc.xref_set_key(resources, "XObject", f"<</Fm0 {form} 0 R>>")
    xref = page.get_contents()[0]
    doc.update_stream(
        xref,
        doc.xref_stream(xref)
        + (
            f"\nq /Span <</ActualText({SECRET}-INLINE)/Lang(en)>> BDC BT /helv 12 Tf 72 700 Td "
            f"({SECRET}) Tj ET EMC Q\n"
            f"q /Span /P0 BDC BT /helv 12 Tf 72 680 Td ({SECRET}) Tj ET EMC Q\n"
            f"q /Fm0 Do Q\n"
        ).encode(),
    )
    return doc.tobytes()


def incremental_update() -> bytes:
    """The secret was removed in a later incremental save but survives in the earlier revision."""
    doc = pymupdf.open()
    page = doc.new_page()
    _three_lines(page)
    page.insert_text((72, 300), "OLD-REVISION-SECRET", fontsize=12)
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        doc.save(path)
        with pymupdf.open(path) as inc:
            pg = inc[0]
            pg.add_redact_annot(pg.search_for("OLD-REVISION-SECRET")[0])
            pg.apply_redactions()
            inc.saveIncr()
        return Path(path).read_bytes()
    finally:
        os.unlink(path)


def encrypted() -> bytes:
    doc = pymupdf.open()
    _three_lines(doc.new_page())
    return doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw=USER_PASSWORD,
        owner_pw=OWNER_PASSWORD,
    )


def multi_column() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    left = "Left column text. " * 3
    right = f"Right column has {SECRET} inside."
    page.insert_textbox(pymupdf.Rect(50, 100, 290, 300), left * 4, fontsize=10)
    page.insert_textbox(pymupdf.Rect(320, 100, 560, 300), right, fontsize=10)
    return doc.tobytes()


def many_pages(count: int = 50) -> bytes:
    doc = pymupdf.open()
    for i in range(count):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}", fontsize=14)
        _three_lines(page)
    return doc.tobytes()


PII_LINES = [
    "Applicant: Jane Q. Doe",
    "SSN: 123-45-6789    Phone: (202) 555-0143",
    "Email: jane.doe@example.com",
    "Address: 1600 Pennsylvania Avenue",
    f"Case reference {SECRET} was opened after an inter-",
    "national review of the file.",
]
PII_PAGE_2 = [
    "Second contact: john.smith@example.org, 415-555-2671",
    f"Card on file 4111 1111 1111 1111; ref {SECRET}",
]


def personal_info() -> bytes:
    """Two pages of personal information (and SECRET), with a word hyphenated across lines."""
    doc = pymupdf.open()
    for lines in (PII_LINES, PII_PAGE_2):
        page = doc.new_page()
        for i, text in enumerate(lines):
            page.insert_text((72, 100 + i * 16), text, fontsize=12)
    return doc.tobytes()


def kitchen_sink() -> bytes:
    """A multi-page demo document combining most cases (for manual testing)."""
    parts = [text_basic(), image_with_ocr_text(), rotated(90), vector_graphics(), annotations()]
    doc = pymupdf.open()
    for part in parts:
        with pymupdf.open(stream=part, filetype="pdf") as src:
            doc.insert_pdf(src)
    doc.set_metadata({"author": SECRET, "title": "Kitchen sink"})
    return doc.tobytes()


FIXTURES: dict[str, Callable[[], bytes]] = {
    "text_basic": text_basic,
    "tight_leading": tight_leading,
    "rotated_90": lambda: rotated(90),
    "rotated_180": lambda: rotated(180),
    "rotated_270": lambda: rotated(270),
    "vertical_text": vertical_text,
    "cropbox_offset": cropbox_offset,
    "off_page_text": off_page_text,
    "outside_crop": outside_crop,
    "image_with_ocr_text": image_with_ocr_text,
    "scanned_image": scanned_image,
    "vector_graphics": vector_graphics,
    "annotations": annotations,
    "existing_redaction": existing_redaction,
    "form_fields": form_fields,
    "field_with_kids": field_with_kids,
    "attachments": attachments,
    "javascript": javascript,
    "metadata": metadata,
    "hidden_text": hidden_text,
    "actual_text": actual_text,
    "incremental_update": incremental_update,
    "encrypted": encrypted,
    "multi_column": multi_column,
    "many_pages": many_pages,
    "personal_info": personal_info,
    "kitchen_sink": kitchen_sink,
}


def write_all(outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, build in FIXTURES.items():
        path = outdir / f"{name}.pdf"
        path.write_bytes(build())
        written.append(path)
    return written


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    for p in write_all(target):
        print(p)
    print(f"Encrypted sample passwords: user={USER_PASSWORD!r} owner={OWNER_PASSWORD!r}")
