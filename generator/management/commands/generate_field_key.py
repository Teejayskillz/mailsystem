from django.core.management.base import BaseCommand

from generator.services.crypto import generate_field_key


class Command(BaseCommand):
    help = "Print a new MAILGEN_FIELD_KEY (url-safe base64, 32 bytes)."

    def handle(self, *args, **options):
        self.stdout.write(generate_field_key())
