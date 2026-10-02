from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from tracker.admin_search import search_view

admin.site.site_header = f"{settings.SITE_NAME} Tracker"
admin.site.site_title = f"{settings.SITE_NAME} Tracker"
admin.site.index_title = "Overview"
# The Tracker has its own sidebar (templates/admin/includes/lf_sidebar.html).
admin.site.enable_nav_sidebar = False

urlpatterns = [
    path(f"{settings.ADMIN_URL}search/", admin.site.admin_view(search_view), name="tracker_search"),
    # Django's per-app index pages duplicate the sidebar; send them to the real pages.
    path(f"{settings.ADMIN_URL}tracker/", RedirectView.as_view(pattern_name="admin:index")),
    path(f"{settings.ADMIN_URL}auth/",
         RedirectView.as_view(pattern_name="admin:auth_user_changelist")),
    path(settings.ADMIN_URL, admin.site.urls),
    path("", include("showcase.urls")),
]

if settings.DEBUG:
    # In production Nginx serves /media/ directly.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
