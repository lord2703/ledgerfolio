"""Data for the Tracker's dashboard and sidebar."""

import datetime
import math

from django import template
from django.conf import settings
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince

from ledger import services as ledger
from ledger.client import NodeClient
from tracker.models import ZERO, Lead, Payment, Project, Receipt, Review, UnansweredQuestion
from tracker.ui import LEAD_TONES, LEDGER_TONES, STATUS_TONES, compact_number, money_short

register = template.Library()

CHART_MONTHS = 6
DEADLINE_WINDOW_DAYS = 30


def figure(value) -> str:
    """A big dashboard number: the currency code is set separately, smaller."""
    return f"{value:,.2f}"


def month_starts(today: datetime.date, count: int):
    year, month = today.year, today.month
    starts = []
    for _ in range(count):
        starts.append(datetime.date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return starts[::-1]


def nice_scale(maximum: float, target_ticks: int = 4):
    """Round gridline values for a chart axis, e.g. 23,500 -> 0, 10k, 20k, 30k."""
    if maximum <= 0:
        return 1.0, [0.0]
    rough = maximum / target_ticks
    magnitude = 10 ** math.floor(math.log10(rough))
    step = next(f * magnitude for f in (1, 2, 2.5, 5, 10) if f * magnitude >= rough)
    top = math.ceil(maximum / step) * step
    return top, [step * i for i in range(round(top / step) + 1)]


def collections_chart(today: datetime.date) -> dict:
    """Payments received per month for the last six months, ready to draw."""
    starts = month_starts(today, CHART_MONTHS)
    totals = dict.fromkeys(starts, ZERO)
    rows = Payment.objects.filter(date__gte=starts[0], date__lte=today).values_list("date", "amount")
    for date, value in rows:
        totals[date.replace(day=1)] += value
    peak = float(max(totals.values()))
    top, ticks = nice_scale(peak)
    months = [
        {
            "label": start.strftime("%b"),
            "full": start.strftime("%B %Y"),
            "amount": money_short(total),
            "percent": round(float(total) / top * 100, 2) if top else 0,
            "current": start == starts[-1],
            "empty": total == 0,
        }
        for start, total in totals.items()
    ]
    return {
        "months": months,
        "ticks": [{"label": compact_number(t), "percent": t / top * 100} for t in ticks],
        "total": money_short(sum(totals.values(), ZERO)),
        "has_data": peak > 0,
    }


def greeting(hour: int) -> str:
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


@register.simple_tag(takes_context=True)
def tracker_dashboard(context):
    request = context["request"]
    now = timezone.localtime()
    today = now.date()
    currency = settings.CURRENCY_CODE

    projects = list(Project.objects.with_totals().select_related("client"))
    contract = sum((p.total_price for p in projects), ZERO)
    collected = sum((p.paid_so_far for p in projects), ZERO)
    owing = [p for p in projects if p.balance > 0]
    outstanding = sum((p.balance for p in owing), ZERO)

    month_start = today.replace(day=1)
    previous_start = (month_start - datetime.timedelta(days=1)).replace(day=1)
    this_month = Payment.objects.filter(date__gte=month_start, date__lte=today).aggregate(
        total=Sum("amount"))["total"] or ZERO
    last_month = Payment.objects.filter(date__gte=previous_start, date__lt=month_start).aggregate(
        total=Sum("amount"))["total"] or ZERO
    if last_month:
        change = (this_month - last_month) / last_month * 100
        delta = {"direction": "up" if change >= 0 else "down", "text": f"{abs(change):.0f}%"}
    else:
        delta = None

    counts = dict(Project.objects.values_list("status").annotate(n=Count("id")))
    busiest = max(counts.values(), default=0) or 1
    project_list = reverse("admin:tracker_project_changelist")
    statuses = [
        {
            "label": label,
            "count": counts.get(value, 0),
            "percent": round(counts.get(value, 0) * 100 / busiest),
            "tone": STATUS_TONES[value],
            "url": f"{project_list}?status__exact={value}",
        }
        for value, label in Project.Status.choices
    ]

    soon = today + datetime.timedelta(days=DEADLINE_WINDOW_DAYS)
    deadlines = [
        {
            "name": p.system_name,
            "client": p.client.name,
            "balance": money_short(p.balance),
            "date": p.deadline,
            "days": (p.deadline - today).days,
            "url": reverse("admin:tracker_project_change", args=[p.pk]),
        }
        for p in sorted(
            (p for p in owing if p.deadline and p.deadline <= soon), key=lambda p: p.deadline
        )[:6]
    ]

    recent_payments = []
    for payment in (Payment.objects.select_related("project__client")
                    .prefetch_related("receipts").order_by("-date", "-id")[:6]):
        receipt = max(payment.receipts.all(), key=lambda r: r.issued_at, default=None)
        recent_payments.append({
            "project": payment.project.system_name,
            "client": payment.project.client.name,
            "date": payment.date,
            "method": payment.get_method_display(),
            "amount": money_short(payment.amount),
            "url": reverse("admin:tracker_payment_change", args=[payment.pk]),
            "receipt": receipt and {
                "number": receipt.receipt_number,
                "status": receipt.get_ledger_status_display(),
                "tone": LEDGER_TONES[receipt.ledger_status],
            },
        })

    recent_leads = [
        {
            "name": lead.name,
            "idea": lead.system_idea,
            "created": lead.created_at,
            "status": lead.get_status_display(),
            "tone": LEAD_TONES[lead.status],
            "url": reverse("admin:tracker_lead_change", args=[lead.pk]),
        }
        for lead in Lead.objects.order_by("-created_at")[:5]
    ]
    new_leads = Lead.objects.filter(status=Lead.Status.NEW).count()

    receipt_counts = dict(Receipt.objects.values_list("ledger_status").annotate(n=Count("id")))
    receipts_total = sum(receipt_counts.values())

    # A short timeout keeps the dashboard fast when the node is down.
    chain = ledger.overview(NodeClient(timeout=1.5), blocks=1)
    if chain.get("online") and chain.get("blocks"):
        latest = chain["blocks"][0]
        if latest["index"] == 0:
            chain["latest_age"] = "Genesis only"
        elif timezone.now() - latest["time"] < datetime.timedelta(minutes=1):
            chain["latest_age"] = "Just now"
        else:
            chain["latest_age"] = f"{timesince(latest['time'])} ago"

    user = request.user
    name = (user.first_name or user.get_username()).capitalize()
    if outstanding:
        summary = (f"{money_short(outstanding)} is still owed across {len(owing)} "
                   f"project{'s' if len(owing) != 1 else ''}.")
    elif projects:
        summary = "Every project is settled. Nothing is owed right now."
    else:
        summary = "Add your first project to start tracking payments and receipts."
    if new_leads:
        summary += f" {new_leads} new message{'s are' if new_leads != 1 else ' is'} waiting for a reply."
    pending_reviews = Review.objects.filter(status=Review.Status.PENDING).count()
    if pending_reviews:
        summary += (f" {pending_reviews} review{'s are' if pending_reviews != 1 else ' is'} "
                    "waiting for your approval.")

    return {
        "greeting": greeting(now.hour),
        "name": name,
        "today": today,
        "summary": summary,
        "currency": currency,
        "contract": money_short(contract),
        "collected": figure(collected),
        "collected_percent": int(collected * 100 / contract) if contract else 0,
        "outstanding": figure(outstanding),
        "owing_count": len(owing),
        "this_month": figure(this_month),
        "previous_month": previous_start,
        "delta": delta,
        "new_leads": new_leads,
        "leads_url": f"{reverse('admin:tracker_lead_changelist')}?status__exact=new",
        "chart": collections_chart(today),
        "statuses": statuses,
        "project_count": len(projects),
        "public_count": sum(1 for p in projects if p.is_public),
        "deadlines": deadlines,
        "recent_payments": recent_payments,
        "recent_leads": recent_leads,
        "receipts_total": receipts_total,
        "receipts_confirmed": receipt_counts.get(Receipt.LedgerStatus.CONFIRMED, 0),
        "receipts_waiting": receipts_total - receipt_counts.get(Receipt.LedgerStatus.CONFIRMED, 0),
        "payments_without_receipt": Payment.objects.filter(receipts__isnull=True).count(),
        "unreviewed_questions": UnansweredQuestion.objects.filter(reviewed=False).count(),
        "pending_reviews": pending_reviews,
        "published_reviews": Review.objects.filter(status=Review.Status.APPROVED).count(),
        "reviews_url": f"{reverse('admin:tracker_review_changelist')}?status__exact=pending",
        "chain": chain,
    }


@register.simple_tag
def tracker_nav_counts():
    """Small numbers shown next to sidebar items."""
    return {
        "new_leads": Lead.objects.filter(status=Lead.Status.NEW).count(),
        "pending_reviews": Review.objects.filter(status=Review.Status.PENDING).count(),
    }
