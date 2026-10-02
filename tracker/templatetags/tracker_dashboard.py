"""Numbers for the admin home page."""

import datetime

from django import template
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from ledger import services as ledger
from ledger.client import NodeClient
from tracker.models import ZERO, Lead, Payment, Project, Receipt
from tracker.services.pdf import money

register = template.Library()


@register.simple_tag
def tracker_dashboard():
    today = timezone.localdate()
    projects = list(Project.objects.with_totals().select_related("client"))

    contract = sum((p.total_price for p in projects), ZERO)
    collected = sum((p.paid_so_far for p in projects), ZERO)
    outstanding = sum((p.balance for p in projects if p.balance > 0), ZERO)
    this_month = Payment.objects.filter(
        date__year=today.year, date__month=today.month
    ).aggregate(total=Sum("amount"))["total"] or ZERO

    status_counts = {value: 0 for value, _ in Project.Status.choices}
    for project in projects:
        status_counts[project.status] += 1
    busiest = max(status_counts.values(), default=0) or 1
    statuses = [
        {
            "label": label,
            "count": status_counts[value],
            "percent": round(status_counts[value] * 100 / busiest),
            "url": f"{reverse('admin:tracker_project_changelist')}?status__exact={value}",
        }
        for value, label in Project.Status.choices
    ]

    soon = today + datetime.timedelta(days=14)
    due = sorted(
        (p for p in projects if p.deadline and p.deadline <= soon and p.balance > 0),
        key=lambda p: p.deadline,
    )[:5]
    attention = [
        {
            "name": project.system_name,
            "client": project.client.name,
            "balance": money(project.balance),
            "deadline": project.deadline,
            "overdue": project.deadline < today,
            "url": reverse("admin:tracker_project_change", args=[project.pk]),
        }
        for project in due
    ]

    # A short timeout: the dashboard must stay fast when the node is down.
    chain = ledger.overview(NodeClient(timeout=1.5), blocks=1)

    return {
        "contract": money(contract),
        "collected": money(collected),
        "outstanding": money(outstanding),
        "this_month": money(this_month),
        "collected_percent": int(collected * 100 / contract) if contract else 0,
        "project_count": len(projects),
        "public_count": sum(1 for p in projects if p.is_public),
        "statuses": statuses,
        "attention": attention,
        "new_leads": Lead.objects.filter(status=Lead.Status.NEW).count(),
        "leads_url": f"{reverse('admin:tracker_lead_changelist')}?status__exact=new",
        "payments_without_receipt": Payment.objects.filter(receipts__isnull=True).count(),
        "receipts_not_confirmed": Receipt.objects.exclude(
            ledger_status=Receipt.LedgerStatus.CONFIRMED
        ).count(),
        "receipt_count": Receipt.objects.count(),
        "chain": chain,
    }
