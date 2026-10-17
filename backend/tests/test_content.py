from __future__ import annotations

import pytest

from pdf_redact.core.content import (
    ContentError,
    Operand,
    dict_entries,
    has_text_properties,
    operations,
    optional_content_markers,
    property_names,
    remove_hidden_content,
    strip_text_properties,
)


def ops(data: bytes) -> list[bytes]:
    return [op.op for op in operations(data)]


def test_tokenizer_handles_strings_dicts_arrays_and_comments():
    data = (
        b"q 1 0 0 1 72 700 cm % a comment with ) and EMC\n"
        b"BT /F1 12 Tf (nested (parens) and \\) escaped) Tj <48 49> Tj "
        b"[(a) -120 (b)] TJ ET /Span <</ActualText (x\\(y) /Nested <</A [1 2]>>>> BDC EMC Q"
    )
    assert ops(data) == [
        b"q", b"cm", b"BT", b"Tf", b"Tj", b"Tj", b"TJ", b"ET", b"BDC", b"EMC", b"Q"
    ]  # fmt: skip
    bdc = next(op for op in operations(data) if op.op == b"BDC")
    assert [o.kind for o in bdc.operands] == ["name", "dict"]


def test_inline_image_is_a_single_operation():
    binary = bytes(range(256)) + b" EMC BDC Tj "
    data = b"q BI /W 2 /H 2 /BPC 8 /CS /G ID " + binary + b"\nEI Q"
    assert ops(data) == [b"q", b"BI", b"Q"]


@pytest.mark.parametrize("data", [b"(unterminated", b"<</A 1", b"[1 2", b"<abc", b") Tj"])
def test_malformed_streams_raise(data):
    with pytest.raises(ContentError):
        list(operations(data))


def test_strip_text_properties_keeps_other_entries():
    data = b"/Span <</MCID 3 /ActualText (secret) /Alt <73> /Lang (en)>> BDC (x) Tj EMC"
    out = strip_text_properties(data)
    assert out is not None
    assert b"secret" not in out and b"<73>" not in out
    assert b"/MCID 3" in out and b"/Lang (en)" in out
    assert not has_text_properties(out)
    assert strip_text_properties(out) is None
    assert ops(out) == ops(data)


def test_property_names():
    data = b"/OC /MC0 BDC EMC /Span /P1 BDC EMC /Span <</MCID 0>> BDC EMC /Artifact BMC EMC"
    assert property_names(data) == {b"MC0", b"P1"}


def hidden(names):
    return lambda name: name in names


def test_hidden_content_is_removed_but_state_is_kept():
    data = (
        b"q /OC /Off BDC 1 0 0 1 10 10 cm 0 0 1 rg BT /F1 12 Tf 0 0 Td (secret) Tj "
        b"(next) ' 1 2 (third) \" ET 0 0 10 10 re f /Im1 Do /Sh0 sh "
        b"BI /W 1 /H 1 /BPC 8 /CS /G ID \x00\nEI EMC Q "
        b"/OC /On BDC BT (shown) Tj ET EMC"
    )
    result = remove_hidden_content(data, hidden({b"Off"}))
    out = result.data
    assert out is not None
    for gone in (b"secret", b"next", b"third", b"Do", b" sh", b"BI", b" f "):
        assert gone not in out
    assert b"(shown) Tj" in out
    # State changes survive, and painting becomes "n" so any clip still applies.
    assert ops(out) == [
        b"q", b"BMC", b"cm", b"rg", b"BT", b"Tf", b"Td", b"T*", b"Tw", b"Tc", b"T*", b"ET",
        b"re", b"n", b"EMC", b"Q", b"BMC", b"BT", b"Tj", b"ET", b"EMC",
    ]  # fmt: skip
    assert result.removed == 7
    assert optional_content_markers(out) == 0


def test_nested_marked_content_inside_hidden_content_is_dropped():
    data = (
        b"/OC /Off BDC /Span <</ActualText (secret)>> BDC (x) Tj EMC /P BMC EMC 1 0 0 1 0 0 cm EMC"
    )
    out = remove_hidden_content(data, hidden({b"Off"})).data
    assert out is not None
    assert b"secret" not in out
    assert ops(out) == [b"BMC", b"cm", b"EMC"]


def test_visible_layers_are_kept_unless_flattening():
    data = b"/OC /On BDC (x) Tj EMC"
    assert remove_hidden_content(data, hidden(set()), flatten=False).data is None
    flat = remove_hidden_content(data, hidden(set())).data
    assert flat == b"/OC BMC (x) Tj EMC"


def test_hidden_xobjects_are_not_drawn():
    data = b"q /Im1 Do Q q /Fm2 Do Q"
    result = remove_hidden_content(data, hidden(set()), hidden_xobject=hidden({b"Im1"}))
    assert result.data == b"q  Q q /Fm2 Do Q"
    assert result.removed == 1


def test_unbalanced_emc_is_tolerated():
    data = b"EMC /OC /Off BDC (x) Tj"
    out = remove_hidden_content(data, hidden({b"Off"})).data
    assert out is not None
    assert b"(x)" not in out


def test_dict_entries_read_indirect_references_as_one_value():
    data = b"<< /Fm0 8 0 R /N 3 /Fm1 12 0 R /A [1 0 R] >>"
    entries = dict_entries(data, Operand(0, len(data), "dict"))
    assert [(k, data[s:e]) for k, s, e in entries] == [
        (b"Fm0", b"/Fm0 8 0 R"),
        (b"N", b"/N 3"),
        (b"Fm1", b"/Fm1 12 0 R"),
        (b"A", b"/A [1 0 R]"),
    ]
