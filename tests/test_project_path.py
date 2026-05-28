"""pending-011 / issue-027 / issue-028 project_path API のテスト。

テスト観点:
- project_path=B を指定した場合、Bだけに作用し current_project(A) を汚さない
- 書き込み系ツールも B のみに作用する
- 例外時に ContextVar がリセットされる
- project_path なし（旧挙動）が維持される
- 存在しない project_path は明確なエラーになる
- cwd 探索フォールバック（AI_STATE.json がある場合のみ）
- issue-027: collab_current_project / collab_version が effective project を表示する
- issue-028: CLI系4ツール（consult/discuss/request_review/setup_cli）が project_path に対応する
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from multiai_relay_mcp import server
from multiai_relay_mcp import state as state_mod

# ─── ヘルパー ────────────────────────────────────────────────

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


def _write_state(project_dir: Path, name: str = "TestProject", **overrides) -> None:
    """プロジェクトフォルダに AI_STATE.json を書き込む。"""
    state = {**_VALID_STATE, "project_name": name, **overrides}
    (project_dir / "AI_STATE.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ─── フィクスチャ ────────────────────────────────────────────

@pytest.fixture
def project_a(tmp_path):
    """プロジェクト A を current_project として設定する。"""
    a = tmp_path / "proj_a"
    a.mkdir()
    _write_state(a, name="ProjectA")
    state_mod.set_current_project(a)
    yield a
    state_mod.set_current_project(None)


@pytest.fixture
def project_b(tmp_path):
    """プロジェクト B（current_project には設定しない）。"""
    b = tmp_path / "proj_b"
    b.mkdir()
    _write_state(b, name="ProjectB")
    yield b


# ─── テスト: 読み取り系 ──────────────────────────────────────

def test_project_path_reads_b_without_switching(project_a, project_b):
    """project_path=B 指定で collab_status が B の情報を返し、current_project は A のまま。"""
    result = server.collab_status(project_path=str(project_b))
    assert "ProjectB" in result
    # current_project は A のまま
    assert state_mod.get_current_project_raw() == project_a


def test_project_path_version_reads_b(project_a, project_b):
    """collab_version(project_path=B) がBのパスを含み、current_project は A のまま。"""
    result = server.collab_version(project_path=str(project_b))
    assert str(project_b) in result
    assert state_mod.get_current_project_raw() == project_a


def test_project_path_doctor_reads_b(project_a, project_b):
    """collab_doctor(project_path=B) がBを診断し、current_project は A のまま。"""
    result = server.collab_doctor(
        check_cli=False, check_ai_call=False,
        project_path=str(project_b),
    )
    assert "ProjectB" in result or str(project_b) in result
    assert state_mod.get_current_project_raw() == project_a


def test_project_path_summary_reads_b(project_a, project_b):
    """collab_summary(project_path=B) がBの情報を含み、current_project は A のまま。"""
    result = server.collab_summary(project_path=str(project_b))
    assert "ProjectB" in result
    assert state_mod.get_current_project_raw() == project_a


def test_project_path_search_scopes_to_b(project_a, project_b):
    """collab_search(project_path=B) がBのみを検索する。"""
    # B に固有のノートを追記
    state_b = json.loads((project_b / "AI_STATE.json").read_text(encoding="utf-8"))
    state_b["notes"].append({
        "timestamp": "2026-05-28T00:00:00", "ai": "claude",
        "text": "UNIQUE_B_NOTE_XYZ789",
    })
    (project_b / "AI_STATE.json").write_text(
        json.dumps(state_b, ensure_ascii=False), encoding="utf-8"
    )
    result = server.collab_search("UNIQUE_B_NOTE_XYZ789", project_path=str(project_b))
    assert "UNIQUE_B_NOTE_XYZ789" in result
    assert state_mod.get_current_project_raw() == project_a


# ─── テスト: 書き込み系 ──────────────────────────────────────

def test_project_path_add_note_writes_to_b_only(project_a, project_b):
    """collab_add_note(project_path=B) がBの AI_STATE.json にのみ書き込む。"""
    server.collab_add_note("B専用メモ_UNIQUE_456", project_path=str(project_b))

    # B に書き込まれている
    state_b = json.loads((project_b / "AI_STATE.json").read_text(encoding="utf-8"))
    assert any("B専用メモ_UNIQUE_456" in n.get("text", "") for n in state_b["notes"])

    # A には書き込まれていない
    state_a = json.loads((project_a / "AI_STATE.json").read_text(encoding="utf-8"))
    assert not any("B専用メモ_UNIQUE_456" in n.get("text", "") for n in state_a["notes"])

    # current_project は A のまま
    assert state_mod.get_current_project_raw() == project_a


def test_project_path_record_issue_writes_to_b_only(project_a, project_b):
    """collab_record_issue(project_path=B) がBだけに issue を記録する。"""
    server.collab_record_issue("B専用issue_TEST999", project_path=str(project_b))

    state_b = json.loads((project_b / "AI_STATE.json").read_text(encoding="utf-8"))
    assert any("B専用issue_TEST999" in i.get("text", "") for i in state_b["known_issues"])

    state_a = json.loads((project_a / "AI_STATE.json").read_text(encoding="utf-8"))
    assert not any("B専用issue_TEST999" in i.get("text", "") for i in state_a["known_issues"])

    assert state_mod.get_current_project_raw() == project_a


# ─── テスト: 旧挙動（project_path なし）──────────────────────

def test_no_project_path_uses_current_project(project_a):
    """project_path を指定しない場合は current_project (A) を使う。"""
    result = server.collab_status()
    assert "ProjectA" in result


def test_no_project_path_add_note_writes_to_a(project_a):
    """project_path なし の collab_add_note は A に書き込む。"""
    server.collab_add_note("Aへのメモ_NOPP")
    state_a = json.loads((project_a / "AI_STATE.json").read_text(encoding="utf-8"))
    assert any("Aへのメモ_NOPP" in n.get("text", "") for n in state_a["notes"])


# ─── テスト: エラー系 ─────────────────────────────────────────

def test_project_path_nonexistent_raises(project_a):
    """存在しない project_path は明確なエラーメッセージを返す。"""
    result = server.collab_status(project_path="/path/that/does/not/exist/xyz999")
    assert "エラー" in result or "見つかりません" in result or "Error" in result.lower()


def test_project_path_context_resets_after_exception(project_a, project_b):
    """例外後に ContextVar がリセットされ、次の呼び出しは current_project を使う。"""
    # B の AI_STATE.json を壊す → collab_status が途中で例外を投げる可能性は低いが、
    # project_context 自体の reset を確認する
    (project_b / "AI_STATE.json").unlink()  # B の state を削除
    # doctor は状態ファイルの有無も診断するが、project_context は必ず reset する
    try:
        server.collab_doctor(
            check_cli=False, check_ai_call=False,
            project_path=str(project_b),
        )
    except Exception:
        pass

    # ContextVar が reset されていれば次の呼び出しは A を参照する
    assert state_mod._project_override.get() is None
    result = server.collab_status()
    assert "ProjectA" in result


# ─── テスト: cwd 探索フォールバック ──────────────────────────

def test_cwd_fallback_finds_project(tmp_path, monkeypatch):
    """current_project 未設定でも cwd に AI_STATE.json があれば _get_project_dir() が返す。"""
    proj = tmp_path / "my_proj"
    proj.mkdir()
    _write_state(proj)
    state_mod.set_current_project(None)
    monkeypatch.chdir(proj)
    try:
        result_dir = state_mod._get_project_dir()
        assert result_dir == proj
    finally:
        state_mod.set_current_project(None)


def test_cwd_fallback_does_not_create(tmp_path, monkeypatch):
    """AI_STATE.json がない cwd では cwd 探索で RuntimeError になる。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    state_mod.set_current_project(None)
    monkeypatch.chdir(empty)
    try:
        with pytest.raises(RuntimeError, match="設定されていません|見つかりません"):
            state_mod._get_project_dir()
    finally:
        state_mod.set_current_project(None)


