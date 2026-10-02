"""Connects the standalone `ai` package to this site.

The assistant is given public project data and two callbacks. It never
receives a database connection or any private field.
"""

import logging
from functools import lru_cache

from django.conf import settings

from ai.assistant import Assistant, Owner
from ai.inference import IntentModel, ModelNotTrained
from ai.retrieval import KnowledgeBase
from tracker.models import Lead, UnansweredQuestion

from .selectors import as_knowledge, public_systems

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model():
    """Load the trained weights once per process."""
    try:
        return IntentModel.load(settings.AI_ARTIFACTS_DIR)
    except ModelNotTrained:
        logger.warning("No trained assistant model found. Run: python -m ai.train")
        return None


def _create_lead(data: dict) -> None:
    Lead.objects.create(
        name=data["name"],
        contact=data["contact"],
        system_idea=data["idea"],
        budget=data.get("budget", ""),
        deadline=data.get("deadline", ""),
        source=Lead.Source.CHATBOT,
    )


def _log_unanswered(message: str, intent: str, confidence: float) -> None:
    UnansweredQuestion.objects.create(
        message=message[:500], predicted_intent=intent, confidence=confidence
    )


def build_assistant() -> Assistant:
    return Assistant(
        model=_model(),
        knowledge=KnowledgeBase(as_knowledge(public_systems())),
        owner=Owner(
            name=settings.OWNER_NAME,
            title=settings.OWNER_TITLE,
            location=settings.OWNER_LOCATION,
            email=settings.OWNER_EMAIL,
            phone=settings.OWNER_PHONE,
            site_name=settings.SITE_NAME,
        ),
        create_lead=_create_lead,
        log_unanswered=_log_unanswered,
        threshold=settings.AI_CONFIDENCE_THRESHOLD,
    )
