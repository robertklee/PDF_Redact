"""Labelled fixtures for the PII detectors: positives must be found, negatives must not be."""

import pytest

from pdf_redact.core.pii import DETECTORS, DETECTORS_BY_ID, CustomPattern, detect, keyword_pattern
from pdf_redact.core.search import compile_query

from .textlines import make_lines

POSITIVES: dict[str, list[tuple[str, str]]] = {
    "ssn": [
        ("SSN: 123-45-6789.", "123-45-6789"),
        ("ssn 078 05 1120", "078 05 1120"),
        ("Social Security No. 219099999", "219099999"),
        ("SS# 536-22-1234 on file", "536-22-1234"),
        ("number 001-01-0001 was", "001-01-0001"),
        ("(772-89-1234)", "772-89-1234"),
        ("ids 123-45-6789, 234-56-7890", "123-45-6789"),
        ("ids 123-45-6789, 234-56-7890", "234-56-7890"),
        ("social security number: 665 12 4321", "665 12 4321"),
        ("ref 457.55.5462 ok", "457.55.5462"),
    ],
    "email": [
        ("Contact jane.doe@example.com today", "jane.doe@example.com"),
        ("<j_smith+tag@mail.co.uk>", "j_smith+tag@mail.co.uk"),
        ("EMAIL: ADMIN@EXAMPLE.ORG", "ADMIN@EXAMPLE.ORG"),
        ("x@y.io,", "x@y.io"),
        ("first.last@sub.domain-name.com.", "first.last@sub.domain-name.com"),
        ("(o'brien@example.ie)", "brien@example.ie"),
        ("user123@test-mail.net", "user123@test-mail.net"),
        ("a.b.c@d.e.fg", "a.b.c@d.e.fg"),
        ("mailto:help%desk@corp.com", "help%desk@corp.com"),
        ("send to support@example.travel now", "support@example.travel"),
    ],
    "phone": [
        ("Call (202) 555-0143.", "(202) 555-0143"),
        ("tel 202-555-0143", "202-555-0143"),
        ("202.555.0143", "202.555.0143"),
        ("+1 202 555 0143", "+1 202 555 0143"),
        ("1-800-555-0199", "1-800-555-0199"),
        ("(415)555-2671", "(415)555-2671"),
        ("Phone: 312 555 7788 ext", "312 555 7788"),
        ("+1 (646) 555-3890", "+1 (646) 555-3890"),
        ("fax 213-555-\n0100", None),  # across a line break: checked separately
        ("cell: 917.555.0144;", "917.555.0144"),
    ],
    "phone_intl": [
        ("+44 20 7946 0958", "+44 20 7946 0958"),
        ("+49 30 901820", "+49 30 901820"),
        ("+33 1 42 68 53 00", "+33 1 42 68 53 00"),
        ("+81-3-1234-5678", "+81-3-1234-5678"),
    ],
    "card": [
        ("Visa 4111 1111 1111 1111", "4111 1111 1111 1111"),
        ("MC 5500-0000-0000-0004", "5500-0000-0000-0004"),
        ("Amex 378282246310005", "378282246310005"),
        ("Discover 6011111111111117.", "6011111111111117"),
        ("card 2223000048400011", "2223000048400011"),
    ],
    "iban": [
        ("IBAN GB82 WEST 1234 5698 7654 32", "GB82 WEST 1234 5698 7654 32"),
        ("DE89370400440532013000", "DE89370400440532013000"),
        ("FR14 2004 1010 0505 0001 3M02 606", "FR14 2004 1010 0505 0001 3M02 606"),
    ],
    "ein": [("EIN 12-3456789", "12-3456789"), ("TIN: 98-7654321", "98-7654321")],
    "ipv4": [("from 192.168.0.1.", "192.168.0.1"), ("host 8.8.8.8 and", "8.8.8.8")],
    "ipv6": [
        ("addr 2001:db8::1 ok", "2001:db8::1"),
        ("fe80::1ff:fe23:4567:890a", "fe80::1ff:fe23:4567:890a"),
    ],
    "date": [
        ("DOB: 04/12/1985", "04/12/1985"),
        ("born 1985-04-12", "1985-04-12"),
        ("on 31.12.1999.", "31.12.1999"),
        ("date 1/2/85", "1/2/85"),
    ],
    "date_named": [
        ("born April 12, 1985", "April 12, 1985"),
        ("on 12 Apr 1985", "12 Apr 1985"),
        ("3rd of March? no: 3rd March 2001", "3rd March 2001"),
        ("Sept. 9, 2020", "Sept. 9, 2020"),
    ],
    "passport": [("Passport No. 912803456", "912803456"), ("passport: C03005988", "C03005988")],
    "drivers_license": [
        ("Driver's License: D1234-5678-9012", "D1234-5678-9012"),
        ("DL # S530-4568-1234", "S530-4568-1234"),
        ("license no. 123456789", "123456789"),
    ],
    "address": [
        (
            "Lives at 123 Main Street, Springfield, IL 62704.",
            "123 Main Street, Springfield, IL 62704",
        ),
        ("1600 Pennsylvania Avenue NW", "1600 Pennsylvania Avenue"),
        ("Office: 42 W. Elm St., Apt 4B", "42 W. Elm St., Apt 4B"),
        ("at 7 Oak Ln today", "7 Oak Ln"),
    ],
}

