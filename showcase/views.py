"""Public pages. Views stay thin: data comes from selectors and services."""

import re

from django.conf import settings
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
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
from tracker.services.pdf import money

from .assistant import build_assistant
from .selectors import public_system, public_systems, tech_summary

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,64}")
PROCESS_STEPS = [
    ("Inquiry", "Tell me what you need. The assistant on this site can take down your details."),
    ("Quotation", "I review the idea and send you a price and a timeline."),
    ("In development", "I build the system and keep you posted on its status."),
    ("Ready for pre-oral", "The system is complete enough to present at your pre-oral defense."),
    ("Ready for final", "Revisions are done and the system is ready for the final defense."),
    ("Fully paid", "The price is settled. Every payment along the way has a verifiable receipt."),
]


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
    return render(request, "showcase/home.html", {
        "systems": systems[:6],
        "system_count": len(systems),
        "techs": tech_summary(systems),
        "process_steps": PROCESS_STEPS,
        "chain": ledger_snapshot(),
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
    return render(request, "showcase/system_detail.html", {"system": system, "others": others})


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
    receipt = Receipt.objects.filter(public_token=public_token).first()
    systems = public_systems()
    context = {"systems": systems, "system_count": len(systems), "receipt": None}

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
        })
        response = render(request, "showcase/verify.html", context)

    # The token in the URL is the client's key to this page: keep it out of
    # search engines and out of Referer headers.
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


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
            "lead_created": reply.lead_created,
        })

    def throttled(self, request, wait):
        raise Throttled(
            detail="You're sending messages quickly. Please wait a moment and try again."
        )
