from django.core.management.base import BaseCommand

from generator.services.sync import SyncService


class Command(BaseCommand):
    help = "Synchronise mailboxes (designed for a cPanel cron job)."

    def add_arguments(self, parser):
        parser.add_argument("--address", default=None, help="Sync one address instead of a batch.")
        parser.add_argument("--limit", type=int, default=None, help="How many addresses to sync.")

    def handle(self, *args, **options):
        from generator.models import Address

        service = SyncService()

        if options["address"]:
            address = Address.objects.filter(address=options["address"]).first()
            if address is None:
                self.stderr.write(self.style.ERROR("Address not found."))
                raise SystemExit(1)
            results = [service.sync_address(address)]
        else:
            results = service.sync_batch(limit=options["limit"])

        for result in results:
            self.stdout.write(str(result))

        if any(r.get("status") == "error" for r in results):
            raise SystemExit(1)
