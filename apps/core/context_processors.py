def global_context(request):
    """Inject commonly needed objects into every template context."""
    from apps.scheduling.models import Schedule
    return {
        "schedule": Schedule.objects.first(),
    }
