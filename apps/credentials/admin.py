from django import forms
from django.contrib import admin

from .models import IntegrationCredential


class IntegrationCredentialForm(forms.ModelForm):
    """Tokens são só de escrita: o admin nunca mostra o valor gravado."""

    new_access_token = forms.CharField(
        label="novo access token",
        required=False,
        strip=True,
        widget=forms.PasswordInput(render_value=False),
        help_text="Deixe vazio para manter o atual.",
    )
    new_refresh_token = forms.CharField(
        label="novo refresh token",
        required=False,
        strip=True,
        widget=forms.PasswordInput(render_value=False),
        help_text="Deixe vazio para manter o atual.",
    )

    class Meta:
        model = IntegrationCredential
        # access_token e refresh_token ficam de fora de propósito: só entram pelos campos new_*
        fields = (
            "platform",
            "label",
            "account_id",
            "is_active",
            "token_type",
            "scopes",
            "expires_at",
            "metadata",
        )

    def save(self, commit: bool = True) -> IntegrationCredential:
        credential = super().save(commit=False)
        if self.cleaned_data.get("new_access_token"):
            credential.access_token = self.cleaned_data["new_access_token"]
        if self.cleaned_data.get("new_refresh_token"):
            credential.refresh_token = self.cleaned_data["new_refresh_token"]
        if commit:
            credential.save()
        return credential


@admin.register(IntegrationCredential)
class IntegrationCredentialAdmin(admin.ModelAdmin):
    form = IntegrationCredentialForm
    list_display = ("platform", "label", "account_id", "status_display", "expires_at", "updated_at")
    list_filter = ("platform", "is_active")
    search_fields = ("label", "account_id")
    readonly_fields = (
        "masked_access_token",
        "masked_refresh_token",
        "last_refreshed_at",
        "last_error",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("platform", "label", "account_id", "is_active")}),
        (
            "Token",
            {
                "fields": (
                    "masked_access_token",
                    "new_access_token",
                    "masked_refresh_token",
                    "new_refresh_token",
                    "token_type",
                    "scopes",
                    "expires_at",
                )
            },
        ),
        (
            "Acompanhamento",
            {"fields": ("last_refreshed_at", "last_error", "metadata", "created_at", "updated_at")},
        ),
    )

    @admin.display(description="situação")
    def status_display(self, obj: IntegrationCredential) -> str:
        return obj.status().label
