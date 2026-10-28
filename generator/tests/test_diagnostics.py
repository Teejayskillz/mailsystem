from django.test import TestCase

from generator.services.diagnostics import collect_checks


class DiagnosticsTests(TestCase):
    def test_offline_checks_return_statuses(self):
        checks = collect_checks(include_network=False)

        self.assertGreater(len(checks), 5)
        keys = {check.key for check in checks}
        self.assertIn("python", keys)
        self.assertIn("db_engine", keys)
        self.assertIn("address_domain", keys)

        for check in checks:
            self.assertIn(check.status, {"ok", "warn", "fail", "skip"})
            self.assertTrue(check.label)
            self.assertIsInstance(check.detail, str)

    def test_no_secret_material_in_checks(self):
        checks = collect_checks(include_network=False)
        blob = "\n".join(f"{c.label} {c.detail} {' '.join(c.evidence)}" for c in checks)

        self.assertNotIn("dummy-token", blob)
        self.assertNotIn("DJANGO_SECRET_KEY=", blob)
