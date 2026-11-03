"""Rotas principais do projeto."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("webhooks/", include("apps.webhooks.urls")),
    path("", include("apps.core.urls")),
]