# ─── テスト: issue-027 表示系の effective project 反映 ────────

def test_current_project_shows_b_when_project_path_b(project_a, project_b):
    """current_project=A + project_path=B → collab_current_project がBを表示する。"""
    result = server.collab_current_project(project_path=str(project_b))
    assert str(project_b) in result
    assert state_mod.get_current_project_raw() == project_a


def test_current_project_none_shows_b_when_project_path_b(tmp_path):
    """current_project 未設定 + project_path=B → collab_current_project がBを表示する（未設定エラーにならない）。"""
    b = tmp_path / "proj_b"
    b.mkdir()
    _write_state(b, name="ProjectB")
    state_mod.set_current_project(None)
    try:
        result = server.collab_current_project(project_path=str(b))
        assert str(b) in result
        assert "未設定" not in result
        assert "設定されていません" not in result
    finally:
        state_mod.set_current_project(None)


def test_version_shows_b_path_when_project_path_b(project_a, project_b):
    """current_project=A + project_path=B → collab_version のプロジェクトパスがBを表示する。"""
    result = server.collab_version(project_path=str(project_b))
    assert str(project_b) in result
    assert state_mod.get_current_project_raw() == project_a


def test_version_none_shows_b_path_when_project_path_b(tmp_path):
    """current_project 未設定 + project_path=B → collab_version のプロジェクトパスがBを表示する。"""
    b = tmp_path / "proj_b"
    b.mkdir()
    _write_state(b, name="ProjectB")
    state_mod.set_current_project(None)
    try:
        result = server.collab_version(project_path=str(b))
        assert str(b) in result
    finally:
        state_mod.set_current_project(None)


