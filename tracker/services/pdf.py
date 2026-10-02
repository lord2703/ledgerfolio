"""PDF documents (receipts now, quotations later) drawn with ReportLab.

The PDF is built only from the receipt's own snapshot fields, so it can be
regenerated at any time and always says the same thing.
"""

import io

import qrcode
from django.conf import settings
from django.utils import timezone
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

INK = HexColor("#0B1020")
GOLD = HexColor("#B8892E")
GOLD_LIGHT = HexColor("#E3B866")
TEXT = HexColor("#1B2033")
MUTED = HexColor("#6B7186")
RULE = HexColor("#E2DDD0")
PAPER = HexColor("#FBF9F4")

# What changes between document types. The layout stays the same.
DOCUMENTS = {
    "receipt": {
        "title": "OFFICIAL RECEIPT",
        "party": "RECEIVED FROM",
        "amount": "AMOUNT PAID",
        "balance": "Remaining balance",
        "date": "Payment date",
    },
    "quotation": {
        "title": "QUOTATION",
        "party": "PREPARED FOR",
        "amount": "QUOTED PRICE",
        "balance": "Balance on acceptance",
        "date": "Quotation date",
    },
}


def money(amount) -> str:
    return f"{settings.CURRENCY_CODE} {amount:,.2f}"


def _qr_image(data: str) -> ImageReader:
    # border=4 is the quiet zone the QR standard asks for: without it phone
    # cameras read the code less reliably.
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    code.add_data(data)
    code.make(fit=True)
    buffer = io.BytesIO()
    code.make_image(fill_color="#0B1020", back_color="white").save(buffer, format="PNG")
    buffer.seek(0)
    return ImageReader(buffer)


def _fit(text: str, font: str, size: float, max_width: float) -> float:
    """Shrink a font size until the text fits the width."""
    while size > 6 and stringWidth(text, font, size) > max_width:
        size -= 0.5
    return size


def _spaced_width(text: str, font: str, size: float, spacing: float = 1.6) -> float:
    return stringWidth(text, font, size) + spacing * len(text)


def _spaced(pdf, x, y, text, font, size, spacing=1.6, align="left"):
    """Letter-spaced small caps. Character spacing is part of the PDF graphics
    state and would leak into every later line, so it is drawn inside a
    saved state that is restored straight after."""
    if align == "right":
        x -= _spaced_width(text, font, size, spacing)
    pdf.saveState()
    text_object = pdf.beginText(x, y)
    text_object.setFont(font, size)
    text_object.setCharSpace(spacing)
    text_object.textOut(text)
    pdf.drawText(text_object)
    pdf.restoreState()


def _long_date(value) -> str:
    """'July 4, 2026': no zero-padded day."""
    return f"{value:%B} {value.day}, {value:%Y}"


