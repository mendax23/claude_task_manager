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
            "directory_tree": self._read_directory_tree(),
            "claude_md": self._read_claude_md(),
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

    def _read_directory_tree(self, max_depth: int = 3, max_entries: int = 200) -> str:
        """Generate a directory tree excluding common noise directories."""
        exclude_dirs = [
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
            ".egg-info", ".eggs", "htmlcov",
        ]
        exclude_args = []
        for d in exclude_dirs:
            exclude_args += ["-not", "-path", f"*/{d}/*"]
        try:
            result = subprocess.run(
                ["find", ".", "-maxdepth", str(max_depth), "-type", "f"] + exclude_args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = result.stdout.strip().split("\n")[:max_entries]
            return "\n".join(sorted(lines))
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            return ""

    def _read_claude_md(self, max_chars: int = 5000) -> str:
        """Read CLAUDE.md project instructions if present."""
        path = self.repo_path / "CLAUDE.md"
        if path.exists():
            return path.read_text(errors="replace")[:max_chars]
        return ""

    def build_context_prompt(self) -> str:
        ctx = self.read_context()
        parts = [f"Repository: {ctx['repo_path']}"]
        if ctx.get("claude_md"):
            parts.append(f"\n\nCLAUDE.md (project instructions):\n{ctx['claude_md']}")
        if ctx.get("directory_tree"):
            parts.append(f"\n\nDirectory structure:\n{ctx['directory_tree']}")
        if ctx["readme"]:
            parts.append(f"\n\nREADME:\n{ctx['readme']}")
        if ctx["recent_commits"]:
            parts.append(f"\n\nRecent commits:\n{ctx['recent_commits']}")
        return "\n".join(parts)
