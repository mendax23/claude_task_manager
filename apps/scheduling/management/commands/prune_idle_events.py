from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete IdleEvent records older than N days (default 7)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Delete events older than this many days (default: 7)",
        )

    def handle(self, *args, **options):
        from apps.scheduling.models import IdleEvent

        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        count, _ = IdleEvent.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} idle event(s) older than {days} day(s)."))
