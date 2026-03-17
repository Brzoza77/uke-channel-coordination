from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO
import unicodedata


mm = 72.0 / 25.4
A4 = (210.0 * mm, 297.0 * mm)


def _clamp_rgb(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class HexColor:
    value: str

    def as_rgb(self) -> tuple[float, float, float]:
        raw = self.value.strip()
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) != 6:
            raise ValueError(f"Unsupported hex color: {self.value!r}")
        r = int(raw[0:2], 16) / 255.0
        g = int(raw[2:4], 16) / 255.0
        b = int(raw[4:6], 16) / 255.0
        return (_clamp_rgb(r), _clamp_rgb(g), _clamp_rgb(b))


WHITE = HexColor("#ffffff")


def _pdf_escape_text(value: str) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _pdf_safe_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.replace("\r", " ").replace("\n", " ")


def _glyph_unit_width(char: str) -> float:
    if char == " ":
        return 0.28
    if char in ".,:;!|`'":
        return 0.24
    if char in "[](){}":
        return 0.33
    if char in "ilIjft":
        return 0.32
    if char in "mwMW@#%&":
        return 0.84
    if char.isdigit():
        return 0.56
    if char.isupper():
        return 0.67
    return 0.52


class SimplePdfCanvas:
    def __init__(self, buffer: BinaryIO | BytesIO, *, pagesize: tuple[float, float] = A4):
        self._buffer = buffer
        self._page_width, self._page_height = pagesize
        self._commands: list[str] = []
        self._font_name = "Helvetica"
        self._font_size = 12.0
        self._fill_rgb = (0.0, 0.0, 0.0)
        self._stroke_rgb = (0.0, 0.0, 0.0)
        self._line_width = 1.0
        self._title = "Document"
        self._author = "Unknown"

    def setTitle(self, title: str) -> None:
        self._title = _pdf_safe_text(title)

    def setAuthor(self, author: str) -> None:
        self._author = _pdf_safe_text(author)

    def setFont(self, font_name: str, font_size: float) -> None:
        self._font_name = font_name
        self._font_size = float(font_size)

    def setFillColor(self, color: HexColor | tuple[float, float, float]) -> None:
        if isinstance(color, HexColor):
            self._fill_rgb = color.as_rgb()
        else:
            self._fill_rgb = tuple(_clamp_rgb(part) for part in color)

    def setStrokeColor(self, color: HexColor | tuple[float, float, float]) -> None:
        if isinstance(color, HexColor):
            self._stroke_rgb = color.as_rgb()
        else:
            self._stroke_rgb = tuple(_clamp_rgb(part) for part in color)

    def setLineWidth(self, width: float) -> None:
        self._line_width = max(0.1, float(width))

    def drawString(self, x: float, y: float, text: str) -> None:
        safe_text = _pdf_escape_text(_pdf_safe_text(text))
        font_ref = "F2" if self._font_name == "Helvetica-Bold" else "F1"
        r, g, b = self._fill_rgb
        self._commands.append(
            f"BT /{font_ref} {self._font_size:.2f} Tf {r:.4f} {g:.4f} {b:.4f} rg "
            f"1 0 0 1 {float(x):.2f} {float(y):.2f} Tm ({safe_text}) Tj ET"
        )

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        r, g, b = self._stroke_rgb
        self._commands.append(
            f"{r:.4f} {g:.4f} {b:.4f} RG {self._line_width:.2f} w "
            f"{float(x1):.2f} {float(y1):.2f} m {float(x2):.2f} {float(y2):.2f} l S"
        )

    def rect(self, x: float, y: float, width: float, height: float, *, fill: int = 0, stroke: int = 1) -> None:
        commands: list[str] = []
        if fill:
            fr, fg, fb = self._fill_rgb
            commands.append(f"{fr:.4f} {fg:.4f} {fb:.4f} rg")
        if stroke:
            sr, sg, sb = self._stroke_rgb
            commands.append(f"{sr:.4f} {sg:.4f} {sb:.4f} RG {self._line_width:.2f} w")
        operator = "B" if fill and stroke else "f" if fill else "S"
        commands.append(f"{float(x):.2f} {float(y):.2f} {float(width):.2f} {float(height):.2f} re {operator}")
        self._commands.append(" ".join(commands))

    def string_width(self, text: str, font_name: str, font_size: float) -> float:
        safe_text = _pdf_safe_text(text)
        bold_bonus = 1.04 if font_name == "Helvetica-Bold" else 1.0
        width_units = sum(_glyph_unit_width(char) for char in safe_text)
        return width_units * float(font_size) * bold_bonus

    def showPage(self) -> None:
        return

    def save(self) -> None:
        pdf_bytes = self._build_pdf()
        self._buffer.write(pdf_bytes)

    def _build_pdf(self) -> bytes:
        stream = "\n".join(self._commands).encode("latin-1", "replace")
        objects: list[bytes] = []

        def add_object(payload: bytes) -> int:
            objects.append(payload)
            return len(objects)

        catalog_id = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
        pages_id = add_object(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        page_payload = (
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 {self._page_width:.2f} {self._page_height:.2f}] "
            f"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> "
            f"/Contents 6 0 R >>"
        ).encode("ascii")
        page_id = add_object(page_payload)
        helvetica_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        helvetica_bold_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        stream_id = add_object(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
        info_id = add_object(
            f"<< /Title ({_pdf_escape_text(self._title)}) /Author ({_pdf_escape_text(self._author)}) >>".encode("latin-1")
        )

        assert catalog_id == 1
        assert page_id == 3
        assert helvetica_id == 4
        assert helvetica_bold_id == 5
        assert stream_id == 6
        assert info_id == 7

        output = bytearray()
        output.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]

        for index, payload in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{index} 0 obj\n".encode("ascii"))
            output.extend(payload)
            output.extend(b"\nendobj\n")

        xref_start = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

        trailer = (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        )
        output.extend(trailer.encode("ascii"))
        return bytes(output)
