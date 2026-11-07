from django.urls import path

from . import views

app_name = "whatsapp"

urlpatterns = [
    path("", views.conversation_list, name="conversation_list"),
    path("<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("<int:pk>/mensagens/", views.conversation_thread, name="conversation_thread"),
    path("<int:pk>/responder/", views.reply, name="reply"),
    path("<int:pk>/botoes-de-teste/", views.send_test_buttons, name="send_test_buttons"),
    path("<int:pk>/lista-de-teste/", views.send_test_list, name="send_test_list"),
    path("<int:pk>/imagem-de-teste/", views.send_test_image, name="send_test_image"),
    path("<int:pk>/cadastro/", views.start_registration, name="start_registration"),
    path("<int:pk>/midia/<int:message_pk>/", views.media, name="media"),
    path(
        "<int:pk>/devolver-ao-assistente/",
        views.give_back_to_assistant,
        name="give_back_to_assistant",
    ),
]
