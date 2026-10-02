"""The Tracker's interface: Django admin, tuned for a one-person freelance desk."""

from django.contrib import admin, messages
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from ledger import services as ledger

from .models import Client, Lead, Payment, Project, ProjectScreenshot, Receipt, UnansweredQuestion
from .services import leads as lead_service
from .services import receipts as receipt_service
from .services.pdf import money


def badge(label, tone):
    """A small status pill. Tone picks the colour; the label always carries the meaning."""
    return format_html('<span class="lf-badge lf-badge--{}">{}</span>', tone, label)


def amount(value):
    """Money that never wraps across two lines in a table cell."""
    return format_html('<span class="lf-money">{}</span>', money(value))


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


# ----------------------------------------------------------------------
# Clients
# ----------------------------------------------------------------------

class ClientProjectInline(admin.TabularInline):
    model = Project
    fields = ("project_link", "status", "total_price", "paid", "owed", "deadline")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = False
    verbose_name_plural = "Projects"

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).with_totals()

    @admin.display(description="System")
    def project_link(self, obj):
        url = reverse("admin:tracker_project_change", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.system_name)

    @admin.display(description="Paid so far")
    def paid(self, obj):
        return amount(obj.paid_so_far)

    @admin.display(description="Balance")
    def owed(self, obj):
        return amount(obj.balance)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "project_count", "created_at")
    search_fields = ("name", "email", "phone", "other_contact")
    inlines = [ClientProjectInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(project_total=Count("projects"))

    @admin.display(description="Projects", ordering="project_total")
    def project_count(self, obj):
        return obj.project_total


# ----------------------------------------------------------------------
# Projects
# ----------------------------------------------------------------------

class PaymentInline(admin.TabularInline):
    model = Payment
    fields = ("date", "amount", "method", "reference", "note", "receipt_link")
    readonly_fields = ("receipt_link",)
    extra = 0

    @admin.display(description="Receipt")
    def receipt_link(self, obj):
        if not obj.pk:
            return "-"
        receipt = obj.receipt
        if receipt is None:
            return "Not issued"
        url = reverse("admin:tracker_receipt_change", args=[receipt.pk])
        return format_html('<a href="{}">{}</a>', url, receipt.receipt_number)


class ScreenshotInline(admin.TabularInline):
    model = ProjectScreenshot
    fields = ("image", "caption", "order")
    extra = 0


class BalanceFilter(admin.SimpleListFilter):
    title = "balance"
    parameter_name = "balance"

    def lookups(self, request, model_admin):
        return [("owing", "Still owing"), ("settled", "Settled")]

    def queryset(self, request, queryset):
        if self.value() == "owing":
            return queryset.filter(balance_total__gt=0)
        if self.value() == "settled":
            return queryset.filter(balance_total__lte=0)
        return queryset


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "system_name", "client", "status_badge", "price", "paid", "owed", "deadline", "is_public",
    )
    list_filter = ("status", BalanceFilter, "is_public", "deadline")
    search_fields = ("system_name", "client__name", "tech_stack", "notes")
    autocomplete_fields = ("client",)
    # A plain date field: browsing by a date-time field would need MySQL's
    # time zone tables, which Windows installs of MySQL don't have.
    date_hierarchy = "deadline"
    inlines = [PaymentInline, ScreenshotInline]
    actions = ["show_on_showcase", "hide_from_showcase"]
    readonly_fields = ("money_summary",)
    fieldsets = (
        ("Tracker (private)", {
            "fields": ("client", "system_name", "total_price", "money_summary", "status",
                       "deadline", "notes"),
        }),
        ("Showcase (public when switched on)", {
            "description": "Only these fields are ever shown on the public site.",
            "fields": ("is_public", "slug", "tagline", "tech_stack", "objectives", "purpose",
                       "preview_style"),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).with_totals().select_related("client")

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return badge(obj.get_status_display(), STATUS_TONES.get(obj.status, "muted"))

    @admin.display(description="Total price", ordering="total_price")
    def price(self, obj):
        return amount(obj.total_price)

    @admin.display(description="Paid so far", ordering="paid_total")
    def paid(self, obj):
        """The amount, with a slim meter of how much of the price it covers."""
        return format_html(
            '<span class="lf-paid">{}<span class="lf-meter lf-meter--slim" role="img" '
            'aria-label="{}% paid" title="{}% paid"><span class="lf-meter__fill" '
            'style="width:{}%"></span></span></span>',
            amount(obj.paid_so_far), obj.paid_percent, obj.paid_percent, obj.paid_percent,
        )

    @admin.display(description="Balance", ordering="balance_total")
    def owed(self, obj):
        return amount(obj.balance)

    @admin.display(description="Payments")
    def money_summary(self, obj):
        if not obj.pk:
            return "Save the project, then add payments below."
        return format_html(
            '<div class="lf-summary">'
            "<div><span>Total price</span><strong>{}</strong></div>"
            "<div><span>Paid so far</span><strong>{}</strong></div>"
            "<div><span>Balance</span><strong>{}</strong></div>"
            "</div>",
            money(obj.total_price), money(obj.paid_so_far), money(obj.balance),
        )

    @admin.action(description="Show selected projects on the Showcase")
    def show_on_showcase(self, request, queryset):
        count = queryset.update(is_public=True)
        self.message_user(request, f"{count} project(s) are now public on the Showcase.")

    @admin.action(description="Hide selected projects from the Showcase")
    def hide_from_showcase(self, request, queryset):
        count = queryset.update(is_public=False)
        self.message_user(request, f"{count} project(s) are now hidden from the Showcase.")


# ----------------------------------------------------------------------
# Payments and receipts
# ----------------------------------------------------------------------

def report_outcome(modeladmin, request, payment, outcome):
    """Tell the admin exactly which steps of receipt generation worked."""
    receipt = outcome.receipt
    verb = "issued" if outcome.created else "already existed, so it was reused"
    parts = [f"Receipt {receipt.receipt_number} {verb}."]
    level = messages.SUCCESS

    if receipt.ledger_status == Receipt.LedgerStatus.CONFIRMED:
        parts.append(f"Sealed in block #{receipt.block_index}.")
    elif outcome.ledger_error:
        parts.append(f"Not on the ledger yet: {outcome.ledger_error}")
        level = messages.WARNING
    else:
        parts.append("Signed and waiting to be mined.")

    if outcome.emailed:
        parts.append(f"Emailed to {receipt.emailed_to}.")
    elif outcome.email_error:
        parts.append(f"Not emailed: {outcome.email_error}.")
        level = messages.WARNING
    modeladmin.message_user(request, " ".join(parts), level)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("date", "project", "client_name", "amount_display", "method", "receipt_state")
    list_filter = ("method", "date")
    search_fields = ("project__system_name", "project__client__name", "reference", "note")
    autocomplete_fields = ("project",)
    date_hierarchy = "date"
    actions = ["generate_and_send_receipt", "generate_receipt_without_email"]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("project__client")
            .prefetch_related("receipts")
        )

    @admin.display(description="Client", ordering="project__client__name")
    def client_name(self, obj):
        return obj.project.client.name

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return amount(obj.amount)

    @admin.display(description="Receipt")
    def receipt_state(self, obj):
        receipts = sorted(obj.receipts.all(), key=lambda r: r.issued_at, reverse=True)
        if not receipts:
            return badge("Not issued", "muted")
        receipt = receipts[0]
        url = reverse("admin:tracker_receipt_change", args=[receipt.pk])
        return format_html(
            '<a href="{}">{}</a> {}', url, receipt.receipt_number,
            badge(receipt.get_ledger_status_display(), LEDGER_TONES[receipt.ledger_status]),
        )

    def _issue(self, request, queryset, send_email):
        for payment in queryset.select_related("project__client"):
            outcome = receipt_service.generate_and_send(payment, send_email=send_email)
            report_outcome(self, request, payment, outcome)

    @admin.action(description="Generate and send receipt")
    def generate_and_send_receipt(self, request, queryset):
        self._issue(request, queryset, send_email=True)

    @admin.action(description="Generate receipt (do not email)")
    def generate_receipt_without_email(self, request, queryset):
        self._issue(request, queryset, send_email=False)


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "receipt_number", "client_name", "system_name", "amount_display", "issued_at",
        "ledger_badge", "emailed_at",
    )
    list_filter = ("ledger_status", "document_type", "issued_at")
    search_fields = ("receipt_number", "client_name", "system_name", "tx_id")
    date_hierarchy = "payment_date"  # a date field; see ProjectAdmin.date_hierarchy
    actions = ["anchor_on_ledger", "resend_email", "regenerate_pdf"]
    readonly_fields = ("verify_link", "pdf_link", "integrity", "amount_display", "balance_display")
    fieldsets = (
        (None, {"fields": ("receipt_number", "document_type", "issued_at", "payment")}),
        ("Share with the client", {"fields": ("verify_link", "pdf_link", "emailed_to", "emailed_at")}),
        ("What the receipt says", {
            "fields": ("client_name", "system_name", "amount_display", "balance_display",
                       "payment_method", "payment_date"),
        }),
        ("Blockchain", {
            "fields": ("integrity", "ledger_status", "content_hash", "tx_id", "block_index",
                       "block_hash"),
        }),
    )

    class Media:
        js = ("js/admin.js",)

    # A receipt is a point-in-time document: it is issued from a payment and
    # then never edited. To correct one, delete it and issue a new receipt.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_urls(self):
        custom = [
            path(
                "<int:pk>/pdf/", self.admin_site.admin_view(self.pdf_view),
                name="tracker_receipt_pdf",
            ),
        ]
        return custom + super().get_urls()

    def pdf_view(self, request, pk):
        """Receipt PDFs hold client data, so only signed-in staff can download them."""
        receipt = get_object_or_404(Receipt, pk=pk)
        if not receipt.pdf:
            receipt_service.store_pdf(receipt)
        try:
            handle = receipt.pdf.open("rb")
        except FileNotFoundError:
            receipt_service.store_pdf(receipt)
            try:
                handle = receipt.pdf.open("rb")
            except FileNotFoundError as exc:
                raise Http404("The PDF could not be generated.") from exc
        return FileResponse(
            handle, content_type="application/pdf", filename=f"{receipt.receipt_number}.pdf"
        )

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return amount(obj.amount)

    @admin.display(description="Balance after this payment")
    def balance_display(self, obj):
        return amount(obj.balance_after)

    @admin.display(description="Ledger", ordering="ledger_status")
    def ledger_badge(self, obj):
        return badge(obj.get_ledger_status_display(), LEDGER_TONES[obj.ledger_status])

    @admin.display(description="Verify link")
    def verify_link(self, obj):
        return format_html(
            '<a href="{0}" target="_blank" rel="noopener">{0}</a> '
            '<button type="button" class="button lf-copy" data-copy="{0}">Copy link</button>',
            obj.verify_url,
        )

    @admin.display(description="PDF")
    def pdf_link(self, obj):
        url = reverse("admin:tracker_receipt_pdf", args=[obj.pk])
        return format_html('<a class="button" href="{}" target="_blank">Open PDF</a>', url)

    @admin.display(description="Integrity")
    def integrity(self, obj):
        result = ledger.verify(obj)
        tone = {
            ledger.VALID: "good", ledger.PENDING: "warn",
            ledger.TAMPERED: "bad", ledger.UNAVAILABLE: "muted",
        }[result.state]
        marks = {True: "Passed", False: "FAILED", None: "Not checked"}
        rows = format_html_join(
            "", "<li><strong>{}:</strong> {} <em>{}</em></li>",
            ((marks[check.passed], check.label, check.detail) for check in result.checks),
        )
        return format_html(
            '{} <span>{}</span><ul class="lf-checks">{}</ul>',
            badge(result.state.title(), tone), result.summary, rows,
        )

    @admin.action(description="Anchor on the ledger (retry)")
    def anchor_on_ledger(self, request, queryset):
        for receipt in queryset:
            try:
                ledger.anchor(receipt)
            except ledger.LedgerError as exc:
                self.message_user(request, f"{receipt.receipt_number}: {exc}", messages.ERROR)
            else:
                self.message_user(
                    request,
                    f"{receipt.receipt_number}: {receipt.get_ledger_status_display().lower()}.",
                )

    @admin.action(description="Email the receipt to the client again")
    def resend_email(self, request, queryset):
        for receipt in queryset.select_related("payment__project__client"):
            to_email = receipt.payment.project.client.email
            if not to_email:
                self.message_user(
                    request, f"{receipt.receipt_number}: the client has no email address.",
                    messages.WARNING,
                )
                continue
            try:
                receipt_service.send_receipt_email(
                    receipt, receipt_service.store_pdf(receipt), to_email
                )
            except Exception as exc:
                self.message_user(
                    request, f"{receipt.receipt_number}: could not send ({exc}).", messages.ERROR
                )
            else:
                self.message_user(request, f"{receipt.receipt_number}: emailed to {to_email}.")

    @admin.action(description="Regenerate the PDF")
    def regenerate_pdf(self, request, queryset):
        for receipt in queryset:
            receipt_service.store_pdf(receipt)
        self.message_user(request, f"Regenerated {queryset.count()} PDF(s).")


