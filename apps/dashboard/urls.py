from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("budget-bar/", views.budget_bar, name="budget_bar"),
    path("search/", views.command_search, name="command_search"),
]
