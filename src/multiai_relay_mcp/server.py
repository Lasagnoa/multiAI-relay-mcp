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
import time
from collections import Counter
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import state as state_mod
from .i18n import get_lang, mode_label, t
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
    _load_registry,
    _load_state,
    get_git_info,
    _now_iso,
    _pid_exists,
    _sessions_dir,
    _state_file,
    _state_transaction,
    _validate_input,
    _validate_related_files,
    _validate_tags,
    _write_atomic,
    register_project,
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
        return t("err.absolute_path", path=project_path)

    path = Path(project_path).resolve()

    if not path.is_dir():
        return t("err.dir_not_found", path=path)

    state_file = path / "AI_STATE.json"

    # 新規作成パス
    if not state_file.exists():
        if not project_name:
            return t("switch.not_found", path=path)
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
        register_project(path, project_name)
        return t("switch.created", path=path, name=project_name, mode=mode_label("plan"))

    # 既存プロジェクトを吸収して接続（project_name は無視）
    state_mod.set_current_project(path)
    # issue-022: BOM付きJSON(utf-8-sig)も透過的に読み込む
    with open(state_file, "r", encoding="utf-8-sig") as f:
        state = json.load(f)

    absorbed = t("switch.absorbed_note") if project_name else ""

    # レジストリに登録
    register_project(path, state.get("project_name", project_name or path.name))

    # 自動ステータスサマリー：毎回 collab_status() を呼ばなくても把握できるよう接続時に表示
    cur_task = state.get("current_task")
    if cur_task:
        task_info = t("switch.task_line", id=cur_task.get("id", "?"), title=cur_task.get("title", "?"))
    else:
        task_info = t("switch.task_none")

    issue_count = len([i for i in state.get("known_issues", []) if isinstance(i, dict)])
    pending_count = len(state.get("pending_tasks", []))

    recent_note = ""
    if state.get("notes"):
        n = state["notes"][-1]
        ts = n.get("timestamp", "")[:16]
        recent_note = "\n" + t("switch.recent_note", ts=ts, text=str(n.get("text", ""))[:80])

    # Git 情報（取得できた場合のみ）
    git_line = ""
    git_info = get_git_info(path)
    if git_info:
        dirty_mark = " *" if git_info["is_dirty"] else ""
        git_line = "\n" + t("switch.git_branch", branch=f"{git_info['branch']}{dirty_mark}")

    lines = [
        t("switch.connected", absorbed=absorbed),
        t("switch.path_line", path=path),
        t("switch.name_line", name=state.get("project_name", "?")),
        t("switch.ai_line", ai=state.get("current_ai", "?").upper()),
        t("switch.mode_line", mode=mode_label(state.get("mode", ""))),
        t("switch.session_line", session=state.get("session_count", 1)),
        task_info,
        t("switch.issue_pending", issues=issue_count, pending=pending_count),
    ]
    return "\n".join(lines) + recent_note + git_line


@mcp.tool()
def collab_current_project(project_path: str = '') -> str:
    """現在アクティブなプロジェクトのパスと存在状態を確認する。"""
    try:
        with state_mod.project_context(project_path):
            # ContextVar override を優先した有効プロジェクトパスを取得
            try:
                effective = _get_project_dir()
            except RuntimeError:
                return t("current.not_set")
            if not effective.exists():
                return t("current.dir_missing", path=effective)
            if not effective.is_dir():
                return t("current.not_dir", path=effective)
            state_ok = (effective / "AI_STATE.json").exists()
            state_status = t("current.state_ok") if state_ok else t("current.state_missing")
            return t("current.ok", path=effective, state_status=state_status)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_list_projects() -> str:
    """
    最近使用したプロジェクトの一覧を表示する。

    collab_switch_project() を呼び出したプロジェクトが最大20件まで記録される。
    """
    entries = _load_registry()
    if not entries:
        return t("list_projects.empty")

    lines = [t("list_projects.header", count=len(entries)), ""]
    for i, entry in enumerate(entries, 1):
        path_str  = entry.get("path", "?")
        name      = entry.get("project_name", "?")
        last_used = entry.get("last_used", "?")[:16]
        mark = t("list_projects.exists_ok") if Path(path_str).exists() else t("list_projects.exists_ng")
        lines.append(f"{i:2}. {mark} [{name}]")
        lines.append(t("list_projects.path", path=path_str))
        lines.append(t("list_projects.last_used", ts=last_used))
    lines += ["", t("list_projects.connect")]
    return "\n".join(lines)

#endregion

#region MCPツール — 診断・情報