# ----------------------------------------------------------------------
# Leads and assistant log
# ----------------------------------------------------------------------

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "idea", "budget", "deadline", "status_badge", "source",
                    "created_at")
    list_filter = ("status", "source", "created_at")
    search_fields = ("name", "contact", "system_idea")
    readonly_fields = ("created_at", "converted_project")
    actions = ["convert", "mark_contacted", "mark_dropped"]

    @admin.display(description="System idea")
    def idea(self, obj):
        return obj.system_idea if len(obj.system_idea) <= 70 else f"{obj.system_idea[:70]}…"

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return badge(obj.get_status_display(), LEAD_TONES.get(obj.status, "muted"))

    @admin.action(description="Convert to client + project")
    def convert(self, request, queryset):
        for lead in queryset:
            project = lead_service.convert_lead(lead)
            url = reverse("admin:tracker_project_change", args=[project.pk])
            self.message_user(
                request,
                format_html(
                    '{} is now a client. <a href="{}">Open the new project</a> to set its '
                    "name and price.", lead.name, url,
                ),
            )

    @admin.action(description="Mark as contacted")
    def mark_contacted(self, request, queryset):
        queryset.update(status=Lead.Status.CONTACTED)

    @admin.action(description="Mark as dropped")
    def mark_dropped(self, request, queryset):
        queryset.update(status=Lead.Status.DROPPED)


@admin.register(UnansweredQuestion)
class UnansweredQuestionAdmin(admin.ModelAdmin):
    list_display = ("message", "predicted_intent", "confidence_percent", "reviewed", "created_at")
    list_filter = ("reviewed", "predicted_intent")
    list_editable = ("reviewed",)
    search_fields = ("message",)

    def has_add_permission(self, request):
        return False

    @admin.display(description="Confidence", ordering="confidence")
    def confidence_percent(self, obj):
        return f"{obj.confidence:.0%}"


admin.site.empty_value_display = "-"
