"""One search box for the whole Tracker: projects, clients, payments, receipts, inquiries."""

from urllib.parse import urlencode

from django.contrib import admin
from django.db.models import Q
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.text import Truncator

from .models import Client, Lead, Payment, Project, Receipt
from .services.pdf import money
from .ui import lead_badge, ledger_badge, project_badge

LIMIT = 6
MAX_QUERY = 100


def _group(label, model, queryset, describe, query):
    total = queryset.count()
    if not total:
        return None
    changelist = reverse(f"admin:tracker_{model._meta.model_name}_changelist")
    return {
        "label": label,
        "count": total,
        "items": [describe(obj) for obj in queryset[:LIMIT]],
        "more_url": f"{changelist}?{urlencode({'q': query})}",
    }


def _item(obj, title, detail, status=""):
    url = reverse(f"admin:tracker_{obj._meta.model_name}_change", args=[obj.pk])
    return {"title": title, "detail": detail, "status": status, "url": url}


def search(query):
    """Grouped results for a query. Searches the same fields as each list page."""
    projects = (
        Project.objects.with_totals().select_related("client")
        .filter(Q(system_name__icontains=query) | Q(client__name__icontains=query)
                | Q(tech_stack__icontains=query) | Q(tagline__icontains=query))
    )
    clients = Client.objects.filter(
        Q(name__icontains=query) | Q(email__icontains=query) | Q(phone__icontains=query)
        | Q(other_contact__icontains=query)
    )
    payments = Payment.objects.select_related("project__client").filter(
        Q(reference__icontains=query) | Q(note__icontains=query)
        | Q(project__system_name__icontains=query) | Q(project__client__name__icontains=query)
    )
    receipts = Receipt.objects.filter(
        Q(receipt_number__icontains=query) | Q(client_name__icontains=query)
        | Q(system_name__icontains=query) | Q(tx_id__iexact=query)
    )
    inquiries = Lead.objects.filter(
        Q(name__icontains=query) | Q(contact__icontains=query) | Q(system_idea__icontains=query)
    )
    groups = [
        _group("Projects", Project, projects, lambda p: _item(
            p, p.system_name, f"{p.client.name} · balance {money(p.balance)}", project_badge(p)
        ), query),
        _group("Clients", Client, clients, lambda c: _item(
            c, c.name, c.email or c.phone or c.other_contact
        ), query),
        _group("Payments", Payment, payments, lambda p: _item(
            p, money(p.amount), f"{p.project.system_name} · {p.project.client.name} · "
                                f"{p.date:%b} {p.date.day}, {p.date.year}"
        ), query),
        _group("Receipts", Receipt, receipts, lambda r: _item(
            r, r.receipt_number, f"{r.client_name} · {r.system_name}", ledger_badge(r)
        ), query),
        _group("Inquiries", Lead, inquiries, lambda lead: _item(
            lead, lead.name, Truncator(lead.system_idea).chars(80), lead_badge(lead)
        ), query),
    ]
    return [group for group in groups if group]


def search_view(request):
    query = request.GET.get("q", "").strip()[:MAX_QUERY]
    groups = search(query) if query else []
    context = {
        **admin.site.each_context(request),
        "title": "Search",
        "page_description": f"Results for “{query}”" if query else
                            "Find any project, client, payment, receipt or inquiry.",
        "query": query,
        "groups": groups,
        "total": sum(group["count"] for group in groups),
    }
    return TemplateResponse(request, "admin/tracker_search.html", context)
