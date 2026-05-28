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
import json
import datetime
import os
import shutil
import subprocess
import sys
import time
import tempfile
from contextlib import contextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

#region 定数・プロジェクト解決

# 現在のプロジェクトパス（プロセス内メモリのみ。ファイルへの書き出しはしない）
_current_project: Path | None = None

# デフォルトのCLI呼び出し設定
DEFAULT_CLI_CONFIG: dict = {
    "claude": {
        "command":     "claude",
        "args_before": ["-p"],
        "args_after":  ["--output-format", "text"],
    },
    "codex": {
        "command":     "codex",
        "args_before": ["exec"],
        "args_after":  [],
    },
}

VALID_MODES = ["plan", "implement", "review", "debug"]
VALID_AI    = ["claude", "codex"]

MODE_LABELS: dict[str, str] = {
    "plan":      "仕様検討・設計",
    "implement": "実装",
    "review":    "レビュー",
    "debug":     "デバッグ",
}

# 入力文字列の最大長（プロンプトインジェクション・状態肥大化対策）
_MAX_INPUT_LEN = 2000

# 状態ファイルの必須キーとデフォルト値（スキーマ検証・補完用）
_STATE_DEFAULTS: dict = {
    "version":                 "1.0",
    "project_name":            "不明",
    "current_ai":              "claude",
    "mode":                    "implement",
    "session_count":           1,
    "last_updated":            "",
    "current_task":            None,
    "completed_tasks":         [],
    "notes":                   [],
    "key_decisions":           [],
    "known_issues":            [],
    "resolved_issues":         [],
    "pending_tasks":           [],
    "completed_pending_tasks": [],
}

#endregion

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

#region プロジェクトディレクトリ解決

def _get_project_dir() -> Path:
    """現在のプロジェクトディレクトリをメモリから取得する"""
    if _current_project is None:
        raise RuntimeError(
            "現在のプロジェクトが設定されていません。\n"
            "collab_switch_project('プロジェクトのフルパス') を呼び出してください。"
        )
    return _current_project

def _state_file()   -> Path: return _get_project_dir() / "AI_STATE.json"
def _handoff_file() -> Path: return _get_project_dir() / "HANDOFF.md"
def _sessions_dir() -> Path: return _get_project_dir() / "ai_sessions"

#endregion

#region 内部ユーティリティ

# HANDOFF.md の信頼境界タグ（このタグを含む入力は拒否する）
_INJECTION_TAG = "<!-- /USER INPUT -->"

def _validate_input(text: str, field: str = "入力", max_len: int = _MAX_INPUT_LEN) -> str | None:
    """
    入力文字列の長さとインジェクションタグを検証する。
    問題があればエラーメッセージを返し、問題なければ None を返す。
    """
    if len(text) > max_len:
        return f"エラー: {field}が長すぎます（最大{max_len}文字、現在{len(text)}文字）。"
    if _INJECTION_TAG in text:
        return f"エラー: {field}に使用できない文字列が含まれています。"
    return None


def _pid_exists(pid: int) -> bool:
    """PIDが現在実行中かどうか確認する（クロスプラットフォーム対応）"""
    if sys.platform == "win32":
        # Windows: OpenProcess でハンドルが取れるか確認する
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    else:
        # POSIX: シグナル0でプロセスの存在を確認する（実際にはシグナルを送らない）
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # プロセスは存在するがアクセス権がない


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")

