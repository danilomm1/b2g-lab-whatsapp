from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("parciais/eventos-recentes/", views.recent_events, name="recent_events"),
]
