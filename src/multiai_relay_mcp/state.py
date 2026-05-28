"""State, validation, and filesystem helpers for multiai-relay-mcp."""

import copy
import datetime
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

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

VALID_MODES      = ["plan", "implement", "review", "debug"]
VALID_AI         = ["claude", "codex"]
VALID_SEVERITIES = ["P0", "P1", "P2", "P3"]       # P0=最優先, P3=低優先
VALID_ISSUE_STATUSES = ["open", "deferred"]         # resolved は collab_resolve_issue が担当

# severity → 絵文字マッピング（HANDOFF / status 表示用）
_SEVERITY_EMOJI: dict[str, str] = {
    "P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "🟢",
}

# Issue フィールドの入力制限
_MAX_TAG_LEN      = 30   # タグ1件の最大文字数
_MAX_TAGS         = 10   # タグの最大件数
_MAX_CATEGORY_LEN = 50   # カテゴリの最大文字数
_MAX_RELATED_FILES = 10  # related_files の最大件数

# タグ・カテゴリの許可文字パターン（ASCII英数字・ハイフン・アンダースコア）
_SLUG_RE = re.compile(r'^[\w\-]+$', re.ASCII)

MODE_LABELS: dict[str, str] = {
    "plan":      "仕様検討・設計",
    "implement": "実装",
    "review":    "レビュー",
    "debug":     "デバッグ",
}

# 入力文字列の最大長（プロンプトインジェクション・状態肥大化対策）
_MAX_INPUT_LEN = 2000

# 状態スキーマのバージョン（collab_version / collab_doctor で参照）
_STATE_SCHEMA_VERSION = "1.0"

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
    "handoff_template":        "full",
}

# ハンドオフテンプレートプリセット一覧
VALID_HANDOFF_TEMPLATES = ["full", "minimal", "review", "debug"]

#endregion

#region プロジェクトディレクトリ解決

def _get_project_dir() -> Path:
    """
    現在のプロジェクトディレクトリをメモリから取得する。

    issue-006 短期対処: プロジェクトパスが削除・移動された場合も即座に検出する。
    1プロセス=1アクティブプロジェクト前提の設計制限については README を参照。
    """
    if _current_project is None:
        raise RuntimeError(
            "現在のプロジェクトが設定されていません。\n"
            "collab_switch_project('プロジェクトのフルパス') を呼び出してください。"
        )
    if not _current_project.exists():
        raise RuntimeError(
            f"プロジェクトディレクトリが見つかりません: {_current_project}\n"
            "ディレクトリが削除・移動された可能性があります。\n"
            "collab_switch_project() で正しいパスを再設定してください。"
        )
    if not _current_project.is_dir():
        raise RuntimeError(
            f"プロジェクトパスがディレクトリではありません: {_current_project}\n"
            "collab_switch_project() で正しいパスを再設定してください。"
        )
    return _current_project

def _state_file()   -> Path: return _get_project_dir() / "AI_STATE.json"
def _handoff_file() -> Path: return _get_project_dir() / "HANDOFF.md"
def _sessions_dir() -> Path: return _get_project_dir() / "ai_sessions"
def _archive_file() -> Path: return _get_project_dir() / "AI_STATE.archive.json"

#endregion

#region 内部ユーティリティ

# HANDOFF.md の信頼境界タグ（このタグを含む入力は拒否する）
_INJECTION_TAG = "<!-- /USER INPUT -->"

def _validate_tags(tags: list, field: str = "tags") -> str | None:
    """タグリストの件数・文字数・文字種を検証する。問題があればエラーメッセージを返す。"""
    if not isinstance(tags, list):
        return f"エラー: {field} はリストで指定してください。"
    if len(tags) > _MAX_TAGS:
        return f"エラー: {field} は最大{_MAX_TAGS}件です（現在{len(tags)}件）。"
    for tag in tags:
        if not isinstance(tag, str):
            return f"エラー: {field} の各要素は文字列である必要があります。"
        if not tag:
            return f"エラー: {field} に空のタグは指定できません。"
        if len(tag) > _MAX_TAG_LEN:
            return f"エラー: {field} の各タグは最大{_MAX_TAG_LEN}文字です: {tag!r}"
        if not _SLUG_RE.match(tag):
            return (f"エラー: {field} はアルファベット・数字・ハイフン・アンダースコアのみ使用できます: {tag!r}")
    return None


