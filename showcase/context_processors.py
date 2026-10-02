from django.conf import settings


def site(request):
    """Public site identity, available in every template."""
    return {
        "site_name": settings.SITE_NAME,
        "owner_name": settings.OWNER_NAME,
        "owner_title": settings.OWNER_TITLE,
        "owner_email": settings.OWNER_EMAIL,
        "owner_location": settings.OWNER_LOCATION,
    }
