import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def run_task(self, task_id: int, run_id: int):
    """Execute a single task via the TaskRunner."""
    from apps.tasks.models import Task, TaskRun, TaskStatus
    from apps.tasks.services.task_runner import TaskRunner

    try:
        task = Task.objects.select_related("project", "llm_config").get(pk=task_id)
        run = TaskRun.objects.get(pk=run_id)
        run.celery_task_id = self.request.id
        run.save(update_fields=["celery_task_id"])

        TaskRunner().run(task, run)

    except Task.DoesNotExist:
        logger.error("Task %s not found", task_id)
    except Exception as exc:
        logger.exception("Task %s execution error: %s", task_id, exc)
        raise self.retry(exc=exc, countdown=60)


@shared_task
def schedule_evergreen_tasks():
    """Move evergreen tasks with next_run_at <= now to SCHEDULED."""
    from apps.tasks.models import Task, TaskStatus

    tasks = Task.objects.filter(
        task_type="evergreen",
        status=TaskStatus.BACKLOG,
        next_run_at__lte=timezone.now(),
    )
    count = tasks.update(status=TaskStatus.SCHEDULED)
    if count:
        logger.info("Scheduled %d evergreen tasks", count)


@shared_task
def advance_chains():
    """Check for chains where current step is done, trigger next step."""
    from apps.tasks.models import TaskChain, Task, TaskRun, TaskStatus

    chains = TaskChain.objects.filter(status=TaskStatus.IN_PROGRESS)
    for chain in chains:
        with transaction.atomic():
            chain = TaskChain.objects.select_for_update().get(pk=chain.pk)
            if chain.status != TaskStatus.IN_PROGRESS:
                continue
            current_tasks = chain.tasks.filter(chain_order=chain.current_step)
            if current_tasks.exists() and all(t.status == TaskStatus.DONE for t in current_tasks):
                chain.advance()
                next_task = chain.get_next_task()
                if next_task:
                    next_run = TaskRun.objects.create(task=next_task)
                    next_task.status = TaskStatus.IN_PROGRESS
                    next_task.save(update_fields=["status"])
                    run_task.delay(next_task.pk, next_run.pk)
                else:
                    chain.status = TaskStatus.DONE
                    chain.save(update_fields=["status"])
