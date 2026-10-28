from __future__ import annotations

import logging

from django.conf import settings
from django.contrib import messages as flash
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import GenerateForm, LoginForm
from .models import Address, Message
from .services.addresses import ProvisioningError, ProvisioningService
from .services.cpanel import CpanelError
from .services.diagnostics import FAIL, OK, WARN, collect_checks
from .services.imap import ImapError, ImapService
from .services.sanitizer import document_from_html, document_from_text, sanitize_email_html
from .services.security import RateLimiter, client_ip
from .services.sync import SyncService

logger = logging.getLogger("mailgen")

ADDRESS_ACTIONS = {"enable", "disable", "delete", "confirm-forward"}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = LoginForm(request.POST or None)
    status = 200

    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        password = form.cleaned_data["password"]
        ip = client_ip(request)

        max_attempts = int(getattr(settings, "MAILGEN_LOGIN_MAX_ATTEMPTS", 5))
        window = int(getattr(settings, "MAILGEN_LOGIN_WINDOW_SECONDS", 900))

        allowed_ip, retry_ip = RateLimiter.hit("login_ip", ip, max_attempts * 4, window)
        allowed_user, retry_user = RateLimiter.hit(
            "login_user", f"{ip}:{username.lower()}", max_attempts, window
        )

        if not allowed_ip or not allowed_user:
            retry_after = max(retry_ip, retry_user)
            status = 429
            form.add_error(
                None,
                f"Too many failed attempts. Try again in about {max(1, retry_after // 60)} minute(s).",
            )
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None and user.is_active and user.is_staff:
                login(request, user)
                request.session["_last_seen"] = int(timezone.now().timestamp())
                RateLimiter.record_login(ip, username, True)
                logger.info("login succeeded", extra={"user": username, "ip": ip})
                next_url = request.GET.get("next") or request.POST.get("next") or ""
                if next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect("dashboard")

            RateLimiter.record_login(ip, username, False)
            logger.warning("login failed", extra={"user": username, "ip": ip})
            form.add_error(None, "Invalid credentials.")

    return render(request, "generator/login.html", {"form": form}, status=status)


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


def csrf_failure(request, reason=""):
    return render(
        request,
        "generator/error.html",
        {
            "title": "Request rejected",
            "status": "403",
            "message": "The form security token was missing or invalid. Reload the page and try again.",
        },
        status=403,
    )


def error_404(request, exception=None):
    return render(
        request,
        "generator/error.html",
        {"title": "Not found", "status": "404", "message": "That page does not exist."},
        status=404,
    )


