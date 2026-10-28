from django.apps import AppConfig


class GeneratorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "generator"
    verbose_name = "Email generator"

    def ready(self):
        # Register system checks (field key, cPanel/IMAP configuration).
        from . import checks  # noqa: F401