def _validate_related_files(files: list) -> str | None:
    """related_files リストのパス安全性を検証する。問題があればエラーメッセージを返す。"""
    if not isinstance(files, list):
        return "エラー: related_files はリストで指定してください。"
    if len(files) > _MAX_RELATED_FILES:
        return f"エラー: related_files は最大{_MAX_RELATED_FILES}件です（現在{len(files)}件）。"
    for fp in files:
        if not isinstance(fp, str):
            return "エラー: related_files の各要素は文字列である必要があります。"
        if not fp:
            return "エラー: related_files に空のパスは指定できません。"
        if len(fp) > _MAX_INPUT_LEN:
            return f"エラー: ファイルパスが長すぎます（最大{_MAX_INPUT_LEN}文字）。"
        if any(c in fp for c in ('\n', '\r', '\t', '\0')):
            return f"エラー: ファイルパスに制御文字を含めることはできません: {fp!r}"
        norm = fp.replace('\\', '/')
        if any(part == '..' for part in norm.split('/')):
            return f"エラー: ファイルパスに「..」を含めることはできません: {fp!r}"
        if Path(fp).is_absolute():
            return f"エラー: related_files には相対パスを指定してください（絶対パス不可）: {fp!r}"
    return None


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
    # issue-022: BOM付きJSON(utf-8-sig)も透過的に読み込む
    with open(sf, "r", encoding="utf-8-sig") as f:
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

    # known_issues: 旧フォーマット（文字列）を構造化dictに移行してから normalize
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
    state["known_issues"] = [
        r for r in (_normalize_issue(iss, resolved=False) for iss in migrated_issues)
        if r is not None
    ]

    # resolved_issues も同様に normalize（status=resolved を補完）
    state["resolved_issues"] = [
        r for r in (_normalize_issue(iss, resolved=True) for iss in state.get("resolved_issues", []))
        if r is not None
    ]

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


def _normalize_issue(issue, resolved: bool = False) -> dict | None:
    """
    Issue レコードの必須キーを補完・型修正する。非dictは None を返す。

    - resolved=False: known_issues 用（status は "open" をデフォルト）
    - resolved=True : resolved_issues 用（status は "resolved" に固定）
    - 旧テキスト内の [P0]〜[P3] プレフィックスを severity に抽出（本文はそのまま保持）
    """
    if not isinstance(issue, dict):
        return None
    issue.setdefault("id", "issue-???")
    issue.setdefault("text", "（データ破損）")
    issue.setdefault("added_at", "")
    issue.setdefault("added_by", "unknown")

    # issue-021: 型安全 — 非文字列フィールドを str に補正してから re.match を呼ぶ
    for _str_key in ("id", "text", "added_at", "added_by"):
        if not isinstance(issue[_str_key], str):
            issue[_str_key] = str(issue[_str_key])

    # [P0]〜[P3] プレフィックスを severity に自動抽出（まだ severity フィールドがない場合）
    if "severity" not in issue:
        m = re.match(r'^\[P([0-3])\]\s*', issue["text"])
        issue["severity"] = f"P{m.group(1)}" if m else "P2"
    if issue.get("severity") not in VALID_SEVERITIES:
        issue["severity"] = "P2"

    # category: slug 文字列（不正値はデフォルトにリセット）
    if not isinstance(issue.get("category"), str) or not issue.get("category"):
        issue["category"] = "general"
    elif not _SLUG_RE.match(issue["category"]) or len(issue["category"]) > _MAX_CATEGORY_LEN:
        issue["category"] = "general"

    # tags: slug 配列（不正要素は除去）
    raw_tags = issue.get("tags", [])
    if not isinstance(raw_tags, list):
        raw_tags = []
    issue["tags"] = [
        t for t in raw_tags
        if isinstance(t, str) and t and _SLUG_RE.match(t) and len(t) <= _MAX_TAG_LEN
    ][:_MAX_TAGS]

    # related_files: 文字列配列（制御文字・絶対パス・.. を除去）
    raw_files = issue.get("related_files", [])
    if not isinstance(raw_files, list):
        raw_files = []
    clean_files = []
    for fp in raw_files:
        if not isinstance(fp, str) or not fp:
            continue
        if any(c in fp for c in ('\n', '\r', '\t', '\0')):
            continue
        if any(part == '..' for part in fp.replace('\\', '/').split('/')):
            continue
        if Path(fp).is_absolute():
            continue
        clean_files.append(fp)
    issue["related_files"] = clean_files[:_MAX_RELATED_FILES]

    # status: resolved_issues は "resolved" 固定、known_issues は open/deferred
    if resolved:
        issue["status"] = "resolved"
        issue.setdefault("resolved_at", "")
        issue.setdefault("resolved_by", "unknown")
    else:
        if issue.get("status") not in VALID_ISSUE_STATUSES:
            issue["status"] = "open"

    return issue

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

def set_current_project(path: Path | None) -> None:
    """Set the process-local active project path."""
    global _current_project
    _current_project = path


def get_current_project_raw() -> Path | None:
    """Return the process-local active project path without validation."""
    return _current_project


def read_raw_state_json(sf: Path) -> tuple[dict | None, bool, str | None]:
    """
    AI_STATE.json を正規化なしで直接読む（collab_doctor 専用）。

    _load_state() は旧フォーマット自動マイグレーションを行うため、
    正規化前の生の破損データを診断したい doctor はこちらを使う。

    Returns:
        (data, has_bom, error_message)
        - data: パース成功時はdict、失敗時はNone
        - has_bom: BOM(UTF-8 BOM)が検出された場合True
        - error_message: パース失敗時のエラー文字列、成功時はNone
    """
    try:
        raw = sf.read_bytes()
        has_bom = raw.startswith(b'\xef\xbb\xbf')
        text = raw.lstrip(b'\xef\xbb\xbf').decode('utf-8')
        return json.loads(text), has_bom, None
    except Exception as e:
        return None, False, str(e)
