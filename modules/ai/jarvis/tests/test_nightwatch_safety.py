"""Integration tests for nightwatch.safety branch isolation — real git,
no mocks. This is the mechanism just wired into harness.execute_task();
before this file, zero tests exercised create_task_branch/abort_task_branch/
merge_task_branch against a real repo (only is_path_protected had coverage,
via a subprocess call in test_harness_e2e.py's scenario C).
"""
from __future__ import annotations

import subprocess

import pytest

import nightwatch.safety as safety_mod


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    """Real git repo, isolated from the actual nixos-ai repo."""
    repo = tmp_path / "safety-test-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "file.txt").write_text("v1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)

    monkeypatch.setattr(safety_mod, "REPO_ROOT", repo)
    return repo


def _head_sha(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def _current_branch(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()


class TestBranchIsolation:
    def test_create_task_branch_switches_to_new_branch(self, isolated_repo):
        branch = safety_mod.create_task_branch("t1", "code-quality")
        assert branch == "nightwatch/code-quality/t1"
        assert _current_branch(isolated_repo) == branch

    def test_abort_returns_to_clean_main_and_deletes_branch(self, isolated_repo):
        main_sha_before = _head_sha(isolated_repo)
        branch = safety_mod.create_task_branch("t2", "code-quality")

        (isolated_repo / "file.txt").write_text("v2 — mudanca que deveria sumir\n")
        subprocess.run(["git", "add", "-A"], cwd=isolated_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "wip"], cwd=isolated_repo, check=True)

        safety_mod.abort_task_branch(branch)

        assert _current_branch(isolated_repo) == "main"
        assert _head_sha(isolated_repo) == main_sha_before, "main não pode ter mudado"
        assert (isolated_repo / "file.txt").read_text() == "v1\n"
        branches = subprocess.run(
            ["git", "-C", str(isolated_repo), "branch", "--list", branch],
            capture_output=True, text=True,
        ).stdout
        assert branch not in branches, "branch deveria ter sido deletada"

    def test_merge_brings_change_into_main(self, isolated_repo):
        branch = safety_mod.create_task_branch("t3", "code-quality")
        (isolated_repo / "file.txt").write_text("v2 — fix real\n")
        subprocess.run(["git", "add", "-A"], cwd=isolated_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "nightwatch: fix"], cwd=isolated_repo, check=True)

        sha = safety_mod.merge_task_branch(branch)

        assert _current_branch(isolated_repo) == "main"
        assert _head_sha(isolated_repo) == sha
        assert (isolated_repo / "file.txt").read_text() == "v2 — fix real\n"
        branches = subprocess.run(
            ["git", "-C", str(isolated_repo), "branch", "--list", branch],
            capture_output=True, text=True,
        ).stdout
        assert branch not in branches, "branch deveria ter sido deletada após merge"

    def test_two_sequential_tasks_dont_leak_into_each_other(self, isolated_repo):
        """O cenário que motivou o fix: task A falha, task B não pode ver
        nem herdar nada do que A tentou."""
        main_sha_before = _head_sha(isolated_repo)

        branch_a = safety_mod.create_task_branch("a", "cat")
        (isolated_repo / "file.txt").write_text("mudanca da task A, vai falhar\n")
        subprocess.run(["git", "add", "-A"], cwd=isolated_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "a"], cwd=isolated_repo, check=True)
        safety_mod.abort_task_branch(branch_a)

        assert _head_sha(isolated_repo) == main_sha_before
        assert (isolated_repo / "file.txt").read_text() == "v1\n"

        branch_b = safety_mod.create_task_branch("b", "cat")
        assert _current_branch(isolated_repo) == branch_b
        assert (isolated_repo / "file.txt").read_text() == "v1\n", (
            "task B nao pode ver a mudanca revertida da task A"
        )


class TestPruneOrphanBranches:
    def test_prune_deletes_leftover_branches_and_returns_to_main(self, isolated_repo):
        safety_mod.create_task_branch("orphan1", "cat")
        subprocess.run(["git", "-C", str(isolated_repo), "checkout", "main"],
                        capture_output=True)
        safety_mod.create_task_branch("orphan2", "cat")
        subprocess.run(["git", "-C", str(isolated_repo), "checkout", "main"],
                        capture_output=True)

        count = safety_mod.prune_orphan_branches()

        assert count == 2
        assert _current_branch(isolated_repo) == "main"
        remaining = subprocess.run(
            ["git", "-C", str(isolated_repo), "branch", "--list", "nightwatch/*"],
            capture_output=True, text=True,
        ).stdout
        assert remaining.strip() == ""

    def test_prune_when_currently_checked_out_on_orphan_branch(self, isolated_repo):
        """Simula processo morto no meio de uma task: o branch fica
        checked-out quando o proximo run inicia."""
        safety_mod.create_task_branch("stuck", "cat")
        assert _current_branch(isolated_repo) == "nightwatch/cat/stuck"

        count = safety_mod.prune_orphan_branches()

        assert count == 1
        assert _current_branch(isolated_repo) == "main"
