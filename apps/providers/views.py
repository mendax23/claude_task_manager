from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import LLMConfig


def provider_list(request):
    providers = LLMConfig.objects.filter(is_active=True)
    return render(request, "providers/list.html", {"providers": providers})


@require_POST
def health_check(request, pk):
    provider = get_object_or_404(LLMConfig, pk=pk)
    # Health check logic will be implemented in Phase 3
    return JsonResponse({"status": "ok", "provider": str(provider)})