def _now_display() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _load_state() -> dict:
    """状態ファイルを読み込む（旧フォーマットの自動マイグレーションを含む）"""
    sf = _state_file()
    if not sf.exists():
        raise RuntimeError(
            f"AI_STATE.json が見つかりません: {sf}\n"
            "collab_switch_project(path, project_name='プロジェクト名') を呼び出して初期化してください。"
        )
    with open(sf, "r", encoding="utf-8") as f:
        state = json.load(f)

    # スキーマ検証: 必須キーの存在確認とデフォルト値での補完
    for key, default in _STATE_DEFAULTS.items():
        if key not in state:
            # issue-005: copy.deepcopy でリストの可変デフォルトが別プロジェクトに漏洩するのを防ぐ
            state[key] = copy.deepcopy(default)
        elif isinstance(default, list) and not isinstance(state[key], list):
            # リスト型が期待されるキーが別の型になっていた場合はリセット
            state[key] = []
        elif isinstance(default, int) and not isinstance(state[key], int):
            try:
                state[key] = int(state[key])
            except (ValueError, TypeError):
                state[key] = copy.deepcopy(default)

    # issue-011: 文字列フィールドの型検証（破損データでの AttributeError を防ぐ）
    for str_key in ("version", "project_name", "last_updated"):
        if not isinstance(state.get(str_key), str):
            state[str_key] = str(state[str_key]) if state.get(str_key) is not None else _STATE_DEFAULTS[str_key]
    # current_ai / mode は値域も検証する
    if state.get("current_ai") not in VALID_AI:
        state["current_ai"] = "claude"
    if state.get("mode") not in VALID_MODES:
        state["mode"] = "implement"
    # current_task が dict 以外なら None にリセット
    if state.get("current_task") is not None and not isinstance(state["current_task"], dict):
        state["current_task"] = None

    # known_issues: 旧フォーマット（文字列）を構造化dictに移行
    migrated_issues = []
    for i, issue in enumerate(state.get("known_issues", [])):
        if isinstance(issue, str):
            migrated_issues.append({
                "id": f"issue-{i + 1:03d}",
                "text": issue,
                "added_at": "unknown",
                "added_by": "unknown",
            })
        else:
            migrated_issues.append(issue)
    state["known_issues"] = migrated_issues

    # issue-013: ネストレコードの normalize（必須キー補完・型修正）
    # 破損レコード（非dict）は除外し、残りを正規化してツールが例外終了しないようにする
    state["notes"] = [
        r for r in (_normalize_note(n) for n in state["notes"]) if r is not None
    ]
    state["key_decisions"] = [
        r for r in (_normalize_decision(d) for d in state["key_decisions"]) if r is not None
    ]
    state["pending_tasks"] = [
        r for r in (_normalize_pending_task(t) for t in state["pending_tasks"]) if r is not None
    ]
    state["completed_tasks"] = [
        r for r in (_normalize_task(t) for t in state["completed_tasks"]) if r is not None
    ]
    state["completed_pending_tasks"] = [
        r for r in (_normalize_pending_task(t) for t in state["completed_pending_tasks"]) if r is not None
    ]
    if state.get("current_task") is not None:
        state["current_task"] = _normalize_task(state["current_task"])

    return state


def _normalize_task(task) -> dict | None:
    """タスクレコードの必須キーを補完・型修正する。非dictは None を返す"""
    if not isinstance(task, dict):
        return None
    task.setdefault("id", "task-???")
    task.setdefault("title", "（データ破損）")
    task.setdefault("description", "")
    task.setdefault("started_at", "")
    task.setdefault("started_by", "unknown")
    if not isinstance(task.get("files_modified"), list):
        task["files_modified"] = []
    return task


def _normalize_note(note) -> dict | None:
    """メモレコードの必須キーを補完・型修正する。非dictは None を返す"""
    if not isinstance(note, dict):
        return None
    note.setdefault("timestamp", "")
    note.setdefault("ai", "unknown")
    if not isinstance(note.get("text"), str):
        note["text"] = str(note.get("text", ""))
    return note


def _normalize_decision(dec) -> dict | None:
    """決定事項レコードの必須キーを補完・型修正する。非dictは None を返す"""
    if not isinstance(dec, dict):
        return None
    dec.setdefault("timestamp", "")
    dec.setdefault("ai", "unknown")
    dec.setdefault("title", "（データ破損）")
    if not isinstance(dec.get("content"), str):
        dec["content"] = str(dec.get("content", ""))
    return dec


def _normalize_pending_task(task) -> dict | None:
    """保留タスクレコードの必須キーを補完・型修正する。非dictは None を返す"""
    if not isinstance(task, dict):
        return None
    task.setdefault("id", "pending-???")
    task.setdefault("title", "（データ破損）")
    task.setdefault("description", "")
    task.setdefault("added_at", "")
    task.setdefault("added_by", "unknown")
    return task

