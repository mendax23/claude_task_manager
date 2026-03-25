import json
from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Schedule, TokenBudget
from .forms import ScheduleForm, TokenBudgetForm


def schedule_settings(request):
    schedule = Schedule.objects.first()
    if request.method == "POST":
        form = ScheduleForm(request.POST, instance=schedule) if schedule else ScheduleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("scheduling:settings")
    else:
        form = ScheduleForm(instance=schedule) if schedule else ScheduleForm()
    return render(request, "scheduling/settings.html", {"schedule": schedule, "form": form})


def budget_overview(request):
    from apps.tasks.models import TaskRun

    budgets = TokenBudget.objects.select_related("provider").all()

    # Daily token usage for the last 14 days (for sparkline)
    fourteen_days_ago = timezone.now() - timedelta(days=14)
    daily_usage = list(
        TaskRun.objects.filter(started_at__gte=fourteen_days_ago)
        .annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(tokens=Sum("tokens_used"))
        .order_by("day")
    )
    # Build a complete 14-day series (fill gaps with 0)
    usage_by_day = {entry["day"]: entry["tokens"] or 0 for entry in daily_usage}
    today = timezone.now().date()
    daily_series = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        daily_series.append({"day": d.strftime("%a"), "tokens": usage_by_day.get(d, 0)})

    # Compute budget insights for each budget
    from apps.scheduling.services.budget_tracker import BudgetTracker
    tracker = BudgetTracker()
    for budget in budgets:
        status = tracker.get_status(budget.provider_id)
        budget.pct_week_elapsed = status.get("pct_week_elapsed", 0)
        budget.drain_active = status.get("drain_mode", False)
        budget.tokens_could_use = max(0, budget.weekly_limit - budget.tokens_used_this_week)
        burn = tracker.get_burn_rate_status(budget.provider_id)
        budget.burn_surplus = burn.get("surplus", False)
        budget.projected_waste_pct = burn.get("projected_waste_pct", 0)
        budget.hours_until_reset = burn.get("hours_until_reset", 0)

    # Count evergreen tasks that could be pulled forward
    from apps.tasks.models import Task
    evergreen_waiting = Task.objects.filter(
        task_type="evergreen", status="scheduled", next_run_at__gt=timezone.now()
    ).count()

    return render(request, "scheduling/budget.html", {
        "budgets": budgets,
        "daily_series": json.dumps(daily_series),
        "evergreen_waiting": evergreen_waiting,
    })


def budget_create(request):
    from apps.providers.models import LLMConfig
    form = TokenBudgetForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("scheduling:budget")
    providers = LLMConfig.objects.all()
    return render(request, "scheduling/budget_form.html", {"form": form, "providers": providers, "creating": True})


def budget_edit(request, pk):
    budget = get_object_or_404(TokenBudget, pk=pk)
    form = TokenBudgetForm(request.POST or None, instance=budget)
    if form.is_valid():
        form.save()
        return redirect("scheduling:budget")
    return render(request, "scheduling/budget_form.html", {"form": form, "budget": budget, "creating": False})


@require_POST
def schedule_toggle(request):
    """Toggle the active schedule on/off and return updated budget bar."""
    from apps.scheduling.services.idle_detector import IdleDetector

    schedule = Schedule.objects.first()
    if not schedule:
        response = HttpResponse(status=404)
        return response
    schedule.is_active = not schedule.is_active
    schedule.save(update_fields=["is_active", "updated_at"])
    msg = "Scheduler enabled" if schedule.is_active else "Scheduler paused"

    budget = TokenBudget.objects.select_related("provider").filter(
        provider__is_default=True
    ).first()
    detector = IdleDetector()
    is_idle = detector.is_short_idle()

    response = render(request, "components/token_budget_bar.html", {
        "budget": budget,
        "is_idle": is_idle,
        "schedule": schedule,
    })
    response["HX-Trigger"] = json.dumps({"agentqueue:success": {"message": msg}})
    return response
