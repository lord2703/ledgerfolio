"""Public pages. Views stay thin: data comes from selectors and services."""

import math
import re

from django.conf import settings
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from ledger import services as ledger
from ledger.client import NodeClient
from tracker.models import Receipt
from tracker.services.leads import record_message
from tracker.services.pdf import money
from tracker.services.reviews import review_for, submit_review

from .assistant import build_assistant
from .forms import ContactForm, ReviewForm
from .selectors import (
    public_reviews,
    public_system,
    public_systems,
    review_summary,
    system_review,
    tech_summary,
)

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,64}")
# Form submissions allowed per visitor: (how many, per this many seconds).
MESSAGE_LIMIT = (5, 3600)
REVIEW_LIMIT = (10, 3600)
PROCESS_STEPS = [
    ("Inquiry", "Send me a message about what you need. I read and answer every one myself."),
    ("Quotation", "I review the idea and send you a price and a timeline."),
    ("In development", "I build the system and keep you posted on its status."),
    ("Ready for pre-oral", "The system is complete enough to present at your pre-oral defense."),
    ("Ready for final", "Revisions are done and the system is ready for the final defense."),
    ("Fully paid", "The price is settled. Every payment along the way has a verifiable receipt."),
]


def marquee(techs):
    """Technology names repeated enough to fill a wide screen, for the scrolling band.

    Returns ([(name, is_repeat), ...], seconds per loop). Repeats are marked so
    screen readers and the reduced-motion layout list each name once.
    """
    if not techs:
        return [], 0
    rounds = max(2, math.ceil(24 / len(techs)))
    items = [(tech, round_ > 0) for round_ in range(rounds) for tech in techs]
    return items, round(len(items) * 2.6)


def client_ip(request) -> str:
    """The visitor's address. Behind Nginx (NUM_PROXIES=1) it comes from X-Forwarded-For."""
    proxies = settings.REST_FRAMEWORK.get("NUM_PROXIES") or 0
    forwarded = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
                 if part.strip()]
    if proxies and forwarded:
        return forwarded[-min(proxies, len(forwarded))]
    return request.META.get("REMOTE_ADDR", "")


def over_limit(request, scope: str, limit: int, window: int) -> bool:
    """Counts a submission; True once this visitor has sent more than `limit` in `window`."""
    key = f"limit:{scope}:{client_ip(request)}"
    if cache.add(key, 1, window):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:  # expired between the two calls
        cache.set(key, 1, window)
        return False


def ledger_snapshot() -> dict:
    """Chain status for page chrome. Cached and short-timed so pages stay fast."""
    snapshot = cache.get("ledger_snapshot")
    if snapshot is None:
        snapshot = ledger.overview(NodeClient(timeout=1.5), blocks=1)
        snapshot.pop("blocks", None)
        cache.set("ledger_snapshot", snapshot, 20)
    return snapshot


@ensure_csrf_cookie
def home(request):
    systems = public_systems()
    techs = tech_summary(systems)
    marquee_items, marquee_duration = marquee(techs)
    return render(request, "showcase/home.html", {
        "systems": systems[:6],
        "system_count": len(systems),
        "techs": techs,
        "marquee_items": marquee_items,
        "marquee_duration": marquee_duration,
        "process_steps": PROCESS_STEPS,
        "chain": ledger_snapshot(),
        "reviews": public_reviews(),
        "review_stats": review_summary(),
    })


@ensure_csrf_cookie
def system_list(request):
    systems = public_systems()
    tech = request.GET.get("tech", "").strip()
    techs = tech_summary(systems)
    shown = [s for s in systems if tech in s.stack] if tech in techs else systems
    return render(request, "showcase/system_list.html", {
        "systems": shown,
        "system_count": len(systems),
        "techs": techs,
        "active_tech": tech if tech in techs else "",
    })


@ensure_csrf_cookie
def system_detail(request, slug):
    system = public_system(slug)
    if system is None:
        # Private and missing systems look identical from outside.
        raise Http404("No such system")
    others = [s for s in public_systems() if s.slug != slug][:3]
    return render(request, "showcase/system_detail.html", {
        "system": system, "others": others, "review": system_review(slug),
    })


