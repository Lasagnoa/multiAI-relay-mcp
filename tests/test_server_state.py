import copy
import json

import pytest

from multiai_relay_mcp import server
from multiai_relay_mcp import state as state_mod


def make_state(**overrides):
    state = copy.deepcopy(state_mod._STATE_DEFAULTS)
    state.update({
        "project_name": "TestProject",
        "current_ai": "codex",
        "mode": "plan",
        "session_count": 1,
        "last_updated": "2026-05-28T00:00:00",
    })
    state.update(overrides)
    return state


def write_state(project_dir, state, encoding="utf-8"):
    (project_dir / "AI_STATE.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding=encoding,
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    state_mod.set_current_project(tmp_path)
    write_state(tmp_path, make_state())
    yield tmp_path
    state_mod.set_current_project(None)


def test_load_state_accepts_bom_and_normalizes_non_string_issue(project):
    write_state(
        project,
        make_state(known_issues=[{
            "id": "issue-001",
            "text": 123,
            "added_at": "2026-05-28T12:00:00",
            "added_by": "codex",
        }]),
        encoding="utf-8-sig",
    )

    state = server._load_state()

    issue = state["known_issues"][0]
    assert issue["text"] == "123"
    assert issue["severity"] == "P2"


def test_timeline_includes_structured_issue_added_at(project):
    result = server.collab_record_issue(
        "timeline issue",
        severity="P1",
        category="review",
        tags=["timeline"],
        related_files=["src/multiai_relay_mcp/server.py"],
    )
    assert "issue-001" in result

    timeline = server.collab_timeline(limit=10, event_type="issue")

    assert "timeline issue" in timeline
    assert "[CODEX]" in timeline


def test_update_issue_rejects_resolved_status(project):
    server.collab_record_issue("update target")

    result = server.collab_update_issue("issue-001", status="resolved")

    assert "エラー" in result
    assert "collab_resolve_issue" in result


def test_checkpoint_dry_run_does_not_write_state_or_handoff(project):
    before = (project / "AI_STATE.json").read_text(encoding="utf-8")

    result = server.collab_checkpoint("dry run message", "claude", dry_run=True)

    after = (project / "AI_STATE.json").read_text(encoding="utf-8")
    assert before == after
    assert not (project / "HANDOFF.md").exists()
    payload = json.loads(result)
    assert payload["dry_run"] is True
    assert payload["target_ai"] == "claude"
