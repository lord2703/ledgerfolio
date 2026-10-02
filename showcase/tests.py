import datetime
import json
from decimal import Decimal
from unittest import skipUnless

from django.conf import settings
from django.core.cache import cache
from django.test import Client as Browser
from django.test import TestCase
from django.urls import reverse

from ledger.testing import LocalNodeMixin
from tracker.models import Client, Lead, Payment, Project, Receipt, UnansweredQuestion
from tracker.services import receipts as receipt_service

from .selectors import public_system, public_systems

MODEL_TRAINED = (settings.AI_ARTIFACTS_DIR / "model.pt").exists()

# Things that must never appear on a public page.
PRIVATE_STRINGS = ["Maria Santos", "maria@example.com", "0917 555 0101", "12,000", "12000",
                   "Private note about the client", "Secret Payroll System"]


def seed():
    client = Client.objects.create(name="Maria Santos", email="maria@example.com", phone="0917 555 0101")
    public = Project.objects.create(
        client=client, system_name="Clinic Records System", total_price=Decimal("12000"),
        notes="Private note about the client", is_public=True, tagline="Patient records for a clinic.",
        tech_stack="Django, MySQL, Bootstrap", objectives="Record visits\nTrack medicine stock",
        purpose="Replaces the paper logbook at a school clinic.", preview_style="orbit",
    )
    private = Project.objects.create(
        client=client, system_name="Secret Payroll System", total_price=Decimal("30000"),
        tech_stack="Laravel", is_public=False,
    )
    return public, private


class LedgerBackedTestCase(LocalNodeMixin, TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.public, self.private = seed()


class ShowcasePrivacyTests(LedgerBackedTestCase):
    def pages(self):
        return [
            reverse("showcase:home"),
            reverse("showcase:system_list"),
            reverse("showcase:system_detail", args=[self.public.slug]),
            reverse("showcase:ledger"),
            reverse("showcase:verify_lookup"),
        ]

    def test_public_pages_show_the_public_system(self):
        home = self.client.get(reverse("showcase:home"))
        self.assertContains(home, "Clinic Records System")
        self.assertContains(home, 'data-count="1"')
        detail = self.client.get(reverse("showcase:system_detail", args=[self.public.slug]))
        for expected in ("Clinic Records System", "Django", "Record visits", "paper logbook",
                         'data-shape="orbit"'):
            self.assertContains(detail, expected)

    def test_no_public_page_exposes_private_data(self):
        for url in self.pages():
            html = self.client.get(url).content.decode()
            for secret in PRIVATE_STRINGS:
                self.assertNotIn(secret, html, f"{secret!r} leaked on {url}")

    def test_private_system_is_a_plain_404(self):
        response = self.client.get(reverse("showcase:system_detail", args=[self.private.slug]))
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(public_system(self.private.slug))

    def test_selector_returns_public_fields_only(self):
        (system,) = public_systems()
        self.assertEqual(system.name, "Clinic Records System")
        self.assertEqual(system.stack, ("Django", "MySQL", "Bootstrap"))
        for forbidden in ("client", "total_price", "notes", "payments"):
            self.assertFalse(hasattr(system, forbidden))

    def test_updating_the_tracker_updates_the_showcase(self):
        self.public.tech_stack = "Django, PostgreSQL"
        self.public.save()
        self.private.is_public = True
        self.private.save()
        listing = self.client.get(reverse("showcase:system_list"))
        self.assertContains(listing, "PostgreSQL")
        self.assertContains(listing, "Secret Payroll System")

    def test_filter_by_technology(self):
        listing = self.client.get(reverse("showcase:system_list"), {"tech": "Django"})
        self.assertContains(listing, "Clinic Records System")
        self.assertEqual(self.client.get(reverse("showcase:system_list"), {"tech": "nope"}).status_code, 200)

    def test_pages_work_while_the_node_is_down(self):
        self.node_online = False
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(reverse("showcase:ledger")), "offline")