@mcp.tool()
def collab_version(project_path: str = '') -> str:
    """
    MCPサーバーと実行環境のバージョン情報を返す。
    """
    try:
        with state_mod.project_context(project_path):
            # ContextVar override を優先した有効プロジェクトパスを表示用に取得
            _unset = t("version.unset")
            try:
                _display_proj = str(_get_project_dir())
            except RuntimeError:
                _display_proj = _unset
            try:
                config_path     = str(_state_file())
            except RuntimeError:
                config_path     = _unset
            try:
                cli_config_path = str(_cli_config_file())
            except RuntimeError:
                cli_config_path = _unset

            lines = [
                f"multiai-relay-mcp v{_VERSION}",
                "",
                t("version.pkg",        ver=_VERSION),
                t("version.schema",     ver=_STATE_SCHEMA_VERSION),
                t("version.python",     ver=sys.version.split()[0]),
                t("version.executable", path=sys.executable),
                "",
                t("version.proj_path",  path=_display_proj),
                t("version.state_path", path=config_path),
                t("version.cli_path",   path=cli_config_path),
            ]
            return "\n".join(lines)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_doctor(
    check_cli:      bool = True,
    check_state:    bool = True,
    check_lock:     bool = True,
    check_ai_call:  bool = False,
    check_schema:   bool = True,
    check_encoding: bool = True,
    check_issues:   bool = True,
    check_recovery: bool = True,
    output:         str  = "text",
    project_path: str = '',
) -> str:
    """
    MCPサーバーと実行環境の健全性を診断する。

    Args:
        check_cli:      CLIコマンドの存在確認（デフォルト: True）
        check_state:    AI_STATE.json の整合性確認（デフォルト: True）
        check_lock:     ロックファイルの状態確認（デフォルト: True）
        check_ai_call:  AI CLI 呼び出し確認（高コスト、デフォルト: False）
        check_schema:   スキーマバージョン・必須キーの確認（デフォルト: True）
        check_encoding: BOM付きJSON検出（デフォルト: True）
        check_issues:   Issueレコードの整合性確認（デフォルト: True）
        check_recovery: アーカイブ・エクスポートファイルの確認（デフォルト: True）
        output:         出力形式 "text"（デフォルト）または "json"
    """
    try:
        with state_mod.project_context(project_path):
            # 診断結果リスト（JSON出力と text 出力を共通で管理）
            diagnostics: list[dict] = []

            def _add(level: str, code: str, message: str, suggestion: str | None = None) -> None:
                diagnostics.append({"level": level, "code": code, "message": message, "suggestion": suggestion})

            def ok(code: str, msg: str, sug: str | None = None)   -> None: _add("OK",   code, msg, sug)
            def warn(code: str, msg: str, sug: str | None = None) -> None: _add("WARN", code, msg, sug)
            def err(code: str, msg: str, sug: str | None = None)  -> None: _add("ERR",  code, msg, sug)

            # ContextVar override を優先して取得（project_path 指定時は override が有効）
            try:
                proj = _get_project_dir()
            except RuntimeError:
                proj = None
            sf   = (proj / "AI_STATE.json") if proj and proj.exists() else None

            #region プロジェクトフォルダ確認
            if proj is None:
                warn("project_unset", t("doctor.project_unset"), t("doctor.project_unset_sug"))
            elif not proj.exists():
                err("project_missing", t("doctor.project_missing", proj=proj),
                    t("doctor.project_missing_sug"))
            else:
                ok("project_dir", t("doctor.project_dir_ok", proj=proj))
            #endregion

            #region エンコーディング確認（BOM検出）
            if check_encoding and sf and sf.exists():
                raw_data, has_bom, raw_err = state_mod.read_raw_state_json(sf)
                if raw_err:
                    err("encoding_parse", t("doctor.encoding_parse_err", err=raw_err),
                        t("doctor.encoding_parse_sug"))
                elif has_bom:
                    warn("bom_detected", t("doctor.bom_detected"),
                         t("doctor.bom_detected_sug"))
                else:
                    ok("encoding_ok", t("doctor.encoding_ok"))
            #endregion

            #region スキーマ確認（raw JSON で正規化前の状態を検査）
            if check_schema and sf and sf.exists():
                raw_data, _, raw_err = state_mod.read_raw_state_json(sf)
                if raw_data is not None:
                    # バージョン確認
                    raw_ver = raw_data.get("version", "(なし)")
                    if raw_ver != _STATE_SCHEMA_VERSION:
                        warn("schema_version",
                             t("doctor.schema_version_mismatch",
                               file_ver=raw_ver, expected=_STATE_SCHEMA_VERSION),
                             t("doctor.schema_version_mismatch_sug"))
                    else:
                        ok("schema_version", t("doctor.schema_version_ok", ver=raw_ver))
                    # 必須キー確認
                    missing = [k for k in _STATE_DEFAULTS if k not in raw_data]
                    if missing:
                        warn("schema_missing_keys",
                             t("doctor.schema_missing_keys", keys=', '.join(missing)),
                             t("doctor.schema_missing_keys_sug"))
                    # リスト型の型確認
                    bad_types = [
                        k for k, v in _STATE_DEFAULTS.items()
                        if isinstance(v, list) and k in raw_data and not isinstance(raw_data[k], list)
                    ]
                    if bad_types:
                        warn("schema_bad_types",
                             t("doctor.schema_bad_types", keys=', '.join(bad_types)),
                             t("doctor.schema_bad_types_sug"))
                    if not missing and not bad_types:
                        ok("schema_keys", t("doctor.schema_keys_ok"))
            #endregion

            #region 状態ファイル確認（_load_state 経由・正規化後）
            if check_state and proj and proj.exists():
                if not sf or not sf.exists():
                    warn("state_missing", t("doctor.state_missing"),
                         t("doctor.state_missing_sug"))
                else:
                    try:
                        loaded = _load_state()
                        ok("state_load", t("doctor.state_load_ok",
                           ai=loaded.get('current_ai', '?').upper(),
                           session=loaded.get('session_count', '?')))
                    except Exception as e:
                        err("state_load_fail", t("doctor.state_load_fail", err=e),
                            t("doctor.state_load_fail_sug"))
            #endregion

            #region Issue 整合性確認（raw JSON で正規化前の状態を検査）
            if check_issues and sf and sf.exists():
                raw_data, _, _ = state_mod.read_raw_state_json(sf)
                if raw_data is not None:
                    for list_key in ("known_issues", "resolved_issues"):
                        issues = raw_data.get(list_key, [])
                        if not isinstance(issues, list):
                            continue
                        # 非dict要素（旧テキストフォーマット等）
                        non_dict_idx = [i for i, iss in enumerate(issues) if not isinstance(iss, dict)]
                        if non_dict_idx:
                            warn("issues_non_dict",
                                 t("doctor.issues_non_dict", list_key=list_key, idx=non_dict_idx),
                                 t("doctor.issues_non_dict_sug"))
                        # 有効な dict issue のみ詳細検査
                        dict_issues = [iss for iss in issues if isinstance(iss, dict)]
                        # severity 不正値
                        bad_sev = [
                            iss.get("id", "?") for iss in dict_issues
                            if "severity" in iss and iss["severity"] not in VALID_SEVERITIES
                        ]
                        if bad_sev:
                            warn("issues_bad_severity",
                                 t("doctor.issues_bad_severity", list_key=list_key, ids=bad_sev),
                                 t("doctor.issues_bad_severity_sug"))
                        # 重複ID（Counter で正確に集計）
                        ids = [iss.get("id") for iss in dict_issues]
                        id_counts = Counter(i for i in ids if i is not None)
                        dups = [i for i, cnt in id_counts.items() if cnt > 1]
                        if dups:
                            warn("issues_duplicate_id",
                                 t("doctor.issues_duplicate_id",
                                   list_key=list_key, ids=list(dict.fromkeys(dups))),
                                 t("doctor.issues_duplicate_id_sug"))
                        # text / id フィールド検証（非文字列・空文字）
                        bad_text = [
                            iss.get("id", f"[{_i}]") for _i, iss in enumerate(dict_issues)
                            if not isinstance(iss.get("text"), str) or not str(iss.get("text", "")).strip()
                        ]
                        if bad_text:
                            warn("issues_bad_text",
                                 t("doctor.issues_bad_text", list_key=list_key, ids=bad_text),
                                 t("doctor.issues_bad_text_sug"))
                        # tags 形式検証 / related_files パス安全性検証
                        bad_tags: list = []
                        bad_files: list = []
                        for _i, _iss in enumerate(dict_issues):
                            _iid = _iss.get("id", f"[{_i}]")
                            _tv = _iss.get("tags")
                            if _tv is not None:
                                if not isinstance(_tv, list) or _validate_tags(_tv) is not None:
                                    bad_tags.append(_iid)
                            _rv = _iss.get("related_files")
                            if _rv is not None:
                                if not isinstance(_rv, list) or _validate_related_files(_rv) is not None:
                                    bad_files.append(_iid)
                        if bad_tags:
                            warn("issues_bad_tags",
                                 t("doctor.issues_bad_tags", list_key=list_key, ids=bad_tags),
                                 t("doctor.issues_bad_tags_sug"))
                        if bad_files:
                            warn("issues_bad_related_files",
                                 t("doctor.issues_bad_related_files", list_key=list_key, ids=bad_files),
                                 t("doctor.issues_bad_related_files_sug"))
                        # id フィールド検証（空文字・非文字列・スラッグ形式外）
                        bad_id: list = []
                        for _i, _iss in enumerate(dict_issues):
                            _raw_id = _iss.get("id")
                            _label  = _raw_id if isinstance(_raw_id, str) and _raw_id else f"[{_i}]"
                            if not isinstance(_raw_id, str) or not _raw_id.strip():
                                bad_id.append(_label)
                            elif not _SLUG_RE.match(_raw_id):
                                bad_id.append(_label)
                        if bad_id:
                            warn("issues_bad_id",
                                 t("doctor.issues_bad_id", list_key=list_key, ids=bad_id),
                                 t("doctor.issues_bad_id_sug"))
                        # category フィールド検証（スラッグ形式・長さチェック）
                        bad_cat: list = []
                        for _i, _iss in enumerate(dict_issues):
                            _cat = _iss.get("category")
                            _iid = _iss.get("id", f"[{_i}]")
                            if _cat is not None:
                                if not isinstance(_cat, str) or not _cat.strip():
                                    bad_cat.append(_iid)
                                elif not _SLUG_RE.match(_cat) or len(_cat) > _MAX_CATEGORY_LEN:
                                    bad_cat.append(_iid)
                        if bad_cat:
                            warn("issues_bad_category",
                                 t("doctor.issues_bad_category", list_key=list_key, ids=bad_cat),
                                 t("doctor.issues_bad_category_sug"))
                        if not any((non_dict_idx, bad_sev, dups, bad_text, bad_id, bad_cat, bad_tags, bad_files)):
                            ok(f"issues_{list_key}", t("doctor.issues_ok",
                               list_key=list_key, count=len(issues)))
            #endregion

            #region ロックファイル確認（PID生存確認・経過秒付き）
            if check_lock and proj and proj.exists():
                lock_file = proj / "AI_STATE.lock"
                if lock_file.exists():
                    try:
                        text = lock_file.read_text(encoding="utf-8").strip()
                        pid  = int(text) if text.isdigit() else None
                        age  = int(time.time() - lock_file.stat().st_mtime)
                        if pid is None:
                            warn("lock_bad_content",
                                 t("doctor.lock_bad_content", content=text),
                                 t("doctor.lock_bad_content_sug"))
                        elif _pid_exists(pid):
                            warn("lock_alive",
                                 t("doctor.lock_alive", pid=pid, age=age),
                                 t("doctor.lock_alive_sug"))
                        else:
                            warn("lock_stale",
                                 t("doctor.lock_stale", pid=pid, age=age),
                                 t("doctor.lock_stale_sug"))
                    except Exception as e:
                        warn("lock_parse_fail", t("doctor.lock_parse_fail", err=e),
                             t("doctor.lock_parse_fail_sug"))
                else:
                    ok("lock_clean", t("doctor.lock_clean"))
            #endregion

            #region CLI コマンド確認
            if check_cli:
                config = _load_cli_config()
                for ai_name in VALID_AI:
                    cfg  = config.get(ai_name, {})
                    cmd  = cfg.get("command", DEFAULT_CLI_CONFIG[ai_name]["command"])
                    path = _resolve_cli_path(ai_name, cmd)
                    if path:
                        ok(f"cli_{ai_name}", t("doctor.cli_ok", AI=ai_name.upper(), path=path))
                    else:
                        warn(f"cli_{ai_name}_missing",
                             t("doctor.cli_missing", AI=ai_name.upper(), cmd=cmd),
                             t("doctor.cli_missing_sug"))
            #endregion

            #region AI 呼び出し確認（高コスト・オプション）
            if check_ai_call:
                for ai_name in VALID_AI:
                    config = _load_cli_config()
                    cfg    = config.get(ai_name, {})
                    cmd    = cfg.get("command", DEFAULT_CLI_CONFIG[ai_name]["command"])
                    path   = _resolve_cli_path(ai_name, cmd)
                    if not path:
                        warn(f"ai_call_{ai_name}_skip",
                             t("doctor.ai_call_skip", AI=ai_name.upper()))
                        continue
                    try:
                        # ヘルスチェック用の簡易プロンプト（CLI確認目的）
                        _health_prompt = (
                            "This is a health check. Please reply with 'OK' only."
                            if get_lang() == 'en'
                            else "ヘルスチェックです。「OK」とだけ答えてください。"
                        )
                        ai_result = _call_ai_cli(ai_name, _health_prompt, timeout=30)
                        # i18n対応: エラーメッセージは言語によって "エラー:" / "Error:" で始まる
                        if ai_result.startswith(("エラー", "Error")):
                            warn(f"ai_call_{ai_name}_err",
                                 t("doctor.ai_call_err", AI=ai_name.upper(), resp=ai_result[:80]))
                        else:
                            ok(f"ai_call_{ai_name}", t("doctor.ai_call_ok", AI=ai_name.upper()))
                    except Exception as e:
                        err(f"ai_call_{ai_name}_exc",
                            t("doctor.ai_call_exc", AI=ai_name.upper(), err=e))
            #endregion

            #region 復旧関連ファイル確認
            if check_recovery and proj and proj.exists():
                archive = proj / "AI_STATE.archive.json"
                if archive.exists():
                    size_kb = archive.stat().st_size // 1024
                    ok("recovery_archive", t("doctor.recovery_archive", size_kb=size_kb))
                exports = list(proj.glob("*.export.json"))
                if exports:
                    ok("recovery_export", t("doctor.recovery_export", count=len(exports)))
            #endregion

            #region 出力
            ok_count   = sum(1 for d in diagnostics if d["level"] == "OK")
            warn_count = sum(1 for d in diagnostics if d["level"] == "WARN")
            err_count  = sum(1 for d in diagnostics if d["level"] == "ERR")

            if output == "json":
                return json.dumps(
                    {"summary": {"ok": ok_count, "warn": warn_count, "err": err_count},
                     "diagnostics": diagnostics},
                    ensure_ascii=False, indent=2,
                )

            _EMOJI = {"OK": "✅ OK  ", "WARN": "⚠️ WARN", "ERR": "❌ ERR "}
            lines = [t("doctor.header", ok=ok_count, warn=warn_count, err=err_count)]
            for d in diagnostics:
                prefix = _EMOJI.get(d["level"], d["level"])
                sug    = t("doctor.suggestion", sug=d["suggestion"]) if d.get("suggestion") else ""
                lines.append(f"{prefix}  {d['message']}{sug}")
            return "\n".join(lines)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)
    #endregion

