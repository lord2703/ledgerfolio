"""Messages from the public site, and turning one into real work."""

from django.db import transaction

from tracker.models import Client, Lead, Project


def record_message(name: str, contact: str, message: str, budget: str = "",
                   deadline: str = "") -> Lead:
    """Save a message someone sent through the public message form."""
    return Lead.objects.create(
        name=name.strip(),
        contact=contact.strip(),
        system_idea=message.strip(),
        budget=budget.strip(),
        deadline=deadline.strip(),
        source=Lead.Source.WEBSITE,
    )


@transaction.atomic
def convert_lead(lead: Lead) -> Project:
    """A message that became work turns into a Client and a Project, ready to be priced."""
    if lead.status == Lead.Status.CONVERTED and lead.converted_project_id:
        return lead.converted_project

    contact_field = "email" if "@" in lead.contact and " " not in lead.contact.strip() else "other_contact"
    client = Client.objects.create(
        name=lead.name,
        notes=f"From a message on {lead.created_at:%Y-%m-%d}.",
        **{contact_field: lead.contact.strip()},
    )
    details = [lead.system_idea]
    if lead.budget:
        details.append(f"Budget mentioned: {lead.budget}")
    if lead.deadline:
        details.append(f"Deadline mentioned: {lead.deadline}")
    project = Project.objects.create(
        client=client,
        system_name=f"{lead.name}'s system"[:150],
        total_price=0,
        notes="\n".join(details),
    )
    lead.status = Lead.Status.CONVERTED
    lead.converted_project = project
    lead.save(update_fields=["status", "converted_project"])
    return project
