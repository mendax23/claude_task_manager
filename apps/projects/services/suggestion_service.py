import json
from typing import TYPE_CHECKING

from apps.providers.base import LLMProvider, LLMRequest, LLMMessage
from .repo_reader import RepoReader

if TYPE_CHECKING:
    from apps.projects.models import Project
    from apps.providers.models import LLMConfig


SUGGESTION_PROMPT = """Based on the following project context, suggest exactly 5 autonomous coding tasks
that an AI agent could perform independently (without human interaction).

Focus on tasks that:
- Have clear, measurable outcomes
- Can be done autonomously (no clarification needed)
- Provide real value (tests, docs, refactoring, bug fixes, content)

Project context:
{context}

Respond with ONLY a JSON array of 5 tasks, each with these fields:
- title: short task title (max 80 chars)
- prompt: the exact prompt to give the AI agent to execute this task
- task_type: "one_shot" or "evergreen"
- priority: 1 (low), 2 (medium), 3 (high), or 4 (urgent)
- tags: list of strings

Example format:
[
  {{
    "title": "Add docstrings to all public functions",
    "prompt": "Add Google-style docstrings to all public functions and methods in this repository...",
    "task_type": "one_shot",
    "priority": 2,
    "tags": ["docs", "quality"]
  }}
]"""


class SuggestionService:
    def __init__(self, project: "Project", llm_config: "LLMConfig"):
        self.project = project
        self.provider = LLMProvider.from_config(llm_config)

    async def suggest_tasks(self) -> list[dict]:
        context = RepoReader(self.project.repo_path).build_context_prompt()
        prompt = SUGGESTION_PROMPT.format(context=context)

        request = LLMRequest(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=2048,
            temperature=0.7,
            stream=False,
        )

        response = await self.provider.complete(request)
        return self._parse_suggestions(response.content)

    def _parse_suggestions(self, content: str) -> list[dict]:
        # Extract JSON from response (handle markdown code blocks)
        content = content.strip()
        if "```" in content:
            start = content.find("[")
            end = content.rfind("]") + 1
            content = content[start:end]

        try:
            suggestions = json.loads(content)
            return suggestions[:5]  # Cap at 5
        except json.JSONDecodeError:
            return []
