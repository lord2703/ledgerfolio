"""The only door between the Showcase and the Tracker's data.

Public pages never receive `Project` model objects. They get `PublicSystem`
values that are copied field by field from rows with `is_public=True`, so
client, price, payments and notes are simply not there to be shown.
"""

import datetime
from dataclasses import dataclass

from django.db.models import Avg, Count
from django.urls import reverse
from django.utils import timezone

from tracker.models import Project, Review

PUBLIC_FIELDS = (
    "id", "system_name", "slug", "tagline", "tech_stack", "objectives", "purpose",
    "preview_style", "created_at",
)


@dataclass(frozen=True)
class Screenshot:
    url: str
    caption: str


@dataclass(frozen=True)
class PublicSystem:
    name: str
    slug: str
    tagline: str
    stack: tuple
    objectives: tuple
    purpose: str
    preview_style: str
    year: int
    screenshots: tuple = ()

    @property
    def url(self) -> str:
        return reverse("showcase:system_detail", args=[self.slug])

    @property
    def cover(self):
        return self.screenshots[0] if self.screenshots else None

    @property
    def initials(self) -> str:
        words = [word for word in self.name.split() if word[0].isalnum()]
        return "".join(word[0] for word in words[:2]).upper() or "S"


def _to_public(project: Project) -> PublicSystem:
    return PublicSystem(
        name=project.system_name,
        slug=project.slug,
        tagline=project.tagline,
        stack=tuple(project.tech_list),
        objectives=tuple(project.objective_list),
        purpose=project.purpose,
        preview_style=project.preview_style,
        year=project.created_at.year,
        screenshots=tuple(
            Screenshot(url=shot.image.url, caption=shot.caption)
            for shot in project.screenshots.all()
        ),
    )


def _queryset():
    return (
        Project.objects.public()
        .only(*PUBLIC_FIELDS)
        .prefetch_related("screenshots")
        .order_by("-created_at")
    )


def public_systems() -> list:
    return [_to_public(project) for project in _queryset()]


def public_system(slug: str):
    project = _queryset().filter(slug=slug).first()
    return _to_public(project) if project else None


@dataclass(frozen=True)
class PublicReview:
    """An approved review as the Showcase may show it.

    `name` is only what the client chose to show. The system is named only
    when that project is itself public.
    """

    rating: int
    comment: str
    name: str
    system_name: str
    system_url: str
    date: datetime.date


REVIEW_FIELDS = ("rating", "comment", "display_name", "updated_at",
                 "project__system_name", "project__slug", "project__is_public")


def _approved_reviews():
    return (
        Review.objects.filter(status=Review.Status.APPROVED)
        .select_related("project").only(*REVIEW_FIELDS).order_by("-updated_at")
    )


def _review_to_public(review: Review) -> PublicReview:
    public = review.project.is_public
    return PublicReview(
        rating=review.rating,
        comment=review.comment,
        name=review.display_name,
        system_name=review.project.system_name if public else "",
        system_url=reverse("showcase:system_detail", args=[review.project.slug]) if public else "",
        date=timezone.localdate(review.updated_at),
    )


def public_reviews(limit: int = 6) -> list:
    return [_review_to_public(review) for review in _approved_reviews()[:limit]]


def review_summary():
    """{"count", "average", "rounded"} over approved reviews, or None when there are none."""
    totals = Review.objects.filter(status=Review.Status.APPROVED).aggregate(
        count=Count("id"), average=Avg("rating"))
    if not totals["count"]:
        return None
    average = round(float(totals["average"]), 1)
    return {"count": totals["count"], "average": average, "rounded": int(average + 0.5)}


def system_review(slug: str):
    """The approved review of one public system, if it has one."""
    review = _approved_reviews().filter(project__slug=slug, project__is_public=True).first()
    return _review_to_public(review) if review else None


def tech_summary(systems) -> list:
    """Every technology across the public systems, most used first."""
    counts = {}
    for system in systems:
        for tech in system.stack:
            counts[tech] = counts.get(tech, 0) + 1
    return sorted(counts, key=lambda tech: (-counts[tech], tech.lower()))


def as_knowledge(systems) -> list:
    """Public systems as plain dicts for the AI assistant."""
    return [
        {
            "name": system.name,
            "url": system.url,
            "tagline": system.tagline,
            "stack": list(system.stack),
            "objectives": list(system.objectives),
            "purpose": system.purpose,
        }
        for system in systems
    ]
