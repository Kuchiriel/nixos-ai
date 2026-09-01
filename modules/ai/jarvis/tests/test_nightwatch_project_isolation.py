"""Integration tests for real cross-project isolation.

Before this: nightwatch.paths.REPO_ROOT was computed once at process
import time and referenced directly (not as a parameter) inside
patcher.py, safe_editor.py, validator.py, evaluator.py, safety.py.
project_isolation.py had ProjectRegistry/ProjectConfig/discover_projects
already built, but nothing ever called anything from it to change where
those five modules actually read and wrote — self.project_registry was
instantiated in Harness.__init__ and never consulted again. One process
= one repo, for its entire lifetime, no matter what task.project said.

These tests exercise use_project_root() + resolve_project_root() against
two real, separate git repos and confirm actual file/git isolation, not
just that the functions return without error.
"""
from __future__ import annotations

import subprocess

import pytest

import nightwatch.project_isolation as pi


def _init_repo(path, filename="marker.txt", content="v1\n"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / filename).write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    """project-a and project-b, real independent git repos, under a
    workspace root that WORKSPACE_ROOT is pointed at for this test only."""
    workspace = tmp_path / "workspace"
    a = _init_repo(workspace / "project-a", content="project A original\n")
    b = _init_repo(workspace / "project-b", content="project B original\n")
    monkeypatch.setattr(pi, "WORKSPACE_ROOT", workspace)
    return a, b


class TestResolveProjectRoot:
    def test_resolves_real_project_by_name(self, two_projects):
        a, b = two_projects
        assert pi.resolve_project_root("project-a") == a
        assert pi.resolve_project_root("project-b") == b

    def test_unresolvable_name_falls_back_to_nixos_ai_default(self, two_projects):
        from nightwatch.paths import REPO_ROOT as DEFAULT_ROOT
        assert pi.resolve_project_root("this-does-not-exist") == DEFAULT_ROOT

    def test_nixos_ai_or_empty_always_falls_back_without_lookup(self, two_projects):
        from nightwatch.paths import REPO_ROOT as DEFAULT_ROOT
        assert pi.resolve_project_root("nixos-ai") == DEFAULT_ROOT
        assert pi.resolve_project_root("") == DEFAULT_ROOT


class TestUseProjectRootIsolation:
    def test_isolated_modules_see_the_override(self, two_projects):
        a, b = two_projects
        import nightwatch.safety as safety_mod
        original = safety_mod.REPO_ROOT
        with pi.use_project_root(a):
            assert safety_mod.REPO_ROOT == a
        assert safety_mod.REPO_ROOT == original, "não restaurou depois do with"

    def test_restores_on_exception(self, two_projects):
        a, b = two_projects
        import nightwatch.validator as validator_mod
        original = validator_mod.REPO_ROOT
        with pytest.raises(ValueError):
            with pi.use_project_root(a):
                assert validator_mod.REPO_ROOT == a
                raise ValueError("simula task explodindo no meio")
        assert validator_mod.REPO_ROOT == original, (
            "uma excecao no meio da task nao pode deixar o proximo task "
            "(de outro projeto) apontando pro repo errado"
        )

    def test_git_commit_lands_in_the_right_repo_not_the_other(self, two_projects):
        """O teste que prova a lacuna real: escrever/commitar dentro do
        use_project_root de A nunca pode aparecer no historico de B."""
        a, b = two_projects
        import nightwatch.safety as safety_mod

        b_head_before = subprocess.run(
            ["git", "-C", str(b), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()

        with pi.use_project_root(a):
            branch = safety_mod.create_task_branch("t1", "test")
            (a / "marker.txt").write_text("project A modified\n")
            subprocess.run(["git", "-C", str(a), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(a), "commit", "-q", "-m", "change"], check=True)
            safety_mod.merge_task_branch(branch)

        assert (a / "marker.txt").read_text() == "project A modified\n"
        assert (b / "marker.txt").read_text() == "project B original\n", (
            "vazou pra B — isolamento nao funcionou"
        )
        b_head_after = subprocess.run(
            ["git", "-C", str(b), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        assert b_head_after == b_head_before, "B ganhou um commit que nunca pediu"

    def test_sequential_tasks_different_projects_dont_bleed(self, two_projects):
        """A -> B -> A, cada troca tem que apontar certo, nao so a primeira."""
        a, b = two_projects
        import nightwatch.patcher as patcher_mod

        with pi.use_project_root(a):
            assert patcher_mod.REPO_ROOT == a
        with pi.use_project_root(b):
            assert patcher_mod.REPO_ROOT == b
        with pi.use_project_root(a):
            assert patcher_mod.REPO_ROOT == a
