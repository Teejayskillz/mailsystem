from django.contrib import admin

from .models import Address, LoginAttempt, Message, Throttle


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = (
        "address",
        "status",
        "is_configured",
        "is_inbox_capable",
        "is_delivery_tested",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("address", "label")
    readonly_fields = (
        "address",
        "local_part",
        "domain",
        "mailbox_password_enc",
        "server_verified_at",
        "forwarder_verified_at",
        "imap_verified_at",
        "first_external_mail_at",
        "imap_uidvalidity",
        "imap_last_uid",
        "last_synced_at",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    fieldsets = (
        (None, {"fields": ("address", "label", "status", "forward_to", "forward_confirmed_at")}),
        ("Evidence", {"fields": (
            "server_verified_at",
            "forwarder_verified_at",
            "imap_verified_at",
            "first_external_mail_at",
            "last_synced_at",
            "last_error",
        )}),
        ("Internal", {"fields": (
            "local_part",
            "domain",
            "mailbox_password_enc",
            "quota_mb",
            "imap_uidvalidity",
            "imap_last_uid",
            "created_at",
            "updated_at",
            "deleted_at",
        )}),
    )

    def has_add_permission(self, request):
        # Addresses are only created through the cPanel provisioning flow.
        return False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "from_addr", "address", "sent_at", "is_read")
    list_filter = ("address", "is_read")
    search_fields = ("subject", "from_addr", "message_id")
    readonly_fields = [f.name for f in Message._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("created_at", "username", "ip", "ok")
    list_filter = ("ok",)
    readonly_fields = ("ip", "username", "ok", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(Throttle)
class ThrottleAdmin(admin.ModelAdmin):
    list_display = ("bucket", "key_hash", "window_start", "counter")
    readonly_fields = ("bucket", "key_hash", "window_start", "counter")

    def has_add_permission(self, request):
        return False