def build_receipt_pdf(receipt) -> bytes:
    labels = DOCUMENTS.get(receipt.document_type, DOCUMENTS["receipt"])
    width, height = A5
    margin = 14 * mm
    inner = width - 2 * margin

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A5)
    pdf.setTitle(f"{labels['title'].title()} {receipt.receipt_number}")
    pdf.setAuthor(settings.OWNER_NAME)
    pdf.setSubject(f"{receipt.get_document_type_display()} for {receipt.system_name}")

    pdf.setFillColor(PAPER)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)

    # --- Header band ---------------------------------------------------
    band = 34 * mm
    pdf.setFillColor(INK)
    pdf.rect(0, height - band, width, band, stroke=0, fill=1)
    pdf.setFillColor(GOLD_LIGHT)
    pdf.rect(0, height - band - 1.2, width, 1.2, stroke=0, fill=1)

    _spaced(pdf, margin, height - 15 * mm, settings.SITE_NAME.upper(), "Helvetica-Bold", 15, 3)
    pdf.setFillColor(HexColor("#B9BED0"))
    pdf.setFont("Helvetica", 8)
    pdf.drawString(margin, height - 21 * mm, f"{settings.OWNER_NAME}  ·  {settings.OWNER_TITLE}")

    pdf.setFillColor(HexColor("#FFFFFF"))
    _spaced(pdf, width - margin, height - 14 * mm, labels["title"], "Helvetica-Bold", 9, align="right")
    pdf.setFillColor(GOLD_LIGHT)
    pdf.setFont("Courier-Bold", 12)
    pdf.drawRightString(width - margin, height - 21 * mm, receipt.receipt_number)

    # --- Party and issue date -------------------------------------------
    y = height - band - 15 * mm
    pdf.setFillColor(MUTED)
    _spaced(pdf, margin, y, labels["party"], "Helvetica", 7)
    _spaced(pdf, width - margin, y, "ISSUED", "Helvetica", 7, align="right")

    y -= 7 * mm
    pdf.setFillColor(TEXT)
    name_size = _fit(receipt.client_name, "Helvetica-Bold", 16, inner - 42 * mm)
    pdf.setFont("Helvetica-Bold", name_size)
    pdf.drawString(margin, y, receipt.client_name)
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(width - margin, y, _long_date(timezone.localtime(receipt.issued_at)))

    # --- Detail rows ------------------------------------------------------
    y -= 9 * mm
    rows = [
        ("System", receipt.system_name),
        (labels["date"], _long_date(receipt.payment_date)),
        ("Payment method", receipt.get_payment_method_display()),
    ]
    pdf.setStrokeColor(RULE)
    pdf.setLineWidth(0.6)
    for label, value in rows:
        pdf.line(margin, y, width - margin, y)
        y -= 6.5 * mm
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8.5)
        pdf.drawString(margin, y, label)
        pdf.setFillColor(TEXT)
        value_size = _fit(value, "Helvetica-Bold", 9.5, inner - 36 * mm)
        pdf.setFont("Helvetica-Bold", value_size)
        pdf.drawRightString(width - margin, y, value)
        y -= 3.5 * mm
    pdf.line(margin, y, width - margin, y)

    # --- Amount panel -------------------------------------------------------
    panel_height = 30 * mm
    y -= 6 * mm + panel_height
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setStrokeColor(RULE)
    pdf.roundRect(margin, y, inner, panel_height, 3 * mm, stroke=1, fill=1)
    pdf.setFillColor(GOLD)
    pdf.roundRect(margin, y, 1.6 * mm, panel_height, 0.8 * mm, stroke=0, fill=1)

    pdf.setFillColor(MUTED)
    _spaced(pdf, margin + 7 * mm, y + panel_height - 8 * mm, labels["amount"], "Helvetica", 7)
    pdf.setFillColor(TEXT)
    amount_text = money(receipt.amount)
    pdf.setFont("Helvetica-Bold", _fit(amount_text, "Helvetica-Bold", 24, inner - 14 * mm))
    pdf.drawString(margin + 7 * mm, y + 11 * mm, amount_text)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(
        margin + 7 * mm, y + 5 * mm, f"{labels['balance']}: {money(receipt.balance_after)}"
    )

    # --- Verification block -------------------------------------------------
    qr_size = 30 * mm
    y -= 8 * mm + qr_size
    qr_box = qr_size + 4 * mm
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.roundRect(margin, y - 2 * mm, qr_box, qr_box, 2 * mm, stroke=1, fill=1)
    pdf.drawImage(_qr_image(receipt.verify_url), margin, y - 2 * mm, qr_box, qr_box)

    text_x = margin + qr_size + 9 * mm
    text_width = width - margin - text_x
    line_y = y + qr_size - 3 * mm
    pdf.setFillColor(GOLD)
    _spaced(pdf, text_x, line_y, "VERIFY THIS DOCUMENT", "Helvetica-Bold", 7.5)
    pdf.setFillColor(TEXT)
    pdf.setFont("Helvetica", 8)
    for line in (
        "Scan the QR code, or open the link below,",
        "to check this document against the",
        f"{settings.SITE_NAME} blockchain.",
    ):
        line_y -= 4.2 * mm
        pdf.drawString(text_x, line_y, line)

    line_y -= 6 * mm
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(text_x, line_y, "SHA-256 FINGERPRINT")
    pdf.setFillColor(TEXT)
    fingerprint = receipt.content_hash or "not fingerprinted yet"
    for chunk in (fingerprint[:32], fingerprint[32:]):
        if chunk:
            line_y -= 3.4 * mm
            pdf.setFont("Courier", _fit(chunk, "Courier", 7, text_width))
            pdf.drawString(text_x, line_y, chunk)

    # --- Verify link and footer ----------------------------------------------
    y -= 9 * mm
    pdf.setFillColor(MUTED)
    link = receipt.verify_url
    pdf.setFont("Courier", _fit(link, "Courier", 7, inner))
    pdf.drawString(margin, y, link)
    pdf.linkURL(link, (margin, y - 2, width - margin, y + 8), relative=0)

    pdf.setStrokeColor(RULE)
    pdf.line(margin, 16 * mm, width - margin, 16 * mm)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.5)
    contact = "  ·  ".join(
        part for part in (settings.OWNER_NAME, settings.OWNER_EMAIL, settings.OWNER_PHONE) if part
    )
    pdf.drawString(margin, 11 * mm, contact)
    pdf.drawRightString(width - margin, 11 * mm, "Thank you.")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
