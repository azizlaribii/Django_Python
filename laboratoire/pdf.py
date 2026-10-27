import unicodedata
import textwrap


def _pdf_text(value):
    value = str(value).replace("œ", "oe").replace("Œ", "OE")
    value = value.replace("æ", "ae").replace("Æ", "AE").replace("ß", "ss")
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.replace("\r", " ").replace("\n", " ")
    escaped = ascii_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("ascii")


def _patient_pdf_text(value):
    value = unicodedata.normalize("NFKC", str(value))
    encoded = value.encode("cp1252", "replace")
    escaped = (
        encoded.replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
        .replace(b"\r", b" ")
        .replace(b"\n", b" ")
    )
    return escaped


def build_report_pdf(lines):
    wrapped_lines = []
    for line in lines:
        if not str(line):
            wrapped_lines.append("")
        else:
            wrapped_lines.extend(textwrap.wrap(
                str(line), width=85, break_long_words=True,
                break_on_hyphens=False,
            ))
    pages = [
        wrapped_lines[index:index + 48]
        for index in range(0, len(wrapped_lines), 48)
    ] or [[]]
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []

    for page_lines in pages:
        stream = bytearray(b"BT\n/F1 10 Tf\n50 790 Td\n14 TL\n")
        for line in page_lines:
            stream.extend(b"(" + _pdf_text(line) + b") Tj\nT*\n")
        stream.extend(b"ET\n")
        content_id = len(objects) + 1
        objects.append(
            b"<< /Length " + str(len(stream)).encode("ascii")
            + b" >>\nstream\n" + bytes(stream) + b"endstream"
        )
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(content_id).encode("ascii") + b" 0 R >>"
        )

    kids = b" ".join(str(page_id).encode("ascii") + b" 0 R" for page_id in page_ids)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(len(page_ids)).encode("ascii") + b" >>"
    )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(
            str(object_id).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n"
        )
    xref_offset = len(output)
    output.extend(b"xref\n0 " + str(len(objects) + 1).encode("ascii") + b"\n")
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        b"trailer\n<< /Size " + str(len(objects) + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii") + b"\n%%EOF"
    )
    return bytes(output)


