import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Create or update the single administrator account. "
        "The account is a staff user (required to log in) and a superuser (for /admin/)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default=None)
        parser.add_argument("--password", default=None, help="Omit to be prompted securely.")
        parser.add_argument("--noinput", action="store_true", help="Fail instead of prompting.")

    def handle(self, *args, **options):
        username = options["username"]
        if not username:
            if options["noinput"]:
                raise CommandError("--username is required with --noinput.")
            username = input("Admin username: ").strip()

        if not username:
            raise CommandError("Username must not be empty.")

        password = options["password"]
        if not password:
            if options["noinput"]:
                raise CommandError("--password is required with --noinput.")
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Password (again): ")
            if password != confirm:
                raise CommandError("Passwords do not match.")

        if len(password) < 12:
            raise CommandError("Password must be at least 12 characters.")

        with transaction.atomic():
            user, created = User.objects.get_or_create(username=username)
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.set_password(password)
            user.save()

        action = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Administrator {username!r} {action}."))
