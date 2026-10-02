"""Issuing receipts: snapshot the payment, anchor it on the ledger, build the
PDF and email it to the client."""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.template.loader import render_to_string
from django.utils import timezone

from ledger import services as ledger
from tracker.models import ZERO, Payment, Receipt

from .pdf import build_receipt_pdf, money

logger = logging.getLogger(__name__)

NUMBER_PREFIX = {
    Receipt.DocumentType.RECEIPT: "RCT",
    Receipt.DocumentType.QUOTATION: "QTN",
}


def next_receipt_number(document_type: str, year: int) -> str:
    prefix = f"{NUMBER_PREFIX[document_type]}-{year}-"
    last = (
        Receipt.objects.filter(receipt_number__startswith=prefix)
        .order_by("-receipt_number")
        .values_list("receipt_number", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:04d}"


def balance_after(payment: Payment):
    """What the client still owed right after this payment was made."""
    project = payment.project
    paid = project.payments.filter(
        Q(date__lt=payment.date) | Q(date=payment.date, pk__lte=payment.pk)
    ).aggregate(total=Sum("amount"))["total"] or ZERO
    return project.total_price - paid


def issue_receipt(payment: Payment) -> Receipt:
    """Create the receipt record for a payment: number, token and data snapshot."""
    issued_at = timezone.now()
    snapshot = {
        "payment": payment,
        "issued_at": issued_at,
        "client_name": payment.project.client.name,
        "system_name": payment.project.system_name,
        "amount": payment.amount,
        "balance_after": balance_after(payment),
        "payment_method": payment.method,
        "payment_date": payment.date,
    }
    year = timezone.localtime(issued_at).year
    for attempt in range(5):
        try:
            with transaction.atomic():
                receipt = Receipt(
                    receipt_number=next_receipt_number(Receipt.DocumentType.RECEIPT, year),
                    **snapshot,
                )
                receipt.content_hash = ledger.receipt_hash(receipt)
                receipt.save()
                return receipt
        except IntegrityError:
            # Two receipts issued at the same moment picked the same number.
            if attempt == 4:
                raise


def store_pdf(receipt: Receipt) -> bytes:
    """(Re)generate the PDF and keep it in private storage."""
    content = build_receipt_pdf(receipt)
    if receipt.pdf:
        receipt.pdf.delete(save=False)
    receipt.pdf.save(f"{receipt.receipt_number}.pdf", ContentFile(content), save=True)
    return content


def send_receipt_email(receipt: Receipt, pdf: bytes, to_email: str) -> None:
    context = {
        "receipt": receipt,
        "amount": money(receipt.amount),
        "balance": money(receipt.balance_after),
        "verify_url": receipt.verify_url,
        "owner_name": settings.OWNER_NAME,
        "site_name": settings.SITE_NAME,
    }
    message = EmailMultiAlternatives(
        subject=f"Receipt {receipt.receipt_number} for {receipt.system_name}",
        body=render_to_string("tracker/email/receipt.txt", context),
        to=[to_email],
        reply_to=[settings.OWNER_EMAIL] if settings.OWNER_EMAIL else None,
    )
    message.attach_alternative(render_to_string("tracker/email/receipt.html", context), "text/html")
    message.attach(f"{receipt.receipt_number}.pdf", pdf, "application/pdf")
    message.send()
    receipt.emailed_to = to_email
    receipt.emailed_at = timezone.now()
    receipt.save(update_fields=["emailed_to", "emailed_at"])


@dataclass
class ReceiptOutcome:
    receipt: Receipt
    created: bool
    ledger_error: str = ""
    emailed: bool = False
    email_error: str = ""


def generate_and_send(payment: Payment, send_email: bool = True) -> ReceiptOutcome:
    """The admin's "Generate and send receipt" action for one payment.

    Each step is independent: if the node or the mail server is down the
    receipt still exists and the failed step can simply be run again.
    """
    receipt = payment.receipt
    created = receipt is None
    if created:
        receipt = issue_receipt(payment)
    outcome = ReceiptOutcome(receipt=receipt, created=created)

    if receipt.ledger_status != Receipt.LedgerStatus.CONFIRMED:
        try:
            ledger.anchor(receipt)
        except ledger.LedgerError as exc:
            outcome.ledger_error = str(exc)

    pdf = store_pdf(receipt)

    to_email = payment.project.client.email
    if not send_email:
        pass
    elif not to_email:
        outcome.email_error = "the client has no email address"
    else:
        try:
            send_receipt_email(receipt, pdf, to_email)
            outcome.emailed = True
        except Exception as exc:  # SMTP errors come in many shapes
            logger.exception("Could not email receipt %s", receipt)
            outcome.email_error = str(exc) or exc.__class__.__name__
    return outcome
