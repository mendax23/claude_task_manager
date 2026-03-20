import asyncio
import json
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from .models import LLMConfig
from .base import LLMProvider


def provider_list(request):
    providers = LLMConfig.objects.filter(is_active=True)
    return render(request, "providers/list.html", {"providers": providers})


@require_POST
def health_check(request, pk):
    config = get_object_or_404(LLMConfig, pk=pk)
    try:
        provider = LLMProvider.from_config(config)
        ok = asyncio.run(provider.health_check())
        event_type = "agentqueue:success" if ok else "agentqueue:error"
        message = f"{config.name} is reachable" if ok else f"{config.name} is not reachable"
    except Exception as e:
        event_type = "agentqueue:error"
        message = str(e)[:200]

    response = HttpResponse(status=200)
    response["HX-Trigger"] = json.dumps({event_type: {"message": message}})
    return response
