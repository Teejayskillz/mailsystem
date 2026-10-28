from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("addresses/generate/", views.generate_address, name="generate_address"),
    path("addresses/<int:pk>/", views.address_detail, name="address_detail"),
    path("addresses/<int:pk>/<str:action>/", views.address_action, name="address_action"),
    path("messages/<int:pk>/", views.message_detail, name="message_detail"),
    path("messages/<int:pk>/render/", views.message_render, name="message_render"),
    path("sync/", views.sync_view, name="sync"),
    path("diagnostics/", views.diagnostics, name="diagnostics"),
]
