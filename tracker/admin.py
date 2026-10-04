"""The Tracker's interface: Django admin, tuned for a one-person freelance desk."""

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from ledger import services as ledger

from .models import (
    Client,
    Lead,
    Payment,
    Project,
    ProjectScreenshot,
    Receipt,
    Review,
    UnansweredQuestion,
    shorten,
)
from .services import leads as lead_service
from .services import receipts as receipt_service
from .ui import (
    amount,
    badge,
    entity,
    lead_badge,
    ledger_badge,
    money_short,
    project_badge,
    reply_links,
    review_badge,
    stars,
    when,
)


def date_filter(title):
    """Django's date filter under a heading of our choosing ("Received", not "Created at")."""

    class DateFilter(admin.DateFieldListFilter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.title = title

    return DateFilter


class TrackerAdminMixin:
    """Page titles, descriptions and form details shared by every Tracker screen."""

    page_title = None  # list page heading; defaults to the plural model name
    page_description = ""  # one line under the heading
    list_per_page = 25

    def changelist_view(self, request, extra_context=None):
        context = {
            "title": self.page_title or self.opts.verbose_name_plural.capitalize(),
            "page_description": self.page_description,
            **(extra_context or {}),
        }
        return super().changelist_view(request, context)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        context = dict(extra_context or {})
        if object_id and self.has_change_permission(request):
            context.setdefault("title", f"Edit {self.opts.verbose_name}")
        return super().changeform_view(request, object_id, form_url, context)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        class Form(form):
            # "Client" rather than "Client:": the labels sit above their fields.
            def __init__(self, *args, **options):
                options.setdefault("label_suffix", "")
                super().__init__(*args, **options)

        Form.__name__ = form.__name__
        return Form


# ----------------------------------------------------------------------
# Clients
# ----------------------------------------------------------------------

class ClientProjectInline(admin.TabularInline):
    model = Project
    fields = ("project_link", "status_badge", "price", "paid", "owed", "deadline")
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

    @admin.display(description="Status")
    def status_badge(self, obj):
        return project_badge(obj)

    @admin.display(description="Total price")
    def price(self, obj):
        return amount(obj.total_price)

    @admin.display(description="Paid so far")
    def paid(self, obj):
        return amount(obj.paid_so_far)

    @admin.display(description="Balance")
    def owed(self, obj):
        return amount(obj.balance)


@admin.register(Client)
class ClientAdmin(TrackerAdminMixin, admin.ModelAdmin):
    page_description = "The people and schools you build systems for."
    list_display = ("client", "phone", "project_count", "added")
    search_fields = ("name", "email", "phone", "other_contact")
    inlines = [ClientProjectInline]
    fieldsets = (
        ("Contact", {"fields": ("name", ("email", "phone"), "other_contact")}),
        ("Notes", {"fields": ("notes",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(project_total=Count("projects"))

    @admin.display(description="Client", ordering="name")
    def client(self, obj):
        return entity(obj.name, obj.email or obj.other_contact)

    @admin.display(description="Projects", ordering="project_total")
    def project_count(self, obj):
        return obj.project_total

    @admin.display(description="Added", ordering="created_at")
    def added(self, obj):
        return when(obj.created_at)


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
    fields = ("preview", "image", "caption", "order")
    readonly_fields = ("preview",)
    extra = 0

    @admin.display(description="Preview")
    def preview(self, obj):
        if not obj.pk or not obj.image:
            return "-"
        return format_html('<img class="lf-thumb" src="{}" alt="">', obj.image.url)


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
class ProjectAdmin(TrackerAdminMixin, admin.ModelAdmin):
    page_description = "Every system you're building or have delivered, and what's been paid."
    list_display = ("project", "status_badge", "price", "paid", "owed", "deadline", "public")
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
        ("Project", {
            "description": "Private. Only you see this part.",
            "fields": (("system_name", "client"), ("total_price", "status", "deadline"),
                       "money_summary", "notes"),
        }),
        ("Showcase", {
            "description": "Switch it on to show these fields on the public site. Client, price, "
                           "payments and notes are never shown there.",
            "fields": ("is_public", ("tagline", "preview_style"), "tech_stack", "objectives",
                       "purpose", "slug"),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).with_totals().select_related("client")

    @admin.display(description="Project", ordering="system_name")
    def project(self, obj):
        return entity(obj.system_name, obj.client.name)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return project_badge(obj)

    @admin.display(description="Public", boolean=True, ordering="is_public")
    def public(self, obj):
        return obj.is_public

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
            money_short(obj.total_price), money_short(obj.paid_so_far), money_short(obj.balance),
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
class PaymentAdmin(TrackerAdminMixin, admin.ModelAdmin):
    page_description = "Every payment received. Select payments, then choose “Generate and send receipt”."
    list_display = ("date", "project", "client_name", "amount_display", "method", "receipt_state")
    list_filter = ("method", "date")
    search_fields = ("project__system_name", "project__client__name", "reference", "note")
    autocomplete_fields = ("project",)
    date_hierarchy = "date"
    actions = ["generate_and_send_receipt", "generate_receipt_without_email"]
    fieldsets = (
        (None, {"fields": ("project", ("amount", "date"), ("method", "reference"), "note")}),
    )

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
            '<span class="lf-stack"><a href="{}">{}</a>{}</span>', url, receipt.receipt_number,
            ledger_badge(receipt),
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
class ReceiptAdmin(TrackerAdminMixin, admin.ModelAdmin):
    page_description = "Issued receipts and whether each one is sealed on the ledger."
    list_display = (
        "receipt_number", "client_name", "system_name", "amount_display", "issued",
        "ledger_status_badge", "emailed",
    )
    list_filter = ("ledger_status", "document_type", ("issued_at", date_filter("issued")))
    search_fields = ("receipt_number", "client_name", "system_name", "tx_id")
    date_hierarchy = "payment_date"  # a date field; see ProjectAdmin.date_hierarchy
    actions = ["anchor_on_ledger", "resend_email", "regenerate_pdf"]
    readonly_fields = ("verify_link", "pdf_link", "integrity", "amount_display", "balance_display")
    fieldsets = (
        ("Share with the client", {"fields": ("verify_link", "pdf_link", ("emailed_to", "emailed_at"))}),
        ("What the receipt says", {
            "fields": (("receipt_number", "document_type"), ("client_name", "system_name"),
                       ("amount_display", "balance_display"), ("payment_method", "payment_date"),
                       ("issued_at", "payment")),
        }),
        ("Blockchain", {
            "fields": ("integrity", ("ledger_status", "block_index"), "content_hash", "tx_id",
                       "block_hash"),
        }),
    )

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
    def ledger_status_badge(self, obj):
        return ledger_badge(obj)

    @admin.display(description="Issued", ordering="issued_at")
    def issued(self, obj):
        return when(obj.issued_at)

    @admin.display(description="Emailed", ordering="emailed_at")
    def emailed(self, obj):
        return when(obj.emailed_at)

    @admin.display(description="Verify link")
    def verify_link(self, obj):
        return format_html(
            '<span class="lf-copyfield"><a href="{0}" target="_blank" rel="noopener">{0}</a>'
            '<button type="button" class="button lf-copy" data-copy="{0}">Copy link</button></span>',
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
        marks = {True: ("pass", "Passed"), False: ("fail", "Failed"), None: ("skip", "Not checked")}
        rows = format_html_join(
            "", '<li class="lf-check lf-check--{}"><span class="lf-check__mark">{}</span>'
                '<span><strong>{}</strong><em>{}</em></span></li>',
            ((*marks[check.passed], check.label, check.detail) for check in result.checks),
        )
        return format_html(
            '<div class="lf-integrity"><p>{} <span>{}</span></p><ul class="lf-checks">{}</ul></div>',
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
# Messages, reviews and assistant log
# ----------------------------------------------------------------------

@admin.register(Lead)
class LeadAdmin(TrackerAdminMixin, admin.ModelAdmin):
    page_title = "Messages"
    page_description = (
        "What people send you from the message form on your site. Answer with the reply "
        "buttons, then mark the message as replied."
    )
    list_display = ("person", "idea", "budget", "deadline", "status_badge", "source", "received")
    list_filter = ("status", "source", ("created_at", date_filter("received")))
    search_fields = ("name", "contact", "system_idea")
    readonly_fields = ("created_at", "converted_project", "reply_options")
    actions = ["mark_contacted", "convert", "mark_dropped"]
    fieldsets = (
        ("From", {"fields": (("name", "contact"), "reply_options")}),
        ("What they wrote", {"fields": ("system_idea", ("budget", "deadline"))}),
        ("Follow-up", {"fields": (("status", "source"), "notes", ("converted_project", "created_at"))}),
    )

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        message = self.get_object(request, object_id) if object_id else None
        if message is not None:
            extra_context = {"title": f"Message from {message.name}", **(extra_context or {})}
        return super().changeform_view(request, object_id, form_url, extra_context)

    @admin.display(description="From", ordering="name")
    def person(self, obj):
        return entity(obj.name, obj.contact)

    @admin.display(description="Message")
    def idea(self, obj):
        return shorten(obj.system_idea, 70)

    @admin.display(description="Reply")
    def reply_options(self, obj):
        if not obj.pk:
            return "Save the message first."
        buttons = format_html_join(
            "", '<a class="button lf-reply" href="{}"{}><svg class="lf-i" aria-hidden="true">'
            '<use href="#lf-i-{}"/></svg>{}</a>',
            ((url, format_html(' target="_blank" rel="noopener"') if icon == "external" else "",
              icon, label) for label, url, icon in reply_links(obj.contact)),
        )
        return format_html(
            '<span class="lf-copyfield">{}<button type="button" class="button lf-copy" '
            'data-copy="{}">Copy contact</button></span>', buttons, obj.contact,
        )

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return lead_badge(obj)

    @admin.display(description="Received", ordering="created_at")
    def received(self, obj):
        return when(obj.created_at)

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

    @admin.action(description="Mark as replied")
    def mark_contacted(self, request, queryset):
        count = queryset.update(status=Lead.Status.CONTACTED)
        self.message_user(request, f"{count} message{'s' if count != 1 else ''} marked as replied.")

    @admin.action(description="Close (no reply needed)")
    def mark_dropped(self, request, queryset):
        count = queryset.update(status=Lead.Status.DROPPED)
        self.message_user(request, f"{count} message{'s' if count != 1 else ''} closed.")


@admin.register(Review)
class ReviewAdmin(TrackerAdminMixin, admin.ModelAdmin):
    page_description = (
        "Reviews clients write from their receipt page. Nothing appears on your site until you "
        "approve it."
    )
    list_display = ("review", "project_link", "shown_as", "status_badge", "received")
    list_filter = ("status", "rating")
    search_fields = ("comment", "display_name", "project__system_name")
    list_select_related = ("project",)
    readonly_fields = ("rating_stars", "comment", "project", "receipt", "created_at", "updated_at")
    actions = ["approve", "hide"]
    fieldsets = (
        ("Review", {"fields": ("rating_stars", "comment", "display_name")}),
        ("On your site", {"fields": ("status",)}),
        ("Details", {"fields": (("project", "receipt"), ("created_at", "updated_at"))}),
    )

    # Reviews come from clients; the owner approves or hides them but never writes them.
    def has_add_permission(self, request):
        return False

    @admin.display(description="Review", ordering="rating")
    def review(self, obj):
        return format_html('<span class="lf-review">{}<span>{}</span></span>',
                           stars(obj.rating), shorten(obj.comment, 90))

    @admin.display(description="Rating")
    def rating_stars(self, obj):
        return stars(obj.rating)

    @admin.display(description="Project", ordering="project__system_name")
    def project_link(self, obj):
        url = reverse("admin:tracker_project_change", args=[obj.project_id])
        return format_html('<a href="{}">{}</a>', url, obj.project.system_name)

    @admin.display(description="Shown as", ordering="display_name")
    def shown_as(self, obj):
        return obj.display_name or "Verified client"

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return review_badge(obj)

    @admin.display(description="Received", ordering="updated_at")
    def received(self, obj):
        return when(obj.updated_at)

    @admin.action(description="Approve and show on the site")
    def approve(self, request, queryset):
        count = queryset.update(status=Review.Status.APPROVED)
        self.message_user(request, f"{count} review{'s' if count != 1 else ''} now on your site.")

    @admin.action(description="Hide from the site")
    def hide(self, request, queryset):
        count = queryset.update(status=Review.Status.HIDDEN)
        self.message_user(request, f"{count} review{'s' if count != 1 else ''} hidden.")


@admin.register(UnansweredQuestion)
class UnansweredQuestionAdmin(TrackerAdminMixin, admin.ModelAdmin):
    page_title = "Assistant log"
    page_description = (
        "Questions the assistant wasn't sure about. Add good ones to ai/data/intents.json, "
        "retrain, then tick “reviewed”."
    )
    list_display = ("message", "predicted_intent", "confidence_percent", "reviewed", "asked")
    list_filter = ("reviewed", "predicted_intent")
    list_editable = ("reviewed",)
    search_fields = ("message",)

    def has_add_permission(self, request):
        return False

    @admin.display(description="Confidence", ordering="confidence")
    def confidence_percent(self, obj):
        return f"{obj.confidence:.0%}"

    @admin.display(description="Asked", ordering="created_at")
    def asked(self, obj):
        return when(obj.created_at)


# ----------------------------------------------------------------------
# Accounts
# ----------------------------------------------------------------------

admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class TrackerUserAdmin(TrackerAdminMixin, UserAdmin):
    page_description = "Who can sign in to the Tracker."


@admin.register(Group)
class TrackerGroupAdmin(TrackerAdminMixin, GroupAdmin):
    page_description = "Permission groups for Tracker accounts."


admin.site.empty_value_display = "-"
