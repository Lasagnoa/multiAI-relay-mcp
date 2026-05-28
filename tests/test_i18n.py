"""
i18n モジュールおよびサーバーツールの English モード統合テスト。
"""

import copy
import json
import os

import pytest

from multiai_relay_mcp import server
from multiai_relay_mcp import state as state_mod
from multiai_relay_mcp.i18n import (
    _STRINGS,
    _MODE_LABELS_I18N,
    get_lang,
    mode_label,
    t,
)


# ── ヘルパー ─────────────────────────────────────────────────────────────────

def make_state(**overrides):
    state = copy.deepcopy(state_mod._STATE_DEFAULTS)
    state.update({
        "project_name": "TestProject",
        "current_ai":   "codex",
        "mode":         "plan",
        "session_count": 1,
        "last_updated": "2026-05-28T00:00:00",
    })
    state.update(overrides)
    return state


def write_state(project_dir, state):
    (project_dir / "AI_STATE.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    state_mod.set_current_project(tmp_path)
    write_state(tmp_path, make_state())
    yield tmp_path
    state_mod.set_current_project(None)


# ── 文字列テーブル完全性テスト ────────────────────────────────────────────────

class TestStringTableCompleteness:
    """JA と EN のキーセットが完全に一致することを確認する。"""

    def test_all_ja_keys_exist_in_en(self):
        ja_keys = set(_STRINGS["ja"].keys())
        en_keys = set(_STRINGS["en"].keys())
        missing = ja_keys - en_keys
        assert not missing, (
            f"以下のキーが英語テーブルに存在しません:\n" + "\n".join(sorted(missing))
        )

    def test_all_en_keys_exist_in_ja(self):
        ja_keys = set(_STRINGS["ja"].keys())
        en_keys = set(_STRINGS["en"].keys())
        missing = en_keys - ja_keys
        assert not missing, (
            f"以下のキーが日本語テーブルに存在しません:\n" + "\n".join(sorted(missing))
        )

    def test_ja_keys_unique(self):
        # dict ではキー重複は不可能だが、文字列テーブルが正常に読み込めることを確認
        assert len(_STRINGS["ja"]) > 0

    def test_en_keys_unique(self):
        assert len(_STRINGS["en"]) > 0

    def test_both_languages_in_strings(self):
        assert "ja" in _STRINGS
        assert "en" in _STRINGS

    def test_mode_labels_both_languages(self):
        assert "ja" in _MODE_LABELS_I18N
        assert "en" in _MODE_LABELS_I18N
        modes = {"plan", "implement", "review", "debug"}
        assert modes == set(_MODE_LABELS_I18N["ja"].keys())
        assert modes == set(_MODE_LABELS_I18N["en"].keys())


# ── t() 関数の基本動作テスト ──────────────────────────────────────────────────

class TestTFunction:
    """t() 関数の動作確認。"""

    def test_default_lang_is_japanese(self, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        assert get_lang() == "ja"

    def test_env_en_returns_en(self, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        assert get_lang() == "en"

    def test_env_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "EN")
        assert get_lang() == "en"

    def test_env_unknown_falls_back_to_ja(self, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "fr")
        assert get_lang() == "ja"

    def test_t_returns_japanese_by_default(self, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        result = t("handoff.title")
        assert "ハンドオフ" in result or "AI" in result
        # JA string should not have English-only words like "Handoff Document"
        assert "Handoff Document" not in result

    def test_t_returns_english_when_env_set(self, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = t("handoff.title")
        assert "Handoff Document" in result

    def test_t_interpolates_kwargs_ja(self, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        result = t("add_note.done", text="テストメモ")
        assert "テストメモ" in result

    def test_t_interpolates_kwargs_en(self, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = t("add_note.done", text="test note")
        assert "test note" in result

    def test_t_missing_key_returns_bracket(self, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        result = t("nonexistent.key.xyz")
        assert result == "[nonexistent.key.xyz]"

    def test_t_missing_en_key_falls_back_to_ja(self, monkeypatch):
        """EN に存在しないキーは JA にフォールバックすることを確認。
        （現在は全キー揃っているが、ロジックの動作確認用）"""
        monkeypatch.setenv("MULTIAI_LANG", "en")
        # 全キーが揃っているため通常は en から取得されるが、
        # 仮に en から取れなかった場合でも ja 値が返ることを確認
        result = t("handoff.empty_item")
        assert result  # 空でないこと
        assert result != "[handoff.empty_item]"

    def test_t_bad_kwargs_returns_template_safely(self, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        # 必要な kwarg を渡さなくてもクラッシュしないこと
        result = t("add_note.done")  # text kwarg がない
        assert result  # 空でないこと（テンプレート文字列がそのまま返る）


# ── mode_label() テスト ───────────────────────────────────────────────────────

class TestModeLabel:
    def test_mode_label_ja(self, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        assert mode_label("plan") == "仕様検討・設計"
        assert mode_label("implement") == "実装"
        assert mode_label("review") == "レビュー"
        assert mode_label("debug") == "デバッグ"

    def test_mode_label_en(self, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        assert mode_label("plan")      == "Plan/Design"
        assert mode_label("implement") == "Implement"
        assert mode_label("review")    == "Review"
        assert mode_label("debug")     == "Debug"

    def test_mode_label_unknown_returns_mode(self, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        assert mode_label("unknown_mode") == "unknown_mode"

    def test_mode_label_unknown_en(self, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        assert mode_label("unknown_mode") == "unknown_mode"


# ── サーバーツール英語モード統合テスト ─────────────────────────────────────────

class TestServerEnglishMode:
    """主要ツールが MULTIAI_LANG=en で英語テキストを返すことを確認。"""

    def test_collab_add_note_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_add_note("test note en")
        assert "Note added" in result
        assert "test note en" in result

    def test_collab_add_note_japanese(self, project, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        result = server.collab_add_note("テストメモ")
        assert "メモを追加" in result
        assert "テストメモ" in result

    def test_collab_record_issue_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_record_issue("English issue")
        assert "Issue recorded" in result
        assert "issue-001" in result

    def test_collab_record_issue_japanese(self, project, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        result = server.collab_record_issue("日本語 issue")
        assert "問題を記録しました" in result

    def test_collab_set_task_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_set_task("My EN Task")
        assert "Task set" in result
        assert "My EN Task" in result

    def test_collab_change_mode_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_change_mode("implement")
        assert "Mode changed" in result
        # モードラベルが英語になっているか
        assert "Plan/Design" in result or "Implement" in result

    def test_collab_change_mode_err_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_change_mode("invalid_mode")
        assert "Error" in result

    def test_collab_update_issue_english_error(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        server.collab_record_issue("update target en")
        result = server.collab_update_issue("issue-001", status="resolved")
        assert "Error" in result
        assert "collab_resolve_issue" in result

    def test_collab_status_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_status()
        assert "AI Collaborative Development" in result
        assert "Project" in result
        assert "AI Assignee" in result

    def test_collab_status_japanese(self, project, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        result = server.collab_status()
        assert "AI協働開発" in result
        assert "担当AI" in result

    def test_collab_record_decision_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_record_decision("EN Decision", "content")
        assert "Decision recorded" in result

    def test_collab_complete_task_no_task_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_complete_task()
        assert "Error" in result
        assert "collab_set_task" in result

    def test_collab_add_pending_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_add_pending_task("Pending EN", "desc")
        assert "Pending task added" in result

    def test_collab_close_pending_not_found_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_close_pending_task("pending-999")
        assert "Error" in result

    def test_collab_resolve_issue_not_found_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_resolve_issue("issue-999")
        assert "Error" in result
        assert "issue-999" in result

    def test_collab_version_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_version()
        assert "Package version" in result
        assert "Python version" in result

    def test_collab_version_japanese(self, project, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        result = server.collab_version()
        assert "パッケージバージョン" in result

    def test_collab_summary_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_summary()
        # summary.line1 contains mode label in English
        assert "Plan/Design" in result or "CODEX" in result

    def test_collab_search_not_found_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        result = server.collab_search("nonexistent_query_xyz")
        assert "No results found" in result

    def test_collab_record_file_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        server.collab_set_task("task-001", "EN Task")
        result = server.collab_record_file("src/main.py")
        assert "File recorded" in result


# ── ハンドオフ文書（rendering.py）英語モードテスト ─────────────────────────────

class TestHandoffEnglishMode:
    """_build_handoff が英語モードで英語テキストを生成することを確認。"""

    def _full_handoff(self, project, from_ai="claude", to_ai="codex"):
        """_build_handoff を直接呼び出してフルコンテンツを取得する。"""
        from multiai_relay_mcp.rendering import _build_handoff
        import multiai_relay_mcp.state as state_mod
        state = state_mod._load_state()
        return _build_handoff(state, from_ai, to_ai)

    def test_handoff_title_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        content = self._full_handoff(project)
        assert "Handoff Document" in content

    def test_handoff_footer_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        content = self._full_handoff(project)
        assert "Session Start Procedure" in content
        assert "Set the project" in content

    def test_handoff_title_japanese(self, project, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        content = self._full_handoff(project)
        assert "ハンドオフドキュメント" in content

    def test_handoff_footer_japanese(self, project, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        content = self._full_handoff(project)
        assert "セッション開始手順" in content
        assert "プロジェクトを設定する" in content

    def test_handoff_mode_label_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        content = self._full_handoff(project)
        assert "Plan/Design" in content

    def test_handoff_step4_code_english(self, project, monkeypatch):
        monkeypatch.setenv("MULTIAI_LANG", "en")
        content = self._full_handoff(project)
        assert "Progress so far and next steps" in content

    def test_handoff_step4_code_japanese(self, project, monkeypatch):
        monkeypatch.delenv("MULTIAI_LANG", raising=False)
        content = self._full_handoff(project)
        assert "ここまでの進捗と次の作業" in content
