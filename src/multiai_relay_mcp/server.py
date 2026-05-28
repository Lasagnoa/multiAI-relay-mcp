#!/usr/bin/env python3
"""
AI協働開発 MCPサーバー
ClaudeとCodexが共通のツール群を通じて状態を共有するMCPサーバー

プロジェクトの切り替えは collab_switch_project() ツールで行う。
設定ファイル（config.toml / claude_desktop_config.json）は一度設定すれば変更不要。

現在のプロジェクトはプロセスのメモリ内にのみ保持される（ファイル書き出しなし）。
プロジェクトフォルダ外への書き込みは一切行わない。
"""

import copy
import hashlib
import re
import json
import datetime
import os
import sys
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import state as state_mod
from .cli import (
    _build_consult_prompt,
    _call_ai_cli,
    _cli_config_file,
    _load_cli_config,
    _resolve_cli_path,
)
from .rendering import _build_handoff
from .state import (
    DEFAULT_CLI_CONFIG,
    MODE_LABELS,
    VALID_AI,
    VALID_HANDOFF_TEMPLATES,
    VALID_ISSUE_STATUSES,
    VALID_MODES,
    VALID_SEVERITIES,
    _MAX_CATEGORY_LEN,
    _MAX_RELATED_FILES,
    _MAX_TAGS,
    _SEVERITY_EMOJI,
    _SLUG_RE,
    _STATE_DEFAULTS,
    _STATE_SCHEMA_VERSION,
    _append_session_log,
    _archive_file,
    _create_session_log,
    _get_project_dir,
    _handoff_file,
    _load_state,
    _now_iso,
    _sessions_dir,
    _state_file,
    _state_transaction,
    _validate_input,
    _validate_related_files,
    _validate_tags,
    _write_atomic,
)

#region MCPサーバーインスタンス

mcp = FastMCP(
    name="AI協働開発サーバー",
    instructions=(
        "ClaudeとCodexが協力して開発するための共有状態管理サーバーです。\n"
        "セッション開始時は必ず collab_switch_project でプロジェクトを設定してから collab_status を呼び出してください。\n"
        "作業中はこまめに collab_add_note でメモを残してください。\n"
        "セッション終了・レートリミット前には collab_checkpoint を呼び出してください。"
    ),
)

#endregion

#region MCPツール — プロジェクト管理

