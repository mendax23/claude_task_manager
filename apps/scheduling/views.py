import json
from django.shortcuts import render
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from .models import Schedule, TokenBudget


def schedule_settings(request):
    schedule = Schedule.objects.first()
    return render(request, "scheduling/settings.html", {"schedule": schedule})


def budget_overview(request):
    budgets = TokenBudget.objects.select_related("provider").all()
    return render(request, "scheduling/budget.html", {"budgets": budgets})


@require_POST
def schedule_toggle(request):
    """Toggle the active schedule on/off."""
    schedule = Schedule.objects.first()
    if not schedule:
        response = HttpResponse(status=404)
        return response
    schedule.is_active = not schedule.is_active
    schedule.save(update_fields=["is_active", "updated_at"])
    msg = "Scheduler enabled" if schedule.is_active else "Scheduler paused"
    event = "agentqueue:success" if schedule.is_active else "agentqueue:success"
    response = HttpResponse(status=200)
    response["HX-Trigger"] = json.dumps({event: {"message": msg}})
    return response
