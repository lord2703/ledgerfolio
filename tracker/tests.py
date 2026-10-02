import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from ledger.testing import LocalNodeMixin

from .models import Client, Lead, Payment, Project, Receipt
from .services import receipts as receipt_service
from .services.leads import convert_lead
from .services.pdf import build_receipt_pdf


def make_project(name="Clinic Records System", price="12000.00", **extra) -> Project:
    client = Client.objects.create(name="Maria Santos", email="maria@example.com")
    return Project.objects.create(
        client=client, system_name=name, total_price=Decimal(price), **extra
    )


def pay(project, amount, day=1, **extra) -> Payment:
    return Payment.objects.create(
        project=project, amount=Decimal(amount), date=datetime.date(2026, 9, day), **extra
    )


class CalculatedFieldTests(TestCase):
    def test_paid_and_balance_come_from_payments(self):
        project = make_project()
        self.assertEqual((project.paid_so_far, project.balance), (Decimal("0"), Decimal("12000.00")))
        pay(project, "5000")
        pay(project, "2500.50", day=2)
        self.assertEqual(project.paid_so_far, Decimal("7500.50"))
        self.assertEqual(project.balance, Decimal("4499.50"))
        self.assertEqual(project.paid_percent, 62)

    def test_annotated_totals_match_the_properties(self):
        project = make_project()
        pay(project, "5000")
        pay(project, "1000", day=3)
        empty = make_project(name="Empty")
        rows = {p.pk: p for p in Project.objects.with_totals()}
        self.assertEqual(rows[project.pk].paid_total, Decimal("6000.00"))
        self.assertEqual(rows[project.pk].balance_total, Decimal("6000.00"))
        self.assertEqual(rows[project.pk].paid_so_far, Decimal("6000.00"))
        self.assertEqual(rows[empty.pk].paid_total, Decimal("0"))
        self.assertEqual(rows[empty.pk].balance, Decimal("12000.00"))

    def test_slugs_are_unique(self):
        first = make_project(name="Inventory System")
        second = make_project(name="Inventory System")
        self.assertEqual(first.slug, "inventory-system")
        self.assertEqual(second.slug, "inventory-system-2")

    def test_showcase_lists(self):
        project = make_project(tech_stack="Django,  MySQL , ,Bootstrap", objectives="- One\n\n• Two\nThree")
        self.assertEqual(project.tech_list, ["Django", "MySQL", "Bootstrap"])
        self.assertEqual(project.objective_list, ["One", "Two", "Three"])


