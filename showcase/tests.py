import datetime
import io
import json
import shutil
import tempfile
from decimal import Decimal
from unittest import skipUnless

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as Browser
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from ledger.testing import LocalNodeMixin
from tracker.models import (
    Client, Lead, Payment, Project, ProjectScreenshot, Receipt, Review, UnansweredQuestion,
)
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
            reverse("showcase:contact"),
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


def picture(name: str) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 10), "#e2b867").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class ScreenshotTests(LedgerBackedTestCase):
    """Pictures are added to a project in the Tracker and shown on the Showcase."""

    def setUp(self):
        super().setUp()
        media = tempfile.mkdtemp(prefix="ledgerfolio-media-")
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        overrides = override_settings(MEDIA_ROOT=media)
        overrides.enable()
        self.addCleanup(overrides.disable)

    def test_screenshots_appear_on_the_card_and_the_system_page(self):
        ProjectScreenshot.objects.create(
            project=self.public, image=picture("dashboard.png"), caption="Visits dashboard", order=2
        )
        ProjectScreenshot.objects.create(
            project=self.public, image=picture("login.png"), caption="Login page", order=1
        )
        listing = self.client.get(reverse("showcase:system_list")).content.decode()
        cover = listing.split('class="card__cover"', 1)[1][:400]
        self.assertIn("/media/projects/", cover)
        self.assertIn("login", cover)  # the lowest order number is the card picture

        detail = self.client.get(
            reverse("showcase:system_detail", args=[self.public.slug])
        ).content.decode()
        self.assertIn("dashboard", detail)
        self.assertLess(detail.index("Login page"), detail.index("Visits dashboard"))

    def test_private_projects_pictures_stay_private(self):
        ProjectScreenshot.objects.create(
            project=self.private, image=picture("payroll.png"), caption="Payroll screen"
        )
        for name in ("showcase:home", "showcase:system_list"):
            self.assertNotContains(self.client.get(reverse(name)), "Payroll screen")


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
        # Other sites never get the link; this site still does, so the review
        # form's POST carries a real Origin for the CSRF check.
        self.assertEqual(response["Referrer-Policy"], "same-origin")
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


class BackLinkTests(LedgerBackedTestCase):
    def test_every_page_but_the_homepage_links_back(self):
        for name, args in (("showcase:system_list", []), ("showcase:system_detail", [self.public.slug]),
                           ("showcase:ledger", []), ("showcase:verify_lookup", []),
                           ("showcase:contact", [])):
            page = self.client.get(reverse(name, args=args))
            # An arrow and label sit beside the logo in the top bar.
            self.assertContains(page, 'class="nav__back"')
            self.assertContains(page, "Back to the homepage")
        home = self.client.get(reverse("showcase:home"))
        self.assertNotContains(home, 'class="nav__back"')
        self.assertNotContains(home, "Back to the homepage")


class MessageFormTests(TestCase):
    """The message form: what visitors write lands in the Tracker's Messages."""

    def setUp(self):
        cache.clear()
        self.url = reverse("showcase:contact")

    def send(self, **fields):
        data = {"name": "Juan dela Cruz", "contact": "juan@example.com",
                "message": "An online enrollment system for our senior high school.",
                "budget": "around 15,000", "deadline": "before March", "website": ""}
        data.update(fields)
        return self.client.post(self.url, data)

    def test_message_reaches_the_tracker(self):
        self.assertRedirects(self.send(), f"{self.url}?sent=1", fetch_redirect_response=False)
        lead = Lead.objects.get()
        self.assertEqual((lead.name, lead.contact, lead.budget, lead.deadline),
                         ("Juan dela Cruz", "juan@example.com", "around 15,000", "before March"))
        self.assertEqual((lead.source, lead.status), (Lead.Source.WEBSITE, Lead.Status.NEW))
        self.assertIn("enrollment", lead.system_idea)

        thanks = self.client.get(f"{self.url}?sent=1")
        self.assertContains(thanks, "Thank you")
        self.assertContains(thanks, "juan@example.com")
        # The thank-you page shows once; reloading it brings back the empty form.
        self.assertContains(self.client.get(f"{self.url}?sent=1"), 'name="message"')

    def test_mistakes_are_explained_and_nothing_is_saved(self):
        response = self.send(name="", message="hi")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "field__error")
        self.assertContains(self.send(contact="juan@"), "looks incomplete")
        self.assertEqual(Lead.objects.count(), 0)

    def test_bots_that_fill_the_hidden_field_save_nothing(self):
        self.assertEqual(self.send(website="http://spam.example").status_code, 302)
        self.assertEqual(Lead.objects.count(), 0)

    def test_too_many_messages_from_one_visitor(self):
        for _ in range(5):
            self.send()
        self.assertContains(self.send(), "short time")
        self.assertEqual(Lead.objects.count(), 5)

    def test_a_system_page_can_prefill_the_message(self):
        self.assertContains(self.client.get(self.url, {"about": "Clinic Records System"}),
                            "I&#x27;d like a system like Clinic Records System.")


