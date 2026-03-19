from django.shortcuts import render
from .models import Schedule, TokenBudget


def schedule_settings(request):
    schedule = Schedule.objects.filter(is_active=True).first()
    return render(request, "scheduling/settings.html", {"schedule": schedule})


def budget_overview(request):
    budgets = TokenBudget.objects.select_related("provider").all()
    return render(request, "scheduling/budget.html", {"budgets": budgets})
