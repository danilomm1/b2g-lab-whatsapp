from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import DeliveryStatus, WebhookDelivery
from .tasks import process_delivery


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "route_key",
        "status",
        "signature_valid",
        "attempts",
        "received_at",
    )
    list_filter = ("provider", "status", "signature_valid")
    search_fields = ("dedupe_key", "route_key", "raw_body")
    date_hierarchy = "received_at"
    actions = ("reprocess",)

    def get_readonly_fields(
        self, request: HttpRequest, obj: WebhookDelivery | None = None
    ) -> list[str]:
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.action(description="Reprocessar entregas falhas ou ignoradas")
    def reprocess(self, request: HttpRequest, queryset: QuerySet[WebhookDelivery]) -> None:
        eligible = queryset.filter(
            signature_valid=True, status__in=[DeliveryStatus.FAILED, DeliveryStatus.IGNORED]
        )
        ids = list(eligible.values_list("pk", flat=True))
        eligible.update(status=DeliveryStatus.RECEIVED, error="")
        for delivery_id in ids:
            process_delivery(delivery_id)
        self.message_user(request, f"{len(ids)} entregas enviadas para a fila.", messages.SUCCESS)
