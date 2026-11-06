from django.urls import path

from . import views

app_name = "whatsapp"

urlpatterns = [
    path("", views.conversation_list, name="conversation_list"),
    path("<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("<int:pk>/mensagens/", views.conversation_thread, name="conversation_thread"),
    path("<int:pk>/responder/", views.reply, name="reply"),
    path("<int:pk>/botoes-de-teste/", views.send_test_buttons, name="send_test_buttons"),
]
