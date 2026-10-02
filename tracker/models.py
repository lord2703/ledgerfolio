"""Tracker data model: clients, projects, payments, receipts and leads.

`Project` is shared with the public Showcase. Only the fields grouped under
"Showcase" are ever shown publicly, and only when `is_public` is on.
"""

import os
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

MONEY = {"max_digits": 12, "decimal_places": 2}
ZERO = Decimal("0.00")


class PrivateStorage(FileSystemStorage):
    """Files on disk under PRIVATE_MEDIA_ROOT, with no public URL.

    Receipt PDFs contain client data, so they are only ever served through a
    staff-only admin view, never by a web server path.
    """

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Private files have no public URL.")


def private_storage():
    return PrivateStorage()


def new_public_token() -> str:
    # 32 random bytes: far too many possibilities to guess or enumerate.
    return secrets.token_urlsafe(32)


def new_salt() -> str:
    return secrets.token_hex(16)


class Client(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True, help_text="Receipts are emailed here.")
    phone = models.CharField(max_length=40, blank=True)
    other_contact = models.CharField(
        max_length=200, blank=True, help_text="Messenger, Facebook link, school, etc."
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProjectQuerySet(models.QuerySet):
    def with_totals(self):
        """Annotate paid-so-far and balance in SQL, for lists and filters."""
        paid = Coalesce(Sum("payments__amount"), Value(ZERO), output_field=DecimalField(**MONEY))
        return self.annotate(paid_total=paid).annotate(
            balance_total=F("total_price") - F("paid_total")
        )

    def public(self):
        return self.filter(is_public=True)


class Project(models.Model):
    class Status(models.TextChoices):
        IN_DEVELOPMENT = "in_development", "In development"
        READY_FOR_PRE_ORAL = "ready_for_pre_oral", "Ready for pre-oral"
        READY_FOR_FINAL = "ready_for_final", "Ready for final"
        FULLY_PAID = "fully_paid", "Fully paid"

    class PreviewStyle(models.TextChoices):
        CRYSTAL = "crystal", "Crystal"
        KNOT = "knot", "Knot"
        STACK = "stack", "Stacked layers"
        ORBIT = "orbit", "Orbit"
        LATTICE = "lattice", "Lattice"
        PRISM = "prism", "Prism"

    # --- Tracker (private) ---
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="projects")
    system_name = models.CharField(max_length=150)
    total_price = models.DecimalField(**MONEY, validators=[MinValueValidator(ZERO)])
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IN_DEVELOPMENT, db_index=True
    )
    deadline = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Private. Never shown on the Showcase.")

    # --- Showcase (public when is_public is on) ---
    is_public = models.BooleanField(
        "show on Showcase", default=False, db_index=True,
        help_text="Only the Showcase fields below become public. "
        "Client, price, payments and notes always stay private.",
    )
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    tagline = models.CharField(max_length=160, blank=True, help_text="One line under the name.")
    tech_stack = models.CharField(
        max_length=300, blank=True, help_text="Comma-separated, e.g. Django, MySQL, Bootstrap"
    )
    objectives = models.TextField(blank=True, help_text="One objective per line.")
    purpose = models.TextField(blank=True)
    preview_style = models.CharField(
        "3D preview", max_length=12, choices=PreviewStyle.choices, default=PreviewStyle.CRYSTAL
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.system_name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = slugify(self.system_name)[:150] or "system"
        slug, n = base, 2
        while Project.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug, n = f"{base}-{n}", n + 1
        return slug

    def get_absolute_url(self):
        return reverse("showcase:system_detail", args=[self.slug])

    # Paid-so-far and balance are always calculated from payments.
    @property
    def paid_so_far(self) -> Decimal:
        if hasattr(self, "paid_total"):
            return self.paid_total
        if not self.pk:
            return ZERO
        return self.payments.aggregate(total=Sum("amount"))["total"] or ZERO

    @property
    def balance(self) -> Decimal:
        return self.total_price - self.paid_so_far

    @property
    def paid_percent(self) -> int:
        if not self.total_price:
            return 100
        return max(0, min(100, int(self.paid_so_far * 100 / self.total_price)))

    @property
    def tech_list(self):
        return [item.strip() for item in self.tech_stack.split(",") if item.strip()]

    @property
    def objective_list(self):
        return [line.strip(" -•\t") for line in self.objectives.splitlines() if line.strip(" -•\t")]


class ProjectScreenshot(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="screenshots")
    image = models.ImageField(upload_to="projects/%Y/")
    caption = models.CharField(max_length=160, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.caption or f"Screenshot of {self.project}"


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        GCASH = "gcash", "GCash"
        MAYA = "maya", "Maya"
        BANK = "bank_transfer", "Bank transfer"
        OTHER = "other", "Other"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    date = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(
        max_length=80, blank=True, help_text="e.g. GCash reference number"
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.amount:,.2f} for {self.project} on {self.date:%b %d, %Y}"

    @property
    def receipt(self):
        """The receipt issued for this payment, if any."""
        return self.receipts.order_by("-issued_at").first()


class Receipt(models.Model):
    """A document issued for a payment, and its anchor on the blockchain.

    The receipt keeps its own snapshot of what was printed (client, system,
    amount, balance). The ledger hash is computed from that snapshot, not from
    the PDF bytes, so the PDF can be regenerated at any time without breaking
    verification, while any edit to the snapshot is detected.
    """

    class DocumentType(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        QUOTATION = "quotation", "Quotation"

    class LedgerStatus(models.TextChoices):
        UNANCHORED = "unanchored", "Not on the ledger yet"
        PENDING = "pending", "Waiting to be mined"
        CONFIRMED = "confirmed", "Confirmed in a block"

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="receipts")
    document_type = models.CharField(
        max_length=12, choices=DocumentType.choices, default=DocumentType.RECEIPT
    )
    receipt_number = models.CharField(max_length=24, unique=True)
    public_token = models.CharField(max_length=64, unique=True, default=new_public_token)
    issued_at = models.DateTimeField(default=timezone.now)

    # Snapshot of the printed data.
    client_name = models.CharField(max_length=150)
    system_name = models.CharField(max_length=150)
    amount = models.DecimalField(**MONEY)
    balance_after = models.DecimalField(**MONEY)
    payment_method = models.CharField(max_length=20, choices=Payment.Method.choices)
    payment_date = models.DateField()
    # Random value mixed into the hash so it cannot be guessed from the data.
    salt = models.CharField(max_length=32, default=new_salt)
    content_hash = models.CharField(max_length=64, blank=True)

    pdf = models.FileField(storage=private_storage, upload_to="receipts/%Y/", blank=True)

    # Blockchain anchor.
    ledger_status = models.CharField(
        max_length=12, choices=LedgerStatus.choices, default=LedgerStatus.UNANCHORED
    )
    tx_id = models.CharField("transaction id", max_length=64, blank=True)
    # The signed transaction as sent to the node, so it can be re-sent if a
    # node ever loses it. Contains only the hash and signature, no receipt data.
    signed_tx = models.JSONField(null=True, blank=True, editable=False)
    block_index = models.PositiveIntegerField(null=True, blank=True)
    block_hash = models.CharField(max_length=64, blank=True)

    emailed_to = models.EmailField(blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return self.receipt_number

    def get_verify_path(self) -> str:
        return reverse("showcase:verify", args=[self.public_token])

    @property
    def verify_url(self) -> str:
        """Full public link for the QR code, email and messages."""
        return f"{settings.SITE_URL}{self.get_verify_path()}"


class Lead(models.Model):
    """An inquiry from someone who wants a system built (usually via the chatbot)."""

    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        CONVERTED = "converted", "Converted"
        DROPPED = "dropped", "Dropped"

    class Source(models.TextChoices):
        CHATBOT = "chatbot", "Portfolio Assistant"
        MANUAL = "manual", "Added by hand"

    name = models.CharField(max_length=150)
    contact = models.CharField(max_length=200, help_text="Email, phone or messaging handle")
    system_idea = models.TextField()
    budget = models.CharField(max_length=120, blank=True)
    deadline = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.NEW, db_index=True
    )
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.MANUAL)
    notes = models.TextField(blank=True)
    converted_project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name}: {self.system_idea[:40]}"


class UnansweredQuestion(models.Model):
    """A chat message the assistant was unsure about, kept to grow the dataset."""

    message = models.CharField(max_length=500)
    predicted_intent = models.CharField(max_length=40, blank=True)
    confidence = models.FloatField(default=0)
    reviewed = models.BooleanField(default=False, help_text="Tick once added to intents.json")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.message[:60]