class _StateLock:
    """
    AI_STATE.json の簡易ファイルロック。
    Claude と Codex が同時に read-modify-write する際のデータ消失を防ぐ。
    ロックファイルに PID を書き込み、スタール解除時に所有者を確認する。
    クラッシュ後に残ったロックファイルは STALE_SEC 秒後に自動解除する。
    """
    _TIMEOUT_SEC = 10  # ロック取得タイムアウト
    _STALE_SEC   = 30  # この秒数より古いロックファイルはスタールとみなす

    def __init__(self, sf: Path):
        self._lock = sf.with_suffix(".lock")

    def _read_lock_pid(self) -> int | None:
        """ロックファイルに記録されたPIDを読む。読めない場合は None を返す"""
        try:
            text = self._lock.read_text(encoding="utf-8").strip()
            return int(text) if text.isdigit() else None
        except OSError:
            return None

    def __enter__(self) -> "_StateLock":
        deadline = time.monotonic() + self._TIMEOUT_SEC
        my_pid = os.getpid()
        while time.monotonic() < deadline:
            try:
                # exist_ok=False → 排他的作成（ほぼアトミック）
                self._lock.touch(exist_ok=False)
                # PIDを書き込んで所有者を記録する
                try:
                    self._lock.write_text(str(my_pid), encoding="utf-8")
                except OSError:
                    pass
                return self
            except FileExistsError:
                # スタールロックを検出したら PID の生存を確認してから解除
                try:
                    age = time.time() - self._lock.stat().st_mtime
                    if age > self._STALE_SEC:
                        lock_pid = self._read_lock_pid()
                        # 自分のPIDでないロックのみ対象
                        if lock_pid != my_pid:
                            # issue-007: PID生存確認 — 生存中のプロセスのロックは奪わない
                            if lock_pid is not None and _pid_exists(lock_pid):
                                # 所有プロセスがまだ動いている → スタールではない
                                time.sleep(0.05)
                                continue
                            self._lock.unlink(missing_ok=True)
                            continue
                except OSError:
                    pass
                time.sleep(0.05)
        raise RuntimeError(
            f"AI_STATE.json のロック取得がタイムアウトしました（{self._TIMEOUT_SEC}秒）。\n"
            f"ロックファイルが残っている場合は手動で削除してください: {self._lock}"
        )

    def __exit__(self, *_) -> None:
        # 自分のPIDのロックのみ削除（他プロセスが上書きした場合は削除しない）
        lock_pid = self._read_lock_pid()
        if lock_pid is None or lock_pid == os.getpid():
            self._lock.unlink(missing_ok=True)


