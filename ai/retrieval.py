"""Retrieval: find which public system or technology a message is about.

The knowledge base is built from plain dicts of PUBLIC project fields only.
Private data (clients, prices, payments, notes) is never passed in, so the
assistant cannot reveal it even by mistake.
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .tokenizer import tokenize

# Words too common in system names to identify one system on their own.
GENERIC = {
    "a", "an", "and", "app", "application", "based", "for", "in", "information", "management",
    "mobile", "my", "of", "on", "online", "our", "platform", "portal", "system", "the", "to",
    "web", "website", "with",
}
MIN_TECH_LENGTH = 3
FUZZY_THRESHOLD = 0.86


@dataclass
class PublicProject:
    name: str
    url: str = ""
    tagline: str = ""
    stack: list = field(default_factory=list)
    objectives: list = field(default_factory=list)
    purpose: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "PublicProject":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class Match:
    masked: str  # the message with names replaced by <project> / <tech>
    projects: list
    techs: list


def _similar(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 5:
        return False
    return SequenceMatcher(None, a, b).ratio() >= FUZZY_THRESHOLD


class KnowledgeBase:
    def __init__(self, projects):
        self.projects = [
            p if isinstance(p, PublicProject) else PublicProject.from_dict(p) for p in projects
        ]
        self._name_tokens = {}
        owners = {}
        for project in self.projects:
            tokens = tokenize(project.name)
            distinctive = [t for t in tokens if t not in GENERIC] or tokens
            self._name_tokens[project.name] = distinctive
            for token in set(distinctive):
                owners.setdefault(token, set()).add(project.name)
        # Tokens that appear in exactly one system's name identify it alone.
        self._unique = {token for token, names in owners.items() if len(names) == 1}

        self._techs = {}
        for project in self.projects:
            for tech in project.stack:
                tokens = tuple(tokenize(tech))
                if tokens and len("".join(tokens)) >= MIN_TECH_LENGTH:
                    self._techs.setdefault(tokens, tech)

    # --- lookups -------------------------------------------------------

    def by_name(self, name: str):
        for project in self.projects:
            if project.name == name:
                return project
        return None

    def projects_using(self, tech: str):
        wanted = tuple(tokenize(tech))
        return [
            project for project in self.projects
            if any(tuple(tokenize(item)) == wanted for item in project.stack)
        ]

    def all_techs(self):
        """Every technology across public systems, most used first."""
        counts = {}
        for project in self.projects:
            for tech in project.stack:
                counts[tech] = counts.get(tech, 0) + 1
        return sorted(counts, key=lambda tech: (-counts[tech], tech.lower()))

    # --- matching ------------------------------------------------------

    def analyse(self, text: str) -> Match:
        words = tokenize(text)
        projects = []

        for project in self.projects:
            distinctive = self._name_tokens[project.name]
            hits = {}
            for token in distinctive:
                for position, word in enumerate(words):
                    if _similar(word, token):
                        hits[token] = position
                        break
            if not hits:
                continue
            complete = len(hits) == len(set(distinctive))
            identifying = any(token in self._unique and len(token) >= 4 for token in hits)
            if complete or identifying:
                projects.append(project)
                first = min(hits.values())
                words = [
                    "<project>" if i == first else word
                    for i, word in enumerate(words)
                    if i == first or i not in hits.values()
                ]

        techs = []
        for tokens, tech in sorted(self._techs.items(), key=lambda item: -len(item[0])):
            size = len(tokens)
            for start in range(len(words) - size + 1):
                if tuple(words[start:start + size]) == tokens:
                    techs.append(tech)
                    words[start:start + size] = ["<tech>"]
                    break

        return Match(masked=" ".join(words), projects=projects, techs=techs)
