"""Contract A — tool surface (E6 evidence: attractors drop)."""
from jarvis.core.tool_surface import classify_task, surface_for, entropy_metrics


def test_classify_task_deterministic():
    assert classify_task("count ERR lines and write result") == "action"
    assert classify_task("write the file with content") == "write"
    assert classify_task("read the log and report") == "read"
    assert classify_task("redact the secret token in .env") == "secret"
    assert classify_task("transform csv into json per schema") == "data"


def test_classify_priorities():
    # "commit"/"git" na frente de "write" (ordem importa — E6: commit rule)
    assert classify_task("commit changed files to git") == "action"
    assert classify_task("secret API token in config") == "secret"


def test_surface_drops_attractor_read_for_action():
    base = ["read_file", "list_directory", "execute_shell",
            "write_file", "str_replace", "build_json_dataset"]
    s = surface_for("action", base)
    assert "read_file" not in s.available  # atractor comprovado (0/6)
    assert "execute_shell" in s.available
    assert "read_file" in s.dropped


def test_surface_write_keeps_writers():
    base = ["read_file", "write_file", "str_replace", "execute_shell"]
    s = surface_for("write", base)
    assert "write_file" in s.available and "str_replace" in s.available


def test_surface_read_keeps_readers():
    base = ["read_file", "execute_shell", "write_file"]
    s = surface_for("read", base)
    assert "read_file" in s.available
    assert "write_file" not in s.available


def test_entropy_metric():
    e = entropy_metrics(["execute_shell", "read_file"])
    assert e["available"] == 2
    assert e["delta"] == 1


def test_surface_to_dict_serializable():
    s = surface_for("action", ["read_file", "execute_shell"])
    d = s.to_dict()
    assert d["task_class"] == "action"
    assert "entropy" in d