def _save_state(state: dict) -> None:
    """状態ファイルに原子的に保存する（ファイルロック＋一時ファイル経由のリネーム）"""
    state["last_updated"] = _now_iso()
    sf = _state_file()

    # 一時ファイルに書き込んでからリネーム → 書き込み中断による破損を防ぐ
    tmp_fd, tmp_path = tempfile.mkstemp(dir=sf.parent, suffix=".tmp", prefix="AI_STATE_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, sf)  # アトミックなリネーム
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

@contextmanager
def _state_transaction():
    """
    AI_STATE.json への read-modify-write をロックで保護するコンテキストマネージャ。

    with _state_transaction() as state:
        state["notes"].append(...)
    # ← ここでロックを解放しつつ原子的に保存される

    _load_state() と _save_state() を直接呼ぶ代わりにこれを使うこと。
    """
    sf = _state_file()
    with _StateLock(sf):
        state = _load_state()
        yield state
        _save_state(state)


def _write_atomic(path: Path, content: str) -> None:
    """テキストファイルを一時ファイル経由で原子的に書き込む（クラッシュ時の破損防止）"""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _append_session_log(ai_name: str, message: str) -> None:
    """現在のセッションログに1行追記する。失敗時は握り潰さず警告を出す"""
    sd = _sessions_dir()
    if not sd.exists():
        return
    logs = sorted(sd.glob(f"*_{ai_name}.md"), reverse=True)
    if not logs:
        return
    time_str = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        with open(logs[0], "a", encoding="utf-8") as f:
            f.write(f"- [{time_str}] [MCP] {message}\n")
    except OSError as e:
        # セッションログへの追記失敗は致命的ではないが記録する
        import warnings
        warnings.warn(f"セッションログへの追記に失敗しました: {logs[0]}: {e}", stacklevel=2)


def _create_session_log(ai_name: str, session_number: int, mode: str) -> None:
    """新しいセッションログファイルを原子的に作成する"""
    sd = _sessions_dir()
    sd.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    content = (
        f"# セッションログ: {ai_name.upper()}\n"
        f"**開始日時:** {_now_display()}\n"
        f"**セッション番号:** {session_number}\n"
        f"**モード:** {MODE_LABELS.get(mode, mode)}\n"
        f"\n## 作業ログ\n"
    )
    _write_atomic(sd / f"{ts}_{ai_name}.md", content)

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
    global _current_project

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
        _current_project = path
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
    _current_project = path
    with open(state_file, "r", encoding="utf-8") as f:
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
    """現在アクティブなプロジェクトのパスを確認する。"""
    if _current_project is None:
        return "現在のプロジェクトは設定されていません。collab_switch_project() を呼び出してください。"
    return f"現在のプロジェクト: {_current_project}"

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
        for issue in state["known_issues"]:
            if isinstance(issue, dict):
                lines.append(f"- [{issue['id']}] {issue['text']}")
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
def collab_record_issue(message: str) -> str:
    """既知の問題・バグ・注意点を記録する。"""
    err = _validate_input(message, "message")
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
            "id": issue_id,
            "text": message,
            "added_at": _now_iso(),
            "added_by": state["current_ai"],
        })
        ai = state["current_ai"]
    _append_session_log(ai, f"問題記録: [{issue_id}] {message}")
    return f"問題を記録しました: [{issue_id}] {message}"


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
        lines.append(f"- [{iss['id']}] {iss['text']}")
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
def collab_generate_handoff(to_ai: str) -> str:
    """
    ハンドオフドキュメントを生成して担当AIを切り替える。

    Args:
        to_ai: 引き継ぎ先のAI。"claude" または "codex"
    """
    if to_ai not in VALID_AI:
        return f"エラー: AIは 'claude' または 'codex' を指定してください。"

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
def collab_checkpoint(message: str, to_ai: str = "") -> str:
    """
    作業メモの追加とハンドオフ生成を一度に行う。

    Args:
        message: 引き継ぎに残す進捗・次の作業内容
        to_ai: 引き継ぎ先。"claude" / "codex"。省略時は現在担当でないAI。
    """
    err = _validate_input(message, "message")
    if err:
        return err
    # issue-014: to_ai が明示指定されていて不正な場合は transaction 外で弾く
    if to_ai and to_ai not in VALID_AI:
        return "エラー: AIは 'claude' または 'codex' を指定してください。"

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

#region ハンドオフ文書生成

