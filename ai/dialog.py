"""Inquiry capture: a short question-by-question conversation.

Collects name, contact, system idea, and optionally budget and deadline, then
asks for confirmation before anything is saved. The whole conversation state
is a small JSON-safe dict, so the caller can keep it in a session.
"""

import re

STEPS = ["name", "contact", "idea", "budget", "deadline", "confirm"]
OPTIONAL = {"budget", "deadline"}
LIMITS = {"name": 80, "contact": 120, "idea": 1000, "budget": 100, "deadline": 100}

CANCEL = {"cancel", "stop", "quit", "exit", "never mind", "nevermind", "forget it", "wag na",
          "huwag na"}
SKIP = {"skip", "none", "no", "n/a", "na", "not sure", "no idea", "wala", "pass", "-", "idk",
        "i dont know", "i don't know", "not yet", "no budget", "no deadline"}
YES = {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "correct", "send", "send it",
       "go", "go ahead", "confirm", "oo", "opo", "sige", "yes please", "thats right",
       "that's right", "right", "looks good"}
NO = {"no", "n", "nope", "nah", "wrong", "hindi", "dont send", "don't send", "no thanks"}

NAME_PREFIX = re.compile(
    r"^(my name is|my name's|i am|i'm|im|this is|it's|its|name is|name:|ako si|si)\s+", re.I
)
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def clean(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _plain(text: str) -> str:
    return re.sub(r"[.!?,]+$", "", text.strip().lower())


def start(owner: str):
    """Begin the flow. Returns (state, first question)."""
    state = {"step": "name", "data": {}}
    return state, (
        f"I'll take down your inquiry and pass it to {owner}. "
        "First, what's your name? (You can say \"cancel\" at any time.)"
    )


def _question(step: str, data: dict, owner: str) -> str:
    if step == "contact":
        return (
            f"Thanks, {data['name']}. How can {owner} reach you? "
            "An email, a phone number, or your Messenger name all work."
        )
    if step == "idea":
        return "What system do you have in mind? A sentence or two about what it should do is enough."
    if step == "budget":
        return "Do you have a budget in mind? This is optional: say \"skip\" to leave it blank."
    if step == "deadline":
        return "When do you need it by? Also optional: \"skip\" works here too."
    summary = [
        "Here is what I have:",
        f"• Name: {data['name']}",
        f"• Contact: {data['contact']}",
        f"• System idea: {data['idea']}",
        f"• Budget: {data.get('budget') or 'not given'}",
        f"• Deadline: {data.get('deadline') or 'not given'}",
        f"Shall I send this to {owner}? (yes / no)",
    ]
    return "\n".join(summary)


def _validate(step: str, text: str):
    """Returns (value, error message). Exactly one of them is None."""
    value = clean(text, LIMITS[step])
    if step == "name":
        value = NAME_PREFIX.sub("", value).strip(" .,!")
        if len(value) < 2 or not re.search(r"[A-Za-zÀ-ÿ]", value):
            return None, "Sorry, I didn't catch a name there. What should I call you?"
    elif step == "contact":
        digits = sum(ch.isdigit() for ch in value)
        if not (EMAIL.search(value) or digits >= 7 or len(value) >= 4):
            return None, "I need a way to reach you: an email, phone number or Messenger name."
        if "@" in value and not EMAIL.search(value):
            return None, "That email doesn't look complete. Could you type it again?"
    elif step == "idea":
        if len(value) < 10:
            return None, "Could you tell me a little more about the system? One sentence is fine."
    return value, None


def advance(state: dict, text: str, owner: str):
    """Process one answer.

    Returns (state, reply, finished_data): state is None once the flow is over,
    and finished_data is the collected inquiry when the visitor confirmed it.
    """
    step, data = state["step"], dict(state.get("data", {}))
    plain = _plain(text)

    if plain in CANCEL:
        return None, "No problem, I've cancelled that. Nothing was saved. Anything else I can help with?", None

    if step == "confirm":
        if plain in YES:
            return None, "", data
        if plain in NO:
            return None, (
                "Okay, I've discarded it and nothing was saved. "
                "If you'd like to try again, just say \"I want to inquire\"."
            ), None
        return state, "Please answer yes to send it, or no to discard it.", None

    if step in OPTIONAL and plain in SKIP:
        data[step] = ""
    else:
        value, error = _validate(step, text)
        if error:
            return state, error, None
        data[step] = value

    next_step = STEPS[STEPS.index(step) + 1]
    return {"step": next_step, "data": data}, _question(next_step, data, owner), None