@mcp.tool()
def collab_switch_project(project_path: str, project_name: str = "") -> str:
    """
    作業するプロジェクトを設定または新規作成する。

    セッション開始時に必ず呼び出すこと。
    プロジェクトパスはメモリ内にのみ保持され、ファイルへの書き出しは行わない。

    - AI_STATE.json が存在する場合: 既存状態を吸収して接続（巻き戻し後も安全）
    - AI_STATE.json が存在しない場合: project_name を指定すれば新規作成、なければエラー

    Args:
        project_path: プロジェクトのフルパス（例: D:\\MyProject）
        project_name: 新規作成時のプロジェクト名。既存プロジェクトでは無視される。
    """
    # 絶対パスであることを確認（相対パスによるディレクトリトラバーサルを防ぐ）
    if not Path(project_path).is_absolute():
        return f"エラー: 絶対パスを指定してください（相対パスは不可）: {project_path}"

    path = Path(project_path).resolve()

    if not path.is_dir():
        return f"エラー: ディレクトリが存在しません: {path}"

    state_file = path / "AI_STATE.json"

    # 新規作成パス
    if not state_file.exists():
        if not project_name:
            return (
                f"AI_STATE.json が見つかりません: {path}\n"
                f"新規プロジェクトとして初期化する場合は project_name を指定してください:\n"
                f'  collab_switch_project("{path}", project_name="プロジェクト名")'
            )
        state_mod.set_current_project(path)
        initial_state = {
            "project_name": project_name,
            "current_ai": "claude",
            "mode": "plan",
            "session_count": 1,
            "last_updated": _now_iso(),
            "current_task": None,
            "completed_tasks": [],
            "notes": [],
            "key_decisions": [],
            "known_issues": [],
            "resolved_issues": [],
            "pending_tasks": [],
            "completed_pending_tasks": [],
        }
        tmp_fd, tmp_path = tempfile.mkstemp(dir=path, suffix=".tmp", prefix="AI_STATE_")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(initial_state, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, state_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        _create_session_log("claude", 1, "plan")
        return (
            f"新規プロジェクトを作成しました\n"
            f"  パス          : {path}\n"
            f"  プロジェクト名: {project_name}\n"
            f"  担当AI        : CLAUDE\n"
            f"  モード        : {MODE_LABELS['plan']}\n\n"
            f"collab_status() で詳細を確認してください。"
        )

    # 既存プロジェクトを吸収して接続（project_name は無視）
    state_mod.set_current_project(path)
    # issue-022: BOM付きJSON(utf-8-sig)も透過的に読み込む
    with open(state_file, "r", encoding="utf-8-sig") as f:
        state = json.load(f)

    absorbed = "（既存を吸収して接続）" if project_name else ""
    return (
        f"プロジェクトを設定しました{absorbed}\n"
        f"  パス          : {path}\n"
        f"  プロジェクト名: {state.get('project_name', '?')}\n"
        f"  担当AI        : {state.get('current_ai', '?').upper()}\n"
        f"  モード        : {MODE_LABELS.get(state.get('mode', ''), state.get('mode', '?'))}\n\n"
        f"collab_status() で詳細を確認してください。"
    )


@mcp.tool()
def collab_current_project() -> str:
    """現在アクティブなプロジェクトのパスと存在状態を確認する。"""
    if state_mod.get_current_project_raw() is None:
        return "現在のプロジェクトは設定されていません。collab_switch_project() を呼び出してください。"
    if not state_mod.get_current_project_raw().exists():
        return (
            f"⚠️ プロジェクトディレクトリが見つかりません: {state_mod.get_current_project_raw()}\n"
            "ディレクトリが削除・移動された可能性があります。\n"
            "collab_switch_project() で正しいパスを再設定してください。"
        )
    if not state_mod.get_current_project_raw().is_dir():
        return (
            f"⚠️ 設定パスがディレクトリではありません: {state_mod.get_current_project_raw()}\n"
            "collab_switch_project() で正しいパスを再設定してください。"
        )
    state_ok = (state_mod.get_current_project_raw() / "AI_STATE.json").exists()
    return (
        f"現在のプロジェクト: {state_mod.get_current_project_raw()}\n"
        f"  状態ファイル: {'存在 ✅' if state_ok else '未作成 ⚠️（collab_switch_project で初期化してください）'}"
    )

#endregion

#region MCPツール — 診断・情報

@mcp.tool()
def collab_version() -> str:
    """
    MCPサーバーと実行環境のバージョン情報を返す。
    """
    project_path = str(state_mod.get_current_project_raw()) if state_mod.get_current_project_raw() else "（未設定）"
    try:
        config_path     = str(_state_file())
    except RuntimeError:
        config_path     = "（未設定）"
    try:
        cli_config_path = str(_cli_config_file())
    except RuntimeError:
        cli_config_path = "（未設定）"

    lines = [
        f"multiai-relay-mcp v{_VERSION}",
        "",
        f"パッケージバージョン    : {_VERSION}",
        f"状態スキーマバージョン  : {_STATE_SCHEMA_VERSION}",
        f"Python バージョン       : {sys.version.split()[0]}",
        f"実行ファイル            : {sys.executable}",
        "",
        f"プロジェクトパス        : {project_path}",
        f"AI_STATE.json           : {config_path}",
        f"cli_config.json         : {cli_config_path}",
    ]
    return "\n".join(lines)


@mcp.tool()
def collab_doctor(
    check_cli:     bool = True,
    check_state:   bool = True,
    check_lock:    bool = True,
    check_ai_call: bool = False,
) -> str:
    """
    MCPサーバーと実行環境の健全性を診断する。

    Args:
        check_cli:     CLIコマンドの存在確認（デフォルト: True）
        check_state:   AI_STATE.json の整合性確認（デフォルト: True）
        check_lock:    ロックファイルの状態確認（デフォルト: True）
        check_ai_call: AI CLI 呼び出し確認（高コスト、デフォルト: False）
    """
    ok_items:   list[str] = []
    warn_items: list[str] = []
    err_items:  list[str] = []

    def ok(msg: str)   -> None: ok_items.append(f"✅ OK   {msg}")
    def warn(msg: str) -> None: warn_items.append(f"⚠️ WARN {msg}")
    def err(msg: str)  -> None: err_items.append(f"❌ ERR  {msg}")

    # プロジェクトフォルダ確認
    if state_mod.get_current_project_raw() is None:
        warn("プロジェクト未設定 — collab_switch_project() を呼んでください")
    elif not state_mod.get_current_project_raw().exists():
        err(f"プロジェクトフォルダが存在しない: {state_mod.get_current_project_raw()}")
    else:
        ok(f"プロジェクトフォルダ: {state_mod.get_current_project_raw()}")

    # 状態ファイル確認
    if check_state and state_mod.get_current_project_raw() and state_mod.get_current_project_raw().exists():
        sf = _state_file()
        if not sf.exists():
            warn("AI_STATE.json が未作成 — collab_switch_project() で新規作成できます")
        else:
            try:
                state = _load_state()
                ok(
                    f"AI_STATE.json 正常"
                    f" (担当: {state.get('current_ai','?').upper()}"
                    f", セッション: #{state.get('session_count','?')})"
                )
            except Exception as e:
                err(f"AI_STATE.json 読み込み失敗: {e}")

    # ロックファイル確認
    if check_lock and state_mod.get_current_project_raw() and state_mod.get_current_project_raw().exists():
        lock_file = _get_project_dir() / "AI_STATE.lock"
        if lock_file.exists():
            try:
                data = json.loads(lock_file.read_text(encoding="utf-8"))
                pid  = data.get("pid", 0)
                if _pid_exists(pid):
                    warn(f"ロックファイルあり (PID {pid} は生存中) — 別プロセスが書き込み中の可能性")
                else:
                    warn(f"古いロックファイルあり (PID {pid} は不在) — 次回書き込み時に自動解除されます")
            except Exception:
                warn("ロックファイルあり（解析不能）— 手動削除を検討: AI_STATE.lock")
        else:
            ok("ロックファイルなし（正常）")

    # CLI コマンド確認
    if check_cli:
        config = _load_cli_config()
        for ai_name in VALID_AI:
            cfg  = config.get(ai_name, {})
            cmd  = cfg.get("command", DEFAULT_CLI_CONFIG[ai_name]["command"])
            path = _resolve_cli_path(ai_name, cmd)
            if path:
                ok(f"{ai_name.upper()} CLI: {path}")
            else:
                warn(f"{ai_name.upper()} CLI 未検出 ({cmd}) — collab_setup_cli() で設定してください")

    # AI 呼び出し確認（高コスト・オプション）
    if check_ai_call:
        for ai_name in VALID_AI:
            config = _load_cli_config()
            cfg    = config.get(ai_name, {})
            cmd    = cfg.get("command", DEFAULT_CLI_CONFIG[ai_name]["command"])
            path   = _resolve_cli_path(ai_name, cmd)
            if not path:
                warn(f"{ai_name.upper()} CLI 呼び出しテストをスキップ（コマンド未検出）")
                continue
            try:
                result = _call_ai_cli(ai_name, "ヘルスチェックです。「OK」とだけ答えてください。", timeout=30)
                if result.startswith("エラー"):
                    warn(f"{ai_name.upper()} CLI 応答エラー: {result[:80]}")
                else:
                    ok(f"{ai_name.upper()} CLI 呼び出し成功")
            except Exception as e:
                err(f"{ai_name.upper()} CLI 呼び出し例外: {e}")

    summary  = f"OK: {len(ok_items)}件  WARN: {len(warn_items)}件  ERR: {len(err_items)}件"
    all_items = ok_items + warn_items + err_items
    return f"# 診断結果 — {summary}\n" + "\n".join(all_items)

#endregion

#region MCPツール — 状態管理

@mcp.tool()
def collab_status(calling_ai: str = "") -> str:
    """
    現在の協働開発状態を取得する。

    セッション開始時に必ず呼び出すこと。
    担当AI・モード・現在タスク・保留タスク・メモ・決定事項・既知の問題を返す。

    Args:
        calling_ai: 呼び出し元のAI（"claude" / "codex"）。指定すると担当AI不一致を警告する。
    """
    state = _load_state()

    lines = [
        "# AI協働開発 現在の状態",
        f"プロジェクト : {state['project_name']}",
        f"パス         : {_get_project_dir()}",
        f"担当AI       : {state['current_ai'].upper()}",
        f"モード       : {MODE_LABELS.get(state['mode'], state['mode'])}",
        f"セッション   : #{state['session_count']}",
        f"最終更新     : {state['last_updated']}",
    ]

    # 担当AI不一致の警告
    if calling_ai and calling_ai in VALID_AI and calling_ai != state.get("current_ai"):
        lines = [
            "⚠️ 担当AI不一致の警告",
            f"  現在の担当: {state['current_ai'].upper()}",
            f"  呼び出し元: {calling_ai.upper()}",
            "  → 必要なら collab_generate_handoff() で担当AIを切り替えてください。",
            "",
        ] + lines

    lines += ["", "## 現在のタスク"]
    if state.get("current_task"):
        task = state["current_task"]
        lines += [f"ID      : {task['id']}", f"タイトル: {task['title']}"]
        if task.get("description"):
            lines.append(f"詳細    : {task['description']}")
        lines.append(f"開始    : {task['started_at'][:16]}  担当: {task.get('started_by', '?').upper()}")
        if task.get("files_modified"):
            lines.append("変更済みファイル:")
            for fp in task["files_modified"]:
                lines.append(f"  - {fp}")
    else:
        lines.append("未設定")

    if state.get("pending_tasks"):
        lines += ["", "## 保留中のタスク"]
        for t in state["pending_tasks"]:
            lines.append(f"- [{t['id']}] {t['title']}")

    if state.get("notes"):
        lines += ["", "## 最近のメモ（最新5件）"]
        for n in state["notes"][-5:]:
            lines.append(f"- [{n['timestamp'][:16]}] ({n['ai'].upper()}) {n['text']}")

    if state.get("key_decisions"):
        lines += ["", "## 重要な決定事項"]
        for dec in state["key_decisions"]:
            lines.append(f"- [{dec['timestamp'][:10]}] {dec['title']}: {dec['content'][:100]}")

    if state.get("known_issues"):
        lines += ["", "## 既知の問題・注意点"]
        # severity 昇順（P0優先）でソート
        sorted_issues = sorted(
            state["known_issues"],
            key=lambda i: VALID_SEVERITIES.index(i.get("severity", "P2"))
            if isinstance(i, dict) and i.get("severity") in VALID_SEVERITIES else 99
        )
        for issue in sorted_issues:
            if isinstance(issue, dict):
                emoji = _SEVERITY_EMOJI.get(issue.get("severity", "P2"), "")
                sev   = issue.get("severity", "P2")
                stat  = "" if issue.get("status", "open") == "open" else f" [{issue['status']}]"
                tags  = f" ({', '.join(issue['tags'])})" if issue.get("tags") else ""
                # 旧テキストに [P0]〜[P3] プレフィックスが残っている場合は表示上だけ除去する
                text  = re.sub(r'^\[P[0-3]\]\s*', '', issue['text'])
                lines.append(f"- {emoji} [{issue['id']}][{sev}]{stat} {text}{tags}")
            else:
                lines.append(f"- {issue}")

    return "\n".join(lines)


@mcp.tool()
def collab_set_task(title: str, description: str = "") -> str:
    """
    現在のタスクを設定する。既存のタスクは自動的に完了済みに移動する。

    Args:
        title: タスクのタイトル
        description: タスクの詳細説明（省略可）
    """
    err = _validate_input(title, "title") or (description and _validate_input(description, "description"))
    if err:
        return err
    with _state_transaction() as state:
        if state.get("current_task"):
            old = state["current_task"]
            old["completed_at"] = _now_iso()
            state["completed_tasks"].append(old)

        task_id = f"task-{len(state['completed_tasks']) + 1:03d}"
        state["current_task"] = {
            "id": task_id, "title": title, "description": description,
            "started_at": _now_iso(), "started_by": state["current_ai"],
            "files_modified": [],
        }
        ai = state["current_ai"]
    _append_session_log(ai, f"タスク開始: [{task_id}] {title}")
    return f"タスクを設定しました: [{task_id}] {title}"


@mcp.tool()
def collab_add_note(message: str) -> str:
    """
    作業メモを追加する。こまめに呼び出すことでハンドオフ精度が上がる。

    Args:
        message: メモの内容
    """
    err = _validate_input(message, "message")
    if err:
        return err
    with _state_transaction() as state:
        state["notes"].append({"timestamp": _now_iso(), "ai": state["current_ai"], "text": message})
        ai = state["current_ai"]
    _append_session_log(ai, f"メモ: {message}")
    return f"メモを追加しました: {message}"


@mcp.tool()
def collab_record_decision(title: str, content: str) -> str:
    """
    重要な設計・実装の決定事項を記録する。

    Args:
        title: 決定事項のタイトル
        content: 決定内容と理由
    """
    err = _validate_input(title, "title") or _validate_input(content, "content")
    if err:
        return err
    with _state_transaction() as state:
        state["key_decisions"].append({
            "timestamp": _now_iso(), "ai": state["current_ai"],
            "title": title, "content": content,
        })
        ai = state["current_ai"]
    _append_session_log(ai, f"決定事項記録: {title}")
    return f"決定事項を記録しました: {title}"


@mcp.tool()
def collab_record_issue(
    message: str,
    severity: str = "P2",
    category: str = "general",
    tags: list | None = None,
    related_files: list | None = None,
) -> str:
    """
    既知の問題・バグ・注意点を記録する。

    Args:
        message:       問題の説明
        severity:      深刻度 P0（最高）/ P1 / P2（既定）/ P3（低）
        category:      カテゴリ（slug形式: 英数字・ハイフン・アンダースコア、例: "auth"）
        tags:          タグリスト（省略可、例: ["routing", "login"]）
        related_files: 関連ファイルのプロジェクト相対パスリスト（省略可）
    """
    tags         = tags or []
    related_files = related_files or []

    # 入力検証
    err = (_validate_input(message, "message")
           or (severity not in VALID_SEVERITIES and f"エラー: severity は {VALID_SEVERITIES} のいずれかを指定してください。")
           or (not _SLUG_RE.match(category) and f"エラー: category はslug形式（英数字・ハイフン・アンダースコア）で指定してください: {category!r}")
           or (len(category) > _MAX_CATEGORY_LEN and f"エラー: category は最大{_MAX_CATEGORY_LEN}文字です。")
           or _validate_tags(tags)
           or _validate_related_files(related_files))
    if err:
        return err

    with _state_transaction() as state:
        # 既存・解決済み両方のIDを参照して単調増加IDを採番
        all_issues = state.get("known_issues", []) + state.get("resolved_issues", [])
        issue_numbers = [
            int(iss["id"].split("-")[-1])
            for iss in all_issues
            if isinstance(iss, dict)
            and iss.get("id", "").startswith("issue-")
            and iss["id"].split("-")[-1].isdigit()
        ]
        issue_id = f"issue-{max(issue_numbers, default=0) + 1:03d}"
        state["known_issues"].append({
            "id":            issue_id,
            "text":          message,
            "severity":      severity,
            "category":      category,
            "tags":          tags,
            "related_files": related_files,
            "status":        "open",
            "added_at":      _now_iso(),
            "added_by":      state["current_ai"],
        })
        ai = state["current_ai"]
    emoji = _SEVERITY_EMOJI.get(severity, "")
    _append_session_log(ai, f"問題記録: [{issue_id}][{severity}] {message}")
    return f"問題を記録しました: {emoji} [{issue_id}][{severity}] {message}"


@mcp.tool()
def collab_resolve_issue(issue_id: str, note: str = "") -> str:
    """
    既知の問題を解決済みにして一覧から取り除く。

    Args:
        issue_id: 解決する問題のID（例: issue-001）。collab_status で確認できる。
        note: 解決内容の補足（省略可）
    """
    # issue-016: note の入力検証
    if note:
        err = _validate_input(note, "note")
        if err:
            return err
    # issue-014: issue_id の存在チェックを transaction 外で先に行う
    pre = _load_state()
    if not any(isinstance(i, dict) and i.get("id") == issue_id for i in pre.get("known_issues", [])):
        return f"エラー: 問題が見つかりません: {issue_id}（collab_status で ID を確認してください）"

    with _state_transaction() as state:
        issues = state.get("known_issues", [])
        matched_index = next(
            (i for i, iss in enumerate(issues)
             if isinstance(iss, dict) and iss.get("id") == issue_id),
            None,
        )
        if matched_index is None:
            return f"エラー: 問題が見つかりません: {issue_id}（collab_status で ID を確認してください）"
        issue = issues.pop(matched_index)
        issue["resolved_at"] = _now_iso()
        issue["resolved_by"] = state["current_ai"]
        if note:
            issue["resolution_note"] = note
        state.setdefault("resolved_issues", []).append(issue)
        ai = state["current_ai"]
    _append_session_log(ai, f"問題解決: [{issue_id}] {issue['text'][:60]}")
    return f"問題を解決済みにしました: [{issue_id}] {issue['text']}"


@mcp.tool()
def collab_update_issue(
    issue_id: str,
    message: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    tags: list | None = None,
    add_tags: list | None = None,
    remove_tags: list | None = None,
    related_files: list | None = None,
    add_related_files: list | None = None,
    remove_related_files: list | None = None,
    status: str | None = None,
) -> str:
    """
    既存の未解決 issue のメタデータを更新する。

    解決済みにする場合は collab_resolve_issue() を使うこと（このツールでは resolved 化不可）。

    Args:
        issue_id:            更新する issue の ID（例: "issue-001"）
        message:             説明文を置換する（省略で変更なし）
        severity:            P0/P1/P2/P3 に変更（省略で変更なし）
        category:            カテゴリを変更（省略で変更なし）
        tags:                タグリストを完全置換（省略で変更なし）
        add_tags:            タグを追記（tags と同時指定不可）
        remove_tags:         タグを削除（tags と同時指定不可）
        related_files:       関連ファイルリストを完全置換（省略で変更なし）
        add_related_files:   関連ファイルを追記（related_files と同時指定不可）
        remove_related_files:関連ファイルを削除（related_files と同時指定不可）
        status:              "open" / "deferred" に変更（省略で変更なし）
    """
    # 排他チェック
    if tags is not None and (add_tags is not None or remove_tags is not None):
        return "エラー: tags と add_tags/remove_tags は同時に指定できません。"
    if related_files is not None and (add_related_files is not None or remove_related_files is not None):
        return "エラー: related_files と add_related_files/remove_related_files は同時に指定できません。"

    # 入力検証
    if message is not None:
        err = _validate_input(message, "message")
        if err:
            return err
    if severity is not None and severity not in VALID_SEVERITIES:
        return f"エラー: severity は {VALID_SEVERITIES} のいずれかを指定してください。"
    if category is not None:
        if not _SLUG_RE.match(category):
            return f"エラー: category はslug形式で指定してください: {category!r}"
        if len(category) > _MAX_CATEGORY_LEN:
            return f"エラー: category は最大{_MAX_CATEGORY_LEN}文字です。"
    if status is not None and status not in VALID_ISSUE_STATUSES:
        return f"エラー: status は {VALID_ISSUE_STATUSES} のいずれかを指定してください（resolved 化は collab_resolve_issue を使ってください）。"
    for tag_list, label in [(tags, "tags"), (add_tags, "add_tags"), (remove_tags, "remove_tags")]:
        if tag_list is not None:
            err = _validate_tags(tag_list, label)
            if err:
                return err
    for file_list, label in [(related_files, "related_files"),
                              (add_related_files, "add_related_files"),
                              (remove_related_files, "remove_related_files")]:
        if file_list is not None:
            err = _validate_related_files(file_list)
            if err:
                return err

    # issue-014: 存在チェックを transaction 外で先に行う
    pre = _load_state()
    if not any(isinstance(i, dict) and i.get("id") == issue_id for i in pre.get("known_issues", [])):
        return f"エラー: 未解決の問題が見つかりません: {issue_id}（解決済み issue は更新不可）"

    with _state_transaction() as state:
        issue = next(
            (i for i in state.get("known_issues", [])
             if isinstance(i, dict) and i.get("id") == issue_id),
            None,
        )
        if issue is None:
            return f"エラー: 問題が見つかりません: {issue_id}"

        if message is not None:
            issue["text"] = message
        if severity is not None:
            issue["severity"] = severity
        if category is not None:
            issue["category"] = category
        if status is not None:
            issue["status"] = status

        # tags の更新
        if tags is not None:
            issue["tags"] = tags
        else:
            current_tags = issue.get("tags", [])
            if add_tags:
                for t in add_tags:
                    if t not in current_tags:
                        current_tags.append(t)
                issue["tags"] = current_tags[:_MAX_TAGS]
            if remove_tags:
                issue["tags"] = [t for t in issue.get("tags", []) if t not in remove_tags]

        # related_files の更新
        if related_files is not None:
            issue["related_files"] = related_files
        else:
            current_files = issue.get("related_files", [])
            if add_related_files:
                for f in add_related_files:
                    if f not in current_files:
                        current_files.append(f)
                issue["related_files"] = current_files[:_MAX_RELATED_FILES]
            if remove_related_files:
                issue["related_files"] = [f for f in issue.get("related_files", [])
                                           if f not in remove_related_files]
        ai = state["current_ai"]

    emoji = _SEVERITY_EMOJI.get(issue.get("severity", "P2"), "")
    _append_session_log(ai, f"問題更新: [{issue_id}]")
    return (
        f"問題を更新しました: {emoji} [{issue_id}][{issue.get('severity','?')}] {issue['text']}\n"
        f"  category: {issue.get('category','?')}  "
        f"tags: {issue.get('tags',[])}  "
        f"status: {issue.get('status','?')}"
    )


@mcp.tool()
def collab_list_resolved() -> str:
    """
    解決済みの問題一覧を表示する。

    collab_resolve_issue() で解決済みにした問題を新しい順で一覧表示する。
    """
    state = _load_state()
    resolved = state.get("resolved_issues", [])
    if not resolved:
        return "解決済みの問題はありません。"

    lines = [f"# 解決済みの問題一覧（{len(resolved)}件）", ""]
    for iss in reversed(resolved):  # 新しい順
        resolved_at = iss.get("resolved_at", "?")[:16]
        resolved_by = iss.get("resolved_by", "?").upper()
        emoji = _SEVERITY_EMOJI.get(iss.get("severity", "P2"), "")
        sev   = iss.get("severity", "?")
        tags  = f" ({', '.join(iss['tags'])})" if iss.get("tags") else ""
        # 旧テキストに [P0]〜[P3] プレフィックスが残っている場合は表示上だけ除去する
        text  = re.sub(r'^\[P[0-3]\]\s*', '', iss['text'])
        lines.append(f"- {emoji} [{iss['id']}][{sev}] {text}{tags}")
        lines.append(f"  解決: {resolved_at}  by {resolved_by}")
        if iss.get("resolution_note"):
            lines.append(f"  メモ: {iss['resolution_note']}")
    return "\n".join(lines)


@mcp.tool()
def collab_record_file(file_path: str) -> str:
    """
    現在のタスクで変更・作成したファイルを記録する。

    Args:
        file_path: ファイルパス（プロジェクトルートからの相対パス推奨）
    """
    # issue-016: ファイルパスの長さ・インジェクションタグ・制御文字を検証
    err = _validate_input(file_path, "file_path")
    if err:
        return err
    if any(c in file_path for c in ("\n", "\r", "\0")):
        return "エラー: file_path に改行・制御文字は使用できません。"

    # issue-014: current_task チェックを transaction 外で行い、
    #            エラー時に last_updated が更新されないようにする
    if not _load_state().get("current_task"):
        return "エラー: 現在のタスクが設定されていません。先に collab_set_task を呼び出してください。"

    with _state_transaction() as state:
        if not state.get("current_task"):  # ロック内での二重確認
            return "エラー: 現在のタスクが設定されていません。先に collab_set_task を呼び出してください。"
        files = state["current_task"]["files_modified"]
        already = file_path in files
        if not already:
            files.append(file_path)
        ai = state["current_ai"]
    if already:
        return f"既に記録済みです: {file_path}"
    _append_session_log(ai, f"ファイル記録: {file_path}")
    return f"ファイルを記録しました: {file_path}"


@mcp.tool()
def collab_change_mode(mode: str) -> str:
    """
    作業モードを変更する。

    Args:
        mode: plan（仕様検討）/ implement（実装）/ review（レビュー）/ debug（デバッグ）
    """
    if mode not in VALID_MODES:
        return f"エラー: モードは {' | '.join(VALID_MODES)} のいずれかを指定してください。"
    with _state_transaction() as state:
        old_mode = state["mode"]
        state["mode"] = mode
        ai = state["current_ai"]
    _append_session_log(ai, f"モード変更: {old_mode} → {mode}")
    return f"モードを変更しました: {MODE_LABELS.get(old_mode, old_mode)} → {MODE_LABELS.get(mode, mode)}"


@mcp.tool()
def collab_add_pending_task(title: str, description: str = "") -> str:
    """
    保留タスクキューにタスクを追加する。

    Args:
        title: タスクのタイトル
        description: タスクの詳細説明（省略可）
    """
    err = _validate_input(title, "title") or (description and _validate_input(description, "description"))
    if err:
        return err
    with _state_transaction() as state:
        task_numbers = [
            int(t["id"].split("-")[-1])
            for t in state.get("pending_tasks", []) + state.get("completed_pending_tasks", [])
            if t.get("id", "").startswith("pending-") and t["id"].split("-")[-1].isdigit()
        ]
        task_id = f"pending-{max(task_numbers, default=0) + 1:03d}"
        state["pending_tasks"].append({
            "id": task_id,
            "title": title, "description": description,
            "added_at": _now_iso(), "added_by": state["current_ai"],
        })
        ai = state["current_ai"]
    _append_session_log(ai, f"保留タスク追加: {title}")
    return f"保留タスクに追加しました: [{task_id}] {title}"


@mcp.tool()
def collab_close_pending_task(task_id: str, note: str = "") -> str:
    """
    保留タスクを完了扱いにし、保留一覧から取り除く。

    Args:
        task_id: 完了する保留タスクID（例: pending-001）
        note: 完了時に残す補足（省略可）
    """
    # issue-016: note の入力検証
    if note:
        err = _validate_input(note, "note")
        if err:
            return err
    # issue-014: task_id の存在チェックを transaction 外で先に行う
    if not any(t.get("id") == task_id for t in _load_state().get("pending_tasks", [])):
        return f"エラー: 保留タスクが見つかりません: {task_id}"

    with _state_transaction() as state:
        pending = state.get("pending_tasks", [])
        matched_index = next((i for i, task in enumerate(pending) if task.get("id") == task_id), None)
        if matched_index is None:
            return f"エラー: 保留タスクが見つかりません: {task_id}"
        task = pending.pop(matched_index)
        task["completed_at"] = _now_iso()
        task["completed_by"] = state["current_ai"]
        if note:
            task["completion_note"] = note
        state.setdefault("completed_pending_tasks", []).append(task)
        ai = state["current_ai"]
    _append_session_log(ai, f"保留タスク完了: [{task_id}] {task['title']}")
    return f"保留タスクを完了しました: [{task_id}] {task['title']}"


@mcp.tool()
def collab_complete_task(note: str = "") -> str:
    """
    現在のタスクを完了済みにして一覧から取り除く。

    collab_set_task() で新タスクを作らずに現在タスクを完了させたい場合に使う。
    完了後は current_task が未設定になる。

    Args:
        note: 完了時のメモ・備考（省略可）
    """
    if note:
        err = _validate_input(note, "note")
        if err:
            return err
    # issue-014: current_task チェックを transaction 外で先に行う
    if not _load_state().get("current_task"):
        return "エラー: 現在のタスクが設定されていません。collab_set_task() で先にタスクを設定してください。"

    with _state_transaction() as state:
        if not state.get("current_task"):  # ロック内での二重確認
            return "エラー: 現在のタスクが設定されていません。collab_set_task() で先にタスクを設定してください。"
        task = state["current_task"]
        task["completed_at"] = _now_iso()
        task["completed_by"] = state["current_ai"]
        if note:
            task["completion_note"] = note
        state["completed_tasks"].append(task)
        state["current_task"] = None
        ai = state["current_ai"]
    _append_session_log(ai, f"タスク完了: [{task['id']}] {task['title']}")
    return f"タスクを完了しました: [{task['id']}] {task['title']}"


@mcp.tool()
def collab_generate_handoff(to_ai: str, dry_run: bool = False) -> str:
    """
    ハンドオフドキュメントを生成して担当AIを切り替える。

    Args:
        to_ai: 引き継ぎ先のAI。"claude" または "codex"
        dry_run: True にすると実際の書き込み・担当切り替えを行わずプレビューのみ返す
    """
    if to_ai not in VALID_AI:
        return f"エラー: AIは 'claude' または 'codex' を指定してください。"

    # dry_run: 状態変更・ファイル書き込みなしでプレビューのみ返す
    if dry_run:
        state   = _load_state()
        from_ai = state["current_ai"]
        preview = _build_handoff(state, from_ai, to_ai)
        return json.dumps({
            "dry_run":          True,
            "would_write_path": str(_handoff_file()),
            "from_ai":          from_ai,
            "target_ai":        to_ai,
            "preview_chars":    len(preview),
            "preview":          preview[:800] + ("…（以降省略）" if len(preview) > 800 else ""),
            "warnings":         [],
        }, ensure_ascii=False, indent=2)

    with _state_transaction() as state:
        from_ai = state["current_ai"]
        # ハンドオフ文書はロック内で原子的に生成（状態と内容の一貫性を保つ）
        _write_atomic(_handoff_file(), _build_handoff(state, from_ai, to_ai))
        state["current_ai"]    = to_ai
        state["session_count"] += 1
        new_session = state["session_count"]
        mode        = state["mode"]

    _append_session_log(from_ai, f"ハンドオフ: {from_ai.upper()} → {to_ai.upper()}")
    _create_session_log(to_ai, new_session, mode)

    return (
        f"ハンドオフを生成しました: {from_ai.upper()} → {to_ai.upper()}\n"
        f"ファイル: {_handoff_file()}\n\n"
        f"{'Claude' if to_ai == 'claude' else 'Codex'} Desktop の新しいセッションで\n"
        f"「HANDOFF.md を読んで続きをお願いします」と伝えてください。"
    )


@mcp.tool()
def collab_checkpoint(message: str, to_ai: str = "", dry_run: bool = False) -> str:
    """
    作業メモの追加とハンドオフ生成を一度に行う。

    Args:
        message: 引き継ぎに残す進捗・次の作業内容
        to_ai: 引き継ぎ先。"claude" / "codex"。省略時は現在担当でないAI。
        dry_run: True にするとメモ追加・ファイル書き込み・担当切り替えを行わずプレビューのみ返す
    """
    err = _validate_input(message, "message")
    if err:
        return err
    # issue-014: to_ai が明示指定されていて不正な場合は transaction 外で弾く
    if to_ai and to_ai not in VALID_AI:
        return "エラー: AIは 'claude' または 'codex' を指定してください。"

    # dry_run: 状態変更・ファイル書き込みなしでプレビューのみ返す
    if dry_run:
        state     = _load_state()
        from_ai   = state["current_ai"]
        target_ai = to_ai or ("claude" if from_ai == "codex" else "codex")
        # メモを仮追加したコピーでプレビュー（実際の state には書き込まない）
        preview_state = copy.deepcopy(state)
        preview_state["notes"].append({"timestamp": _now_iso(), "ai": from_ai, "text": message})
        preview = _build_handoff(preview_state, from_ai, target_ai)
        return json.dumps({
            "dry_run":          True,
            "would_write_path": str(_handoff_file()),
            "from_ai":          from_ai,
            "target_ai":        target_ai,
            "preview_chars":    len(preview),
            "preview":          preview[:800] + ("…（以降省略）" if len(preview) > 800 else ""),
            "warnings":         [],
        }, ensure_ascii=False, indent=2)

    with _state_transaction() as state:
        from_ai = state["current_ai"]
        target_ai = to_ai or ("claude" if from_ai == "codex" else "codex")
        state["notes"].append({"timestamp": _now_iso(), "ai": from_ai, "text": message})
        _write_atomic(_handoff_file(), _build_handoff(state, from_ai, target_ai))
        state["current_ai"] = target_ai
        state["session_count"] += 1
        new_session = state["session_count"]
        mode = state["mode"]

    _append_session_log(from_ai, f"メモ: {message}")
    _append_session_log(from_ai, f"チェックポイント/ハンドオフ: {from_ai.upper()} → {target_ai.upper()}")
    _create_session_log(target_ai, new_session, mode)
    return (
        f"チェックポイントを生成しました: {from_ai.upper()} → {target_ai.upper()}\n"
        f"メモ: {message}\n"
        f"ファイル: {_handoff_file()}"
    )

#endregion

#region MCPツール — AI相談・議論

@mcp.tool()
def collab_consult(ai: str, question: str, save_result: bool = True) -> str:
    """
    相手のAI（CLIバージョン）を一時的に呼び出して相談する。

    Claude Desktop から呼ぶと Codex CLI に相談でき、
    Codex Desktop から呼ぶと Claude CLI に相談できる。

    Args:
        ai: 呼び出すAI。"claude" または "codex"
        question: 相談・質問の内容
        save_result: 回答をメモとして状態に保存するか（デフォルト: True）
    """
    if ai not in VALID_AI:
        return f"エラー: ai は 'claude' または 'codex' を指定してください。"
    err = _validate_input(question, "question")
    if err:
        return err

    response = _call_ai_cli(ai, _build_consult_prompt(question))

    save_failed = False
    if save_result:
        try:
            short_q = question[:60] + ("…" if len(question) > 60 else "")
            with _state_transaction() as state:
                state["notes"].append({
                    "timestamp": _now_iso(), "ai": state["current_ai"],
                    "text": f"[{ai.upper()}に相談] {short_q}",
                    "consult": {"question": question, "response": response},
                })
                caller_ai = state["current_ai"]
            _append_session_log(caller_ai, f"{ai.upper()}CLIへの相談: {short_q}")
        except Exception:
            save_failed = True

    result = f"【{ai.upper()} CLI の回答】\n\n{response}"
    if save_failed:
        result += "\n\n⚠️ メモへの保存に失敗しました"
    return result


@mcp.tool()
def collab_discuss(ai: str, topic: str, rounds: int = 2) -> str:
    """
    相手のAI（CLIバージョン）と複数ラウンドの議論を行う。
    ラウンドごとにトークンを消費するため rounds は 2〜3 を推奨。

    Args:
        ai: 議論相手のAI。"claude" または "codex"
        topic: 議論するテーマ・問題
        rounds: 往復ラウンド数（デフォルト: 2、最大: 4）
    """
    if ai not in VALID_AI:
        return f"エラー: ai は 'claude' または 'codex' を指定してください。"
    err = _validate_input(topic, "topic")
    if err:
        return err

    rounds = min(max(rounds, 1), 4)
    history: list[dict] = []
    current_prompt = topic

    for i in range(rounds):
        context = _build_consult_prompt(current_prompt)
        if history:
            context += "\n\n---\n\n## これまでの議論の流れ\n"
            for h in history:
                context += f"\n**{h['speaker']}:** {h['text'][:400]}\n"
        response = _call_ai_cli(ai, context)
        history.append({"speaker": ai.upper(), "text": response})
        if i + 1 < rounds:
            current_prompt = (
                f"以下の回答を踏まえて、さらに深掘りした質問や意見を述べてください:\n\n{response[:600]}"
            )

    result_lines = [f"【{ai.upper()} CLI との議論結果】（{rounds}ラウンド）", ""]
    for j, h in enumerate(history, 1):
        result_lines += [f"### ラウンド {j} — {h['speaker']}", "", h["text"], ""]
    result = "\n".join(result_lines)

    save_failed = False
    try:
        short_topic = topic[:60] + ("…" if len(topic) > 60 else "")
        with _state_transaction() as state:
            state["notes"].append({
                "timestamp": _now_iso(), "ai": state["current_ai"],
                "text": f"[{ai.upper()}と議論] {short_topic}",
                "discuss": {"topic": topic, "rounds": rounds, "history": history},
            })
            caller_ai = state["current_ai"]
        _append_session_log(caller_ai, f"{ai.upper()}CLIとの議論: {short_topic}")
    except Exception:
        save_failed = True

    if save_failed:
        result += "\n⚠️ メモへの保存に失敗しました"
    return result


@mcp.tool()
def collab_setup_cli(ai: str, command: str, args_before: list[str] = [], args_after: list[str] = []) -> str:
    """
    CLI の呼び出し設定をカスタマイズして保存する。
    デフォルト設定で動かない場合に使う。

    Args:
        ai: 設定するAI。"claude" または "codex"
        command: CLIのコマンド名またはフルパス
        args_before: プロンプトの前に渡す引数
        args_after: プロンプトの後に渡す引数
    """
    # ai の検証
    if ai not in VALID_AI:
        return f"エラー: ai は 'claude' または 'codex' を指定してください。"

    # command の検証: ファイル名のステム（拡張子なし）が VALID_AI に含まれるもののみ許可
    cmd_stem = Path(command).stem.lower()
    if cmd_stem not in VALID_AI:
        return (
            f"エラー: command に設定できるのは 'claude' または 'codex' の実行ファイルのみです。\n"
            f"指定値: {command}（ファイル名: {cmd_stem}）"
        )

    # args の型検証
    if not isinstance(args_before, list):
        args_before = []
    if not isinstance(args_after, list):
        args_after = []

    cfg_file = _cli_config_file()
    config = {}
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8-sig") as f:
            config = json.load(f)

    config[ai] = {"command": command, "args_before": args_before, "args_after": args_after}
    _write_atomic(cfg_file, json.dumps(config, ensure_ascii=False, indent=2))

    path = _resolve_cli_path(ai, command)
    status = f"見つかりました: {path}" if path else "⚠ 見つかりません。パスを確認してください。"
    return (
        f"CLI設定を保存しました: {cfg_file}\n"
        f"  AI      : {ai.upper()}\n"
        f"  command : {command}  →  {status}\n"
        f"  実行例  : {command} {' '.join(args_before)} \"<プロンプト>\" {' '.join(args_after)}"
    )

#endregion

#region MCPツール — メンテナンス

@mcp.tool()
def collab_search(query: str) -> str:
    """
    キーワードでメモ・決定事項・問題・タスクを横断検索する。

    メモ・決定事項・既知の問題・解決済み問題・保留タスク・現在タスクを
    大文字小文字を区別せずにキーワード検索する。

    Args:
        query: 検索キーワード
    """
    state = _load_state()
    q = query.lower()
    results: list[str] = []

    # メモ
    for n in state.get("notes", []):
        text = n.get("text", "")
        if q in text.lower():
            results.append(f"[メモ]   {n['timestamp'][:16]} ({n['ai'].upper()}) {text}")

    # 決定事項
    for d in state.get("key_decisions", []):
        title, content = d.get("title", ""), d.get("content", "")
        if q in title.lower() or q in content.lower():
            results.append(f"[決定]   {d['timestamp'][:10]} {title}: {content[:100]}")

    # 既知の問題（text + category + tags + related_files も検索対象）
    for iss in state.get("known_issues", []):
        if not isinstance(iss, dict):
            continue
        hit = (q in iss.get("text", "").lower()
               or q in iss.get("category", "").lower()
               or any(q in t.lower() for t in iss.get("tags", []))
               or any(q in fp.lower() for fp in iss.get("related_files", [])))
        if hit:
            emoji = _SEVERITY_EMOJI.get(iss.get("severity", "P2"), "")
            results.append(f"[問題]   {emoji}[{iss['id']}][{iss.get('severity','?')}] {iss['text']}")

    # 解決済みの問題（同様に拡張フィールドも検索）
    for iss in state.get("resolved_issues", []):
        if not isinstance(iss, dict):
            continue
        hit = (q in iss.get("text", "").lower()
               or q in iss.get("category", "").lower()
               or any(q in t.lower() for t in iss.get("tags", []))
               or any(q in fp.lower() for fp in iss.get("related_files", []))
               or q in iss.get("resolution_note", "").lower())
        if hit:
            emoji = _SEVERITY_EMOJI.get(iss.get("severity", "P2"), "")
            results.append(f"[解決済] {emoji}[{iss['id']}][{iss.get('severity','?')}] {iss['text']}")

    # 保留タスク
    for t in state.get("pending_tasks", []):
        if q in t.get("title", "").lower() or q in t.get("description", "").lower():
            results.append(f"[保留]   [{t['id']}] {t['title']}")

    # 現在タスク
    ct = state.get("current_task")
    if ct and (q in ct.get("title", "").lower() or q in ct.get("description", "").lower()):
        results.append(f"[タスク] [{ct['id']}] {ct['title']}")

    # 完了済みタスク（issue-010: 検索漏れ修正）
    for t in state.get("completed_tasks", []):
        hit = (q in t.get("title", "").lower() or q in t.get("description", "").lower()
               or q in t.get("completion_note", "").lower())
        if not hit:
            hit = any(q in fp.lower() for fp in t.get("files_modified", []))
        if hit:
            results.append(f"[完了タスク] [{t['id']}] {t['title']} ({t.get('completed_at', '?')[:10]})")

    # 完了した保留タスク（issue-010: 検索漏れ修正）
    for t in state.get("completed_pending_tasks", []):
        if (q in t.get("title", "").lower() or q in t.get("description", "").lower()
                or q in t.get("completion_note", "").lower()):
            results.append(f"[完了保留] [{t['id']}] {t['title']} ({t.get('completed_at', '?')[:10]})")

    if not results:
        return f"「{query}」に一致する項目は見つかりませんでした。"

    lines = [f"# 検索結果: 「{query}」（{len(results)}件）", ""]
    lines.extend(results)
    return "\n".join(lines)


@mcp.tool()
def collab_timeline(
    limit:      int = 20,
    since:      str = "",
    actor:      str = "",
    event_type: str = "",
) -> str:
    """
    プロジェクトの更新イベントを時系列で返す。

    Args:
        limit:      最大表示件数（デフォルト: 20、最大: 100）
        since:      この日時以降のみ表示（ISO形式: 2026-05-01T00:00）
        actor:      AIフィルター（"claude" / "codex" / "" で全員）
        event_type: イベント種別フィルター
                    "note" / "decision" / "issue" / "issue_resolved" /
                    "task" / "task_done" / "pending" / "pending_done" / "" で全種別
    """
    state = _load_state()

    # 全イベントを収集
    events: list[dict] = []

    def _add(ts: str, kind: str, ai: str, label: str) -> None:
        if ts:
            events.append({"ts": ts, "kind": kind, "ai": ai.lower(), "label": label})

    for n in state.get("notes", []):
        _add(n.get("timestamp", ""), "note", n.get("ai", "?"), n.get("text", "")[:100])

    for d in state.get("key_decisions", []):
        _add(d.get("timestamp", ""), "decision", d.get("ai", "?"), d.get("title", "")[:80])

    for iss in state.get("known_issues", []):
        if isinstance(iss, dict):
            # issue-020: 構造化issueは added_at/added_by を優先、旧データは timestamp/ai にフォールバック
            _add(
                iss.get("added_at", "") or iss.get("timestamp", ""),
                "issue",
                iss.get("added_by", "") or iss.get("ai", "?"),
                f"[{iss.get('id','?')}] {iss.get('text','')[:80]}",
            )

    for iss in state.get("resolved_issues", []):
        if isinstance(iss, dict):
            _add(
                iss.get("resolved_at", iss.get("timestamp", "")),
                "issue_resolved",
                iss.get("resolved_by", "?"),
                f"[{iss.get('id','?')}] 解決: {iss.get('text','')[:60]}",
            )

    ct = state.get("current_task")
    if ct:
        _add(ct.get("started_at", ""), "task", ct.get("started_by", "?"),
             f"[{ct.get('id','?')}] {ct.get('title','')[:60]}")

    for t in state.get("completed_tasks", []):
        _add(t.get("completed_at", t.get("started_at", "")), "task_done",
             t.get("started_by", "?"),
             f"[{t.get('id','?')}] 完了: {t.get('title','')[:60]}")

    for t in state.get("pending_tasks", []):
        _add(t.get("added_at", ""), "pending", t.get("added_by", "?"),
             f"[{t.get('id','?')}] {t.get('title','')[:60]}")

    for t in state.get("completed_pending_tasks", []):
        _add(t.get("completed_at", ""), "pending_done", t.get("added_by", "?"),
             f"[{t.get('id','?')}] 完了: {t.get('title','')[:60]}")

    # 降順ソート
    events.sort(key=lambda e: e["ts"], reverse=True)

    # フィルタリング
    if since:
        events = [e for e in events if e["ts"] >= since]
    if actor:
        events = [e for e in events if e["ai"] == actor.lower()]
    if event_type:
        events = [e for e in events if e["kind"] == event_type]

    # 件数制限
    limit = max(1, min(limit, 100))
    events = events[:limit]

    if not events:
        return "（表示できるイベントがありません）"

    # 種別ラベル
    KIND_LABELS: dict[str, str] = {
        "note":          "📝 メモ    ",
        "decision":      "📌 決定    ",
        "issue":         "⚠️  問題    ",
        "issue_resolved":"✅ 問題解決",
        "task":          "🔧 タスク  ",
        "task_done":     "✅ タスク完",
        "pending":       "⏳ 保留    ",
        "pending_done":  "✅ 保留完了",
    }

    lines = [f"# タイムライン（{len(events)}件）", ""]
    for e in events:
        kind_label = KIND_LABELS.get(e["kind"], e["kind"])
        ts = e["ts"][:16] if len(e["ts"]) >= 16 else e["ts"]
        lines.append(f"{ts}  {kind_label}  [{e['ai'].upper()}]  {e['label']}")

    return "\n".join(lines)


@mcp.tool()
def collab_request_review(
    ai:          str,
    focus:       list[str] = [],
    scope:       str = "",
    save_result: bool = True,
) -> str:
    """
    相手AIにコードレビューまたは設計レビューを依頼する。
    collab_consult の薄いラッパー。

    Args:
        ai:          レビュアーAI。"claude" または "codex"
        focus:       レビューの重点事項リスト（例: ["セキュリティ", "パフォーマンス"]）
        scope:       レビュー対象の説明（ファイル名・機能名など）
        save_result: 結果をメモとして保存するか（デフォルト: True）
    """
    if ai not in VALID_AI:
        return f"エラー: ai は 'claude' または 'codex' を指定してください。"

    focus_text = "・".join(focus) if focus else "全般"
    scope_text = scope or "現在の実装全体"
    question = (
        f"[レビュー依頼]\n"
        f"対象スコープ: {scope_text}\n"
        f"重点事項: {focus_text}\n\n"
        f"問題点・改善点・リスクを指摘してください。"
    )

    err = _validate_input(question, "question")
    if err:
        return err

    response    = _call_ai_cli(ai, _build_consult_prompt(question))
    save_failed = False

    if save_result:
        try:
            label = f"[{ai.upper()}にレビュー依頼] {scope_text[:60]}"
            with _state_transaction() as state:
                state["notes"].append({
                    "timestamp": _now_iso(), "ai": state["current_ai"],
                    "text":    label,
                    "consult": {"question": question, "response": response},
                })
                caller_ai = state["current_ai"]
            _append_session_log(caller_ai, label)
        except Exception:
            save_failed = True

    result = f"【{ai.upper()} CLI のレビュー】\n\n{response}"
    if save_failed:
        result += "\n\n⚠️ メモへの保存に失敗しました"
    return result


@mcp.tool()
def collab_summary() -> str:
    """
    現在の状態をコンパクトな4行で表示する。

    collab_status() の簡易版。ログ確認やヘッダ把握に使う。
    """
    state = _load_state()
    ct = state.get("current_task")
    task_str = f"[{ct['id']}] {ct['title']}" if ct else "未設定"
    issues  = len(state.get("known_issues", []))
    pending = len(state.get("pending_tasks", []))
    mode_label = MODE_LABELS.get(state["mode"], state["mode"])

    return (
        f"📋 {state['project_name']} | {state['current_ai'].upper()} | {mode_label} | セッション#{state['session_count']}\n"
        f"🔧 タスク : {task_str}\n"
        f"⏳ 保留  : {pending}件  ⚠️ 問題: {issues}件\n"
        f"🕐 最終更新: {state['last_updated'][:16]}"
    )


@mcp.tool()
def collab_cleanup_sessions(keep_per_ai: int = 5) -> str:
    """
    ai_sessions/ フォルダの古いセッションログを削除する。

    AIごとに新しい順で指定件数だけ残し、残りを削除する。
    セッションログが積み重なってきたときに呼ぶ。

    Args:
        keep_per_ai: AIごとに残すログファイル数（デフォルト: 5）
    """
    if keep_per_ai < 1:
        return "エラー: keep_per_ai は 1 以上を指定してください。"

    sd = _sessions_dir()
    if not sd.exists():
        return "ai_sessions/ フォルダが存在しません。"

    deleted: list[str] = []
    kept: dict[str, int] = {}
    for ai in VALID_AI:
        logs = sorted(sd.glob(f"*_{ai}.md"), reverse=True)  # 新しい順
        kept[ai] = min(len(logs), keep_per_ai)
        for log_file in logs[keep_per_ai:]:
            log_file.unlink(missing_ok=True)
            deleted.append(log_file.name)

    if not deleted:
        summary = "  " + "、".join(f"{ai.upper()}: {kept[ai]}件" for ai in VALID_AI)
        return f"削除対象なし（各AI最新{keep_per_ai}件以内）。\n現在のログ数:\n{summary}"

    kept_summary = "  " + "、".join(f"{ai.upper()}: {kept[ai]}件残存" for ai in VALID_AI)
    return (
        f"{len(deleted)}件のセッションログを削除しました。\n"
        f"残存ログ:\n{kept_summary}\n"
        f"削除ファイル:\n" + "\n".join(f"  - {n}" for n in deleted)
    )


@mcp.tool()
def collab_cleanup_history(
    keep_notes: int = 100,
    keep_completed_tasks: int = 50,
    archive: bool = True,
    dry_run: bool = False,
) -> str:
    """
    古いメモ・完了タスクを整理してAI_STATE.jsonをスリムにする。

    넘치는 notes / completed_tasks を AI_STATE.archive.json にアーカイブし、
    状態ファイルを指定件数以内に保つ。

    Args:
        keep_notes:           残すメモの最新件数（デフォルト: 100）
        keep_completed_tasks: 残す完了タスクの最新件数（デフォルト: 50）
        archive:              True = 削除分を AI_STATE.archive.json に退避、
                              False = 単純削除
        dry_run:              True = 実際には変更せず予測結果だけ返す
    """
    if keep_notes < 1 or keep_completed_tasks < 1:
        return "エラー: keep_notes / keep_completed_tasks は 1 以上を指定してください。"

    # dry_run: 変更せずに予測結果を返す
    state = _load_state()
    notes_total     = len(state.get("notes", []))
    tasks_total     = len(state.get("completed_tasks", []))
    notes_trim      = max(0, notes_total - keep_notes)
    tasks_trim      = max(0, tasks_total - keep_completed_tasks)

    if notes_trim == 0 and tasks_trim == 0:
        return (
            f"整理不要です。\n"
            f"  メモ: {notes_total}件（上限 {keep_notes}件）\n"
            f"  完了タスク: {tasks_total}件（上限 {keep_completed_tasks}件）"
        )

    if dry_run:
        return (
            f"[dry_run] 実行すると以下が整理されます:\n"
            f"  メモ: {notes_total}件 → {notes_total - notes_trim}件残存（{notes_trim}件アーカイブ）\n"
            f"  完了タスク: {tasks_total}件 → {tasks_total - tasks_trim}件残存（{tasks_trim}件アーカイブ）\n"
            f"  アーカイブ先: {'AI_STATE.archive.json' if archive else '（単純削除）'}\n"
            f"dry_run=False で実行してください。"
        )

    # アーカイブ対象を確定
    archived_notes = state["notes"][:notes_trim]
    archived_tasks = state["completed_tasks"][:tasks_trim]

    if archive and (archived_notes or archived_tasks):
        # AI_STATE.archive.json を読み込み（なければ新規）
        af = _archive_file()
        if af.exists():
            try:
                with open(af, "r", encoding="utf-8-sig") as f:
                    arc = json.load(f)
            except Exception:
                arc = {"notes": [], "completed_tasks": []}
        else:
            arc = {"notes": [], "completed_tasks": []}

        arc.setdefault("notes", []).extend(archived_notes)
        arc.setdefault("completed_tasks", []).extend(archived_tasks)
        arc["last_archived"] = _now_iso()

        # アーカイブファイルを原子的に書き込む
        tmp_fd, tmp_path = tempfile.mkstemp(dir=_get_project_dir(), suffix=".tmp", prefix="arc_")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(arc, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, af)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # 状態を更新（古いレコードを削除）
    with _state_transaction() as st:
        st["notes"]           = st["notes"][notes_trim:]
        st["completed_tasks"] = st["completed_tasks"][tasks_trim:]

    archive_note = "AI_STATE.archive.json に退避" if archive else "単純削除"
    return (
        f"履歴を整理しました。\n"
        f"  メモ: {notes_total}件 → {notes_total - notes_trim}件（{notes_trim}件を{archive_note}）\n"
        f"  完了タスク: {tasks_total}件 → {tasks_total - tasks_trim}件（{tasks_trim}件を{archive_note}）"
    )


@mcp.tool()
def collab_export_state(
    output_path: str = "",
    include_sessions: bool = False,
    redact_cli_config: bool = True,
) -> str:
    """
    現在の状態をJSONファイルとしてエクスポートする。

    SHA-256チェックサム付きのバックアップファイルを生成する。
    collab_import_state() で復元・マージが可能。

    Args:
        output_path:       出力先ファイルパス。省略時はプロジェクトフォルダに
                           AI_STATE_backup_YYYYMMDD_HHMMSS.json を生成
        include_sessions:  True = ai_sessions/ の内容も含める
        redact_cli_config: True = cli_config.json（APIキー等含む可能性）は含めない（デフォルト）
    """
    state = _load_state()
    proj_dir = _get_project_dir()

    # 出力パスを決定する
    if output_path:
        out = Path(output_path)
        if not out.is_absolute():
            return "エラー: output_path は絶対パスを指定してください。"
    else:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = proj_dir / f"AI_STATE_backup_{ts}.json"

    # エクスポート用ペイロードを組み立てる
    payload: dict = {
        "export_version":  "1.0",
        "exported_at":     _now_iso(),
        "source_project":  str(proj_dir),
        "state":           state,
    }

    if include_sessions:
        sd = _sessions_dir()
        session_data: dict[str, str] = {}
        if sd.exists():
            for log_file in sorted(sd.glob("*.md")):
                try:
                    session_data[log_file.name] = log_file.read_text(encoding="utf-8")
                except OSError:
                    session_data[log_file.name] = "（読み込み失敗）"
        payload["sessions"] = session_data

    if not redact_cli_config:
        cfg_file = proj_dir / "cli_config.json"
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8-sig") as f:
                    payload["cli_config"] = json.load(f)
            except Exception:
                payload["cli_config"] = None

    # SHA-256チェックサムを計算する（checksum フィールド自体は除外して計算）
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    payload["checksum"] = checksum

    # ファイルに書き込む
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(out, json.dumps(payload, ensure_ascii=False, indent=2))
    except OSError as e:
        return f"エラー: ファイルの書き込みに失敗しました: {e}"

    return (
        f"状態をエクスポートしました。\n"
        f"  出力ファイル: {out}\n"
        f"  SHA-256: {checksum[:16]}...\n"
        f"  メモ: {len(state.get('notes', []))}件  "
        f"決定事項: {len(state.get('key_decisions', []))}件  "
        f"問題: {len(state.get('known_issues', []))}件\n"
        f"復元: collab_import_state('{out}')"
    )


@mcp.tool()
def collab_import_state(
    input_path: str,
    mode: str = "validate",
    backup: bool = True,
) -> str:
    """
    collab_export_state() で生成したバックアップから状態をインポートする。

    モード:
    - validate : チェックサムと内容を検証するだけ（変更なし）
    - merge    : エクスポート内のメモ・決定事項・問題を現在の状態に追記する
    - replace  : 現在の状態をエクスポートの内容で完全置換する

    Args:
        input_path: エクスポートファイルのフルパス
        mode:       "validate" / "merge" / "replace"（デフォルト: validate）
        backup:     True = replace 実行前に現在の状態を自動バックアップ（デフォルト: True）
    """
    if mode not in ("validate", "merge", "replace"):
        return "エラー: mode は 'validate' / 'merge' / 'replace' のいずれかを指定してください。"

    in_path = Path(input_path)
    if not in_path.is_absolute():
        return "エラー: input_path は絶対パスを指定してください。"
    if not in_path.exists():
        return f"エラー: ファイルが見つかりません: {in_path}"

    # ファイルを読み込む（issue-022: BOM付きUTF-8も許容）
    try:
        with open(in_path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
    except Exception as e:
        return f"エラー: ファイルの読み込みに失敗しました: {e}"

    # チェックサム検証
    stored_checksum = payload.pop("checksum", None)
    if stored_checksum is None:
        return "エラー: チェックサムが見つかりません。このファイルはエクスポートされたものではない可能性があります。"

    payload_json     = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    calc_checksum    = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    payload["checksum"] = stored_checksum  # 元に戻す（表示用）

    if calc_checksum != stored_checksum:
        return (
            f"エラー: チェックサムが一致しません。ファイルが破損または改ざんされています。\n"
            f"  格納値: {stored_checksum[:16]}...\n"
            f"  計算値: {calc_checksum[:16]}..."
        )

    imported_state = payload.get("state", {})
    exported_at    = payload.get("exported_at", "不明")
    source_project = payload.get("source_project", "不明")

    # ── validate モード ─────────────────────────────────────────────────
    if mode == "validate":
        notes_count    = len(imported_state.get("notes", []))
        dec_count      = len(imported_state.get("key_decisions", []))
        issue_count    = len(imported_state.get("known_issues", []))
        task_count     = len(imported_state.get("completed_tasks", []))
        return (
            f"チェックサム検証: OK ✅\n"
            f"  エクスポート日時: {exported_at}\n"
            f"  ソースプロジェクト: {source_project}\n"
            f"  メモ: {notes_count}件  決定事項: {dec_count}件  "
            f"問題: {issue_count}件  完了タスク: {task_count}件\n"
            f"インポートするには mode='merge' または mode='replace' を指定してください。"
        )

    # ── merge / replace モード ──────────────────────────────────────────
    if mode == "replace" and backup:
        # 現在の状態を replace 前にバックアップ
        ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = _get_project_dir() / f"AI_STATE_before_import_{ts}.json"
        try:
            current_state = _load_state()
            _write_atomic(bak, json.dumps(current_state, ensure_ascii=False, indent=2))
        except Exception as e:
            return f"エラー: バックアップの作成に失敗しました: {e}"

    merged_notes    = 0
    merged_decs     = 0
    merged_issues   = 0

    with _state_transaction() as st:
        if mode == "replace":
            # 完全置換: インポート状態をそのまま使用する
            for key, val in imported_state.items():
                st[key] = val
        else:
            # merge: メモ・決定事項・既知の問題を追記する（重複は timestamp で簡易判定）
            existing_note_ts   = {n.get("timestamp") for n in st.get("notes", [])}
            existing_dec_ts    = {d.get("timestamp") for d in st.get("key_decisions", [])}
            existing_issue_ids = {i.get("id") if isinstance(i, dict) else None
                                  for i in st.get("known_issues", [])}

            for note in imported_state.get("notes", []):
                if note.get("timestamp") not in existing_note_ts:
                    st["notes"].append(note)
                    merged_notes += 1

            for dec in imported_state.get("key_decisions", []):
                if dec.get("timestamp") not in existing_dec_ts:
                    st["key_decisions"].append(dec)
                    merged_decs += 1

            for issue in imported_state.get("known_issues", []):
                issue_id = issue.get("id") if isinstance(issue, dict) else None
                if issue_id not in existing_issue_ids:
                    st["known_issues"].append(issue)
                    merged_issues += 1

    if mode == "replace":
        backup_note = f"（バックアップ: {bak.name}）" if backup else ""
        return (
            f"状態を完全置換しました。{backup_note}\n"
            f"  エクスポート日時: {exported_at}\n"
            f"  ソースプロジェクト: {source_project}"
        )
    else:
        return (
            f"状態をマージしました。\n"
            f"  追加メモ: {merged_notes}件  "
            f"追加決定事項: {merged_decs}件  "
            f"追加問題: {merged_issues}件\n"
            f"  エクスポート日時: {exported_at}"
        )


@mcp.tool()
def collab_set_handoff_template(preset: str = "full") -> str:
    """
    HANDOFF.md の生成テンプレートを切り替える。

    プリセット:
    - full    : 全セクション（デフォルト）
    - minimal : 現在タスク＋最新メモ3件＋既知の問題のみ（高速ハンドオフ向け）
    - review  : full ＋ レビューポイントセクション（コードレビュー引き継ぎ向け）
    - debug   : full ＋ デバッグ情報セクション（障害対応引き継ぎ向け）

    Args:
        preset: "full" / "minimal" / "review" / "debug"（デフォルト: "full"）
    """
    if preset not in VALID_HANDOFF_TEMPLATES:
        return (
            f"エラー: preset は {VALID_HANDOFF_TEMPLATES} のいずれかを指定してください。\n"
            f"指定値: '{preset}'"
        )

    with _state_transaction() as state:
        old_preset = state.get("handoff_template", "full")
        state["handoff_template"] = preset

    preset_desc = {
        "full":    "全セクション（デフォルト）",
        "minimal": "現在タスク＋最新3件＋既知の問題のみ",
        "review":  "full＋レビューポイントセクション",
        "debug":   "full＋デバッグ情報セクション",
    }
    return (
        f"ハンドオフテンプレートを変更しました。\n"
        f"  {old_preset} → {preset}\n"
        f"  内容: {preset_desc.get(preset, preset)}\n"
        f"次回の collab_generate_handoff() / collab_checkpoint() から反映されます。"
    )

#endregion

#region エントリポイント

def _print_help(version_only: bool = False) -> None:
    """
    ヘルプ / バージョン情報を出力する。
    uvx ランチャー経由では stdout に書けない場合があるため、
    stdout → stderr → CONOUT$ の順でフォールバックする。
    """
    text = f"multiai-relay-mcp {_VERSION}\n" if version_only else _HELP_TEXT
    encoded = text.encode("utf-8", errors="replace")

    # 1) fd=1 (stdout) への直接書き込み
    try:
        os.write(1, encoded)
        return
    except OSError:
        pass

    # 2) fd=2 (stderr) へのフォールバック
    try:
        os.write(2, encoded)
        return
    except OSError:
        pass

    # 3) Windows コンソール (CONOUT$) への直接書き込み
    if sys.platform == "win32":
        try:
            with open("CONOUT$", "wb") as con:
                con.write(encoded)
            return
        except OSError:
            pass



_VERSION = "1.0.16"

# ヘルプテキスト（AIが読むことを想定して日本語で詳述）
_HELP_TEXT = f"""\
multiAI-relay-mcp v{_VERSION}
ClaudeとCodexが共有状態を通じて協調開発するためのMCPサーバーです。

使い方:
  uvx --from <パッケージディレクトリ> multiai-relay-mcp   # MCPサーバーとして起動（stdio）
  uvx --from <パッケージディレクトリ> multiai-relay-mcp --help
  uvx --from <パッケージディレクトリ> multiai-relay-mcp --version

オプション:
  -h, --help     このヘルプを表示して終了
  --version      バージョンを表示して終了

MCPツール一覧（Claude Desktop / Codex Desktop から自動呼び出し）:
  collab_switch_project     作業プロジェクトを設定・新規作成する（セッション開始時に必須）
  collab_current_project    現在のプロジェクトパスを表示する
  collab_status             現在の状態（担当AI・モード・タスク・メモ等）を表示する
  collab_summary            状態を4行でコンパクトに表示する（ヘッダ確認用）
  collab_set_task           現在タスクを設定する
  collab_add_note           メモを追記する
  collab_record_decision    決定事項を記録する
  collab_record_issue       課題・懸念点を記録する（issue-NNN IDが付く）
  collab_resolve_issue      既知の問題を解決済みにする
  collab_list_resolved      解決済みの問題一覧を表示する
  collab_search             キーワードで全データを横断検索する
  collab_record_file        変更ファイルを記録する
  collab_change_mode        モードを切り替える（plan / implement / review / debug）
  collab_add_pending_task   未着手タスクを追加する
  collab_close_pending_task 完了した保留タスクを一覧から取り除く
  collab_complete_task      現在のタスクを完了済みにする（新タスクなしで完了させる場合）
  collab_generate_handoff   引き継ぎ文書（HANDOFF.md）を生成する（dry_run オプションあり）
  collab_checkpoint         メモ追加と引き継ぎ文書生成を一度に行う（dry_run オプションあり）
  collab_consult            相手AIのCLIを呼び出して質問・相談する
  collab_discuss            相手AIと複数ターンの議論を行う
  collab_request_review     相手AIにコードレビューを依頼する（consult の薄いラッパー）
  collab_setup_cli          AIのCLIパス・引数設定をカスタマイズする
  collab_version            MCPサーバーと実行環境のバージョン情報を返す
  collab_doctor             MCPサーバーと実行環境の健全性を診断する
  collab_timeline           プロジェクトの更新イベントを時系列で返す
  collab_cleanup_sessions   古いセッションログを削除する
  collab_cleanup_history    古いメモ・完了タスクを整理してアーカイブする
  collab_update_issue       既存issueのseverity/category/tags/related_files/statusを更新する
  collab_export_state       現在の状態をSHA-256チェックサム付きJSONでエクスポートする
  collab_import_state       エクスポートしたJSONから状態をインポートする
  collab_set_handoff_template  HANDOFF.md の生成テンプレートを切り替える

プロジェクトの切り替え:
  Desktop アプリを再起動しなくても collab_switch_project() を呼ぶだけで
  作業対象プロジェクトを変更できます。
  プロジェクトパスはプロセスのメモリ内にのみ保持され、ファイルには書き出しません。

書き込み先ファイル（プロジェクトフォルダ内のみ）:
  AI_STATE.json    状態ファイル
  HANDOFF.md       引き継ぎ文書
  ai_sessions/     セッションログ
  cli_config.json  CLI設定（collab_setup_cli() を呼んだ場合のみ生成）

初回セットアップ:
  1. Claude Desktop / Codex Desktop の MCP 設定に本サーバーを登録する
  2. collab_switch_project('プロジェクトのフルパス') を呼ぶ
  3. collab_status で状態を確認する
"""


def main() -> None:
    """uvx / uv run から呼び出されるエントリポイント"""
    # --help / -h / --version のみ解釈する（それ以外の引数は無視してMCPとして起動）
    args = sys.argv[1:]
    if any(a in ("-h", "--help") for a in args):
        _print_help()
        sys.exit(0)
    if "--version" in args:
        _print_help(version_only=True)
        sys.exit(0)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

#endregion
