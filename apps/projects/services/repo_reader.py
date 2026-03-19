import subprocess
from pathlib import Path


class RepoReader:
    """Reads context from a git repository for use in LLM prompts."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)

    def read_context(self) -> dict:
        return {
            "readme": self._read_readme(),
            "recent_commits": self._read_recent_commits(),
            "repo_path": str(self.repo_path),
        }

    def _read_readme(self, max_chars: int = 3000) -> str:
        for name in ["README.md", "README.rst", "README.txt", "README"]:
            path = self.repo_path / name
            if path.exists():
                content = path.read_text(errors="replace")
                return content[:max_chars]
        return ""

    def _read_recent_commits(self, n: int = 20) -> str:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"-{n}"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            return ""

    def build_context_prompt(self) -> str:
        ctx = self.read_context()
        parts = [f"Repository: {ctx['repo_path']}"]
        if ctx["readme"]:
            parts.append(f"\n\nREADME:\n{ctx['readme']}")
        if ctx["recent_commits"]:
            parts.append(f"\n\nRecent commits:\n{ctx['recent_commits']}")
        return "\n".join(parts)
