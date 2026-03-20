import json
from asgiref.sync import async_to_sync
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from .models import LLMConfig
from .forms import LLMConfigForm
from .base import LLMProvider


def provider_list(request):
    providers = LLMConfig.objects.filter(is_active=True)
    return render(request, "providers/list.html", {
        "providers": providers,
        "form": LLMConfigForm(),
    })


def provider_create(request):
    form = LLMConfigForm(request.POST or None)
    is_htmx = request.headers.get("HX-Request")
    if form.is_valid():
        form.save()
        if is_htmx:
            response = HttpResponse()
            response["HX-Redirect"] = "/providers/"
            return response
        return redirect("providers:list")
    return render(request, "providers/create.html", {"form": form})


def provider_edit(request, pk):
    config = get_object_or_404(LLMConfig, pk=pk)
    form = LLMConfigForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("providers:list")
    return render(request, "providers/edit.html", {"form": form, "provider": config})


@require_POST
def provider_delete(request, pk):
    config = get_object_or_404(LLMConfig, pk=pk)
    config.is_active = False
    config.save(update_fields=["is_active", "updated_at"])
    return redirect("providers:list")


@require_POST
def health_check(request, pk):
    config = get_object_or_404(LLMConfig, pk=pk)
    try:
        provider = LLMProvider.from_config(config)
        ok = async_to_sync(provider.health_check)()
        event_type = "agentqueue:success" if ok else "agentqueue:error"
        message = f"{config.name} is reachable" if ok else f"{config.name} is not reachable"
    except Exception as e:
        event_type = "agentqueue:error"
        message = f"{config.name}: {str(e)[:200]}"

    response = HttpResponse(status=200)
    response["HX-Trigger"] = json.dumps({event_type: {"message": message}})
    return response
