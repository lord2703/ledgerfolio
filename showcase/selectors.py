"""The only door between the Showcase and the Tracker's data.

Public pages never receive `Project` model objects. They get `PublicSystem`
values that are copied field by field from rows with `is_public=True`, so
client, price, payments and notes are simply not there to be shown.
"""

from dataclasses import dataclass

from django.urls import reverse

from tracker.models import Project

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