def _build_handoff(state: dict, from_ai: str, to_ai: str) -> str:
    """ハンドオフ用マークダウン文書を生成する"""
    mode_label = MODE_LABELS.get(state["mode"], state["mode"])
    lines = [
        "# AI協働開発 ハンドオフドキュメント", "",
        f"> **引き継ぎ元:** {from_ai.upper()}　→　**引き継ぎ先:** {to_ai.upper()}",
        f"> **日時:** {_now_display()}　｜　**プロジェクト:** {state['project_name']}",
        f"> **モード:** {mode_label}　｜　**セッション:** #{state['session_count']}",
        "", "---", "", "## 現在のタスク", "",
    ]

    if state.get("current_task"):
        task = state["current_task"]
        # issue-009: タスクタイトル/詳細もユーザー入力なのでタグでラップする
        lines += [f"**タスクID:** `{task['id']}`",
                  f"**タイトル:** <!-- USER INPUT -->{task['title']}<!-- /USER INPUT -->"]
        if task.get("description"):
            lines.append(f"**詳細:** <!-- USER INPUT -->{task['description']}<!-- /USER INPUT -->")
        lines.append(f"**開始:** {task['started_at'][:16]}  担当: {task.get('started_by', '?').upper()}")
        if task.get("files_modified"):
            # issue-016: files_modified もユーザー入力なのでタグでラップする
            lines += ["", "**変更済みファイル:**"] + [
                f"- <!-- USER INPUT -->`{fp}`<!-- /USER INPUT -->" for fp in task["files_modified"]
            ]
    else:
        lines.append("*タスクは設定されていません。*")

    def section(title, items, empty="*なし*"):
        return ["", "---", "", f"## {title}", ""] + (items if items else [empty])

    lines += section("保留中のタスク",
        [f"- [ ] <!-- USER INPUT -->{t['title']}<!-- /USER INPUT -->"
         + (f" — <!-- USER INPUT -->{t['description']}<!-- /USER INPUT -->" if t.get("description") else "")
         for t in state.get("pending_tasks", [])])
    # 外部入力（ユーザーが記録した内容）はタグで囲んで信頼済み指示と区別する
    notes = state.get("notes", [])
    note_lines = []
    if len(notes) > 10:
        note_lines.append(f"- *過去{len(notes) - 10}件のメモを省略*")
    note_lines += [
        f"- `{n['timestamp'][:16]}` ({n['ai'].upper()}) <!-- USER INPUT -->{n['text']}<!-- /USER INPUT -->"
        for n in notes[-10:]
    ]
    lines += section("最近のメモ（最新10件）", note_lines)

    decisions = state.get("key_decisions", [])
    if decisions:
        lines += ["", "---", "", "## 重要な決定事項", ""]
        if len(decisions) > 10:
            lines.append(f"*過去{len(decisions) - 10}件の決定事項を省略*")
            lines.append("")
        for dec in decisions[-10:]:
            lines += [
                f"### <!-- USER INPUT -->{dec['title']}<!-- /USER INPUT -->",
                f"*{dec['timestamp'][:10]}  by {dec['ai'].upper()}*",
                "",
                "<!-- USER INPUT -->",
                dec["content"],
                "<!-- /USER INPUT -->",
                "",
            ]
    else:
        lines += ["", "---", "", "## 重要な決定事項", "", "*なし*"]

    def _fmt_issue(iss) -> str:
        if isinstance(iss, dict):
            return f"- ⚠️ [{iss['id']}] <!-- USER INPUT -->{iss['text']}<!-- /USER INPUT -->"
        return f"- ⚠️ <!-- USER INPUT -->{iss}<!-- /USER INPUT -->"

    lines += section("既知の問題・注意点",
        [_fmt_issue(i) for i in state.get("known_issues", [])])
    # issue-016: 完了タスクのタイトルもユーザー入力なのでタグでラップする
    lines += section("完了済みタスク（最近5件）",
        [f"- ✅ `{t['id']}` <!-- USER INPUT -->{t['title']}<!-- /USER INPUT --> ({t.get('completed_at', '?')[:10]})"
         for t in state.get("completed_tasks", [])[-5:]])
    lines += section("完了した保留タスク（最近5件）",
        [f"- ✅ `{t['id']}` <!-- USER INPUT -->{t['title']}<!-- /USER INPUT --> ({t.get('completed_at', '?')[:10]})"
         for t in state.get("completed_pending_tasks", [])[-5:]])

    lines += [
        "", "---", "", f"## {to_ai.upper()} セッション開始手順", "",
        "**1. プロジェクトを設定する（毎セッション必須）**",
        "```", f'collab_switch_project("{_get_project_dir()}")', "```", "",
        "**2. 状態を確認する**",
        "```", "collab_status()", "```", "",
        "**3. 作業中はこまめにメモを残す**",
        "```", 'collab_add_note("気づいたことや進捗")', "```", "",
        "**4. セッション終了・レートリミット前にチェックポイントを生成する**",
        "```", f'collab_checkpoint("ここまでの進捗と次の作業", "{from_ai}")', "```",
    ]
    return "\n".join(lines) + "\n"

#endregion

#region CLI呼び出しユーティリティ

def _cli_config_file() -> Path:
    """CLI設定ファイルのパスを返す（プロジェクトフォルダ内）"""
    return _get_project_dir() / "cli_config.json"


def _load_cli_config() -> dict:
    """CLI設定を読み込む（プロジェクトフォルダ内の cli_config.json を参照）"""
    config = {k: dict(v) for k, v in DEFAULT_CLI_CONFIG.items()}
    try:
        cfg_file = _cli_config_file()
        if cfg_file.exists():
            with open(cfg_file, "r", encoding="utf-8") as f:
                for ai, cfg in json.load(f).items():
                    config.setdefault(ai, {}).update(cfg)
    except RuntimeError:
        # プロジェクト未設定の場合はデフォルト設定を返す
        pass
    return config


