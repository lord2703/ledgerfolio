from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = f"{settings.SITE_NAME} Tracker"
admin.site.site_title = f"{settings.SITE_NAME} Tracker"
admin.site.index_title = "Overview"

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("", include("showcase.urls")),
]

if settings.DEBUG:
    # In production Nginx serves /media/ directly.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