@ensure_csrf_cookie
def contact(request):
    """The message form: what visitors send here lands in the Tracker's Messages."""
    if request.GET.get("sent") and "message_sent" in request.session:
        return render(request, "showcase/contact.html", {"sent": request.session.pop("message_sent")})

    if request.method == "POST":
        form = ContactForm(request.POST)
        if over_limit(request, "message", *MESSAGE_LIMIT):
            form.add_error(None, "You've sent several messages in a short time. "
                                 "Please wait a while before sending another.")
        elif form.is_valid():
            data = form.cleaned_data
            if not data["website"]:  # filled in only by bots: they get the same reply, nothing is saved
                record_message(data["name"], data["contact"], data["message"],
                               data["budget"], data["deadline"])
            request.session["message_sent"] = {"name": data["name"], "contact": data["contact"]}
            return redirect(f"{reverse('showcase:contact')}?sent=1")
    else:
        about = " ".join(request.GET.get("about", "").split())[:150]
        form = ContactForm(initial={"message": f"I'd like a system like {about}. " if about else ""})
    return render(request, "showcase/contact.html", {"form": form})


@ensure_csrf_cookie
def ledger_page(request):
    return render(request, "showcase/ledger.html", {
        "chain": ledger.overview(NodeClient(timeout=3.0), blocks=8),
    })


@ensure_csrf_cookie
def verify_lookup(request):
    """Lets someone paste a verify link or code instead of scanning the QR."""
    code = request.GET.get("code", "").strip()
    not_found = False
    if code:
        candidates = TOKEN_PATTERN.findall(code.rstrip("/").rsplit("/", 1)[-1])
        if candidates and Receipt.objects.filter(public_token=candidates[0]).exists():
            return redirect("showcase:verify", public_token=candidates[0])
        not_found = True
    return render(request, "showcase/verify_lookup.html", {"code": code, "not_found": not_found})


@never_cache
@ensure_csrf_cookie
def verify(request, public_token):
    receipt = Receipt.objects.filter(public_token=public_token).select_related("payment").first()
    systems = public_systems()
    context = {"systems": systems, "system_count": len(systems), "receipt": None}

    # Holding the receipt link is what lets a client write a review, so the
    # review form posts back to this same page.
    review_form = None
    if receipt is not None and request.method == "POST":
        review_form = ReviewForm(request.POST)
        if over_limit(request, "review", *REVIEW_LIMIT):
            review_form.add_error(None, "Too many tries in a short time. Please wait a while.")
        elif review_form.is_valid():
            submit_review(receipt, **review_form.cleaned_data)
            return redirect(f"{request.path}?review=sent#review")

    if receipt is None:
        response = render(request, "showcase/verify.html", context, status=404)
    else:
        result = ledger.verify(receipt)
        if result.block and receipt.ledger_status != Receipt.LedgerStatus.CONFIRMED:
            ledger.refresh(receipt)
        # Only these few fields ever reach the public page.
        context.update({
            "result": result,
            "receipt": {
                "number": receipt.receipt_number,
                "kind": receipt.get_document_type_display(),
                "issued_at": receipt.issued_at,
                "system_name": receipt.system_name,
                "amount": money(receipt.amount) if settings.VERIFY_SHOW_AMOUNT else None,
            },
            "review_box": review_box(request, receipt, result, review_form),
        })
        response = render(request, "showcase/verify.html", context)

    # The token in the URL is the client's key to this page: keep it out of
    # search engines and out of Referer headers sent to other sites. (Same-site
    # requests keep their origin, which the review form's CSRF check needs.)
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "same-origin"
    return response


def review_box(request, receipt, result, form):
    """What the review section of the verify page shows."""
    existing = review_for(receipt)
    editing = request.GET.get("review") == "edit"
    if form is None and (existing is None or editing):
        initial = ({"rating": existing.rating, "comment": existing.comment,
                    "display_name": existing.display_name} if existing else {})
        form = ReviewForm(initial=initial)
    return {
        "allowed": result.state != ledger.TAMPERED,
        "form": form,
        "sent": request.GET.get("review") == "sent",
        "existing": existing and {
            "rating": existing.rating,
            "comment": existing.comment,
            "name": existing.display_name,
            "status": existing.status,
            "status_label": existing.get_status_display(),
        },
    }


class ChatThrottle(AnonRateThrottle):
    scope = "chat"


@method_decorator(csrf_protect, name="dispatch")
class ChatView(APIView):
    """POST {"message": "..."} -> the assistant's reply. Rate-limited per visitor."""

    throttle_classes = [ChatThrottle]

    def post(self, request):
        message = request.data.get("message") if isinstance(request.data, dict) else None
        if not isinstance(message, str) or not message.strip():
            return Response({"detail": "Send a JSON body with a 'message' string."}, status=400)

        reply = build_assistant().reply(message, request.session.get("assistant"))
        request.session["assistant"] = reply.state
        return Response({
            "reply": reply.text,
            "suggestions": reply.suggestions,
            "links": reply.links,
        })

    def throttled(self, request, wait):
        raise Throttled(
            detail="You're sending messages quickly. Please wait a moment and try again."
        )
