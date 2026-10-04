from django.urls import path

from . import views

app_name = "showcase"

urlpatterns = [
    path("", views.home, name="home"),
    path("systems/", views.system_list, name="system_list"),
    path("systems/<slug:slug>/", views.system_detail, name="system_detail"),
    path("ledger/", views.ledger_page, name="ledger"),
    path("contact/", views.contact, name="contact"),
    path("verify/", views.verify_lookup, name="verify_lookup"),
    path("verify/<str:public_token>/", views.verify, name="verify"),
    path("api/chat/", views.ChatView.as_view(), name="chat"),
]
