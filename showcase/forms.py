"""The two forms visitors fill in: a message to the owner, and a client review."""

import re

from django import forms

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _one_line(value: str) -> str:
    return " ".join(value.split())


class ContactForm(forms.Form):
    name = forms.CharField(label="Your name", min_length=2, max_length=150,
                           widget=forms.TextInput(attrs={"autocomplete": "name"}))
    contact = forms.CharField(
        label="How can I reach you?", min_length=4, max_length=200,
        help_text="An email address, phone number or Messenger name.",
        widget=forms.TextInput(attrs={"autocomplete": "email"}),
    )
    message = forms.CharField(
        label="What do you need?", min_length=10, max_length=2000,
        help_text="Describe the system you have in mind, or ask me anything.",
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    budget = forms.CharField(label="Budget", max_length=120, required=False,
                             help_text="For example: around ₱15,000.")
    deadline = forms.CharField(label="Deadline", max_length=120, required=False,
                               help_text="For example: before the end of March.")
    # Hidden from people; bots that fill every field are quietly ignored.
    website = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"tabindex": "-1", "autocomplete": "off"}))

    def clean_name(self):
        return _one_line(self.cleaned_data["name"])

    def clean_contact(self):
        value = _one_line(self.cleaned_data["contact"])
        if "@" in value and not EMAIL.search(value):
            raise forms.ValidationError("That email address looks incomplete.")
        return value


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(
        label="Your rating", coerce=int, choices=[(n, n) for n in range(5, 0, -1)],
        error_messages={"required": "Choose from 1 to 5 stars."},
    )
    comment = forms.CharField(
        label="Your review", min_length=10, max_length=1000,
        help_text="How was working with me, and what does the system do for you?",
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    display_name = forms.CharField(
        label="Name to show", max_length=80, required=False,
        help_text="For example \"Ana, BSIT student\". Leave it empty to appear as a verified client.",
    )

    def clean_display_name(self):
        return _one_line(self.cleaned_data["display_name"])