class ReviewTests(LedgerBackedTestCase):
    """Clients review from their receipt's verify page; the owner approves."""

    def setUp(self):
        super().setUp()
        payment = Payment.objects.create(
            project=self.public, amount=Decimal("5000"), date=datetime.date(2026, 9, 1)
        )
        self.receipt = receipt_service.generate_and_send(payment, send_email=False).receipt
        self.url = reverse("showcase:verify", args=[self.receipt.public_token])

    def write(self, url=None, **fields):
        data = {"rating": "5", "comment": "Great work, delivered before our defense.",
                "display_name": "Ana, BSIT student"}
        data.update(fields)
        return self.client.post(url or self.url, data)

    def test_review_waits_for_approval_then_appears_on_the_site(self):
        self.assertContains(self.client.get(self.url), "How would you rate working with")
        self.assertRedirects(self.write(), f"{self.url}?review=sent#review", fetch_redirect_response=False)
        review = Review.objects.get()
        self.assertEqual((review.rating, review.status, review.project_id, review.receipt_id),
                         (5, Review.Status.PENDING, self.public.pk, self.receipt.pk))
        page = self.client.get(f"{self.url}?review=sent")
        self.assertContains(page, "Your rating was sent")
        self.assertContains(page, "Waiting for approval")

        home, detail = reverse("showcase:home"), reverse("showcase:system_detail", args=[self.public.slug])
        self.assertNotContains(self.client.get(home), "delivered before our defense")
        review.status = Review.Status.APPROVED
        review.save()
        for url in (home, detail):
            html = self.client.get(url)
            self.assertContains(html, "delivered before our defense")
            self.assertContains(html, "Ana, BSIT student")
            self.assertContains(html, "Verified client")

    def test_writing_again_replaces_the_review_and_needs_approval_again(self):
        self.write()
        Review.objects.update(status=Review.Status.APPROVED)
        self.assertContains(self.client.get(f"{self.url}?review=edit"), "Edit your rating")
        self.write(rating="4", comment="Edited: still very happy with the system.")
        review = Review.objects.get()
        self.assertEqual((review.rating, review.status), (4, Review.Status.PENDING))

    def test_stars_alone_are_enough(self):
        self.assertEqual(self.write(rating="5", comment="", display_name="").status_code, 302)
        review = Review.objects.get()
        self.assertEqual((review.rating, review.comment, review.display_name), (5, "", ""))
        self.assertContains(self.client.get(self.url), "without a comment")
        Review.objects.update(status=Review.Status.APPROVED)
        home = self.client.get(reverse("showcase:home"))
        self.assertContains(home, "Rated 5 out of 5")
        self.assertContains(home, "Verified client")

    def test_a_rating_is_required(self):
        response = self.write(rating="", comment="Lovely work.")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose from 1 to 5 stars")
        self.assertEqual(Review.objects.count(), 0)

    def test_review_of_a_private_project_never_names_it(self):
        payment = Payment.objects.create(
            project=self.private, amount=Decimal("1000"), date=datetime.date(2026, 9, 2)
        )
        receipt = receipt_service.generate_and_send(payment, send_email=False).receipt
        self.write(reverse("showcase:verify", args=[receipt.public_token]),
                   comment="Very good work on our payroll.", display_name="")
        Review.objects.update(status=Review.Status.APPROVED)
        home = self.client.get(reverse("showcase:home")).content.decode()
        self.assertIn("Very good work on our payroll.", home)
        for secret in PRIVATE_STRINGS:
            self.assertNotIn(secret, home)

    def test_only_a_real_receipt_link_can_review(self):
        response = self.write(reverse("showcase:verify", args=["x" * 43]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Review.objects.count(), 0)

    def test_tampered_receipt_shows_no_review_form(self):
        Receipt.objects.filter(pk=self.receipt.pk).update(amount=Decimal("50.00"))
        self.assertNotContains(self.client.get(self.url), "How would you rate working with")


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

    def test_inquiries_are_passed_to_the_owner(self):
        reply = self.say("I want a system built")
        self.assertIn(reverse("showcase:contact"), [link["url"] for link in reply["links"]])
        self.assertIn("personally", reply["reply"])
        self.say("Juan dela Cruz")  # the chat never collects details
        self.assertEqual(Lead.objects.count(), 0)

    def test_unsure_questions_are_logged_and_point_to_the_owner(self):
        reply = self.say("zxqv blorptang wibble")
        self.assertIn("not sure", reply["reply"])
        self.assertEqual(UnansweredQuestion.objects.count(), 1)
        self.assertIn(reverse("showcase:contact"), [link["url"] for link in reply["links"]])

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
