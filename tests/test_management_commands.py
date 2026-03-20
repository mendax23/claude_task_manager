import pytest
from datetime import timedelta
from django.core.management import call_command
from django.utils import timezone
from io import StringIO


@pytest.mark.django_db
def test_prune_idle_events_command_default(db):
    from apps.scheduling.models import IdleEvent

    old = IdleEvent.objects.create(idle_ms=1000, is_idle=True, source="xprintidle")
    IdleEvent.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=10)
    )
    recent = IdleEvent.objects.create(idle_ms=500, is_idle=False, source="xprintidle")

    out = StringIO()
    call_command("prune_idle_events", stdout=out)

    assert not IdleEvent.objects.filter(pk=old.pk).exists()
    assert IdleEvent.objects.filter(pk=recent.pk).exists()
    assert "Deleted 1" in out.getvalue()


@pytest.mark.django_db
def test_prune_idle_events_command_custom_days(db):
    from apps.scheduling.models import IdleEvent

    event = IdleEvent.objects.create(idle_ms=100, is_idle=False, source="xprintidle")
    IdleEvent.objects.filter(pk=event.pk).update(
        created_at=timezone.now() - timedelta(days=3)
    )

    out = StringIO()
    call_command("prune_idle_events", "--days=2", stdout=out)

    assert not IdleEvent.objects.filter(pk=event.pk).exists()
    assert "Deleted 1" in out.getvalue()


@pytest.mark.django_db
def test_prune_idle_events_command_nothing_to_delete(db):
    out = StringIO()
    call_command("prune_idle_events", stdout=out)
    assert "Deleted 0" in out.getvalue()
