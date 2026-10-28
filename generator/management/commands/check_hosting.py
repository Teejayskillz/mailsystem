from django.core.management.base import BaseCommand

from generator.services.diagnostics import collect_checks


class Command(BaseCommand):
    help = "Run read-only hosting/integration diagnostics and print the result."

    def add_arguments(self, parser):
        parser.add_argument(
            "--offline",
            action="store_true",
            help="Skip checks that contact cPanel, DNS or IMAP.",
        )

    def handle(self, *args, **options):
        checks = collect_checks(include_network=not options["offline"])

        width = max(len(c.label) for c in checks) if checks else 10
        failures = 0

        for check in checks:
            marker = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}.get(
                check.status, check.status.upper()
            )
            if check.status == "fail":
                failures += 1
            self.stdout.write(f"[{marker}] {check.label.ljust(width)}  {check.detail}")
            for item in check.evidence:
                self.stdout.write(f"        - {item}")

        if failures:
            self.stderr.write(self.style.ERROR(f"\n{failures} check(s) failed."))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("\nAll executed checks passed."))
