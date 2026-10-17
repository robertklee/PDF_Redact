"""A small PDF content-stream tokenizer and two rewriters MuPDF does not provide.

MuPDF's redaction removes glyphs but keeps marked-content properties such as ``/ActualText``,
which can repeat the removed text, and its filters keep content in hidden optional content
(layers). Both are rewritten here at the level of single operators; all other bytes are copied
unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

WHITESPACE = frozenset(b"\x00\t\n\x0c\r ")
DELIMITERS = frozenset(b"()<>[]{}/%")
NUMBER_START = frozenset(b"+-.0123456789")
# Marked-content properties that hold text: replacement, alternate and expansion text.
TEXT_PROPERTIES = (b"ActualText", b"Alt", b"E")

_EI = re.compile(rb"(?<=[\x00\t\n\x0c\r ])EI(?=[\x00\t\n\x0c\r ()<>\[\]{}/%]|$)")

TEXT_SHOWING = frozenset({b"Tj", b"TJ", b"'", b'"'})
PATH_PAINTING = frozenset({b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"})
MARKED_CONTENT = frozenset({b"BDC", b"BMC", b"EMC", b"MP", b"DP"})


class ContentError(ValueError):
    """The content stream could not be parsed."""


@dataclass(slots=True)
class Operand:
    start: int
    end: int
    kind: str  # name, number, string, hex, array, dict, keyword


@dataclass(slots=True)
class Operation:
    op: bytes
    operands: list[Operand]
    start: int  # start of the first operand, or of the operator
    end: int


def _skip(data: bytes, i: int) -> int:
    n = len(data)
    while i < n:
        c = data[i]
        if c in WHITESPACE:
            i += 1
        elif c == 0x25:  # % comment
            while i < n and data[i] not in b"\r\n":
                i += 1
        else:
            break
    return i


def _regular_end(data: bytes, i: int) -> int:
    n = len(data)
    while i < n and data[i] not in WHITESPACE and data[i] not in DELIMITERS:
        i += 1
    return i


def _string_end(data: bytes, i: int) -> int:
    depth, n = 0, len(data)
    while i < n:
        c = data[i]
        if c == 0x5C:  # backslash escapes the next byte
            i += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ContentError("unterminated string")


def _object_end(data: bytes, i: int) -> tuple[int, str]:
    """End offset and kind of the object starting at `i` (which is not whitespace)."""
    c = data[i]
    if c == 0x28:
        return _string_end(data, i), "string"
    if c == 0x2F:
        return _regular_end(data, i + 1), "name"
    if c == 0x3C:
        if data[i + 1 : i + 2] == b"<":
            return _container_end(data, i + 2, b">>"), "dict"
        end = data.find(b">", i + 1)
        if end < 0:
            raise ContentError("unterminated hex string")
        return end + 1, "hex"
    if c == 0x5B:
        return _container_end(data, i + 1, b"]"), "array"
    if c in DELIMITERS:
        raise ContentError(f"unexpected {chr(c)!r} at offset {i}")
    end = _regular_end(data, i)
    return end, "number" if c in NUMBER_START else "keyword"


def _container_end(data: bytes, i: int, close: bytes) -> int:
    n = len(data)
    while True:
        i = _skip(data, i)
        if i >= n:
            raise ContentError("unterminated array or dictionary")
        if data.startswith(close, i):
            return i + len(close)
        i, _ = _object_end(data, i)


def operations(data: bytes) -> Iterator[Operation]:
    """The operations of a content stream; an inline image is one ``BI`` operation."""
    operands: list[Operand] = []
    i, n = 0, len(data)
    while True:
        i = _skip(data, i)
        if i >= n:
            return
        c = data[i]
        if c in DELIMITERS or c in NUMBER_START:
            end, kind = _object_end(data, i)
            operands.append(Operand(i, end, kind))
            i = end
            continue
        end = _regular_end(data, i)
        word = data[i:end]
        if word in (b"true", b"false", b"null"):
            operands.append(Operand(i, end, "keyword"))
        elif word == b"BI":
            end = _inline_image_end(data, end)
            yield Operation(b"BI", [], i, end)
            operands = []
        else:
            start = operands[0].start if operands else i
            yield Operation(word, operands, start, end)
            operands = []
        i = end


def _inline_image_end(data: bytes, i: int) -> int:
    n = len(data)
    while True:
        i = _skip(data, i)
        if i >= n:
            raise ContentError("inline image without ID")
        end, kind = _object_end(data, i)
        if kind == "keyword" and data[i:end] == b"ID":
            match = _EI.search(data, end + 1)
            if not match:
                raise ContentError("inline image without EI")
            return match.end()
        i = end


def dict_entries(data: bytes, operand: Operand) -> list[tuple[bytes, int, int]]:
    """(key, start, end) of each entry of an inline dictionary operand."""
    entries = []
    i = operand.start + 2
    while True:
        i = _skip(data, i)
        if data.startswith(b">>", i):
            return entries
        key_end, kind = _object_end(data, i)
        if kind != "name":
            raise ContentError("dictionary key is not a name")
        value_start = _skip(data, key_end)
        value_end, kind = _object_end(data, value_start)
        if kind == "number":
            value_end = _reference_end(data, value_end)
        entries.append((data[i + 1 : key_end], i, value_end))
        i = value_end


def _reference_end(data: bytes, i: int) -> int:
    """End of the indirect reference (``12 0 R``) whose first integer ends at `i`, else `i`."""
    gen_start = _skip(data, i)
    if gen_start >= len(data) or data[gen_start] not in b"0123456789":
        return i
    gen_end = _regular_end(data, gen_start)
    r_start = _skip(data, gen_end)
    if data[r_start : r_start + 1] != b"R":
        return i
    r_end = _regular_end(data, r_start)
    return r_end if r_end == r_start + 1 else i


def _apply(data: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    out, pos = [], 0
    for start, end, replacement in edits:
        out += [data[pos:start], replacement]
        pos = end
    out.append(data[pos:])
    return b"".join(out)


def _without_keys(data: bytes, operand: Operand, keys: tuple[bytes, ...]) -> bytes | None:
    entries = dict_entries(data, operand)
    kept = [data[s:e] for key, s, e in entries if key not in keys]
    if len(kept) == len(entries):
        return None
    return b"<<" + b" ".join(kept) + b">>"


def strip_text_properties(data: bytes, keys: tuple[bytes, ...] = TEXT_PROPERTIES) -> bytes | None:
    """Remove text-bearing entries from inline marked-content property lists.

    Returns the new stream, or None when nothing changed. Named property lists (resources) are
    handled by the caller.
    """
    edits = []
    for op in operations(data):
        if op.op in (b"BDC", b"DP") and len(op.operands) == 2 and op.operands[1].kind == "dict":
            props = op.operands[1]
            replacement = _without_keys(data, props, keys)
            if replacement is not None:
                edits.append((props.start, props.end, replacement))
    return _apply(data, edits) if edits else None


def property_names(data: bytes) -> set[bytes]:
    """Names of resource property lists used by marked-content operators (without the slash)."""
    names = set()
    for op in operations(data):
        if op.op in (b"BDC", b"DP") and len(op.operands) == 2 and op.operands[1].kind == "name":
            o = op.operands[1]
            names.add(data[o.start + 1 : o.end])
    return names


@dataclass
class OptionalContentResult:
    data: bytes | None  # None when unchanged
    removed: int  # painting operators removed from hidden content


def remove_hidden_content(
    data: bytes,
    is_hidden: Callable[[bytes], bool],
    flatten: bool = True,
    hidden_xobject: Callable[[bytes], bool] | None = None,
) -> OptionalContentResult:
    """Remove what hidden optional content paints, keeping its graphics-state changes.

    `is_hidden(name)` decides for each ``/OC /name BDC`` property list. Inside hidden content,
    text showing, path painting, shadings, XObjects and inline images are dropped (path painting
    becomes ``n`` so clipping still applies); state operators such as ``q``/``Q``/``cm`` stay, as
    viewers also execute them. With `flatten`, visible optional-content markers become plain
    ``/OC BMC`` so the content no longer depends on layer settings. `hidden_xobject(name)` drops
    ``/name Do`` for XObjects that are themselves optional content and hidden.
    """
    edits: list[tuple[int, int, bytes]] = []
    stack: list[bool] = []  # per open marked-content sequence: is it (inside) hidden content
    removed = 0
    for op in operations(data):
        hidden = bool(stack) and stack[-1]
        name = op.op
        if name in (b"BDC", b"BMC"):
            starts_oc = (
                name == b"BDC"
                and len(op.operands) == 2
                and data[op.operands[0].start : op.operands[0].end] == b"/OC"
            )
            if hidden:
                stack.append(True)
                edits.append((op.start, op.end, b""))
                continue
            if starts_oc:
                props = op.operands[1]
                now_hidden = props.kind == "name" and is_hidden(data[props.start + 1 : props.end])
                stack.append(now_hidden)
                if now_hidden or flatten:
                    edits.append((op.start, op.end, b"/OC BMC"))
                continue
            stack.append(False)
            continue
        if name == b"EMC":
            inner = len(stack) > 1 and stack[-2]
            if stack:
                stack.pop()
            if inner:
                edits.append((op.start, op.end, b""))
            continue
        if not hidden:
            if (
                name == b"Do"
                and hidden_xobject is not None
                and len(op.operands) == 1
                and op.operands[0].kind == "name"
                and hidden_xobject(data[op.operands[0].start + 1 : op.operands[0].end])
            ):
                edits.append((op.start, op.end, b""))
                removed += 1
            continue
        if name in (b"Tj", b"TJ", b"sh", b"Do", b"BI", b"MP", b"DP"):
            edits.append((op.start, op.end, b""))
        elif name == b"'":
            edits.append((op.start, op.end, b"T*"))
        elif name == b'"' and len(op.operands) == 3:
            aw, ac = (data[o.start : o.end] for o in op.operands[:2])
            edits.append((op.start, op.end, aw + b" Tw " + ac + b" Tc T*"))
        elif name in PATH_PAINTING:
            edits.append((op.end - len(name), op.end, b"n"))
        else:
            continue
        if name not in (b"MP", b"DP"):
            removed += 1
    if not edits:
        return OptionalContentResult(None, 0)
    return OptionalContentResult(_apply(data, edits), removed)


def optional_content_markers(data: bytes) -> int:
    """Number of ``/OC`` marked-content sequences in a stream."""
    return sum(
        1
        for op in operations(data)
        if op.op == b"BDC"
        and len(op.operands) == 2
        and data[op.operands[0].start : op.operands[0].end] == b"/OC"
    )


def has_text_properties(data: bytes, keys: tuple[bytes, ...] = TEXT_PROPERTIES) -> bool:
    for op in operations(data):
        if (
            op.op in (b"BDC", b"DP")
            and len(op.operands) == 2
            and op.operands[1].kind == "dict"
            and any(key in keys for key, _, _ in dict_entries(data, op.operands[1]))
        ):
            return True
    return False
