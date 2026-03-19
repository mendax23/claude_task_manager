import logging
from celery import shared_task
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


@shared_task
def generate_suggestions(project_id: int):
    """Async task: generate AI task suggestions for a project."""
    from apps.projects.models import Project
    from apps.projects.services.suggestion_service import SuggestionService

    try:
        project = Project.objects.get(pk=project_id)
        llm_config = project.llm_config or _get_default_config()
        if not llm_config:
            logger.warning("No LLM config available for suggestions")
            return

        service = SuggestionService(project, llm_config)
        suggestions = async_to_sync(service.suggest_tasks)()

        # Broadcast suggestions to dashboard WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "dashboard",
            {
                "type": "notification",
                "message": f"Generated {len(suggestions)} task suggestions for {project.name}",
                "suggestions": suggestions,
                "project_id": project_id,
            },
        )
    except Project.DoesNotExist:
        logger.error("Project %s not found", project_id)
    except Exception as e:
        logger.exception("Suggestion generation failed: %s", e)


def _get_default_config():
    from apps.providers.models import LLMConfig
    return LLMConfig.objects.filter(is_default=True, is_active=True).first()