def _resolve_cli_path(ai: str, command: str) -> str | None:
    """CLIの実行ファイルパスを解決する"""
    found = shutil.which(command)
    if found:
        return found
    if ai == "codex":
        env_path = os.environ.get("CODEX_CLI_PATH")
        if env_path and Path(env_path).exists():
            return env_path
        codex_bin = Path.home() / "AppData" / "Local" / "OpenAI" / "Codex" / "bin"
        if codex_bin.exists():
            matches = sorted(codex_bin.rglob("codex.exe"), reverse=True)
            if matches:
                return str(matches[0])
    return None


def _call_ai_cli(ai: str, prompt: str, timeout: int = 180) -> str:
    """指定 AI の CLI をサブプロセスとして呼び出し、回答テキストを返す"""
    config = _load_cli_config()
    cfg = config.get(ai)
    if not cfg:
        return f"エラー: '{ai}' のCLI設定がありません。"

    cli_path = _resolve_cli_path(ai, cfg["command"])
    if not cli_path:
        return (
            f"エラー: {ai.upper()} CLI が見つかりません。\n"
            f"・'{cfg['command']}' が PATH に存在するか確認してください。\n"
            f"・または collab_setup_cli() で設定してください。"
        )

    cmd = [cli_path] + cfg.get("args_before", []) + [prompt] + cfg.get("args_after", [])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        response = result.stdout.strip() or result.stderr.strip()
        if not response:
            # 応答が空の場合は対話TUIが起動した可能性がある
            return (
                f"（{ai.upper()} CLI から応答がありませんでした）\n"
                f"Codex CLI が対話モードで起動している可能性があります。\n"
                f"collab_setup_cli('{ai}', ...) で非対話引数を設定してください。"
            )
        return response
    except subprocess.TimeoutExpired:
        return f"エラー: {ai.upper()} CLI が {timeout}秒 以内に応答しませんでした。"
    except FileNotFoundError:
        return f"エラー: 実行ファイルが見つかりません: {cli_path}"
    except Exception as e:
        return f"エラー: {ai.upper()} CLI 呼び出し中に問題が発生しました: {e}"


def _build_consult_prompt(question: str) -> str:
    """現在のプロジェクト文脈を付加した相談プロンプトを生成する"""
    try:
        state = _load_state()
        task_title = state["current_task"]["title"] if state.get("current_task") else "未設定"
        lines = [
            "[AI協働開発システムからの相談]",
            f"プロジェクト : {state['project_name']}",
            f"現在のタスク : {task_title}",
            f"相談元の AI  : {state['current_ai'].upper()}",
        ]
        if state.get("key_decisions"):
            lines += ["", "## 既存の設計決定事項（参考）"]
            for dec in state["key_decisions"][-3:]:
                lines.append(f"- {dec['title']}: {dec['content'][:200]}")
        lines += ["", "---", "", f"## 相談内容\n{question}"]
        return "\n".join(lines)
    except Exception:
        return question

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
        with open(cfg_file, "r", encoding="utf-8") as f:
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

    # 既知の問題
    for iss in state.get("known_issues", []):
        if isinstance(iss, dict) and q in iss.get("text", "").lower():
            results.append(f"[問題]   [{iss['id']}] {iss['text']}")

    # 解決済みの問題
    for iss in state.get("resolved_issues", []):
        if isinstance(iss, dict) and q in iss.get("text", "").lower():
            results.append(f"[解決済] [{iss['id']}] {iss['text']}")

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



_VERSION = "1.0.8"

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
  collab_generate_handoff   引き継ぎ文書（HANDOFF.md）を生成する
  collab_checkpoint         メモ追加と引き継ぎ文書生成を一度に行う
  collab_consult            相手AIのCLIを呼び出して質問・相談する
  collab_discuss            相手AIと複数ターンの議論を行う
  collab_setup_cli          AIのCLIパス・引数設定をカスタマイズする
  collab_cleanup_sessions   古いセッションログを削除する

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
