from django.contrib.auth.apps import AuthConfig


class AccountsConfig(AuthConfig):
    """Django's users and groups, under the name the Tracker's menu uses."""

    verbose_name = "Accounts"
