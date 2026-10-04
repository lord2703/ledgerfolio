"""The Portfolio Assistant: turns a visitor's message into a reply.

    message -> retrieval (which system / technology?) -> intent classifier
            -> answer filled from the live public project list or a template

If the classifier is unsure it says so, logs the question so the dataset can
grow, and points the visitor to the owner instead of guessing. Inquiries are
never taken in the chat: the owner answers them personally, so the assistant
hands the visitor a link to the site's message form.
"""

import re
from dataclasses import dataclass, field

from .inference import IntentModel
from .retrieval import KnowledgeBase

MAX_MESSAGE_LENGTH = 500


def clean(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


@dataclass
class Owner:
    name: str = "the developer"
    title: str = "Freelance Systems Developer"
    location: str = ""
    email: str = ""
    phone: str = ""
    site_name: str = "Ledgerfolio"
    contact_url: str = "/contact/"  # the site's message form


@dataclass
class Reply:
    text: str
    state: dict
    intent: str = ""
    confidence: float = 0.0
    suggestions: list = field(default_factory=list)
    links: list = field(default_factory=list)  # [{"label": ..., "url": ...}]


DEFAULT_SUGGESTIONS = ["What systems have you built?", "How does working with you go?",
                       "How do I verify a receipt?", "I want a system built"]

STATUS_MEANINGS = {
    "in development": "In development: the system is being built.",
    "pre oral": "Ready for pre-oral: the system is complete enough to present at your "
                "pre-oral defense.",
    "final": "Ready for final: revisions are done and the system is ready for the final defense.",
    "fully paid": "Fully paid: the whole price has been settled and the project is closed out.",
}


def _listing(items, limit=6):
    items = list(items)
    shown = items[:limit]
    text = ", ".join(shown)
    return f"{text}, and {len(items) - limit} more" if len(items) > limit else text


class Assistant:
    def __init__(self, model: IntentModel | None, knowledge: KnowledgeBase, owner: Owner,
                 log_unanswered=None, threshold: float = 0.55):
        self.model = model
        self.kb = knowledge
        self.owner = owner
        self.log_unanswered = log_unanswered
        self.threshold = threshold

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def reply(self, message: str, state: dict | None = None) -> Reply:
        state = dict(state or {})
        state.pop("lead", None)  # left over from conversations before the message form
        message = clean(message or "", MAX_MESSAGE_LENGTH)
        if not message:
            return Reply("Type a question and I'll do my best to help.", state,
                         suggestions=DEFAULT_SUGGESTIONS)

        offered = state.pop("offer", None)
        if self.model is None:
            return self._unsure(message, state, intent="", confidence=0.0, reason=(
                "My language model hasn't been trained on this server yet, so I can't answer "
                "questions right now."
            ))

        match = self.kb.analyse(message)
        prediction = self.model.predict(match.masked)
        intent, confidence = prediction.intent, prediction.confidence

        if offered == "contact" and intent == "affirm" and confidence >= self.threshold:
            return self._send_to_owner(state, intent, confidence)

        if confidence < self.threshold:
            return self._unsure(message, state, intent, confidence)

        handler = getattr(self, f"_on_{intent}", self._on_out_of_scope)
        reply = handler(match, state)
        reply.intent, reply.confidence = intent, confidence
        return reply

    # ------------------------------------------------------------------
    # Unsure, and handing over to the owner
    # ------------------------------------------------------------------

    def _unsure(self, message, state, intent, confidence, reason=None) -> Reply:
        if self.log_unanswered:
            self.log_unanswered(message, intent, confidence)
        state["offer"] = "contact"
        text = reason or "I'm not sure I understood that, and I'd rather not guess."
        return Reply(
            f"{text} I can tell you about the systems {self.owner.name} has built and how projects "
            f"and receipts work. For anything else, send {self.owner.name} a message and you'll "
            "get a personal reply.",
            state, intent=intent, confidence=confidence, links=self._message_link(),
            suggestions=["What systems have you built?", "How does working with you go?"],
        )

    def _send_to_owner(self, state, intent="make_inquiry", confidence=1.0) -> Reply:
        owner = self.owner.name
        return Reply(
            f"{owner} answers every inquiry personally, so I'll pass you over. Use the button "
            f"below to send {owner} a message: your name, how to reach you, and a sentence or two "
            f"about the system you need. {owner} will reply to you directly.",
            state, intent=intent, confidence=confidence, links=self._message_link(),
            suggestions=["How does working with you go?", "What systems have you built?"],
        )

    def _message_link(self):
        return [{"label": f"Send {self.owner.name} a message", "url": self.owner.contact_url}]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _project(self, match, state):
        """The system being discussed: named now, or the one from earlier."""
        if match.projects:
            state["last_project"] = match.projects[0].name
            return match.projects[0]
        return self.kb.by_name(state.get("last_project", ""))

    def _which_project(self, state, about: str) -> Reply:
        if not self.kb.projects:
            return self._no_projects(state)
        names = [project.name for project in self.kb.projects]
        return Reply(
            f"Which system would you like the {about} of? There's {_listing(names)}.",
            state, suggestions=[f"{about.capitalize()} of {name}" for name in names[:3]],
        )

    def _no_projects(self, state) -> Reply:
        return Reply(
            f"{self.owner.name} hasn't published any systems here yet. Check back soon, or send "
            f"{self.owner.name} a message if you'd like a system built.",
            state, links=self._message_link(),
        )

    @staticmethod
    def _link(project):
        return [{"label": f"Open {project.name}", "url": project.url}] if project.url else []

    # ------------------------------------------------------------------
    # Small talk
    # ------------------------------------------------------------------

    def _on_greeting(self, match, state) -> Reply:
        return Reply(
            f"Hello! I'm the Portfolio Assistant for {self.owner.name}. Ask me about the systems "
            "on this site, how a project goes, how receipts are verified, or tell me if you'd "
            "like a system built.",
            state, suggestions=DEFAULT_SUGGESTIONS,
        )

    def _on_goodbye(self, match, state) -> Reply:
        return Reply("Goodbye, and thanks for stopping by!", state)

    def _on_thanks(self, match, state) -> Reply:
        return Reply("You're welcome! Is there anything else you'd like to know?", state)

    def _on_affirm(self, match, state) -> Reply:
        return Reply("Great. What would you like to know?", state, suggestions=DEFAULT_SUGGESTIONS)

    def _on_deny(self, match, state) -> Reply:
        return Reply("No problem. I'm here if you need anything.", state)

    def _on_ask_capabilities(self, match, state) -> Reply:
        return Reply(
            f"I'm the Portfolio Assistant, a small chatbot {self.owner.name} built and trained "
            f"from scratch for this site. I can:\n"
            f"• tell you about the systems {self.owner.name} has built: what they are, their "
            "tech stack, objectives and purpose\n"
            "• explain how a project goes and what each status means\n"
            "• explain how receipts and blockchain verification work\n"
            f"• point you to the message form, so you can write to {self.owner.name} directly",
            state, suggestions=DEFAULT_SUGGESTIONS,
        )

    def _on_ask_owner(self, match, state) -> Reply:
        owner = self.owner
        where = f" based in {owner.location}" if owner.location else ""
        count = len(self.kb.projects)
        work = (
            f" {count} of the systems built so far {'is' if count == 1 else 'are'} on display here."
            if count else ""
        )
        return Reply(
            f"{owner.name} is a {owner.title.lower()}{where}, working solo: the same person "
            f"plans, builds and delivers your system.{work}",
            state, suggestions=["What systems have you built?", "How can I contact you?"],
        )

    # ------------------------------------------------------------------
    # Systems
    # ------------------------------------------------------------------

    def _on_ask_how_many(self, match, state) -> Reply:
        count = len(self.kb.projects)
        if not count:
            return self._no_projects(state)
        names = _listing(project.name for project in self.kb.projects)
        noun = "system" if count == 1 else "systems"
        return Reply(
            f"There {'is' if count == 1 else 'are'} {count} {noun} on display here: {names}.",
            state, suggestions=["What tech stack do you use?", "Show me your systems"],
        )

    def _on_ask_projects(self, match, state) -> Reply:
        if not self.kb.projects:
            return self._no_projects(state)
        lines = [
            f"• {project.name}" + (f": {project.tagline}" if project.tagline else "")
            for project in self.kb.projects[:8]
        ]
        return Reply(
            f"Here are the systems {self.owner.name} has on display:\n" + "\n".join(lines)
            + "\nAsk me about any of them.",
            state,
            suggestions=[f"Tell me about {p.name}" for p in self.kb.projects[:3]],
            links=[{"label": project.name, "url": project.url}
                   for project in self.kb.projects[:8] if project.url],
        )

    def _on_ask_project_info(self, match, state) -> Reply:
        project = self._project(match, state)
        if project is None:
            return self._on_ask_projects(match, state)
        parts = [project.name + (f": {project.tagline}" if project.tagline else "")]
        if project.purpose:
            parts.append(project.purpose)
        if project.stack:
            parts.append(f"Built with {_listing(project.stack, 8)}.")
        return Reply(
            "\n".join(parts), state, links=self._link(project),
            suggestions=[f"Objectives of {project.name}", f"Purpose of {project.name}"],
        )

    def _on_ask_stack(self, match, state) -> Reply:
        if match.techs:
            tech = match.techs[0]
            users = self.kb.projects_using(tech)
            names = _listing(project.name for project in users)
            noun = "system uses" if len(users) == 1 else "systems use"
            return Reply(
                f"Yes, {len(users)} {noun} {tech}: {names}.", state,
                links=[link for project in users[:4] for link in self._link(project)],
            )
        # "what stack did it use?" refers back to the system discussed earlier;
        # a bare "what stack do you use?" is about all of them.
        refers_back = {"it", "its", "that", "this"} & set(match.masked.split())
        project = self._project(match, state) if match.projects or refers_back else None
        if project is not None:
            if not project.stack:
                return Reply(f"The tech stack for {project.name} isn't listed yet.", state)
            return Reply(
                f"{project.name} was built with {_listing(project.stack, 10)}.", state,
                links=self._link(project), suggestions=[f"Objectives of {project.name}"],
            )
        techs = self.kb.all_techs()
        if not techs:
            return self._no_projects(state)
        return Reply(
            f"Across the systems on display, {self.owner.name} has worked with "
            f"{_listing(techs, 12)}. Ask about a specific system to see its exact stack.",
            state, suggestions=[f"What stack did {p.name} use?" for p in self.kb.projects[:2]],
        )

    def _on_ask_objectives(self, match, state) -> Reply:
        project = self._project(match, state)
        if project is None:
            return self._which_project(state, "objectives")
        if not project.objectives:
            return Reply(f"The objectives for {project.name} aren't listed yet.", state,
                         links=self._link(project))
        lines = "\n".join(f"• {objective}" for objective in project.objectives[:8])
        return Reply(f"The objectives of {project.name}:\n{lines}", state,
                     links=self._link(project), suggestions=[f"Purpose of {project.name}"])

    def _on_ask_purpose(self, match, state) -> Reply:
        project = self._project(match, state)
        if project is None:
            return self._which_project(state, "purpose")
        if not project.purpose:
            return Reply(f"The purpose of {project.name} isn't written up yet.", state,
                         links=self._link(project))
        return Reply(f"{project.name}: {project.purpose}", state, links=self._link(project),
                     suggestions=[f"What stack did {project.name} use?"])

    # ------------------------------------------------------------------
    # Working together
    # ------------------------------------------------------------------

    def _on_ask_process(self, match, state) -> Reply:
        owner = self.owner.name
        return Reply(
            "Here is how a project goes:\n"
            f"1. Inquiry: you send {owner} a message about the system you need.\n"
            f"2. Quotation: {owner} reviews it and gives you a price and timeline.\n"
            "3. In development: the system is built.\n"
            "4. Ready for pre-oral: it is complete enough to present at your pre-oral defense.\n"
            "5. Ready for final: revisions are done and it is ready for the final defense.\n"
            "6. Fully paid: the whole price is settled and the project is closed out.\n"
            "Every payment along the way gets a PDF receipt that you can verify online.",
            state, suggestions=["How do receipts work?", "I want a system built"],
        )

    def _on_ask_status_meaning(self, match, state) -> Reply:
        asked = [text for key, text in STATUS_MEANINGS.items() if key in match.masked]
        lines = asked or list(STATUS_MEANINGS.values())
        intro = "" if asked else "A project moves through these statuses:\n"
        return Reply(intro + "\n".join(f"• {line}" for line in lines), state,
                     suggestions=["How does working with you go?"])

    def _on_ask_receipt(self, match, state) -> Reply:
        return Reply(
            f"Yes. For every payment, {self.owner.name} issues a PDF receipt and emails it to "
            "you. It shows the receipt number, date, system name, amount paid and remaining "
            "balance, plus a QR code. Scanning the QR code opens a page that checks the receipt "
            "against the blockchain and tells you whether it is valid.",
            state, suggestions=["How do I verify a receipt?"],
        )

    def _on_ask_verify(self, match, state) -> Reply:
        return Reply(
            "Scan the QR code on your receipt or open its verify link. The site recomputes the "
            "receipt's SHA-256 fingerprint and looks for it on the "
            f"{self.owner.site_name} blockchain, where it was recorded as a transaction signed "
            f"with {self.owner.name}'s private key. If the receipt was edited, the signature is "
            "wrong, or the chain was changed, the page says \"tampered\"; otherwise \"valid\".\n"
            f"One honest note: {self.owner.name} currently runs all the nodes, so the chain is "
            "tamper-evident but not decentralized yet.",
            state, links=[{"label": "Verify a receipt", "url": "/verify/"},
                          {"label": "See the ledger", "url": "/ledger/"}],
        )

    def _on_ask_pricing(self, match, state) -> Reply:
        return Reply(
            "The price depends on what the system needs to do, so there's no fixed price list. "
            f"{self.owner.name} gives each project its own quotation, payments can be made in "
            "parts, and every payment gets a verifiable receipt. To get a quotation, send "
            f"{self.owner.name} a message about what you need.",
            state, links=self._message_link(), suggestions=["How does working with you go?"],
        )

    def _on_ask_timeline(self, match, state) -> Reply:
        return Reply(
            "It depends on the size of the system and your deadline, so "
            f"{self.owner.name} confirms the timeline per project. Send {self.owner.name} a "
            "message with what you need and when you need it.",
            state, links=self._message_link(),
        )

    def _on_ask_contact(self, match, state) -> Reply:
        owner = self.owner
        ways = [f"email {owner.email}" if owner.email else "", f"call or text {owner.phone}"
                if owner.phone else ""]
        ways = [way for way in ways if way]
        also = f"You can also {' or '.join(ways)}. " if ways else ""
        return Reply(
            f"The easiest way is the message form on this site: it goes straight to {owner.name}, "
            f"who replies personally. {also}".strip(),
            state, links=self._message_link(),
        )

    def _on_make_inquiry(self, match, state) -> Reply:
        return self._send_to_owner(state)

    # ------------------------------------------------------------------
    # Boundaries
    # ------------------------------------------------------------------

    def _on_private_data(self, match, state) -> Reply:
        return Reply(
            "Sorry, I can't help with that. Client names, prices and payment records are "
            "private, and I don't have access to them. I can tell you about the public systems, "
            "the process, or how receipt verification works.",
            state, suggestions=["What systems have you built?", "How do I verify a receipt?"],
        )

    def _on_out_of_scope(self, match, state) -> Reply:
        return Reply(
            f"That's outside what I can help with. I only know about {self.owner.name}'s "
            f"systems and how projects and receipts work. To ask {self.owner.name} directly, "
            "send a message.",
            state, suggestions=DEFAULT_SUGGESTIONS, links=self._message_link(),
        )
