"""Detectors for personal information, run over normalised page text.

Each detector is a regular expression followed by a validator that removes false positives
(checksums, valid ranges, real calendar dates, or a keyword such as "passport" just before an
otherwise ambiguous number).
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date

from .search import Match, match_at, normalize, page_indexes

Validator = Callable[[re.Match[str], str], bool]

# A separator inside a number: "-" or "." (optionally spaced, e.g. across a line break) or a space.
_SEP = r"(?:\s?[-.]\s?|\s)"
_CONTEXT_WINDOW = 60


@dataclass(frozen=True)
class Detector:
    id: str
    label: str
    short: str
    description: str
    pattern: re.Pattern[str]
    validate: Validator | None = None
    default: bool = True


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _preceded_by(keyword: re.Pattern[str]) -> Validator:
    def check(m: re.Match[str], text: str) -> bool:
        return bool(keyword.search(text[max(0, m.start() - _CONTEXT_WINDOW) : m.start()]))

    return check


def _ssn(m: re.Match[str], text: str) -> bool:
    area, group, serial = m["area"], m["group"], m["serial"]
    if area in ("000", "666") or area.startswith("9") or group == "00" or serial == "0000":
        return False
    separated = m["s1"] is not None and m["s2"] is not None
    return separated or _SSN_CONTEXT(m, text)


_SSN_CONTEXT = _preceded_by(re.compile(r"(?i)\b(?:SSN|SS#|social\s+security)"))

_EIN_PREFIXES = {
    *range(1, 7),
    *range(10, 17),
    *range(20, 28),
    *range(30, 49),
    *range(50, 69),
    *range(71, 78),
    *range(80, 89),
    *range(90, 96),
    98,
    99,
}


def _ein(m: re.Match[str], _: str) -> bool:
    return int(m.group()[:2]) in _EIN_PREFIXES


def _luhn(number: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(number)):
        n = int(d)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


_CARD_PREFIX = re.compile(
    r"4|5[1-5]|2(?:2[2-9]|[3-6]\d|7[01]|720)"  # Visa, Mastercard
    r"|3[47]|3(?:0[0-5]|[68])|35"  # Amex, Diners, JCB
    r"|6(?:011|5|4[4-9]|2)"  # Discover, UnionPay
)


def _card(m: re.Match[str], _: str) -> bool:
    number = _digits(m.group())
    return 13 <= len(number) <= 19 and bool(_CARD_PREFIX.match(number)) and _luhn(number)


def _iban(m: re.Match[str], _: str) -> bool:
    value = re.sub(r"\s", "", m.group())
    if not 15 <= len(value) <= 34:
        return False
    rearranged = value[4:] + value[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def _phone_intl(m: re.Match[str], _: str) -> bool:
    return 8 <= len(_digits(m.group())) <= 15


def _ipv4(m: re.Match[str], _: str) -> bool:
    try:
        ipaddress.IPv4Address(m.group())
    except ValueError:
        return False
    return True


def _ipv6(m: re.Match[str], _: str) -> bool:
    value = m.group()
    try:
        ipaddress.IPv6Address(value)
    except ValueError:
        return False
    return len(re.sub(r"[^0-9A-Fa-f]", "", value)) >= 3


_MONTHS = {
    name: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for name in names
}
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)


def _valid_date(y: int, m: int, d: int) -> bool:
    if y < 100:
        y += 2000 if y < 50 else 1900
    try:
        date(y, m, d)
    except ValueError:
        return False
    return 1800 <= y <= 2200


def _numeric_date(m: re.Match[str], _: str) -> bool:
    if m["iso"]:
        y, mo, d = (int(v) for v in re.split(r"[-/.]", m["iso"]))
        return _valid_date(y, mo, d)
    a, b, y = (int(v) for v in re.split(r"[-/.]", m.group()))
    return _valid_date(y, a, b) or _valid_date(y, b, a)


def _named_date(m: re.Match[str], _: str) -> bool:
    day = m["d1"] or m["d2"]
    if not day:
        return False
    month = _MONTHS[m["month"].lower().rstrip(".")]
    return _valid_date(int(m["year"]), month, int(day))


_STREET_TYPES = (
    r"Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl|"
    r"Terrace|Ter|Parkway|Pkwy|Circle|Cir|Highway|Hwy|Square|Sq|Trail|Trl"
)

DETECTORS: list[Detector] = [
    Detector(
        "ssn",
        "Social Security numbers",
        "SSN",
        "123-45-6789; unseparated numbers only after “SSN”",
        re.compile(
            rf"(?<![\w-])(?P<area>\d{{3}})(?P<s1>{_SEP})?(?P<group>\d{{2}})(?P<s2>{_SEP})?"
            rf"(?P<serial>\d{{4}})(?![\w-])"
        ),
        _ssn,
    ),
    Detector(
        "ein",
        "Employer ID numbers",
        "EIN",
        "12-3456789",
        re.compile(r"(?<![\w-])\d{2}-\d{7}(?![\w-])"),
        _ein,
    ),
    Detector(
        "email",
        "Email addresses",
        "Email",
        "name@example.com",
        re.compile(r"(?<![\w.%+-])[\w.%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?!\w)"),
    ),
    Detector(
        "phone",
        "Phone numbers (US)",
        "Phone",
        "(202) 555-0143, 202.555.0143, +1 202 555 0143",
        re.compile(
            rf"(?<![\w+])(?:\+?1{_SEP}?)?(?:\(\s?[2-9]\d{{2}}\s?\)\s?|[2-9]\d{{2}}{_SEP})"
            rf"[2-9]\d{{2}}{_SEP}\d{{4}}(?!\w)"
        ),
    ),
    Detector(
        "phone_intl",
        "Phone numbers (international)",
        "Phone",
        "+44 20 7946 0958",
        re.compile(rf"(?<![\w+])\+[1-9]\d{{0,2}}(?:{_SEP}?\(?\d{{1,4}}\)?){{2,6}}(?!\w)"),
        _phone_intl,
    ),
    Detector(
        "card",
        "Payment card numbers",
        "Card",
        "Checked with the Luhn checksum",
        re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])"),
        _card,
    ),
    Detector(
        "iban",
        "Bank account numbers (IBAN)",
        "IBAN",
        "GB82 WEST 1234 5698 7654 32",
        re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}(?![A-Za-z0-9])"),
        _iban,
    ),
    Detector(
        "ipv4",
        "IP addresses (IPv4)",
        "IP",
        "192.168.0.1",
        re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d]|\.\d)"),
        _ipv4,
    ),
    Detector(
        "ipv6",
        "IP addresses (IPv6)",
        "IP",
        "2001:db8::1",
        re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])"),
        _ipv6,
    ),
    Detector(
        "date",
        "Dates",
        "Date",
        "Including dates of birth: 04/12/1985, 1985-04-12, 12 April 1985",
        re.compile(
            r"(?<![\w/.-])(?:(?P<iso>\d{4}[-/.]\d{1,2}[-/.]\d{1,2})|"
            r"\d{1,2}[-/.]\d{1,2}[-/.](?:\d{4}|\d{2}))(?![\w/-]|\.\d)"
        ),
        _numeric_date,
        default=False,
    ),
    Detector(
        "date_named",
        "Dates (written)",
        "Date",
        "April 12, 1985; 12 Apr 1985",
        re.compile(
            rf"(?i)(?<!\w)(?:(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+)?(?P<month>{_MONTH})\.?"
            rf"(?:\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?)?,?\s+(?P<year>\d{{4}})(?!\w)"
        ),
        _named_date,
        default=False,
    ),
    Detector(
        "passport",
        "Passport numbers (US)",
        "Passport",
        "After the word “passport”",
        re.compile(r"(?<!\w)[A-Z]?\d{8,9}(?!\w)"),
        _preceded_by(re.compile(r"(?i)\bpassport")),
    ),
    Detector(
        "drivers_license",
        "Driver's license numbers",
        "License",
        "After “driver's license”, “DL” or “license no.”",
        re.compile(
            r"(?<![\w-])(?=[A-Z0-9-]*\d[A-Z0-9-]*\d[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{4,16}[A-Z0-9](?![\w-])"
        ),
        _preceded_by(
            re.compile(r"(?i)\b(?:driver'?s?\s+licen[cs]e|DLN?\b|licen[cs]e\s+(?:no\b|number|#))")
        ),
    ),
    Detector(
        "address",
        "Street addresses (US)",
        "Address",
        "123 Main Street, Apt 4, Springfield, IL 62704",
        re.compile(
            rf"(?<![\w-])\d{{1,6}}[A-Z]?\s+(?:[NSEW]\.?\s+)?(?:[A-Z0-9][\w'.-]*\s+){{1,4}}?"
            rf"(?:{_STREET_TYPES})\b\.?"
            r"(?:,?\s+(?:Apt|Apartment|Suite|Ste|Unit|Fl|Floor|#)\.?\s*#?[\w-]+)?"
            r"(?:,?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2},?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?)?"
        ),
    ),
]

DETECTORS_BY_ID = {d.id: d for d in DETECTORS}


@dataclass(frozen=True)
class CustomPattern:
    name: str
    pattern: re.Pattern[str]


def keyword_pattern(keywords: Iterable[str]) -> re.Pattern[str] | None:
    """Whole-word, case-insensitive match of any keyword (whitespace-insensitive)."""
    parts = []
    for kw in keywords:
        words = normalize(kw).split()
        if words:
            parts.append(r"\s+".join(re.escape(w) for w in words))
    if not parts:
        return None
    parts.sort(key=len, reverse=True)
    return re.compile(rf"(?<!\w)(?:{'|'.join(parts)})(?!\w)", re.IGNORECASE)


def detect(
    page: int,
    lines: list[dict],
    detectors: Iterable[Detector],
    keywords: re.Pattern[str] | None = None,
    custom: Iterable[CustomPattern] = (),
) -> Iterator[Match]:
    """Matches of every detector on one page. Hits inside a longer hit are dropped."""
    rules: list[tuple[str, re.Pattern[str], Validator | None]] = [
        (d.id, d.pattern, d.validate) for d in detectors
    ]
    if keywords is not None:
        rules.append(("keyword", keywords, None))
    rules += [(f"custom:{c.name}", c.pattern, None) for c in custom]

    found: list[Match] = []
    for index in page_indexes(lines):
        for category, pattern, validate in rules:
            for m in pattern.finditer(index.text):
                if m.end() <= m.start() or (validate and not validate(m, index.text)):
                    continue
                match = match_at(page, index, m.start(), m.end(), category)
                if match:
                    found.append(match)

    # Longest first, so shorter hits contained in them (or duplicates) can be dropped.
    found.sort(key=lambda m: (m.span[0], -m.span[1]))
    reach = -1  # furthest end of the hits kept so far, which all start at or before this one
    for match in found:
        if match.span[1] <= reach:
            continue
        reach = match.span[1]
        yield match
