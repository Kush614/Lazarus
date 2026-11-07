"""Git history as demo evidence: adopt keeps a proposal, rollback reverts it."""
import pathlib
import subprocess

TRACKED = ["port", "agents/digger/strategy.md"]


class Repo:
    def __init__(self, root: str | pathlib.Path):
        self.root = pathlib.Path(root)

    def _git(self, *args) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def head(self) -> str:
        return self._git("rev-parse", "HEAD")

    def propose(self, version: int) -> str:
        paths = [p for p in TRACKED if (self.root / p).exists()]
        self._git("add", "--", *paths)
        self._git("commit", "--allow-empty", "-m", f"chore(port): v{version} proposed", "--", *paths)
        return self.head()

    def adopt(self, version: int, score: float, parent_score: float | None) -> str:
        delta = f" ({score - parent_score:+.2f})" if parent_score is not None else ""
        self._git("commit", "--allow-empty", "-m", f"feat(port): v{version} adopted {score:.2f}{delta}, 0 regressions")
        return self.head()

    def rollback(self, proposal: str, version: int, score: float, regressions: list[str]) -> str:
        """Restores only the tracked paths. `git revert` refuses on a dirty tree, and logs/ always is."""
        changed = self._git("diff", "--name-only", f"{proposal}^", proposal, "--", *TRACKED).splitlines()
        if changed:
            self._git("restore", f"--source={proposal}^", "--staged", "--worktree", "--", *changed)
        self._git("commit", "--allow-empty", "-m",
                  f"revert(port): v{version} rolled back {score:.2f}, regressions [{', '.join(regressions)}]")
        return self.head()