#endregion

#region MCPツール — 状態管理

@mcp.tool()
def collab_status(calling_ai: str = "", project_path: str = '') -> str:
    """
    現在の協働開発状態を取得する。

    セッション開始時に必ず呼び出すこと。
    担当AI・モード・現在タスク・保留タスク・メモ・決定事項・既知の問題を返す。

    Args:
        calling_ai: 呼び出し元のAI（"claude" / "codex"）。指定すると担当AI不一致を警告する。
    """
    try:
        with state_mod.project_context(project_path):
            state = _load_state()

            proj_dir = _get_project_dir()
            lines = [
                t("status.header"),
                t("status.project",      name=state["project_name"]),
                t("status.path",         path=proj_dir),
                t("status.ai",           ai=state["current_ai"].upper()),
                t("status.mode",         mode=mode_label(state["mode"])),
                t("status.session",      session=state["session_count"]),
                t("status.last_updated", ts=state["last_updated"]),
            ]

            # Git 情報（取得できた場合のみ）
            git_info = get_git_info(proj_dir)
            if git_info:
                dirty_mark = t("status.git_dirty") if git_info["is_dirty"] else ""
                lines.append(t("status.git_branch", branch=f"{git_info['branch']}{dirty_mark}"))
                if git_info["commits"]:
                    lines.append(t("status.git_commit", commit=git_info["commits"][0]))

            # 担当AI不一致の警告
            if calling_ai and calling_ai in VALID_AI and calling_ai != state.get("current_ai"):
                lines = [
                    t("status.warn_ai_mismatch"),
                    t("status.warn_current_ai", ai=state["current_ai"].upper()),
                    t("status.warn_calling_ai", ai=calling_ai.upper()),
                    t("status.warn_handoff"),
                    "",
                ] + lines

            lines += ["", t("status.task_header")]
            if state.get("current_task"):
                task = state["current_task"]
                lines += [
                    t("status.task_id",    id=task["id"]),
                    t("status.task_title", title=task["title"]),
                ]
                if task.get("description"):
                    lines.append(t("status.task_desc", desc=task["description"]))
                lines.append(t("status.task_started",
                               ts=task["started_at"][:16],
                               ai=task.get("started_by", "?").upper()))
                if task.get("files_modified"):
                    lines.append(t("status.task_files"))
                    for fp in task["files_modified"]:
                        lines.append(f"  - {fp}")
            else:
                lines.append(t("status.task_none"))

            if state.get("pending_tasks"):
                lines += ["", t("status.pending_header")]
                for pt in state["pending_tasks"]:
                    lines.append(f"- [{pt['id']}] {pt['title']}")

            if state.get("notes"):
                note_count = len(state["notes"])
                lines += ["", t("status.notes_header", count=note_count)]
                # notes ソフト上限警告
                if note_count >= 300:
                    lines.append(t("status.notes_warn_300", count=note_count))
                elif note_count >= 200:
                    lines.append(t("status.notes_warn_200", count=note_count))
                for n in state["notes"][-5:]:
                    lines.append(f"- [{n['timestamp'][:16]}] ({n['ai'].upper()}) {n['text']}")

            if state.get("key_decisions"):
                lines += ["", t("status.decisions_header")]
                for dec in state["key_decisions"]:
                    lines.append(f"- [{dec['timestamp'][:10]}] {dec['title']}: {dec['content'][:100]}")

            if state.get("known_issues"):
                lines += ["", t("status.issues_header")]
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
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_set_task(title: str, description: str = "", project_path: str = '') -> str:
    """
    現在のタスクを設定する。既存のタスクは自動的に完了済みに移動する。

    Args:
        title: タスクのタイトル
        description: タスクの詳細説明（省略可）
    """
    try:
        with state_mod.project_context(project_path):
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
            _append_session_log(ai, t("set_task.log", id=task_id, title=title))
            return t("set_task.done", id=task_id, title=title)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_add_note(message: str, project_path: str = '') -> str:
    """
    作業メモを追加する。こまめに呼び出すことでハンドオフ精度が上がる。

    Args:
        message: メモの内容
    """
    try:
        with state_mod.project_context(project_path):
            err = _validate_input(message, "message")
            if err:
                return err
            with _state_transaction() as state:
                state["notes"].append({"timestamp": _now_iso(), "ai": state["current_ai"], "text": message})
                note_count = len(state["notes"])
                ai = state["current_ai"]
            _append_session_log(ai, t("add_note.log", text=message))
            result = t("add_note.done", text=message)
            # notes ソフト上限警告
            if note_count >= 300:
                result += t("add_note.warn_300", count=note_count)
            return result
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_record_decision(title: str, content: str, project_path: str = '') -> str:
    """
    重要な設計・実装の決定事項を記録する。

    Args:
        title: 決定事項のタイトル
        content: 決定内容と理由
    """
    try:
        with state_mod.project_context(project_path):
            err = _validate_input(title, "title") or _validate_input(content, "content")
            if err:
                return err
            with _state_transaction() as state:
                state["key_decisions"].append({
                    "timestamp": _now_iso(), "ai": state["current_ai"],
                    "title": title, "content": content,
                })
                ai = state["current_ai"]
            _append_session_log(ai, t("record_decision.log", title=title))
            return t("record_decision.done", title=title)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_record_issue(
    message: str,
    severity: str = "P2",
    category: str = "general",
    tags: list | None = None,
    related_files: list | None = None,
    project_path: str = '',
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
    try:
        with state_mod.project_context(project_path):
            tags         = tags or []
            related_files = related_files or []

            # 入力検証
            err = (_validate_input(message, "message")
                   or (severity not in VALID_SEVERITIES
                       and t("record_issue.err_severity", valid=VALID_SEVERITIES))
                   or (not _SLUG_RE.match(category)
                       and t("record_issue.err_category_slug", cat=category))
                   or (len(category) > _MAX_CATEGORY_LEN
                       and t("record_issue.err_category_long", max=_MAX_CATEGORY_LEN))
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
            _append_session_log(ai, t("record_issue.log", id=issue_id, sev=severity, text=message))
            return t("record_issue.done", emoji=emoji, id=issue_id, sev=severity, text=message)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_resolve_issue(issue_id: str, note: str = "", project_path: str = '') -> str:
    """
    既知の問題を解決済みにして一覧から取り除く。

    Args:
        issue_id: 解決する問題のID（例: issue-001）。collab_status で確認できる。
        note: 解決内容の補足（省略可）
    """
    try:
        with state_mod.project_context(project_path):
            # issue-016: note の入力検証
            if note:
                err = _validate_input(note, "note")
                if err:
                    return err
            # issue-014: issue_id の存在チェックを transaction 外で先に行う
            pre = _load_state()
            if not any(isinstance(i, dict) and i.get("id") == issue_id for i in pre.get("known_issues", [])):
                return t("resolve_issue.not_found", id=issue_id)

            with _state_transaction() as state:
                issues = state.get("known_issues", [])
                matched_index = next(
                    (i for i, iss in enumerate(issues)
                     if isinstance(iss, dict) and iss.get("id") == issue_id),
                    None,
                )
                if matched_index is None:
                    return t("resolve_issue.not_found", id=issue_id)
                issue = issues.pop(matched_index)
                issue["resolved_at"] = _now_iso()
                issue["resolved_by"] = state["current_ai"]
                if note:
                    issue["resolution_note"] = note
                state.setdefault("resolved_issues", []).append(issue)
                ai = state["current_ai"]
            _append_session_log(ai, t("resolve_issue.log", id=issue_id, text=issue["text"][:60]))
            return t("resolve_issue.done", id=issue_id, text=issue["text"])
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


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
    project_path: str = '',
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
    try:
        with state_mod.project_context(project_path):
            # 排他チェック
            if tags is not None and (add_tags is not None or remove_tags is not None):
                return t("update_issue.err_tags_conflict")
            if related_files is not None and (add_related_files is not None or remove_related_files is not None):
                return t("update_issue.err_files_conflict")

            # 入力検証
            if message is not None:
                err = _validate_input(message, "message")
                if err:
                    return err
            if severity is not None and severity not in VALID_SEVERITIES:
                return t("update_issue.err_severity", valid=VALID_SEVERITIES)
            if category is not None:
                if not _SLUG_RE.match(category):
                    return t("update_issue.err_category_slug", cat=category)
                if len(category) > _MAX_CATEGORY_LEN:
                    return t("update_issue.err_category_long", max=_MAX_CATEGORY_LEN)
            if status is not None and status not in VALID_ISSUE_STATUSES:
                return t("update_issue.err_status", valid=VALID_ISSUE_STATUSES)
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
                return t("update_issue.not_found", id=issue_id)

            with _state_transaction() as state:
                issue = next(
                    (i for i in state.get("known_issues", [])
                     if isinstance(i, dict) and i.get("id") == issue_id),
                    None,
                )
                if issue is None:
                    return t("update_issue.not_found_inner", id=issue_id)

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
                        for tg in add_tags:
                            if tg not in current_tags:
                                current_tags.append(tg)
                        issue["tags"] = current_tags[:_MAX_TAGS]
                    if remove_tags:
                        issue["tags"] = [tg for tg in issue.get("tags", []) if tg not in remove_tags]

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
            _append_session_log(ai, t("update_issue.log", id=issue_id))
            return t("update_issue.done",
                     emoji=emoji, id=issue_id,
                     sev=issue.get("severity", "?"), text=issue["text"],
                     cat=issue.get("category", "?"),
                     tags=issue.get("tags", []),
                     status=issue.get("status", "?"))
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_list_resolved(project_path: str = '') -> str:
    """
    解決済みの問題一覧を表示する。

    collab_resolve_issue() で解決済みにした問題を新しい順で一覧表示する。
    """
    try:
        with state_mod.project_context(project_path):
            state = _load_state()
            resolved = state.get("resolved_issues", [])
            if not resolved:
                return t("list_resolved.empty")

            lines = [t("list_resolved.header", count=len(resolved)), ""]
            for iss in reversed(resolved):  # 新しい順
                resolved_at = iss.get("resolved_at", "?")[:16]
                resolved_by = iss.get("resolved_by", "?").upper()
                emoji = _SEVERITY_EMOJI.get(iss.get("severity", "P2"), "")
                sev   = iss.get("severity", "?")
                tags  = f" ({', '.join(iss['tags'])})" if iss.get("tags") else ""
                # 旧テキストに [P0]〜[P3] プレフィックスが残っている場合は表示上だけ除去する
                text  = re.sub(r'^\[P[0-3]\]\s*', '', iss['text'])
                lines.append(f"- {emoji} [{iss['id']}][{sev}] {text}{tags}")
                lines.append(t("list_resolved.resolved_by", ts=resolved_at, ai=resolved_by))
                if iss.get("resolution_note"):
                    lines.append(t("list_resolved.note", note=iss["resolution_note"]))
            return "\n".join(lines)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_record_file(file_path: str, project_path: str = '') -> str:
    """
    現在のタスクで変更・作成したファイルを記録する。

    Args:
        file_path: ファイルパス（プロジェクトルートからの相対パス推奨）
    """
    try:
        with state_mod.project_context(project_path):
            # issue-016: ファイルパスの長さ・インジェクションタグ・制御文字を検証
            err = _validate_input(file_path, "file_path")
            if err:
                return err
            if any(c in file_path for c in ("\n", "\r", "\0")):
                return t("record_file.err_control")

            # issue-014: current_task チェックを transaction 外で行い、
            #            エラー時に last_updated が更新されないようにする
            if not _load_state().get("current_task"):
                return t("record_file.err_no_task")

            with _state_transaction() as state:
                if not state.get("current_task"):  # ロック内での二重確認
                    return t("record_file.err_no_task")
                files = state["current_task"]["files_modified"]
                already = file_path in files
                if not already:
                    files.append(file_path)
                ai = state["current_ai"]
            if already:
                return t("record_file.already", path=file_path)
            _append_session_log(ai, t("record_file.log", path=file_path))
            return t("record_file.done", path=file_path)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_change_mode(mode: str, project_path: str = '') -> str:
    """
    作業モードを変更する。

    Args:
        mode: plan（仕様検討）/ implement（実装）/ review（レビュー）/ debug（デバッグ）
    """
    try:
        with state_mod.project_context(project_path):
            if mode not in VALID_MODES:
                return t("change_mode.err", valid=" | ".join(VALID_MODES))
            with _state_transaction() as state:
                old_mode = state["mode"]
                state["mode"] = mode
                ai = state["current_ai"]
            _append_session_log(ai, t("change_mode.log", old=old_mode, new=mode))
            return t("change_mode.done", old=mode_label(old_mode), new=mode_label(mode))
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_add_pending_task(title: str, description: str = "", project_path: str = '') -> str:
    """
    保留タスクキューにタスクを追加する。

    Args:
        title: タスクのタイトル
        description: タスクの詳細説明（省略可）
    """
    try:
        with state_mod.project_context(project_path):
            err = _validate_input(title, "title") or (description and _validate_input(description, "description"))
            if err:
                return err
            with _state_transaction() as state:
                task_numbers = [
                    int(task["id"].split("-")[-1])
                    for task in state.get("pending_tasks", []) + state.get("completed_pending_tasks", [])
                    if task.get("id", "").startswith("pending-") and task["id"].split("-")[-1].isdigit()
                ]
                task_id = f"pending-{max(task_numbers, default=0) + 1:03d}"
                state["pending_tasks"].append({
                    "id": task_id,
                    "title": title, "description": description,
                    "added_at": _now_iso(), "added_by": state["current_ai"],
                })
                ai = state["current_ai"]
            _append_session_log(ai, t("add_pending.log", title=title))
            return t("add_pending.done", id=task_id, title=title)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_close_pending_task(task_id: str, note: str = "", project_path: str = '') -> str:
    """
    保留タスクを完了扱いにし、保留一覧から取り除く。

    Args:
        task_id: 完了する保留タスクID（例: pending-001）
        note: 完了時に残す補足（省略可）
    """
    try:
        with state_mod.project_context(project_path):
            # issue-016: note の入力検証
            if note:
                err = _validate_input(note, "note")
                if err:
                    return err
            # issue-014: task_id の存在チェックを transaction 外で先に行う
            if not any(pt.get("id") == task_id for pt in _load_state().get("pending_tasks", [])):
                return t("close_pending.not_found", id=task_id)

            with _state_transaction() as state:
                pending = state.get("pending_tasks", [])
                matched_index = next((i for i, task in enumerate(pending) if task.get("id") == task_id), None)
                if matched_index is None:
                    return t("close_pending.not_found", id=task_id)
                task = pending.pop(matched_index)
                task["completed_at"] = _now_iso()
                task["completed_by"] = state["current_ai"]
                if note:
                    task["completion_note"] = note
                state.setdefault("completed_pending_tasks", []).append(task)
                ai = state["current_ai"]
            _append_session_log(ai, t("close_pending.log", id=task_id, title=task["title"]))
            return t("close_pending.done", id=task_id, title=task["title"])
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_complete_task(note: str = "", project_path: str = '') -> str:
    """
    現在のタスクを完了済みにして一覧から取り除く。

    collab_set_task() で新タスクを作らずに現在タスクを完了させたい場合に使う。
    完了後は current_task が未設定になる。

    Args:
        note: 完了時のメモ・備考（省略可）
    """
    try:
        with state_mod.project_context(project_path):
            if note:
                err = _validate_input(note, "note")
                if err:
                    return err
            # issue-014: current_task チェックを transaction 外で先に行う
            if not _load_state().get("current_task"):
                return t("complete_task.err_no_task")

            with _state_transaction() as state:
                if not state.get("current_task"):  # ロック内での二重確認
                    return t("complete_task.err_no_task")
                task = state["current_task"]
                task["completed_at"] = _now_iso()
                task["completed_by"] = state["current_ai"]
                if note:
                    task["completion_note"] = note
                state["completed_tasks"].append(task)
                state["current_task"] = None
                ai = state["current_ai"]
            _append_session_log(ai, t("complete_task.log", id=task["id"], title=task["title"]))
            return t("complete_task.done", id=task["id"], title=task["title"])
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_generate_handoff(to_ai: str, dry_run: bool = False, project_path: str = '') -> str:
    """
    ハンドオフドキュメントを生成して担当AIを切り替える。

    Args:
        to_ai: 引き継ぎ先のAI。"claude" または "codex"
        dry_run: True にすると実際の書き込み・担当切り替えを行わずプレビューのみ返す
    """
    try:
        with state_mod.project_context(project_path):
            if to_ai not in VALID_AI:
                return t("generate_handoff.err_ai")

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

            _append_session_log(from_ai,
                t("generate_handoff.log", from_ai=from_ai.upper(), to_ai=to_ai.upper()))
            _create_session_log(to_ai, new_session, mode)

            app = t("generate_handoff.app_claude") if to_ai == "claude" else t("generate_handoff.app_codex")
            return t("generate_handoff.done",
                     from_ai=from_ai.upper(), to_ai=to_ai.upper(),
                     file=_handoff_file(), app=app)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_checkpoint(message: str, to_ai: str = "", dry_run: bool = False, project_path: str = '') -> str:
    """
    作業メモの追加とハンドオフ生成を一度に行う。

    Args:
        message: 引き継ぎに残す進捗・次の作業内容
        to_ai: 引き継ぎ先。"claude" / "codex"。省略時は現在担当でないAI。
        dry_run: True にするとメモ追加・ファイル書き込み・担当切り替えを行わずプレビューのみ返す
    """
    try:
        with state_mod.project_context(project_path):
            err = _validate_input(message, "message")
            if err:
                return err
            # issue-014: to_ai が明示指定されていて不正な場合は transaction 外で弾く
            if to_ai and to_ai not in VALID_AI:
                return t("checkpoint.err_ai")

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

            _append_session_log(from_ai, t("checkpoint.log_note", text=message))
            _append_session_log(from_ai,
                t("checkpoint.log_handoff", from_ai=from_ai.upper(), to_ai=target_ai.upper()))
            _create_session_log(target_ai, new_session, mode)
            return t("checkpoint.done",
                     from_ai=from_ai.upper(), to_ai=target_ai.upper(),
                     msg=message, file=_handoff_file())
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)

#endregion

#region MCPツール — AI相談・議論

@mcp.tool()
def collab_consult(ai: str, question: str, save_result: bool = True, project_path: str = '') -> str:
    """
    相手のAI（CLIバージョン）を一時的に呼び出して相談する。

    Claude Desktop から呼ぶと Codex CLI に相談でき、
    Codex Desktop から呼ぶと Claude CLI に相談できる。

    Args:
        ai: 呼び出すAI。"claude" または "codex"
        question: 相談・質問の内容
        save_result: 回答をメモとして状態に保存するか（デフォルト: True）
    """
    try:
        with state_mod.project_context(project_path):
            if ai not in VALID_AI:
                return t("err.invalid_ai")
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
                            "text": t("consult.note_label", AI=ai.upper(), question=short_q),
                            "consult": {"question": question, "response": response},
                        })
                        caller_ai = state["current_ai"]
                    _append_session_log(caller_ai, t("consult.log", AI=ai.upper(), question=short_q))
                except Exception:
                    save_failed = True

            result = t("consult.result", AI=ai.upper(), response=response)
            if save_failed:
                result += t("consult.save_failed")
            return result
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_discuss(ai: str, topic: str, rounds: int = 2, project_path: str = '') -> str:
    """
    相手のAI（CLIバージョン）と複数ラウンドの議論を行う。
    ラウンドごとにトークンを消費するため rounds は 2〜3 を推奨。

    Args:
        ai: 議論相手のAI。"claude" または "codex"
        topic: 議論するテーマ・問題
        rounds: 往復ラウンド数（デフォルト: 2、最大: 4）
    """
    try:
        with state_mod.project_context(project_path):
            if ai not in VALID_AI:
                return t("err.invalid_ai")
            err = _validate_input(topic, "topic")
            if err:
                return err

            rounds = min(max(rounds, 1), 4)
            history: list[dict] = []
            current_prompt = topic

            for i in range(rounds):
                context = _build_consult_prompt(current_prompt)
                if history:
                    context += "\n\n---\n\n" + t("discuss.history_header") + "\n"
                    for h in history:
                        context += f"\n**{h['speaker']}:** {h['text'][:400]}\n"
                response = _call_ai_cli(ai, context)
                history.append({"speaker": ai.upper(), "text": response})
                if i + 1 < rounds:
                    current_prompt = t("discuss.followup", response=response[:600])

            result_lines = [t("discuss.result_header", AI=ai.upper(), rounds=rounds), ""]
            for j, h in enumerate(history, 1):
                result_lines += [t("discuss.round_header", n=j, ai=h["speaker"]), "", h["text"], ""]
            result = "\n".join(result_lines)

            save_failed = False
            try:
                short_topic = topic[:60] + ("…" if len(topic) > 60 else "")
                with _state_transaction() as state:
                    state["notes"].append({
                        "timestamp": _now_iso(), "ai": state["current_ai"],
                        "text": t("discuss.note_label", AI=ai.upper(), topic=short_topic),
                        "discuss": {"topic": topic, "rounds": rounds, "history": history},
                    })
                    caller_ai = state["current_ai"]
                _append_session_log(caller_ai, t("discuss.log", AI=ai.upper(), topic=short_topic))
            except Exception:
                save_failed = True

            if save_failed:
                result += t("discuss.save_failed")
            return result
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_setup_cli(
    ai: str,
    command: str,
    args_before: list[str] | None = None,
    args_after: list[str] | None = None,
    project_path: str = '',
) -> str:
    """
    CLI の呼び出し設定をカスタマイズして保存する。
    デフォルト設定で動かない場合に使う。

    Args:
        ai: 設定するAI。"claude" または "codex"
        command: CLIのコマンド名またはフルパス
        args_before: プロンプトの前に渡す引数（省略時は空リスト）
        args_after: プロンプトの後に渡す引数（省略時は空リスト）
    """
    try:
        with state_mod.project_context(project_path):
            # ai の検証
            if ai not in VALID_AI:
                return t("err.invalid_ai")

            # command の検証: ファイル名のステム（拡張子なし）が VALID_AI に含まれるもののみ許可
            cmd_stem = Path(command).stem.lower()
            if cmd_stem not in VALID_AI:
                return t("setup_cli.err_cmd", cmd=command, stem=cmd_stem)

            # None デフォルトを空リストに正規化
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
            status = t("setup_cli.path_ok", path=path) if path else t("setup_cli.path_missing")
            return t("setup_cli.done",
                     file=cfg_file, AI=ai.upper(), cmd=command, status=status,
                     args_before=" ".join(args_before), args_after=" ".join(args_after))
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)