def error_500(request):
    return render(
        request,
        "generator/error.html",
        {
            "title": "Server error",
            "status": "500",
            "message": "The request could not be completed. The error has been logged.",
        },
        status=500,
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
@require_GET
def dashboard(request):
    addresses = (
        Address.objects.live()
        .annotate(unread=Count("messages", filter=Q(messages__is_read=False)))
        .order_by("-created_at")
    )
    address_list = list(addresses)

    recent_messages = Message.objects.select_related("address").order_by("-sent_at", "-id")[:15]

    stats = {
        "total": len(address_list),
        "configured": sum(1 for a in address_list if a.is_configured),
        "inbox_capable": sum(1 for a in address_list if a.is_inbox_capable),
        "delivery_tested": sum(1 for a in address_list if a.is_delivery_tested),
        "limit": int(getattr(settings, "MAILGEN_MAX_ADDRESSES", 10)),
    }

    return render(
        request,
        "generator/dashboard.html",
        {
            "addresses": address_list,
            "recent_messages": recent_messages,
            "stats": stats,
            "generate_form": GenerateForm(),
            "address_domain": getattr(settings, "MAILGEN_ADDRESS_DOMAIN", ""),
            "forward_to": getattr(settings, "MAILGEN_FORWARD_TO", ""),
        },
    )


@login_required
@require_POST
def generate_address(request):
    allowed, retry_after = RateLimiter.hit("generate", str(request.user.pk), 10, 3600)
    if not allowed:
        flash.error(request, f"Address generation is rate limited. Try again in {retry_after}s.")
        return redirect("dashboard")

    form = GenerateForm(request.POST)
    if not form.is_valid():
        flash.error(request, "Invalid label.")
        return redirect("dashboard")

    try:
        address = ProvisioningService().create(label=form.cleaned_data.get("label", ""))
    except ProvisioningError as exc:
        flash.error(request, str(exc))
        return redirect("dashboard")
    except CpanelError as exc:  # defensive: services normally wrap this
        logger.exception("unexpected cPanel error during provisioning")
        flash.error(request, str(exc))
        return redirect("dashboard")

    flash.success(request, f"Created {address.address}. Verify it with a real test message.")
    return redirect("address_detail", pk=address.pk)


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
@login_required
@require_GET
def address_detail(request, pk: int):
    address = get_object_or_404(Address.objects.live(), pk=pk)

    queryset = address.messages.order_by("-sent_at", "-id")
    query = (request.GET.get("q") or "").strip()
    if query:
        queryset = queryset.filter(Q(subject__icontains=query) | Q(from_addr__icontains=query))

    paginator = Paginator(queryset, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "generator/address_detail.html",
        {
            "address": address,
            "page": page,
            "query": query,
            "has_messages": queryset.exists(),
        },
    )


@login_required
@require_POST
def address_action(request, pk: int, action: str):
    if action not in ADDRESS_ACTIONS:
        return redirect("dashboard")

    address = get_object_or_404(Address.objects.live(), pk=pk)
    service = ProvisioningService()

    try:
        if action == "disable":
            service.disable(address)
            flash.success(request, f"{address.address} disabled: forwarding removed, incoming mail suspended.")
        elif action == "enable":
            service.enable(address)
            flash.success(request, f"{address.address} re-enabled and forwarding restored.")
        elif action == "delete":
            service.delete(address)
            flash.success(request, f"{address.address} deleted from cPanel.")
            return redirect("dashboard")
        elif action == "confirm-forward":
            address.forward_confirmed_at = timezone.now()
            address.save(update_fields=["forward_confirmed_at", "updated_at"])
            flash.success(request, "Marked as confirmed in your primary inbox.")
    except ProvisioningError as exc:
        flash.error(request, str(exc))
    except CpanelError as exc:
        logger.exception("cPanel error during address action")
        flash.error(request, str(exc))

    return redirect("address_detail", pk=address.pk)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
@login_required
@require_GET
def message_detail(request, pk: int):
    message = get_object_or_404(
        Message.objects.select_related("address"),
        pk=pk,
        address__status__in=[Address.Status.ACTIVE, Address.Status.DISABLED],
    )

    if not message.is_read:
        message.is_read = True
        message.save(update_fields=["is_read"])

    return render(
        request,
        "generator/message_detail.html",
        {
            "message": message,
            "address": message.address,
            "render_url": reverse("message_render", args=[message.pk]),
        },
    )


@login_required
@require_GET
def message_render(request, pk: int):
    """Serve one sanitised message inside a sandboxed iframe."""
    message = get_object_or_404(
        Message.objects.select_related("address"),
        pk=pk,
        address__status__in=[Address.Status.ACTIVE, Address.Status.DISABLED],
    )

    try:
        payload = ImapService().fetch_message(message.address, message.uid)
    except ImapError as exc:
        body = (
            '<!doctype html><html><head><meta charset="utf-8"></head><body>'
            "<p>This message could not be loaded from the mailbox.</p>"
            f"<p><small>{_escape(str(exc))}</small></p></body></html>"
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("message render failed", extra={"message_id": message.pk})
        body = (
            '<!doctype html><html><head><meta charset="utf-8"></head><body>'
            "<p>This message could not be loaded.</p></body></html>"
        )
    else:
        if payload.get("html"):
            body = document_from_html(
                sanitize_email_html(payload["html"]), title=message.subject or "Message"
            )
        else:
            body = document_from_text(payload.get("text", ""), title=message.subject or "Message")

    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "base-uri 'none'; form-action 'none'; sandbox"
    )
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


def _escape(value: str) -> str:
    from html import escape

    return escape(value, quote=True)


# ---------------------------------------------------------------------------
# Synchronisation
# ---------------------------------------------------------------------------
@login_required
@require_POST
def sync_view(request):
    allowed, retry_after = RateLimiter.hit("sync", str(request.user.pk), 30, 60)
    if not allowed:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"error": "rate_limited", "retry_after": retry_after}, status=429)
        flash.error(request, f"Sync is rate limited. Try again in {retry_after}s.")
        return redirect("dashboard")

    results = SyncService().sync_batch()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"results": results})

    imported = sum(r.get("imported", 0) for r in results if r.get("status") == "ok")
    errors = [r for r in results if r.get("status") == "error"]
    if imported:
        flash.success(request, f"Imported {imported} new message(s).")
    if errors:
        flash.error(request, f"{len(errors)} mailbox(es) could not be synced; see the address page.")
    if not imported and not errors:
        flash.info(request, "No new messages.")
    return redirect(request.POST.get("next") or "dashboard")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def diagnostics(request):
    include_network = request.method == "POST"
    checks = collect_checks(include_network=include_network)

    summary = {
        "ok": sum(1 for c in checks if c.status == OK),
        "warn": sum(1 for c in checks if c.status == WARN),
        "fail": sum(1 for c in checks if c.status == FAIL),
    }

    return render(
        request,
        "generator/diagnostics.html",
        {"checks": checks, "summary": summary, "network_ran": include_network},
    )