class _PatientReportPdf:
    page_width = 595
    page_height = 842
    left = 44
    right = 551
    bottom = 54

    def __init__(self, patient_name, metadata, laboratory_name, header_text):
        self.patient_name = patient_name
        self.metadata = metadata
        self.laboratory_name = laboratory_name
        self.header_text = header_text
        self.pages = []
        self.y = 0
        self._new_page(first=True)

    def _emit(self, command):
        if isinstance(command, str):
            command = command.encode("ascii")
        self.pages[-1].extend(command)

    def _set_fill(self, color):
        self._emit(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg\n")

    def _set_stroke(self, color):
        self._emit(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG\n")

    def _rect(self, x, y, width, height, color, stroke=None):
        self._emit("q\n")
        self._set_fill(color)
        if stroke:
            self._set_stroke(stroke)
            self._emit(f"{x} {y} {width} {height} re B\n")
        else:
            self._emit(f"{x} {y} {width} {height} re f\n")
        self._emit("Q\n")

    def _round_rect(self, x, y, width, height, radius, color):
        curve = radius * 0.55228475
        self._emit(
            "q\n"
            f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg\n"
            f"{x + radius} {y} m "
            f"{x + width - radius} {y} l "
            f"{x + width - radius + curve:.2f} {y} "
            f"{x + width} {y + radius - curve:.2f} "
            f"{x + width} {y + radius} c "
            f"{x + width} {y + height - radius} l "
            f"{x + width} {y + height - radius + curve:.2f} "
            f"{x + width - radius + curve:.2f} {y + height} "
            f"{x + width - radius} {y + height} c "
            f"{x + radius} {y + height} l "
            f"{x + radius - curve:.2f} {y + height} "
            f"{x} {y + height - radius + curve:.2f} "
            f"{x} {y + height - radius} c "
            f"{x} {y + radius} l "
            f"{x} {y + radius - curve:.2f} "
            f"{x + radius - curve:.2f} {y} "
            f"{x + radius} {y} c f Q\n"
        )

    def _line(self, x1, y1, x2, y2, color=(0.86, 0.89, 0.93), width=0.8):
        self._emit(
            f"q {color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG "
            f"{width:.1f} w {x1} {y1} m {x2} {y2} l S Q\n"
        )

    def _circle(self, center_x, center_y, radius, color):
        curve = radius * 0.55228475
        self._emit(
            "q\n"
            f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg\n"
            f"{center_x + radius:.2f} {center_y:.2f} m\n"
            f"{center_x + radius:.2f} {center_y + curve:.2f} "
            f"{center_x + curve:.2f} {center_y + radius:.2f} "
            f"{center_x:.2f} {center_y + radius:.2f} c\n"
            f"{center_x - curve:.2f} {center_y + radius:.2f} "
            f"{center_x - radius:.2f} {center_y + curve:.2f} "
            f"{center_x - radius:.2f} {center_y:.2f} c\n"
            f"{center_x - radius:.2f} {center_y - curve:.2f} "
            f"{center_x - curve:.2f} {center_y - radius:.2f} "
            f"{center_x:.2f} {center_y - radius:.2f} c\n"
            f"{center_x + curve:.2f} {center_y - radius:.2f} "
            f"{center_x + radius:.2f} {center_y - curve:.2f} "
            f"{center_x + radius:.2f} {center_y:.2f} c f Q\n"
        )

    def _text(self, value, x, y, size=10, *, bold=False, color=(0.10, 0.16, 0.24)):
        font = "F2" if bold else "F1"
        safe = _patient_pdf_text(value)
        self._emit(
            f"BT /{font} {size} Tf {color[0]:.3f} {color[1]:.3f} "
            f"{color[2]:.3f} rg {x:.1f} {y:.1f} Td (".encode("ascii")
            + safe
            + b") Tj ET\n"
        )

    def _wrapped(self, value, width, size=10):
        limit = max(18, int(width / (size * 0.52)))
        wrapped = []
        for paragraph in str(value or "").replace("\r", "").split("\n"):
            wrapped.extend(textwrap.wrap(
                paragraph,
                width=limit,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [""])
        return wrapped or [""]

    def _logo(self):
        x, y, size = self.left, 777, 38
        self._round_rect(x, y, size, size, 8, (0.02, 0.68, 0.79))
        ink = (0.04, 0.20, 0.34)
        self._emit(
            f"q {ink[0]:.3f} {ink[1]:.3f} {ink[2]:.3f} RG "
            "2.0 w 1 J 1 j "
            f"{x + 11} {y + 28} m {x + 11} {y + 21} l "
            f"{x + 11} {y + 18} {x + 14} {y + 16} {x + 17} {y + 16} c "
            f"{x + 20} {y + 16} {x + 22} {y + 19} {x + 22} {y + 22} c "
            f"{x + 22} {y + 19} {x + 24} {y + 16} {x + 27} {y + 16} c "
            f"{x + 30} {y + 16} {x + 32} {y + 19} {x + 32} {y + 22} c "
            f"{x + 32} {y + 15} {x + 31} {y + 12} {x + 28} {y + 10} c "
            f"{x + 25} {y + 8} {x + 22} {y + 9} {x + 22} {y + 5} c S "
            f"{x + 19} {y + 28} m {x + 19} {y + 24} l "
            f"{x + 19} {y + 21} {x + 22} {y + 19} {x + 25} {y + 19} c S Q\n"
        )
        self._circle(x + 22, y + 5, 2.3, ink)
        self._text("Santé", x + 47, y + 23, 16, bold=True, color=(0.10, 0.16, 0.24))
        self._text("Connect", x + 87, y + 23, 16, bold=True, color=(0.02, 0.43, 0.69))
        self._text(
            self.laboratory_name or "LABORATOIRE",
            x + 47,
            y + 8,
            8,
            bold=True,
            color=(0.38, 0.45, 0.54),
        )

    def _footer(self, page_number, total_pages):
        self._line(self.left, 42, self.right, 42)
        self._text(
            "Document confidentiel - destine au patient concerne",
            self.left,
            28,
            8,
            color=(0.38, 0.45, 0.54),
        )
        self._text(
            f"Page {page_number} / {total_pages}",
            self.right - 58,
            28,
            8,
            color=(0.38, 0.45, 0.54),
        )

    def _new_page(self, *, first=False):
        self.pages.append(bytearray())
        self._rect(0, 833, self.page_width, 9, (0.02, 0.68, 0.79))
        self._logo()
        self._text(
            "CONFIDENTIEL",
            self.right - 75,
            796,
            8,
            bold=True,
            color=(0.31, 0.22, 0.64),
        )
        self._line(self.left, 765, self.right, 765, (0.78, 0.83, 0.90), 1.0)
        if first:
            title = self.header_text or "COMPTE RENDU D'ANALYSES"
            title_lines = self._wrapped(title, self.right - self.left, 20)
            for index, line in enumerate(title_lines):
                self._text(
                    line,
                    self.left,
                    739 - index * 23,
                    20,
                    bold=True,
                    color=(0.10, 0.16, 0.24),
                )
            subtitle_y = 739 - len(title_lines) * 23
            self._text(
                "Espace patient - Resultats de laboratoire",
                self.left,
                subtitle_y,
                9,
                color=(0.38, 0.45, 0.54),
            )
            self.y = subtitle_y - 18
            self._metadata_card()
        else:
            self._text(
                "COMPTE RENDU D'ANALYSES - SUITE",
                self.left,
                739,
                14,
                bold=True,
                color=(0.10, 0.16, 0.24),
            )
            self._text(
                f"Patient : {self.patient_name}",
                self.left,
                720,
                9,
                color=(0.38, 0.45, 0.54),
            )
            self.y = 695

    def _metadata_card(self):
        card_top = self.y
        row_gap = 31
        rows = (len(self.metadata) + 1) // 2
        card_height = 44 + rows * row_gap
        self._rect(
            self.left,
            card_top - card_height,
            self.right - self.left,
            card_height,
            (0.96, 0.97, 0.99),
            (0.86, 0.89, 0.93),
        )
        self._text("PATIENT", self.left + 13, card_top - 16, 7, bold=True, color=(0.38, 0.45, 0.54))
        self._text(
            self.patient_name,
            self.left + 13,
            card_top - 31,
            11,
            bold=True,
        )
        self.y = card_top - 48
        x_columns = (self.left + 13, self.left + 260)
        for index, (label, value) in enumerate(self.metadata):
            column = index % 2
            if column == 0 and index:
                self.y -= row_gap
            x = x_columns[column]
            self._text(label.upper(), x, self.y, 7, bold=True, color=(0.38, 0.45, 0.54))
            self._text(value, x, self.y - 13, 9, color=(0.10, 0.16, 0.24))
        self.y = card_top - card_height - 18

    def _ensure_space(self, height):
        if self.y - height < self.bottom:
            self._new_page()

    def _write_detail(self, label, value):
        lines = self._wrapped(value, self.right - self.left - 28, 9)
        self._ensure_space(25)
        self._text(
            label.upper(),
            self.left + 14,
            self.y,
            7,
            bold=True,
            color=(0.38, 0.45, 0.54),
        )
        self.y -= 12
        for line in lines:
            self._ensure_space(12)
            self._text(line, self.left + 14, self.y, 9)
            self.y -= 12
        self.y -= 4

    def add_result(self, result):
        self._ensure_space(78)
        self.y -= 5
        title_lines = self._wrapped(
            result.get("title", "Analyse"),
            self.right - self.left - 28,
            11,
        )
        title_line_height = 14
        heading_height = 15 + len(title_lines) * title_line_height
        heading_bottom = self.y - heading_height
        self._rect(
            self.left,
            heading_bottom,
            self.right - self.left,
            heading_height,
            (0.92, 0.97, 0.98),
            (0.82, 0.90, 0.92),
        )
        title_y = self.y - 15
        for line in title_lines:
            self._text(line, self.left + 13, title_y, 11, bold=True)
            title_y -= title_line_height
        self.y = heading_bottom - 15

        value = result.get("value")
        if value is not None:
            unit = result.get("unit", "")
            display_value = f"{value} {unit}".strip()
            value_lines = self._wrapped(display_value, self.right - self.left - 30, 18)
            self._ensure_space(25)
            self._text(
                "RESULTAT",
                self.left + 14,
                self.y,
                7,
                bold=True,
                color=(0.02, 0.43, 0.52),
            )
            self.y -= 23
            for line in value_lines:
                self._ensure_space(23)
                self._text(
                    line,
                    self.left + 14,
                    self.y,
                    18,
                    bold=True,
                    color=(0.02, 0.43, 0.52),
                )
                self.y -= 23
            self.y -= 3

        for label, detail in result.get("details", ()):
            self._write_detail(label, detail)
        self.y -= 12
        self._line(self.left, self.y, self.right, self.y, (0.90, 0.92, 0.95), 0.6)
        self.y -= 15

    def finish(self, signature=None):
        if signature:
            for line in self._wrapped(signature, self.right - self.left, 9):
                self._ensure_space(13)
                self._text(line, self.left, self.y, 9)
                self.y -= 13
        total_pages = len(self.pages)
        for index in range(1, total_pages + 1):
            self._footer_stream(index, total_pages)
        return _assemble_pdf(self.pages)

    def _footer_stream(self, page_number, total_pages):
        original_page = self.pages
        self.pages = [original_page[page_number - 1]]
        self._footer(page_number, total_pages)
        self.pages = original_page


def _assemble_pdf(page_streams):
    objects = [
        b"",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>",
    ]
    page_ids = []
    for stream in page_streams:
        content_id = len(objects) + 1
        objects.append(
            b"<< /Length " + str(len(stream)).encode("ascii")
            + b" >>\nstream\n" + bytes(stream) + b"endstream"
        )
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents "
            + str(content_id).encode("ascii") + b" 0 R >>"
        )
    kids = b" ".join(str(page_id).encode("ascii") + b" 0 R" for page_id in page_ids)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(len(page_ids)).encode("ascii") + b" >>"
    )
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(
            str(object_id).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n"
        )
    xref_offset = len(output)
    output.extend(b"xref\n0 " + str(len(objects) + 1).encode("ascii") + b"\n")
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        b"trailer\n<< /Size " + str(len(objects) + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii") + b"\n%%EOF"
    )
    return bytes(output)


def build_patient_report_pdf(
    *,
    patient_name,
    metadata,
    results,
    laboratory_name="",
    header_text="",
    signature="",
):
    report = _PatientReportPdf(
        patient_name=patient_name,
        metadata=metadata,
        laboratory_name=laboratory_name,
        header_text=header_text,
    )
    for result in results:
        report.add_result(result)
    return report.finish(signature=signature)
