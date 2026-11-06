from django.contrib import admin

from .models import FlowRun, MessageTemplate, WhatsAppForm


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "language", "category", "status", "rejected_reason", "updated_at")
    list_filter = ("status", "category", "language")
    search_fields = ("name", "meta_id")
    readonly_fields = ("updated_at",)


@admin.register(FlowRun)
class FlowRunAdmin(admin.ModelAdmin):
    list_display = ("flow_key", "contact", "node", "status", "started_at", "updated_at")
    list_filter = ("flow_key", "status")
    search_fields = ("contact__name", "contact__phone", "flow_key")
    raw_id_fields = ("conversation", "contact")
    readonly_fields = ("started_at", "updated_at", "finished_at")


@admin.register(WhatsAppForm)
class WhatsAppFormAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "meta_id", "updated_at")
    list_filter = ("status",)
    search_fields = ("name", "meta_id")
    readonly_fields = ("updated_at",)