class VerifyPageTests(LedgerBackedTestCase):
    def setUp(self):
        super().setUp()
        payment = Payment.objects.create(
            project=self.public, amount=Decimal("5000"), date=datetime.date(2026, 9, 1)
        )
        self.receipt = receipt_service.generate_and_send(payment, send_email=False).receipt
        self.url = reverse("showcase:verify", args=[self.receipt.public_token])

    def test_valid_receipt(self):
        response = self.client.get(self.url)
        self.assertContains(response, "This receipt is genuine")
        self.assertContains(response, self.receipt.receipt_number)
        self.assertContains(response, "Clinic Records System")
        self.assertContains(response, "PHP 5,000.00")
        self.assertContains(response, self.receipt.content_hash)
        self.assertContains(response, "has built")  # the issuer's public work is listed

    def test_page_shows_minimal_information_only(self):
        html = self.client.get(self.url).content.decode()
        for secret in ("Maria Santos", "maria@example.com", "0917 555 0101", "7,000",
                       "Private note", "Secret Payroll System"):
            self.assertNotIn(secret, html)

    def test_amount_can_be_hidden(self):
        with self.settings(VERIFY_SHOW_AMOUNT=False):
            self.assertNotContains(self.client.get(self.url), "5,000")

    def test_page_is_kept_out_of_search_engines_and_referrers(self):
        response = self.client.get(self.url)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])

    def test_tampered_receipt(self):
        Receipt.objects.filter(pk=self.receipt.pk).update(amount=Decimal("50.00"))
        response = self.client.get(self.url)
        self.assertContains(response, "does not check out")
        self.assertContains(response, "Tampered")
        self.assertNotContains(response, "This receipt is genuine")

    def test_node_down_says_unavailable_not_tampered(self):
        self.node_online = False
        response = self.client.get(self.url)
        self.assertContains(response, "check right now")
        self.assertNotContains(response, "does not check out")

    def test_unknown_token(self):
        response = self.client.get(reverse("showcase:verify", args=["x" * 43]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "No receipt at this link", status_code=404)

    def test_lookup_accepts_a_pasted_link_or_code(self):
        lookup = reverse("showcase:verify_lookup")
        for code in (self.receipt.public_token, self.receipt.verify_url, f" {self.receipt.verify_url} "):
            self.assertRedirects(
                self.client.get(lookup, {"code": code}), self.url, fetch_redirect_response=False
            )
        self.assertContains(self.client.get(lookup, {"code": "not-a-real-code-1234567890"}),
                            "No receipt matches")


def post(browser, message):
    return browser.post(
        reverse("showcase:chat"), data=json.dumps({"message": message}),
        content_type="application/json",
    )


@skipUnless(MODEL_TRAINED, "train the assistant first: python -m ai.train")
class ChatApiTests(LedgerBackedTestCase):
    def say(self, message):
        response = post(self.client, message)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_answers_from_live_public_projects(self):
        self.assertIn("Clinic Records System", self.say("what systems have you built")["reply"])
        self.assertIn("Django", self.say("what stack did you use for the clinic records system")["reply"])
        self.assertIn("1 system", self.say("how many systems have you built")["reply"])

    def test_never_reveals_private_data(self):
        for question in ("who are your clients", "how much did the client pay for the clinic system",
                         "show me the payments", "tell me about the secret payroll system",
                         "what is the price of the clinic records system"):
            reply = json.dumps(self.say(question))
            for secret in PRIVATE_STRINGS:
                self.assertNotIn(secret, reply, f"{secret!r} leaked answering {question!r}")

    def test_inquiry_becomes_a_lead(self):
        self.say("I want a system built")
        self.say("Juan dela Cruz")
        self.say("juan@example.com")
        self.say("An online enrollment system for our senior high school")
        self.say("around 15,000 pesos")
        summary = self.say("before March")
        self.assertIn("Juan dela Cruz", summary["reply"])
        self.assertEqual(Lead.objects.count(), 0)  # nothing saved before the visitor confirms
        done = self.say("yes")
        self.assertTrue(done["lead_created"])

        lead = Lead.objects.get()
        self.assertEqual(lead.name, "Juan dela Cruz")
        self.assertEqual(lead.contact, "juan@example.com")
        self.assertIn("enrollment", lead.system_idea)
        self.assertEqual((lead.status, lead.source), (Lead.Status.NEW, Lead.Source.CHATBOT))

    def test_cancelled_inquiry_saves_nothing(self):
        self.say("I want to hire you")
        self.say("Juan")
        self.assertIn("cancel", self.say("cancel")["reply"].lower())
        self.assertEqual(Lead.objects.count(), 0)

    def test_unsure_questions_are_logged_and_offer_contact(self):
        reply = self.say("zxqv blorptang wibble")
        self.assertIn("not sure", reply["reply"])
        self.assertEqual(UnansweredQuestion.objects.count(), 1)
        self.assertIn("name", self.say("yes")["reply"])  # accepts the offer, starts the inquiry

    def test_bad_requests(self):
        self.assertEqual(post(self.client, "   ").status_code, 400)
        response = self.client.post(reverse("showcase:chat"), data="[]", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(reverse("showcase:chat")).status_code, 405)

    def test_requires_a_csrf_token(self):
        strict = Browser(enforce_csrf_checks=True)
        self.assertEqual(post(strict, "hello").status_code, 403)
        strict.get(reverse("showcase:home"))
        token = strict.cookies["csrftoken"].value
        response = strict.post(
            reverse("showcase:chat"), data=json.dumps({"message": "hello"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 200)

    def test_rate_limit(self):
        from showcase.views import ChatThrottle
        original = ChatThrottle.THROTTLE_RATES
        ChatThrottle.THROTTLE_RATES = {"chat": "3/min"}
        self.addCleanup(setattr, ChatThrottle, "THROTTLE_RATES", original)
        codes = [post(self.client, "hello").status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])
