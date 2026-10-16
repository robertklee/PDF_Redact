"""Request/response schemas for the HTTP API (camelCase on the wire)."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from .core.redact import Appearance, Mark, RedactOptions

HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    return tuple(int(value[i : i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def _normalise_rect(r: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not all(math.isfinite(v) for v in r):
        raise ValueError("rect coordinates must be finite numbers")
    x0, y0, x1, y1 = r
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


Rect = Annotated[tuple[float, float, float, float], AfterValidator(_normalise_rect)]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AppearanceIn(ApiModel):
    fill: HexColor | None = "#000000"
    text_color: HexColor = "#ffffff"
    overlay_text: str = Field(default="", max_length=200)
    font_size: float | None = Field(default=None, ge=4, le=72)
    align: Literal["left", "center", "right"] = "center"

    def to_engine(self) -> Appearance:
        return Appearance(
            fill=_hex_to_rgb(self.fill) if self.fill else None,
            text_color=_hex_to_rgb(self.text_color),
            overlay_text=self.overlay_text,
            font_size=self.font_size,
            align=self.align,
        )


class MarkIn(ApiModel):
    id: str = Field(min_length=1, max_length=100)
    page: int = Field(ge=0)
    kind: Literal["text", "area", "page"]
    rects: list[Rect] = Field(default_factory=list, max_length=10_000)
    appearance: AppearanceIn = Field(default_factory=AppearanceIn)

    @field_validator("rects")
    @classmethod
    def _rects_required(cls, rects: list, info) -> list:
        if info.data.get("kind") != "page" and not rects:
            raise ValueError("text and area marks need at least one rect")
        return rects

    def to_engine(self) -> Mark:
        return Mark(self.id, self.page, self.kind, list(self.rects), self.appearance.to_engine())


class OptionsIn(ApiModel):
    images: Literal["pixels", "remove", "none"] = "pixels"
    graphics: Literal["covered", "touched", "none"] = "covered"

    def to_engine(self) -> RedactOptions:
        return RedactOptions(images=self.images, graphics=self.graphics)


class ApplyRequest(ApiModel):
    marks: list[MarkIn] = Field(max_length=100_000)
    options: OptionsIn = Field(default_factory=OptionsIn)


class UnlockRequest(ApiModel):
    password: str = Field(max_length=1024)


class PageOut(ApiModel):
    index: int
    width: float
    height: float
    rotation: int


class NoticeOut(ApiModel):
    code: str
    level: Literal["info", "warning"]
    message: str


class DocumentOut(ApiModel):
    id: str
    filename: str
    size: int
    sha256: str
    needs_password: bool
    page_count: int
    pages: list[PageOut]
    notices: list[NoticeOut]


class CheckOut(ApiModel):
    name: str
    status: Literal["pass", "warn", "fail"]
    message: str
    page: int | None = None
    mark_id: str | None = None


class VerificationOut(ApiModel):
    passed: bool
    counts: dict[str, int]
    checks: list[CheckOut]


class StatsOut(ApiModel):
    marks: int
    rects: int
    pages: list[int]
    glyphs_removed: int
    text_marks_as_area: list[str]
    safety_pass_glyphs: int


class OutputOut(ApiModel):
    id: str
    document_id: str
    filename: str
    size: int
    sha256: str
    stats: StatsOut
    verification: VerificationOut