#endregion

#region MCPツール — メンテナンス

@mcp.tool()
def collab_search(query: str, project_path: str = '') -> str:
    """
    キーワードでメモ・決定事項・問題・タスクを横断検索する。

    メモ・決定事項・既知の問題・解決済み問題・保留タスク・現在タスクを
    大文字小文字を区別せずにキーワード検索する。

    Args:
        query: 検索キーワード
    """
    try:
        with state_mod.project_context(project_path):
            state = _load_state()
            q = query.lower()
            results: list[str] = []

            # メモ
            for n in state.get("notes", []):
                text = n.get("text", "")
                if q in text.lower():
                    results.append(t("search.note",
                                     ts=n["timestamp"][:16], ai=n["ai"].upper(), text=text))

            # 決定事項
            for d in state.get("key_decisions", []):
                title, content = d.get("title", ""), d.get("content", "")
                if q in title.lower() or q in content.lower():
                    results.append(t("search.decision",
                                     ts=d["timestamp"][:10], title=title, content=content[:100]))

            # 既知の問題（text + category + tags + related_files も検索対象）
            for iss in state.get("known_issues", []):
                if not isinstance(iss, dict):
                    continue
                hit = (q in iss.get("text", "").lower()
                       or q in iss.get("category", "").lower()
                       or any(q in tg.lower() for tg in iss.get("tags", []))
                       or any(q in fp.lower() for fp in iss.get("related_files", [])))
                if hit:
                    emoji = _SEVERITY_EMOJI.get(iss.get("severity", "P2"), "")
                    results.append(t("search.issue",
                                     emoji=emoji, id=iss["id"], sev=iss.get("severity", "?"), text=iss["text"]))

            # 解決済みの問題（同様に拡張フィールドも検索）
            for iss in state.get("resolved_issues", []):
                if not isinstance(iss, dict):
                    continue
                hit = (q in iss.get("text", "").lower()
                       or q in iss.get("category", "").lower()
                       or any(q in tg.lower() for tg in iss.get("tags", []))
                       or any(q in fp.lower() for fp in iss.get("related_files", []))
                       or q in iss.get("resolution_note", "").lower())
                if hit:
                    emoji = _SEVERITY_EMOJI.get(iss.get("severity", "P2"), "")
                    results.append(t("search.resolved",
                                     emoji=emoji, id=iss["id"], sev=iss.get("severity", "?"), text=iss["text"]))

            # 保留タスク
            for pt in state.get("pending_tasks", []):
                if q in pt.get("title", "").lower() or q in pt.get("description", "").lower():
                    results.append(t("search.pending", id=pt["id"], title=pt["title"]))

            # 現在タスク
            ct = state.get("current_task")
            if ct and (q in ct.get("title", "").lower() or q in ct.get("description", "").lower()):
                results.append(t("search.task", id=ct["id"], title=ct["title"]))

            # 完了済みタスク（issue-010: 検索漏れ修正）
            for ct2 in state.get("completed_tasks", []):
                hit = (q in ct2.get("title", "").lower() or q in ct2.get("description", "").lower()
                       or q in ct2.get("completion_note", "").lower())
                if not hit:
                    hit = any(q in fp.lower() for fp in ct2.get("files_modified", []))
                if hit:
                    results.append(t("search.task_done",
                                     id=ct2["id"], title=ct2["title"],
                                     ts=ct2.get("completed_at", "?")[:10]))

            # 完了した保留タスク（issue-010: 検索漏れ修正）
            for pt2 in state.get("completed_pending_tasks", []):
                if (q in pt2.get("title", "").lower() or q in pt2.get("description", "").lower()
                        or q in pt2.get("completion_note", "").lower()):
                    results.append(t("search.pending_done",
                                     id=pt2["id"], title=pt2["title"],
                                     ts=pt2.get("completed_at", "?")[:10]))

            if not results:
                return t("search.not_found", query=query)

            lines = [t("search.header", query=query, count=len(results)), ""]
            lines.extend(results)
            return "\n".join(lines)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_timeline(
    limit:      int = 20,
    since:      str = "",
    actor:      str = "",
    event_type: str = "",
    project_path: str = '',
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
    try:
        with state_mod.project_context(project_path):
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
                        f"[{iss.get('id','?')}] {t('timeline.issue_resolved_label', text=iss.get('text','')[:60])}",
                    )

            ct = state.get("current_task")
            if ct:
                _add(ct.get("started_at", ""), "task", ct.get("started_by", "?"),
                     f"[{ct.get('id','?')}] {ct.get('title','')[:60]}")

            for ct3 in state.get("completed_tasks", []):
                _add(ct3.get("completed_at", ct3.get("started_at", "")), "task_done",
                     ct3.get("started_by", "?"),
                     f"[{ct3.get('id','?')}] {t('timeline.task_done_label', title=ct3.get('title','')[:60])}")

            for pt3 in state.get("pending_tasks", []):
                _add(pt3.get("added_at", ""), "pending", pt3.get("added_by", "?"),
                     f"[{pt3.get('id','?')}] {pt3.get('title','')[:60]}")

            for pt4 in state.get("completed_pending_tasks", []):
                _add(pt4.get("completed_at", ""), "pending_done", pt4.get("added_by", "?"),
                     f"[{pt4.get('id','?')}] {t('timeline.pending_done_label', title=pt4.get('title','')[:60])}")

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
                return t("timeline.empty")

            # 種別ラベル（言語対応）
            KIND_LABELS: dict[str, str] = {
                "note":          t("timeline.kind.note"),
                "decision":      t("timeline.kind.decision"),
                "issue":         t("timeline.kind.issue"),
                "issue_resolved":t("timeline.kind.resolved"),
                "task":          t("timeline.kind.task"),
                "task_done":     t("timeline.kind.task_done"),
                "pending":       t("timeline.kind.pending"),
                "pending_done":  t("timeline.kind.pending_done"),
            }

            lines = [t("timeline.header", count=len(events)), ""]
            for e in events:
                kind_label = KIND_LABELS.get(e["kind"], e["kind"])
                ts = e["ts"][:16] if len(e["ts"]) >= 16 else e["ts"]
                lines.append(f"{ts}  {kind_label}  [{e['ai'].upper()}]  {e['label']}")

            return "\n".join(lines)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_request_review(
    ai:          str,
    focus:       list[str] | None = None,
    scope:       str = "",
    save_result: bool = True,
    project_path: str = '',
) -> str:
    """
    相手AIにコードレビューまたは設計レビューを依頼する。
    collab_consult の薄いラッパー。

    Args:
        ai:          レビュアーAI。"claude" または "codex"
        focus:       レビューの重点事項リスト（例: ["セキュリティ", "パフォーマンス"]）（省略時は空リスト）
        scope:       レビュー対象の説明（ファイル名・機能名など）
        save_result: 結果をメモとして保存するか（デフォルト: True）
    """
    try:
        with state_mod.project_context(project_path):
            if ai not in VALID_AI:
                return t("err.invalid_ai")

            # None デフォルトを空リストに正規化
            if not isinstance(focus, list):
                focus = []
            focus_text = "・".join(focus) if focus else t("request_review.focus_default")
            scope_text = scope or t("request_review.scope_default")
            question = t("request_review.question", scope=scope_text, focus=focus_text)

            err = _validate_input(question, "question")
            if err:
                return err

            response    = _call_ai_cli(ai, _build_consult_prompt(question))
            save_failed = False

            if save_result:
                try:
                    label = t("request_review.note_label", AI=ai.upper(), scope=scope_text[:60])
                    with _state_transaction() as state:
                        state["notes"].append({
                            "timestamp": _now_iso(), "ai": state["current_ai"],
                            "text":    label,
                            "consult": {"question": question, "response": response},
                        })
                        caller_ai = state["current_ai"]
                    _append_session_log(caller_ai, t("request_review.log", AI=ai.upper(), scope=scope_text[:60]))
                except Exception:
                    save_failed = True

            result = t("request_review.result", AI=ai.upper(), response=response)
            if save_failed:
                result += t("request_review.save_failed")
            return result
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_summary(project_path: str = '') -> str:
    """
    現在の状態をコンパクトな4行で表示する。

    collab_status() の簡易版。ログ確認やヘッダ把握に使う。
    """
    try:
        with state_mod.project_context(project_path):
            state = _load_state()
            ct = state.get("current_task")
            task_str = f"[{ct['id']}] {ct['title']}" if ct else t("summary.task_none")
            issues   = len(state.get("known_issues", []))
            pending  = len(state.get("pending_tasks", []))

            return "\n".join([
                t("summary.line1", project=state["project_name"],
                  ai=state["current_ai"].upper(), mode=mode_label(state["mode"]),
                  session=state["session_count"]),
                t("summary.line2", task=task_str),
                t("summary.line3", pending=pending, issues=issues),
                t("summary.line4", ts=state["last_updated"][:16]),
            ])
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_cleanup_sessions(keep_per_ai: int = 5, project_path: str = '') -> str:
    """
    ai_sessions/ フォルダの古いセッションログを削除する。

    AIごとに新しい順で指定件数だけ残し、残りを削除する。
    セッションログが積み重なってきたときに呼ぶ。

    Args:
        keep_per_ai: AIごとに残すログファイル数（デフォルト: 5）
    """
    try:
        with state_mod.project_context(project_path):
            if keep_per_ai < 1:
                return t("cleanup_sessions.err")

            sd = _sessions_dir()
            if not sd.exists():
                return t("cleanup_sessions.no_dir")

            deleted: list[str] = []
            kept: dict[str, int] = {}
            for ai_name in VALID_AI:
                logs = sorted(sd.glob(f"*_{ai_name}.md"), reverse=True)  # 新しい順
                kept[ai_name] = min(len(logs), keep_per_ai)
                for log_file in logs[keep_per_ai:]:
                    log_file.unlink(missing_ok=True)
                    deleted.append(log_file.name)

            if not deleted:
                summary_str = "  " + "、".join(
                    t("cleanup_sessions.summary_item", AI=ai_n.upper(), count=kept[ai_n])
                    for ai_n in VALID_AI
                )
                return t("cleanup_sessions.no_target", keep=keep_per_ai, summary=summary_str)

            kept_str = "  " + "、".join(
                t("cleanup_sessions.kept_item", AI=ai_n.upper(), count=kept[ai_n])
                for ai_n in VALID_AI
            )
            return t("cleanup_sessions.done",
                     count=len(deleted), kept=kept_str,
                     files="\n".join(f"  - {n}" for n in deleted))
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_cleanup_history(
    keep_notes: int = 100,
    keep_completed_tasks: int = 50,
    archive: bool = True,
    dry_run: bool = False,
    project_path: str = '',
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
    try:
        with state_mod.project_context(project_path):
            if keep_notes < 1 or keep_completed_tasks < 1:
                return t("cleanup_history.err")

            # dry_run: 変更せずに予測結果を返す
            state = _load_state()
            notes_total     = len(state.get("notes", []))
            tasks_total     = len(state.get("completed_tasks", []))
            notes_trim      = max(0, notes_total - keep_notes)
            tasks_trim      = max(0, tasks_total - keep_completed_tasks)

            if notes_trim == 0 and tasks_trim == 0:
                return t("cleanup_history.no_need",
                         notes=notes_total, keep_notes=keep_notes,
                         tasks=tasks_total, keep_tasks=keep_completed_tasks)

            if dry_run:
                archive_dest = (t("cleanup_history.archive_dest") if archive
                                else t("cleanup_history.delete_dest"))
                return t("cleanup_history.dry_run",
                         notes=notes_total, notes_after=notes_total - notes_trim, notes_trim=notes_trim,
                         tasks=tasks_total, tasks_after=tasks_total - tasks_trim, tasks_trim=tasks_trim,
                         archive_dest=archive_dest)

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
                _write_atomic(af, json.dumps(arc, ensure_ascii=False, indent=2))

            # 状態を更新（古いレコードを削除）
            with _state_transaction() as st:
                st["notes"]           = st["notes"][notes_trim:]
                st["completed_tasks"] = st["completed_tasks"][tasks_trim:]

            dest_note = t("cleanup_history.archive_note") if archive else t("cleanup_history.delete_note")
            return t("cleanup_history.done",
                     notes=notes_total, notes_after=notes_total - notes_trim, notes_trim=notes_trim,
                     tasks=tasks_total, tasks_after=tasks_total - tasks_trim, tasks_trim=tasks_trim,
                     dest=dest_note)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_export_state(
    output_path: str = "",
    include_sessions: bool = False,
    redact_cli_config: bool = True,
    project_path: str = '',
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
    try:
        with state_mod.project_context(project_path):
            state = _load_state()
            proj_dir = _get_project_dir()

            # 出力パスを決定する
            if output_path:
                out = Path(output_path)
                if not out.is_absolute():
                    return t("export.err_path")
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
                            session_data[log_file.name] = t("export.session_read_error")
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
                return t("export.err_write", err=e)

            return t("export.done",
                     out=out, checksum=checksum[:16],
                     notes=len(state.get("notes", [])),
                     decisions=len(state.get("key_decisions", [])),
                     issues=len(state.get("known_issues", [])))
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_import_state(
    input_path: str,
    mode: str = "validate",
    backup: bool = True,
    project_path: str = '',
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
    try:
        with state_mod.project_context(project_path):
            if mode not in ("validate", "merge", "replace"):
                return t("import.err_mode")

            in_path = Path(input_path)
            if not in_path.is_absolute():
                return t("import.err_path")
            if not in_path.exists():
                return t("import.err_not_found", path=in_path)

            # ファイルを読み込む（issue-022: BOM付きUTF-8も許容）
            try:
                with open(in_path, "r", encoding="utf-8-sig") as f:
                    payload = json.load(f)
            except Exception as e:
                return t("import.err_read", err=e)

            # チェックサム検証
            stored_checksum = payload.pop("checksum", None)
            if stored_checksum is None:
                return t("import.err_no_checksum")

            payload_json     = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            calc_checksum    = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            payload["checksum"] = stored_checksum  # 元に戻す（表示用）

            if calc_checksum != stored_checksum:
                return t("import.err_checksum_mismatch",
                         stored=stored_checksum[:16], calc=calc_checksum[:16])

            imported_state = payload.get("state", {})
            _unknown       = t("import.unknown")
            exported_at    = payload.get("exported_at", _unknown)
            source_project = payload.get("source_project", _unknown)

            # ── validate モード ─────────────────────────────────────────────────
            if mode == "validate":
                return t("import.validated",
                         exported_at=exported_at, source=source_project,
                         notes=len(imported_state.get("notes", [])),
                         decisions=len(imported_state.get("key_decisions", [])),
                         issues=len(imported_state.get("known_issues", [])),
                         tasks=len(imported_state.get("completed_tasks", [])))

            # ── merge / replace モード ──────────────────────────────────────────
            if mode == "replace" and backup:
                # 現在の状態を replace 前にバックアップ
                ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                bak = _get_project_dir() / f"AI_STATE_before_import_{ts}.json"
                try:
                    current_state = _load_state()
                    _write_atomic(bak, json.dumps(current_state, ensure_ascii=False, indent=2))
                except Exception as e:
                    return t("import.err_backup", err=e)

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
                backup_note = t("import.replaced_backup", name=bak.name) if backup else ""
                return t("import.replaced",
                         backup=backup_note, exported_at=exported_at, source=source_project)
            else:
                return t("import.merged",
                         notes=merged_notes, decisions=merged_decs, issues=merged_issues,
                         exported_at=exported_at)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)


@mcp.tool()
def collab_set_handoff_template(preset: str = "full", project_path: str = '') -> str:
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
    try:
        with state_mod.project_context(project_path):
            if preset not in VALID_HANDOFF_TEMPLATES:
                return t("set_template.err", valid=VALID_HANDOFF_TEMPLATES, preset=preset)

            with _state_transaction() as state:
                old_preset = state.get("handoff_template", "full")
                state["handoff_template"] = preset

            desc = t(f"set_template.desc.{preset}", **{}) or preset
            return t("set_template.done", old=old_preset, new=preset, desc=desc)
    except RuntimeError as _pp_e:
        return t("err.runtime", msg=_pp_e)

#endregion

#region エントリポイント

_VERSION = "1.1.0"

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
  collab_list_projects      最近使ったプロジェクト一覧を表示する

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
