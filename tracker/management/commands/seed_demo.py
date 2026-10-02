import datetime
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tracker.models import Client, Lead, Payment, Project, Receipt

MARKER = "Demo data created by seed_demo."

# (client, system, price, status, public, preview, tagline, stack, objectives, purpose, payments)
PROJECTS = [
    (
        "Demo Client A", "Clinic Records System", "18000", Project.Status.FULLY_PAID, True, "crystal",
        "Patient records, visits and medicine stock for a small school clinic.",
        "Django, MySQL, Bootstrap, Chart.js",
        "Record patient visits and diagnoses in one searchable place\n"
        "Track medicine stock and warn before it runs out\n"
        "Produce monthly health reports without manual tallying",
        "Built for a school clinic that kept visits in paper logbooks. Nurses can pull up a "
        "student's history in seconds, and monthly reports that took a day now take a click.",
        [("9000", 60), ("9000", 20)],
    ),
    (
        "Demo Client B", "Dormitory Reservation and Billing System", "22000",
        Project.Status.READY_FOR_FINAL, True, "stack",
        "Room reservations, tenant records and monthly billing for a dormitory.",
        "Laravel, MySQL, Tailwind CSS, Alpine.js",
        "Let tenants reserve a room online and see what is available\n"
        "Generate monthly bills and record payments per tenant\n"
        "Give the owner a clear view of occupancy and unpaid balances",
        "Built for a dormitory owner who tracked rooms and rent in a notebook. It replaces the "
        "notebook with one place for rooms, tenants and bills.",
        [("8000", 45), ("7000", 12)],
    ),
    (
        "Demo Client C", "Alumni Tracer Portal", "15000", Project.Status.READY_FOR_PRE_ORAL, True,
        "orbit",
        "Keeps a school in touch with its graduates and their careers.",
        "Django, PostgreSQL, HTMX, Tailwind CSS",
        "Collect graduate employment data through an online tracer survey\n"
        "Show employment statistics by course and year\n"
        "Announce events and job openings to alumni",
        "Built for an alumni office that needed tracer study data for accreditation, and a "
        "simpler way to reach graduates than group chats.",
        [("5000", 30)],
    ),
    (
        "Demo Client D", "Supply Request and Inventory System", "16500",
        Project.Status.IN_DEVELOPMENT, True, "lattice",
        "Office supply requests, approvals and stock levels in one flow.",
        "PHP, MySQL, Bootstrap, jQuery",
        "Let staff request supplies online instead of on paper forms\n"
        "Route requests for approval and keep a history of each one\n"
        "Keep stock counts accurate as items are issued",
        "Built for a supply office that handled requests on paper slips, so nobody had to guess "
        "what was in stock or where a request was stuck.",
        [("5000", 9)],
    ),
    (
        "Demo Client E", "QR Attendance Monitor", "12000", Project.Status.FULLY_PAID, True, "prism",
        "Attendance by QR scan, with reports for officers.",
        "Flutter, Firebase, Dart",
        "Record attendance by scanning a QR code on a phone\n"
        "Flag late and absent members automatically\n"
        "Export attendance summaries per training day",
        "Built for a student organization that called attendance by voice. Scanning takes "
        "seconds per person and the report is ready when formation ends.",
        [("6000", 90), ("6000", 70)],
    ),
    (
        "Demo Client F", "Research Repository", "20000", Project.Status.IN_DEVELOPMENT, True, "knot",
        "A searchable archive of a college's theses and capstone projects.",
        "Django, MySQL, Python, Bootstrap",
        "Store approved research papers with searchable abstracts\n"
        "Let students check whether a topic was already done\n"
        "Control who can download full manuscripts",
        "Built for a college library that kept bound copies on a shelf. Students can now search "
        "past research by title, author or keyword before choosing a topic.",
        [("7000", 5)],
    ),
    (
        "Demo Client G", "Payroll Prototype", "30000", Project.Status.IN_DEVELOPMENT, False,
        "crystal", "", "", "", "", [("10000", 3)],
    ),
]

LEADS = [
    ("Demo Visitor", "demo.visitor@example.com",
     "An online enrollment system for a small senior high school.", "Around 15,000", "Before March"),
]


class Command(BaseCommand):
    help = (
        "Fill the Tracker with clearly fictional demo clients and projects so the admin and the "
        "Showcase can be tried out. Use --clear to remove them again."
    )

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Remove the demo data and stop")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=True, so it can't touch a live site.")

        demo_clients = Client.objects.filter(notes=MARKER)
        if options["clear"] or demo_clients.exists():
            Receipt.objects.filter(payment__project__client__in=demo_clients).delete()
            Payment.objects.filter(project__client__in=demo_clients).delete()
            Project.objects.filter(client__in=demo_clients).delete()
            removed = demo_clients.count()
            demo_clients.delete()
            Lead.objects.filter(notes=MARKER).delete()
            if options["clear"]:
                self.stdout.write(self.style.SUCCESS(f"Removed demo data ({removed} clients)."))
                return

        today = timezone.localdate()
        for (client_name, system, price, status, public, preview, tagline, stack, objectives,
             purpose, payments) in PROJECTS:
            client = Client.objects.create(
                name=client_name, email=f"{client_name.lower().replace(' ', '.')}@example.com",
                notes=MARKER,
            )
            project = Project.objects.create(
                client=client, system_name=system, total_price=Decimal(price), status=status,
                is_public=public, preview_style=preview, tagline=tagline, tech_stack=stack,
                objectives=objectives, purpose=purpose,
                deadline=today + datetime.timedelta(days=10 + 9 * len(payments)),
            )
            for amount, days_ago in payments:
                Payment.objects.create(
                    project=project, amount=Decimal(amount),
                    date=today - datetime.timedelta(days=days_ago), method=Payment.Method.GCASH,
                )

        for name, contact, idea, budget, deadline in LEADS:
            Lead.objects.create(
                name=name, contact=contact, system_idea=idea, budget=budget, deadline=deadline,
                source=Lead.Source.CHATBOT, notes=MARKER,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Created {len(PROJECTS)} demo projects. They are fictional: remove them with "
            "`python manage.py seed_demo --clear` before publishing your real systems."
        ))
