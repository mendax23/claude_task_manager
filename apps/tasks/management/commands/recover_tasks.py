"""
Manually recover tasks stuck in IN_PROGRESS.

Usage:
    python manage.py recover_tasks          # recover all stale tasks
    python manage.py recover_tasks --run 18 # recover specific run
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Recover tasks stuck in IN_PROGRESS due to worker failure."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run", type=int, help="Recover a specific TaskRun by ID"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be recovered without making changes"
        )

    def handle(self, *args, **options):
        from apps.tasks.models import TaskRun, TaskStatus
        from apps.tasks.services.tmux_manager import TmuxManager
        from apps.tasks.celery_tasks import _try_recover_run, _find_result_event

        tmux = TmuxManager()

        if options["run"]:
            runs = TaskRun.objects.filter(pk=options["run"]).select_related(
                "task", "task__project", "task__llm_config"
            )
        else:
            runs = TaskRun.objects.filter(
                status=TaskStatus.IN_PROGRESS,
            ).select_related("task", "task__project", "task__llm_config")

        if not runs.exists():
            self.stdout.write("No in-progress runs found.")
            return

        for run in runs:
            task = run.task
            json_file = f"/tmp/aq_task_{task.pk}_{run.pk}.json"
            result = _find_result_event(json_file)
            tmux_alive = run.tmux_session and tmux.is_alive(run.tmux_session)
            exit_code = None
            if tmux_alive:
                exit_code = tmux.check_exit_marker(run.tmux_session)

            self.stdout.write(
                f"\nRun #{run.pk} — Task #{task.pk}: {task.title}\n"
                f"  Status: {run.status} | Started: {run.started_at}\n"
                f"  Tmux: {'alive' if tmux_alive else 'dead'} ({run.tmux_session})\n"
                f"  Exit marker: {exit_code}\n"
                f"  Result event in file: {'YES' if result else 'NO'}"
            )
            if result:
                self.stdout.write(
                    f"  Result: {'ERROR' if result.get('is_error') else 'SUCCESS'}"
                    f" | Tokens: {result.get('usage', {}).get('output_tokens', 0)}"
                )

            if options["dry_run"]:
                if result or exit_code is not None or not tmux_alive:
                    self.stdout.write(self.style.WARNING("  -> WOULD RECOVER"))
                else:
                    self.stdout.write("  -> Still running, no action needed")
                continue

            _try_recover_run(run, tmux)
            run.refresh_from_db()
            task.refresh_from_db()
            self.stdout.write(
                self.style.SUCCESS(
                    f"  -> Run: {run.status} | Task: {task.status}"
                )
            )
