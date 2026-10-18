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