# ─── テスト: issue-028 CLI系ツールの project_path 対応 ────────

def test_consult_saves_to_b_only(project_a, project_b):
    """collab_consult(project_path=B) がBのメモにだけ保存し、Aを汚さない。"""
    with patch("multiai_relay_mcp.server._call_ai_cli", return_value="モックレスポンス"):
        server.collab_consult("claude", "テスト質問_UNIQUE_CONSULT", project_path=str(project_b))

    state_b = json.loads((project_b / "AI_STATE.json").read_text(encoding="utf-8"))
    assert any("テスト質問_UNIQUE_CONSULT" in str(n) for n in state_b["notes"])

    state_a = json.loads((project_a / "AI_STATE.json").read_text(encoding="utf-8"))
    assert not any("テスト質問_UNIQUE_CONSULT" in str(n) for n in state_a["notes"])

    assert state_mod.get_current_project_raw() == project_a


def test_request_review_saves_to_b_only(project_a, project_b):
    """collab_request_review(project_path=B) がBのメモにだけ保存し、Aを汚さない。"""
    with patch("multiai_relay_mcp.server._call_ai_cli", return_value="レビューモックレスポンス"):
        server.collab_request_review("claude", scope="テスト_UNIQUE_REVIEW", project_path=str(project_b))

    state_b = json.loads((project_b / "AI_STATE.json").read_text(encoding="utf-8"))
    assert any("テスト_UNIQUE_REVIEW" in str(n) for n in state_b["notes"])

    state_a = json.loads((project_a / "AI_STATE.json").read_text(encoding="utf-8"))
    assert not any("テスト_UNIQUE_REVIEW" in str(n) for n in state_a["notes"])

    assert state_mod.get_current_project_raw() == project_a


def test_setup_cli_writes_to_b_only(project_a, project_b):
    """collab_setup_cli(project_path=B) がBのcli_config.jsonにだけ書き込み、Aを汚さない。"""
    server.collab_setup_cli("claude", "claude", project_path=str(project_b))

    assert (project_b / "cli_config.json").exists()
    assert not (project_a / "cli_config.json").exists()
    assert state_mod.get_current_project_raw() == project_a


def test_discuss_saves_to_b_only(project_a, project_b):
    """collab_discuss(project_path=B, rounds=1) がBのメモにだけ保存し、Aを汚さない。"""
    with patch("multiai_relay_mcp.server._call_ai_cli", return_value="議論モックレスポンス"):
        server.collab_discuss("claude", "テスト議題_UNIQUE_DISCUSS", rounds=1,
                               project_path=str(project_b))

    state_b = json.loads((project_b / "AI_STATE.json").read_text(encoding="utf-8"))
    assert any("テスト議題_UNIQUE_DISCUSS" in str(n) for n in state_b["notes"])

    state_a = json.loads((project_a / "AI_STATE.json").read_text(encoding="utf-8"))
    assert not any("テスト議題_UNIQUE_DISCUSS" in str(n) for n in state_a["notes"])

    assert state_mod.get_current_project_raw() == project_a
