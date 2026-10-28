"""cPanel UAPI client tests: response shapes, error detail, secret hygiene.

s44.srvx.ws returns a *flat* UAPI envelope without the usual "result" wrapper;
these tests pin support for both shapes.
"""

import json
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from generator.services.cpanel import CpanelClient, CpanelError

TOKEN = "test-token-value"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, content_type="application/json"):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.headers = {"Content-Type": content_type}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def make_client():
    return CpanelClient(
        base_url="https://s44.example.com:2083",
        user="cpuser",
        token=TOKEN,
        timeout=5,
        verify_tls=True,
    )


def with_response(client, response):
    client._session.get = MagicMock(return_value=response)
    return client._session.get


class EnvelopeTests(SimpleTestCase):
    def test_flat_envelope_is_accepted(self):
        client = make_client()
        payload = {
            "status": 1,
            "data": [{"domain": "mailsystem.nzdworld.com"}],
            "errors": None,
            "messages": None,
            "warnings": None,
            "metadata": {"transformed": 1},
        }
        with_response(client, FakeResponse(payload=payload))

        self.assertEqual(
            client.list_mail_domains(),
            ["mailsystem.nzdworld.com"],
        )

    def test_wrapped_envelope_is_accepted(self):
        client = make_client()
        payload = {
            "apiversion": 3,
            "module": "Email",
            "func": "list_mail_domains",
            "result": {"status": 1, "data": [{"domain": "example.com"}], "errors": None},
        }
        with_response(client, FakeResponse(payload=payload))

        self.assertEqual(client.list_mail_domains(), ["example.com"])

    def test_flat_envelope_list_pops(self):
        client = make_client()
        payload = {
            "status": 1,
            "data": [{"email": "a@example.com", "suspended_incoming": 0}],
            "errors": None,
        }
        with_response(client, FakeResponse(payload=payload))

        self.assertEqual(len(client.list_pops()), 1)


class ErrorDetailTests(SimpleTestCase):
    def test_flat_error_reports_cpanel_message(self):
        client = make_client()
        payload = {
            "status": 0,
            "data": None,
            "errors": ["The Email module is not available for this account."],
            "messages": None,
        }
        with_response(client, FakeResponse(payload=payload))

        with self.assertRaises(CpanelError) as ctx:
            client.list_mail_domains()

        message = str(ctx.exception)
        self.assertIn("Email::list_mail_domains", message)
        self.assertIn("The Email module is not available", message)

    def test_missing_error_text_never_becomes_unknown_error(self):
        client = make_client()
        payload = {"status": 0, "data": None, "errors": None, "messages": None, "warnings": None}
        with_response(client, FakeResponse(payload=payload))

        with self.assertRaises(CpanelError) as ctx:
            client.list_mail_domains()

        message = str(ctx.exception)
        self.assertIn("status=0", message)
        self.assertIn("no error text", message)
        self.assertIn("Receive Mail", message)
        self.assertNotIn("unknown error", message.lower())

    def test_warnings_are_included(self):
        client = make_client()
        payload = {"status": 0, "data": None, "errors": None, "warnings": ["MailReceive role disabled"]}
        with_response(client, FakeResponse(payload=payload))

        with self.assertRaisesMessage(CpanelError, "MailReceive role disabled"):
            client.list_mail_domains()

    def test_html_login_page_is_reported_clearly(self):
        client = make_client()
        response = FakeResponse(
            status_code=200,
            payload=None,
            text="<html><body>cPanel Login</body></html>",
            content_type="text/html; charset=UTF-8",
        )
        with_response(client, response)

        with self.assertRaises(CpanelError) as ctx:
            client.list_mail_domains()

        message = str(ctx.exception)
        self.assertIn("non-JSON", message)
        self.assertIn("text/html", message)
        self.assertIn("API token was rejected", message)

    def test_http_401(self):
        client = make_client()
        with_response(client, FakeResponse(status_code=401, payload=None, text=""))

        with self.assertRaisesMessage(CpanelError, "rejected the API token"):
            client.list_mail_domains()

    def test_http_500(self):
        client = make_client()
        with_response(client, FakeResponse(status_code=500, payload=None, text=""))

        with self.assertRaisesMessage(CpanelError, "HTTP 500"):
            client.list_mail_domains()


class TransportTests(SimpleTestCase):
    def test_url_header_and_tls_verification(self):
        client = make_client()
        get = with_response(
            client,
            FakeResponse(payload={"status": 1, "data": [], "errors": None}),
        )

        client.list_mail_domains()

        args, kwargs = get.call_args
        self.assertEqual(args[0], "https://s44.example.com:2083/execute/Email/list_mail_domains")
        self.assertEqual(kwargs["headers"]["Authorization"], f"cpanel cpuser:{TOKEN}")
        self.assertTrue(kwargs["verify"])
        self.assertEqual(client._session.headers["Accept"], "application/json")

    def test_token_never_appears_in_errors_or_logs(self):
        client = make_client()
        payload = {"status": 0, "data": None, "errors": ["nope"]}
        with_response(client, FakeResponse(payload=payload))

        with self.assertLogs("mailgen", level="DEBUG") as captured:
            with self.assertRaises(CpanelError) as ctx:
                client.list_mail_domains()

        blob = "\n".join(captured.output) + str(ctx.exception)
        self.assertNotIn(TOKEN, blob)

    def test_not_configured(self):
        client = CpanelClient(base_url="", user="", token="")

        with self.assertRaisesMessage(CpanelError, "not configured"):
            client.list_pops()