NEGATIVES: dict[str, list[str]] = {
    "ssn": [
        "000-12-3456",
        "666-12-3456",
        "900-12-3456",
        "123-00-4567",
        "123-45-0000",
        "order 123456789 shipped",  # unseparated, no SSN context
        "ISBN 978-3-16-148410-0",
        "1234-56-7890",
        "phone 202-555-0143",
    ],
    "email": ["user@localhost", "@example.com", "name@", "a@b.c", "version 1.2.3@beta"],
    "phone": [
        "123-456-7890",  # area code cannot start with 1
        "202-055-0143",  # exchange cannot start with 0
        "Invoice 2021-555-01",
        "4111 1111 1111 1111",
        "ISBN 0-306-40615-2",
        "12025550143999",
    ],
    "card": ["4111 1111 1111 1112", "1234 5678 9012 3456", "Order 2021000000000000"],
    "iban": ["GB82 WEST 1234 5698 7654 33", "AB12"],
    "ipv4": ["256.1.1.1", "version 1.2.3.4.5", "10.0.0"],
    "ipv6": ["12:30:45", "a:b", "time 10:15"],
    "date": ["13/13/2020", "99/99/99", "version 1.2.3", "02/30/2020"],
    "date_named": ["April 2020", "May I help", "March 32, 2020"],
    "passport": ["Order 912803456"],
    "drivers_license": ["ABCDEFGH", "the license agreement 2021"],
    "address": ["We have 3 Dogs and 2 Cats", "In 2020 Street art"],
}


def run(text: str, ids: list[str]) -> list[tuple[str | None, str]]:
    detectors = [DETECTORS_BY_ID[i] for i in ids]
    return [(m.category, m.text) for m in detect(0, make_lines(*text.split("\n")), detectors)]


@pytest.mark.parametrize("category", sorted(POSITIVES))
def test_recall(category):
    cases = [(t, e) for t, e in POSITIVES[category] if e is not None]
    found = sum((category, expected) in run(text, [category]) for text, expected in cases)
    misses = [(t, e) for t, e in cases if (category, e) not in run(t, [category])]
    assert found / len(cases) >= 0.95, misses


@pytest.mark.parametrize("category", sorted(NEGATIVES))
def test_precision(category):
    hits = {text: run(text, [category]) for text in NEGATIVES[category]}
    assert {t: h for t, h in hits.items() if h} == {}


def test_number_split_across_lines():
    [(category, text)] = run("fax 213-555-\n0100 now", ["phone"])
    assert category == "phone"
    assert text == "213-555- 0100"


def test_longer_hits_win_and_categories_do_not_duplicate():
    ids = [d.id for d in DETECTORS]
    hits = run("Call +1 202 555 0143 or mail a@example.com", ids)
    assert hits == [("phone", "+1 202 555 0143"), ("email", "a@example.com")]


def test_keywords_and_custom_patterns():
    lines = make_lines("Project Bluebird and project  BLUEBIRD; case ABC-123")
    keywords = keyword_pattern(["project bluebird", "  "])
    custom = [CustomPattern("case", compile_query(r"[A-Z]{3}-\d{3}", "regex", True))]
    hits = [(m.category, m.text) for m in detect(0, lines, [], keywords, custom)]
    assert hits == [
        ("keyword", "Project Bluebird"),
        ("keyword", "project  BLUEBIRD"),
        ("custom:case", "ABC-123"),
    ]
    assert keyword_pattern(["", " "]) is None


def test_detector_ids_are_unique():
    assert len(DETECTORS_BY_ID) == len(DETECTORS)
