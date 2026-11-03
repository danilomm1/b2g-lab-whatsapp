from django.contrib import admin

from .models import ChannelIdentity, Consent, Contact, Conversation, Event, Message, Tag


class ChannelIdentityInline(admin.TabularInline):
    model = ChannelIdentity
    extra = 0


class ConsentInline(admin.TabularInline):
    model = Consent
    extra = 0
    fields = ("channel", "purpose", "granted_at", "source", "revoked_at", "revocation_source")


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("__str__", "email", "phone", "instagram_handle", "source", "created_at")
    list_filter = ("tags", "source")
    search_fields = (
        "name",
        "email",
        "phone",
        "instagram_handle",
        "facebook_handle",
        "threads_handle",
        "youtube_handle",
    )
    filter_horizontal = ("tags",)
    inlines = (ChannelIdentityInline, ConsentInline)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Consent)
class ConsentAdmin(admin.ModelAdmin):
    list_display = ("contact", "channel", "purpose", "granted_at", "revoked_at", "source")
    list_filter = ("channel", "purpose", "revoked_at")
    search_fields = ("contact__name", "contact__email", "contact__phone")
    raw_id_fields = ("contact",)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("created_at", "direction", "kind", "body", "status", "is_proactive")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("contact", "channel", "status", "last_inbound_at", "last_message_at")
    list_filter = ("channel", "status")
    search_fields = ("contact__name", "contact__phone", "external_id")
    raw_id_fields = ("contact",)
    inlines = (MessageInline,)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "direction", "kind", "status", "is_proactive")
    list_filter = ("channel", "direction", "status", "is_proactive")
    search_fields = ("body", "external_id")
    raw_id_fields = ("conversation",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "event_type", "channel", "contact", "summary")
    list_filter = ("channel", "event_type")
    search_fields = ("event_type", "summary", "external_id")
    raw_id_fields = ("contact",)
    date_hierarchy = "occurred_at"
