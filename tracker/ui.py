"""Presentation helpers shared by the Tracker admin, its dashboard and its search."""

from django.conf import settings
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.utils.html import format_html

from .models import Lead, Project, Receipt
from .services.pdf import money

# Screens use the short sign; receipt PDFs keep the code ("PHP 7,000.00").
CURRENCY_SYMBOLS = {"PHP": "₱", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}

STATUS_TONES = {
    Project.Status.IN_DEVELOPMENT: "info",
    Project.Status.READY_FOR_PRE_ORAL: "warn",
    Project.Status.READY_FOR_FINAL: "accent",
    Project.Status.FULLY_PAID: "good",
}
LEDGER_TONES = {
    Receipt.LedgerStatus.UNANCHORED: "bad",
    Receipt.LedgerStatus.PENDING: "warn",
    Receipt.LedgerStatus.CONFIRMED: "good",
}
LEAD_TONES = {
    Lead.Status.NEW: "accent",
    Lead.Status.CONTACTED: "info",
    Lead.Status.CONVERTED: "good",
    Lead.Status.DROPPED: "muted",
}


def badge(label, tone):
    """A small status pill. Tone picks the colour; the label always carries the meaning."""
    return format_html('<span class="lf-badge lf-badge--{}">{}</span>', tone, label)


def project_badge(project):
    return badge(project.get_status_display(), STATUS_TONES.get(project.status, "muted"))


def ledger_badge(receipt):
    return badge(receipt.get_ledger_status_display(), LEDGER_TONES[receipt.ledger_status])


def lead_badge(lead):
    return badge(lead.get_status_display(), LEAD_TONES.get(lead.status, "muted"))


def money_short(value) -> str:
    """₱7,000.00, or the code form when the currency has no sign listed."""
    symbol = CURRENCY_SYMBOLS.get(settings.CURRENCY_CODE)
    if not symbol:
        return money(value)
    return f"{'-' if value < 0 else ''}{symbol}{abs(value):,.2f}"


def amount(value):
    """Money that never wraps across two lines in a table cell."""
    return format_html('<span class="lf-money">{}</span>', money_short(value))


def when(value):
    """A date and time as two short lines, the time quieter. None stays None (shown as "-")."""
    if value is None:
        return None
    local = timezone.localtime(value)
    return format_html(
        '<span class="lf-when">{}<small>{}</small></span>',
        date_format(local, "M j, Y"), date_format(local, "g:i A"),
    )


def initials(name: str) -> str:
    words = [word for word in str(name).split() if word[:1].isalnum()]
    return "".join(word[0] for word in words[:2]).upper() or "?"


def entity(title, detail="", avatar=None):
    """A table cell with an initials avatar, a bold title and a quieter line under it."""
    return format_html(
        '<span class="lf-ent"><span class="lf-ent__avatar" aria-hidden="true">{}</span>'
        '<span class="lf-ent__text"><span class="lf-ent__title">{}</span>{}</span></span>',
        avatar if avatar is not None else initials(title),
        title,
        format_html('<span class="lf-ent__detail" title="{}">{}</span>', detail, detail) if detail else "",
    )


def compact_number(value) -> str:
    """12500 -> '12.5k', 1250000 -> '1.25M'. For chart axes."""
    value = float(value)
    for limit, suffix in ((1_000_000, "M"), (1_000, "k")):
        if abs(value) >= limit:
            text = f"{value / limit:.2f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return f"{value:,.0f}"
