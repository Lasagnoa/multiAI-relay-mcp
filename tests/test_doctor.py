"""collab_doctor 診断拡張のテスト。

Codex設計: テスト先行（TDD）でdoctor拡張を実装する。
カバー対象: 正常state・BOM・schema version不一致・非dict issue・
           invalid severity・重複issue id・lock PID不在・JSON出力
"""
import json
import time
from pathlib import Path

import pytest

from multiai_relay_mcp import server
from multiai_relay_mcp import state as state_mod

# ─── フィクスチャ ─────────────────────────────────────────────────

_VALID_STATE = {
    "version": "1.0",
    "project_name": "TestProject",
    "current_ai": "claude",
    "mode": "implement",
    "session_count": 1,
    "last_updated": "2026-05-28T00:00:00",
    "current_task": None,
    "completed_tasks": [],
    "notes": [],
    "key_decisions": [],
    "known_issues": [],
    "resolved_issues": [],
    "pending_tasks": [],
    "completed_pending_tasks": [],
    "handoff_template": "full",
}


def _write(project_dir: Path, state: dict, encoding: str = "utf-8") -> None:
    (project_dir / "AI_STATE.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding=encoding,
    )


def _patch(base: dict, **overrides) -> dict:
    import copy
    d = copy.deepcopy(base)
    d.update(overrides)
    return d


@pytest.fixture
def project(tmp_path):
    state_mod.set_current_project(tmp_path)
    _write(tmp_path, _VALID_STATE)
    yield tmp_path
    state_mod.set_current_project(None)


# ─── テスト ───────────────────────────────────────────────────────

def test_doctor_normal_state_no_err(project):
    """正常な state ではエラー・警告が出ない。"""
    result = server.collab_doctor(check_cli=False, check_ai_call=False)
    assert "❌" not in result  # ERR 行なし
    assert "⚠️" not in result  # WARN 行なし（false-positive 防止）
    assert "AI_STATE.json" in result


def test_doctor_detects_bom(project):
    """BOM付き AI_STATE.json を WARN として検出する。"""
    _write(project, _VALID_STATE, encoding="utf-8-sig")
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_encoding=True,
    )
    assert "WARN" in result
    assert "BOM" in result


def test_doctor_detects_schema_version_mismatch(project):
    """schema version が _STATE_SCHEMA_VERSION と異なる場合を WARN として検出する。"""
    _write(project, _patch(_VALID_STATE, version="0.9"))
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_schema=True,
    )
    assert "WARN" in result or "ERR" in result
    # バージョン不一致が報告されている
    assert "0.9" in result or "バージョン" in result or "version" in result.lower()


def test_doctor_detects_missing_required_key(project):
    """必須キーが欠落した state を WARN として検出する。"""
    state = {k: v for k, v in _VALID_STATE.items() if k != "current_ai"}
    _write(project, state)
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_schema=True,
    )
    assert "WARN" in result or "ERR" in result


def test_doctor_detects_non_dict_issue(project):
    """known_issues に非dict要素（文字列）があることを WARN として検出する。"""
    _write(project, _patch(_VALID_STATE, known_issues=["旧フォーマットのissue文字列"]))
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_issues=True,
    )
    assert "WARN" in result or "ERR" in result
    assert "issue" in result.lower() or "known_issues" in result


def test_doctor_detects_invalid_severity(project):
    """issue の severity が無効値の場合を WARN として検出する。"""
    bad_issue = {
        "id": "issue-001", "text": "テスト",
        "added_at": "2026-05-28T00:00:00", "added_by": "claude",
        "severity": "INVALID",
    }
    _write(project, _patch(_VALID_STATE, known_issues=[bad_issue]))
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_issues=True,
    )
    assert "WARN" in result or "ERR" in result


def test_doctor_detects_duplicate_issue_ids(project):
    """known_issues に重複IDがある場合を WARN として検出する。"""
    issue_a = {"id": "issue-001", "text": "最初", "added_at": "", "added_by": "claude", "severity": "P2"}
    issue_b = {"id": "issue-001", "text": "重複", "added_at": "", "added_by": "codex", "severity": "P1"}
    _write(project, _patch(_VALID_STATE, known_issues=[issue_a, issue_b]))
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_issues=True,
    )
    assert "WARN" in result or "ERR" in result
    assert "重複" in result or "duplicate" in result.lower() or "issue-001" in result


def test_doctor_detects_non_string_text(project):
    """issue の text フィールドが非文字列（整数）の場合を WARN として検出する。"""
    bad_issue = {
        "id": "issue-001", "text": 123,
        "added_at": "2026-05-28T00:00:00", "added_by": "claude",
        "severity": "P2",
    }
    _write(project, _patch(_VALID_STATE, known_issues=[bad_issue]))
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_issues=True,
    )
    assert "WARN" in result or "ERR" in result


def test_doctor_detects_invalid_tag_format(project):
    """issue の tags に不正形式（スペース・記号を含む）がある場合を WARN として検出する。"""
    bad_issue = {
        "id": "issue-001", "text": "テスト",
        "added_at": "2026-05-28T00:00:00", "added_by": "claude",
        "severity": "P2",
        "tags": ["ok-tag", "bad tag!"],  # スペース・記号入りタグ
    }
    _write(project, _patch(_VALID_STATE, known_issues=[bad_issue]))
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_issues=True,
    )
    assert "WARN" in result or "ERR" in result


def test_doctor_detects_dangerous_related_files(project):
    """issue の related_files に危険なパス（..を含む）がある場合を WARN として検出する。"""
    bad_issue = {
        "id": "issue-001", "text": "テスト",
        "added_at": "2026-05-28T00:00:00", "added_by": "claude",
        "severity": "P2",
        "related_files": ["../escape.txt"],  # パストラバーサル
    }
    _write(project, _patch(_VALID_STATE, known_issues=[bad_issue]))
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        check_issues=True,
    )
    assert "WARN" in result or "ERR" in result


def test_doctor_detects_stale_lock_dead_pid(project):
    """存在しない PID のロックファイルを WARN として検出する。"""
    lock = project / "AI_STATE.lock"
    lock.write_text("999999999", encoding="utf-8")  # 存在しないPID
    result = server.collab_doctor(check_cli=False, check_ai_call=False, check_lock=True)
    assert "WARN" in result
    assert "ロック" in result or "lock" in result.lower()


def test_doctor_json_output_structure(project):
    """output='json' でパーサブルな構造を返す。"""
    result = server.collab_doctor(check_cli=False, check_ai_call=False, output="json")
    payload = json.loads(result)
    assert "summary" in payload
    assert "ok" in payload["summary"]
    assert "warn" in payload["summary"]
    assert "err" in payload["summary"]
    assert "diagnostics" in payload
    assert isinstance(payload["diagnostics"], list)
    for diag in payload["diagnostics"]:
        assert "level" in diag
        assert "code" in diag
        assert "message" in diag
        assert "suggestion" in diag
