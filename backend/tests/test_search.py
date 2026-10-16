import re

import pytest

from pdf_redact.core.search import build_index, compile_query, find, normalize

from .textlines import CHAR_W, make_lines


def search(lines, query, mode="phrase", case_sensitive=False):
    return list(find(0, lines, compile_query(query, mode, case_sensitive)))


def test_phrase_maps_to_character_boxes():
    lines = make_lines("Account number TOPSECRET-4471 is confidential.")
    [m] = search(lines, "topsecret-4471")
    assert m.text == "TOPSECRET-4471"
    start = len("Account number ")
    assert m.rects == [(72 + start * CHAR_W, 100, 72 + (start + 14) * CHAR_W, 110)]
    assert m.angle == 0
    assert m.before == "Account number "
    assert m.after == " is confidential."


def test_case_sensitivity_and_whole_words():
    lines = make_lines("Secret secrets SECRET")
    assert [m.text for m in search(lines, "secret")] == ["Secret", "secret", "SECRET"]
    assert [m.text for m in search(lines, "secret", case_sensitive=True)] == ["secret"]
    assert [m.text for m in search(lines, "secret", mode="word")] == ["Secret", "SECRET"]


def test_phrase_spans_lines_with_one_rect_per_line():
    lines = make_lines("the account number is", "123 and more")
    [m] = search(lines, "number is 123")
    assert len(m.rects) == 2
    assert m.text == "number is 123"


def test_hyphenated_words_match_with_and_without_hyphen():
    lines = make_lines("an inter-", "national agreement, well-", "known")
    [m] = search(lines, "international")
    assert m.text == "inter- national"
    assert len(m.rects) == 2
    # The hyphen glyph is part of the redacted range.
    assert m.rects[0][2] == 72 + len("an inter-") * CHAR_W
    assert [x.text for x in search(lines, "inter-national")] == ["inter- national"]
    assert [x.text for x in search(lines, "well-known")] == ["well- known"]


def test_ligatures_quotes_and_dashes_are_normalised():
    lines = make_lines("The \ufb01nal o\ufb03ce \u201cquote\u201d 2020\u20132021 it\u2019s")
    assert [m.text for m in search(lines, "final office")] == ["\ufb01nal o\ufb03ce"]
    assert [m.text for m in search(lines, '"quote"')] == ["\u201cquote\u201d"]
    assert [m.text for m in search(lines, "2020-2021")] == ["2020\u20132021"]
    assert [m.text for m in search(lines, "it's")] == ["it\u2019s"]
    # A match inside a ligature covers the whole glyph.
    [m] = search(lines, "inal")
    assert m.text == "\ufb01nal"


def test_whitespace_runs_and_extra_spaces_in_query():
    lines = make_lines("too    many   spaces")
    [m] = search(lines, "  too many\tspaces ")
    assert m.text == "too    many   spaces"


def test_regex_mode():
    lines = make_lines("Case 2021-001, case 2022-117 and 99-1")
    assert [m.text for m in search(lines, r"\d{4}-\d{3}", mode="regex")] == ["2021-001", "2022-117"]
    # Empty matches are ignored.
    assert search(lines, r"x*", mode="regex") == []
    with pytest.raises(re.error):
        compile_query("(unclosed", "regex", False)
    with pytest.raises(re.error):
        compile_query("   ", "phrase", False)


def test_vertical_text():
    lines = make_lines("Account TOPSECRET-4471", direction=(0, 1))
    [m] = search(lines, "TOPSECRET-4471")
    assert m.angle == 270
    x0, y0, x1, y1 = m.rects[0]
    assert (x1 - x0, y1 - y0) == (10, 14 * CHAR_W)


def test_index_maps_every_character():
    index = build_index(make_lines("ab", "cd"))
    assert index.text == "ab cd"
    assert index.source == [0, 1, None, 2, 3]
    assert index.ranges(1, 4) == [(0, 1, 2), (1, 0, 1)]


def test_normalize():
    assert normalize("\ufb01\u00ad\u2014") == "fi-"
