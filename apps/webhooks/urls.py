from django.urls import path

from . import views

app_name = "webhooks"

urlpatterns = [
    path("<slug:provider>/", views.receive, name="receive"),
]
