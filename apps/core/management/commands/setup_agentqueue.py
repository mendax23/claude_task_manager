from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Interactive first-time setup for AgentQueue"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("\n=== AgentQueue Setup ===\n"))

        self._create_superuser()
        self._create_default_schedule()
        self._prompt_llm_config()

        self.stdout.write(self.style.SUCCESS("\nSetup complete! Run 'make dev' to start.\n"))

    def _create_superuser(self):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("  Superuser already exists — skipping.")
            return

        self.stdout.write("\nCreate admin user:")
        username = input("  Username [admin]: ").strip() or "admin"
        email = input("  Email: ").strip()
        password = input("  Password: ").strip()

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"  Created superuser '{username}'"))

    def _create_default_schedule(self):
        from apps.scheduling.models import Schedule

        if Schedule.objects.exists():
            self.stdout.write("  Schedule already configured — skipping.")
            return

        Schedule.objects.create(
            name="default",
            is_active=True,
            idle_threshold_minutes=15,
            away_threshold_hours=1,
            enable_token_spreading=True,
        )
        self.stdout.write(self.style.SUCCESS("  Created default schedule (15min idle threshold)"))

    def _prompt_llm_config(self):
        from apps.providers.models import LLMConfig, ProviderType

        if LLMConfig.objects.exists():
            self.stdout.write("  LLM provider already configured — skipping.")
            return

        self.stdout.write("\nConfigure LLM provider:")
        self.stdout.write("  1. Claude Max (CLI)")
        self.stdout.write("  2. Anthropic API")
        self.stdout.write("  3. OpenRouter")
        self.stdout.write("  4. Ollama (local)")
        self.stdout.write("  0. Skip (configure later in admin)")

        choice = input("  Choice [1]: ").strip() or "1"

        type_map = {
            "1": ProviderType.CLAUDE_MAX,
            "2": ProviderType.ANTHROPIC,
            "3": ProviderType.OPENROUTER,
            "4": ProviderType.OLLAMA,
        }

        if choice not in type_map:
            self.stdout.write("  Skipping LLM config — configure at http://localhost:8000/admin/")
            return

        provider_type = type_map[choice]
        config = {"name": "default", "provider_type": provider_type, "is_default": True}

        if provider_type == ProviderType.ANTHROPIC:
            config["api_key"] = input("  Anthropic API key: ").strip()
            config["model_name"] = input("  Model [claude-opus-4-6]: ").strip() or "claude-opus-4-6"
        elif provider_type == ProviderType.OPENROUTER:
            config["api_key"] = input("  OpenRouter API key: ").strip()
            config["model_name"] = input("  Model [openai/gpt-4o-mini]: ").strip() or "openai/gpt-4o-mini"
        elif provider_type == ProviderType.OLLAMA:
            config["base_url"] = input("  Ollama URL [http://localhost:11434]: ").strip() or "http://localhost:11434"
            config["model_name"] = input("  Model [llama3]: ").strip() or "llama3"
        elif provider_type == ProviderType.CLAUDE_MAX:
            config["claude_cli_path"] = input("  Claude CLI path [claude]: ").strip() or "claude"
            config["model_name"] = input("  Model [claude-opus-4-6]: ").strip() or "claude-opus-4-6"

        LLMConfig.objects.create(**config)
        self.stdout.write(self.style.SUCCESS(f"  Created LLM config: {config['name']}"))