class ReceiptIssueTests(TestCase):
    def test_receipt_snapshots_the_payment(self):
        project = make_project()
        payment = pay(project, "5000", method="gcash")
        receipt = receipt_service.issue_receipt(payment)
        self.assertRegex(receipt.receipt_number, r"^RCT-\d{4}-0001$")
        self.assertEqual(receipt.client_name, "Maria Santos")
        self.assertEqual(receipt.system_name, "Clinic Records System")
        self.assertEqual(receipt.amount, Decimal("5000"))
        self.assertEqual(receipt.balance_after, Decimal("7000.00"))
        self.assertEqual(len(receipt.content_hash), 64)
        self.assertGreaterEqual(len(receipt.public_token), 40)

    def test_numbers_increase_and_tokens_differ(self):
        project = make_project()
        first = receipt_service.issue_receipt(pay(project, "1000"))
        second = receipt_service.issue_receipt(pay(project, "1000", day=2))
        self.assertTrue(first.receipt_number.endswith("-0001"))
        self.assertTrue(second.receipt_number.endswith("-0002"))
        self.assertNotEqual(first.public_token, second.public_token)

    def test_balance_after_ignores_later_payments(self):
        project = make_project()
        early = pay(project, "4000", day=1)
        pay(project, "3000", day=10)
        # Issued late, but the receipt still shows the balance right after its own payment.
        self.assertEqual(receipt_service.balance_after(early), Decimal("8000.00"))

    def test_later_edits_do_not_change_an_issued_receipt(self):
        project = make_project()
        receipt = receipt_service.issue_receipt(pay(project, "5000"))
        project.system_name = "Renamed System"
        project.save()
        project.client.name = "New Name"
        project.client.save()
        receipt.refresh_from_db()
        self.assertEqual(receipt.system_name, "Clinic Records System")
        self.assertEqual(receipt.client_name, "Maria Santos")

    def test_pdf_is_generated_and_repeatable(self):
        receipt = receipt_service.issue_receipt(pay(make_project(), "5000"))
        pdf = build_receipt_pdf(receipt)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 2000)
        receipt.document_type = Receipt.DocumentType.QUOTATION
        self.assertTrue(build_receipt_pdf(receipt).startswith(b"%PDF"))

    def test_verify_url_uses_the_public_site_address(self):
        receipt = receipt_service.issue_receipt(pay(make_project(), "5000"))
        with self.settings(SITE_URL="https://example.test"):
            self.assertEqual(
                receipt.verify_url, f"https://example.test/verify/{receipt.public_token}/"
            )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class GenerateAndSendTests(LocalNodeMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.payment = pay(make_project(), "5000")

    def test_full_flow_anchors_stores_pdf_and_emails(self):
        outcome = receipt_service.generate_and_send(self.payment)
        receipt = outcome.receipt
        self.assertTrue(outcome.created)
        self.assertEqual(receipt.ledger_status, Receipt.LedgerStatus.CONFIRMED)
        self.assertTrue(receipt.pdf.name.endswith(".pdf"))
        self.assertTrue(outcome.emailed)

        (message,) = mail.outbox
        self.assertEqual(message.to, ["maria@example.com"])
        self.assertIn(receipt.receipt_number, message.subject)
        self.assertIn(receipt.verify_url, message.body)
        name, content, mimetype = message.attachments[0]
        self.assertEqual((name, mimetype), (f"{receipt.receipt_number}.pdf", "application/pdf"))
        self.assertTrue(content.startswith(b"%PDF"))

    def test_running_again_reuses_the_receipt(self):
        first = receipt_service.generate_and_send(self.payment).receipt
        again = receipt_service.generate_and_send(self.payment)
        self.assertFalse(again.created)
        self.assertEqual(again.receipt.pk, first.pk)
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertEqual(self.node.chain.transaction_count, 1)

    def test_node_down_still_issues_and_emails_and_can_be_retried(self):
        self.node_online = False
        outcome = receipt_service.generate_and_send(self.payment)
        self.assertIn("not reachable", outcome.ledger_error)
        self.assertEqual(outcome.receipt.ledger_status, Receipt.LedgerStatus.UNANCHORED)
        self.assertTrue(outcome.emailed)

        self.node_online = True
        retry = receipt_service.generate_and_send(self.payment, send_email=False)
        self.assertEqual(retry.ledger_error, "")
        self.assertEqual(retry.receipt.ledger_status, Receipt.LedgerStatus.CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)

    def test_client_without_email_is_reported_not_raised(self):
        self.payment.project.client.email = ""
        self.payment.project.client.save()
        outcome = receipt_service.generate_and_send(self.payment)
        self.assertFalse(outcome.emailed)
        self.assertIn("no email", outcome.email_error)


class LeadTests(TestCase):
    def test_converted_lead_becomes_client_and_project(self):
        lead = Lead.objects.create(
            name="Juan Cruz", contact="juan@example.com", system_idea="An enrollment system",
            budget="15k", deadline="March",
        )
        project = convert_lead(lead)
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.CONVERTED)
        self.assertEqual(lead.converted_project, project)
        self.assertEqual(project.client.name, "Juan Cruz")
        self.assertEqual(project.client.email, "juan@example.com")
        self.assertIn("enrollment", project.notes)
        self.assertFalse(project.is_public)
        self.assertEqual(convert_lead(lead), project)  # converting twice changes nothing
        self.assertEqual(Project.objects.count(), 1)

    def test_non_email_contact_is_kept_as_other_contact(self):
        lead = Lead.objects.create(name="Ana", contact="0917 123 4567", system_idea="A POS system")
        project = convert_lead(lead)
        self.assertEqual(project.client.email, "")
        self.assertEqual(project.client.other_contact, "0917 123 4567")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AdminTests(LocalNodeMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser("lord", "lord@example.com", "pw")
        self.client.force_login(self.admin)
        self.project = make_project(status=Project.Status.READY_FOR_FINAL)
        self.payment = pay(self.project, "5000")

    def test_dashboard_and_lists_render(self):
        Lead.objects.create(name="Juan", contact="juan@example.com", system_idea="An enrollment system")
        receipt_service.generate_and_send(self.payment, send_email=False)
        for name in ("index", "tracker_client_changelist", "tracker_project_changelist",
                     "tracker_payment_changelist", "tracker_receipt_changelist",
                     "tracker_lead_changelist", "tracker_unansweredquestion_changelist"):
            response = self.client.get(reverse(f"admin:{name}"))
            self.assertEqual(response.status_code, 200, name)
        dashboard = self.client.get(reverse("admin:index")).content.decode()
        self.assertIn("Outstanding balance", dashboard)
        self.assertIn("PHP 7,000.00", dashboard)
        self.assertIn("Online, chain intact", dashboard)

    def test_dashboard_survives_the_node_being_down(self):
        self.node_online = False
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "Offline")

    def test_project_list_shows_calculated_money_and_filters_by_status(self):
        make_project(name="Other System", status=Project.Status.IN_DEVELOPMENT)
        url = reverse("admin:tracker_project_changelist")
        response = self.client.get(url)
        self.assertContains(response, "PHP 7,000.00")
        filtered = self.client.get(url, {"status__exact": "ready_for_final"})
        self.assertContains(filtered, "Clinic Records System")
        self.assertNotContains(filtered, "Other System")
        owing = self.client.get(url, {"balance": "settled"})
        self.assertNotContains(owing, "Clinic Records System")

    def test_project_page_has_inline_payments(self):
        response = self.client.get(reverse("admin:tracker_project_change", args=[self.project.pk]))
        self.assertContains(response, "payments-0-amount")
        self.assertContains(response, "Paid so far")

    def test_generate_and_send_receipt_action(self):
        response = self.client.post(
            reverse("admin:tracker_payment_changelist"),
            {"action": "generate_and_send_receipt", "_selected_action": [self.payment.pk]},
            follow=True,
        )
        receipt = Receipt.objects.get()
        self.assertContains(response, f"Receipt {receipt.receipt_number} issued")
        self.assertContains(response, "Sealed in block #1")
        self.assertContains(response, "Emailed to maria@example.com")
        self.assertEqual(len(mail.outbox), 1)

        detail = self.client.get(reverse("admin:tracker_receipt_change", args=[receipt.pk]))
        self.assertContains(detail, receipt.verify_url)
        self.assertContains(detail, "Copy link")
        self.assertContains(detail, "genuine")

        pdf = self.client.get(reverse("admin:tracker_receipt_pdf", args=[receipt.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(pdf.streaming_content).startswith(b"%PDF"))

    def test_receipt_pdf_is_not_public(self):
        receipt = receipt_service.generate_and_send(self.payment, send_email=False).receipt
        self.client.logout()
        response = self.client.get(reverse("admin:tracker_receipt_pdf", args=[receipt.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_convert_lead_action(self):
        lead = Lead.objects.create(name="Juan", contact="juan@example.com", system_idea="An enrollment system")
        response = self.client.post(
            reverse("admin:tracker_lead_changelist"),
            {"action": "convert", "_selected_action": [lead.pk]}, follow=True,
        )
        self.assertContains(response, "is now a client")
        self.assertTrue(Client.objects.filter(name="Juan").exists())
