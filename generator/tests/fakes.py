"""Deterministic stand-ins for external systems.

These fakes are used only by the test suite; production code always talks to
the real cPanel UAPI and IMAP server.
"""

from __future__ import annotations

from datetime import datetime, timezone

from generator.services.cpanel import CpanelError


class FakeCpanelClient:
    is_configured = True

    def __init__(self, domains=("example.com",), fail: set[str] | None = None):
        self.domains = [d.lower() for d in domains]
        self.pops: dict[str, int] = {}
        self.forwarders: dict[str, list[str]] = {}
        self.fail = fail or set()
        self.deleted_pops: list[str] = []
        self.calls: list[str] = []

    # reads
    def list_mail_domains(self):
        self.calls.append("list_mail_domains")
        return list(self.domains)

    def list_pops(self):
        self.calls.append("list_pops")
        return [
            {"email": email, "suspended_incoming": int(suspended)}
            for email, suspended in self.pops.items()
        ]

    def list_forwarders(self, domain):
        self.calls.append("list_forwarders")
        rows = []
        for address, destinations in self.forwarders.items():
            if address.endswith("@" + domain):
                rows.extend({"dest": address, "forward": dest} for dest in destinations)
        return rows

    def mailbox_exists(self, email):
        return email.lower() in self.pops

    def is_suspended_incoming(self, email):
        return bool(self.pops.get(email.lower(), 0))

    def forwarder_targets(self, address):
        return list(self.forwarders.get(address.lower(), []))

    def forwarder_exists(self, address, destination):
        return destination.lower() in [d.lower() for d in self.forwarders.get(address.lower(), [])]

    # writes
    def add_pop(self, email, password, quota_mb=100):
        self.calls.append("add_pop")
        if "add_pop" in self.fail:
            raise CpanelError("simulated add_pop failure")
        self.pops[email.lower()] = 0

    def delete_pop(self, email):
        self.calls.append("delete_pop")
        self.pops.pop(email.lower(), None)
        self.deleted_pops.append(email)

    def add_forwarder(self, address, destination):
        self.calls.append("add_forwarder")
        if "add_forwarder" in self.fail:
            raise CpanelError("simulated add_forwarder failure")
        self.forwarders.setdefault(address.lower(), []).append(destination)

    def delete_forwarder(self, address, destination):
        self.calls.append("delete_forwarder")
        remaining = [
            d for d in self.forwarders.get(address.lower(), []) if d.lower() != destination.lower()
        ]
        self.forwarders[address.lower()] = remaining

    def suspend_incoming(self, email):
        self.calls.append("suspend_incoming")
        if email.lower() in self.pops:
            self.pops[email.lower()] = 1

    def unsuspend_incoming(self, email):
        self.calls.append("unsuspend_incoming")
        if email.lower() in self.pops:
            self.pops[email.lower()] = 0


class FakeImapService:
    def __init__(self, messages=None, uidvalidity=1, fail=False):
        self.messages = messages or []
        self.uidvalidity = uidvalidity
        self.fail = fail
        self.calls: list[str] = []

    def verify(self, address):
        self.calls.append("verify")
        if self.fail:
            raise RuntimeError("simulated imap failure")

    def fetch_new(self, address, limit=None):
        self.calls.append("fetch_new")
        if self.fail:
            from generator.services.imap import ImapError

            raise ImapError("simulated imap failure")
        return {"uidvalidity": self.uidvalidity, "reset": False, "messages": list(self.messages)}

    def fetch_message(self, address, uid):
        self.calls.append("fetch_message")
        return {
            "uid": uid,
            "subject": "Test",
            "from": "sender@example.net",
            "to": address.address,
            "date": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "html": "<p>Hello</p>",
            "text": "Hello",
            "message_id": "<test@example.net>",
        }


def envelope(uid: int, sender: str = "sender@example.net", subject: str = "Your code") -> dict:
    return {
        "uid": uid,
        "message_id": f"<{uid}@example.net>",
        "from_addr": sender,
        "from_name": "Sender",
        "subject": subject,
        "sent_at": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        "is_read": False,
    }
