#!/usr/bin/env python3
"""
AI協働開発管理ツール
ClaudeとCodexが協力して開発するためのハンドオフ・状態管理システム

使い方:
  python multiai_relay.py init              # 初期化
  python multiai_relay.py status            # 現在の状態表示
  python multiai_relay.py handoff claude    # Claudeへ引き継ぎ
  python multiai_relay.py handoff codex     # Codexへ引き継ぎ
  python multiai_relay.py mode plan         # モード変更
  python multiai_relay.py task "タスク名"   # タスク設定
  python multiai_relay.py note "メモ内容"   # メモ追加
  python multiai_relay.py decision "タイトル" "内容"  # 決定事項記録
  python multiai_relay.py issue "問題内容"  # 既知の問題記録
  python multiai_relay.py file "パス"       # 作業ファイル記録
"""

import json
import argparse
import datetime
import sys
import io
from pathlib import Path

# Windows環境でのUTF-8出力を強制する
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

#region 定数定義

STATE_FILE = "AI_STATE.json"
HANDOFF_FILE = "HANDOFF.md"
SESSIONS_DIR = "ai_sessions"

VALID_AI = ["claude", "codex"]
VALID_MODES = ["plan", "implement", "review", "debug"]

MODE_LABELS = {
    "plan":      "仕様検討・設計",
    "implement": "実装",
    "review":    "レビュー",
    "debug":     "デバッグ",
}

#endregion

#region ユーティリティ

def get_timestamp() -> str:
    """ISO形式のタイムスタンプを返す"""
    return datetime.datetime.now().isoformat(timespec="seconds")

def get_display_time() -> str:
    """表示用の日時文字列を返す"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def load_state() -> dict:
    """状態ファイルを読み込む"""
    if not Path(STATE_FILE).exists():
        print(f"エラー: {STATE_FILE} が見つかりません。")
        print(f"  → まず 'python multiai_relay.py init' を実行してください。")
        sys.exit(1)
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: dict) -> None:
    """状態ファイルを保存する"""
    state["last_updated"] = get_timestamp()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def append_session_log(ai_name: str, message: str) -> None:
    """現在のセッションログにメッセージを追記する"""
    sessions_dir = Path(SESSIONS_DIR)
    if not sessions_dir.exists():
        return

    # 対象AIの最新ログファイルを探す
    logs = sorted(sessions_dir.glob(f"*_{ai_name}.md"), reverse=True)
    if not logs:
        return

    time_str = datetime.datetime.now().strftime("%H:%M:%S")
    with open(logs[0], "a", encoding="utf-8") as f:
        f.write(f"- [{time_str}] {message}\n")

def create_session_log(ai_name: str, session_number: int, mode: str) -> Path:
    """新しいセッションログファイルを作成して返す"""
    sessions_dir = Path(SESSIONS_DIR)
    sessions_dir.mkdir(exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = sessions_dir / f"{ts}_{ai_name}.md"

    content = f"""# セッションログ: {ai_name.upper()}
**開始日時:** {get_display_time()}
**セッション番号:** {session_number}
**モード:** {MODE_LABELS.get(mode, mode)}

## 作業ログ
"""
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(content)

    return log_path

#endregion

#region コマンド実装

def cmd_init(args) -> None:
    """システムを初期化する"""
    if Path(STATE_FILE).exists() and not args.force:
        print(f"警告: {STATE_FILE} は既に存在します。")
        print(f"  → 上書きする場合は '--force' オプションを付けてください。")
        return

    project_name = args.project_name or Path.cwd().name
    start_ai = args.start_ai or "claude"

    state = {
        "version": "1.0",
        "project_name": project_name,
        "current_ai": start_ai,
        "mode": "implement",
        "current_task": None,
        "pending_tasks": [],
        "completed_tasks": [],
        "notes": [],
        "key_decisions": [],
        "known_issues": [],
        "last_updated": get_timestamp(),
        "session_count": 1,
    }

    save_state(state)
    create_session_log(start_ai, 1, state["mode"])

    print(f"✅ AI協働開発システムを初期化しました")
    print(f"   プロジェクト名 : {project_name}")
    print(f"   最初の担当AI  : {start_ai.upper()}")
    print(f"")
    print(f"次のステップ:")
    print(f"  1. 'python multiai_relay.py task \"タスク名\"' でタスクを設定")
    print(f"  2. 開発を進める")
    print(f"  3. 引き継ぎ時は 'python multiai_relay.py handoff claude|codex' を実行")
    print(f"")
    print(f"各AIの操作手順は CLAUDE_INSTRUCTIONS.md / CODEX_INSTRUCTIONS.md を参照してください。")


def cmd_status(args) -> None:
    """現在の状態を表示する"""
    state = load_state()

    divider = "=" * 52
    print(f"\n{divider}")
    print(f"  AI協働開発システム - 現在の状態")
    print(f"{divider}")
    print(f"  プロジェクト  : {state['project_name']}")
    print(f"  担当AI        : {state['current_ai'].upper()}")
    print(f"  モード        : {MODE_LABELS.get(state['mode'], state['mode'])}")
    print(f"  セッション数  : {state['session_count']}")
    print(f"  最終更新      : {state['last_updated']}")
    print(f"{divider}")

    # 現在のタスク
    if state.get("current_task"):
        task = state["current_task"]
        print(f"\n【現在のタスク】")
        print(f"  ID     : {task['id']}")
        print(f"  タイトル: {task['title']}")
        if task.get("description"):
            print(f"  詳細   : {task['description']}")
        print(f"  開始   : {task['started_at'][:16]}")
        if task.get("files_modified"):
            print(f"  変更ファイル:")
            for fp in task["files_modified"]:
                print(f"    - {fp}")
    else:
        print(f"\n【現在のタスク】未設定")

    # 保留中タスク
    if state.get("pending_tasks"):
        print(f"\n【保留中のタスク】")
        for t in state["pending_tasks"]:
            print(f"  - {t['title']}")

    # 最近のメモ（最新3件）
    notes = state.get("notes", [])
    if notes:
        print(f"\n【最近のメモ】")
        for n in notes[-3:]:
            print(f"  [{n['timestamp'][:16]}] ({n['ai'].upper()}) {n['text']}")

    # 既知の問題
    if state.get("known_issues"):
        print(f"\n【既知の問題】")
        for issue in state["known_issues"]:
            print(f"  ⚠️  {issue}")

    print(f"\n{divider}\n")


def cmd_handoff(args) -> None:
    """ハンドオフドキュメントを生成して担当AIを切り替える"""
    state = load_state()
    to_ai = args.to_ai

    if to_ai not in VALID_AI:
        print(f"エラー: AIは 'claude' または 'codex' を指定してください。")
        sys.exit(1)

    from_ai = state["current_ai"]

    # ハンドオフドキュメントを生成・保存
    content = generate_handoff_document(state, from_ai, to_ai)
    with open(HANDOFF_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    # セッションログに記録
    append_session_log(from_ai, f"ハンドオフ: {from_ai.upper()} → {to_ai.upper()}")

    # 担当AIを切り替えて状態を保存
    state["current_ai"] = to_ai
    state["session_count"] += 1
    save_state(state)

    # 新しいセッションログを作成
    create_session_log(to_ai, state["session_count"], state["mode"])

    print(f"✅ ハンドオフ完了: {from_ai.upper()} → {to_ai.upper()}")
    print(f"   ファイル: {HANDOFF_FILE}")
    print(f"")

    if to_ai == "claude":
        print(f"【Claudeへの引き継ぎ手順】")
        print(f"  Claude Desktop で新しいセッションを開始し、")
        print(f"  以下を伝えてください:")
        print(f"  「HANDOFF.md と AI_STATE.json を読んで、続きの開発をお願いします」")
    else:
        print(f"【Codexへの引き継ぎ手順】")
        print(f"  Codex Desktop で新しいセッションを開始し、")
        print(f"  以下を伝えてください:")
        print(f"  「HANDOFF.md と AI_STATE.json を読んで、続きの開発をお願いします」")


def cmd_mode(args) -> None:
    """作業モードを切り替える"""
    state = load_state()
    new_mode = args.new_mode

    if new_mode not in VALID_MODES:
        print(f"エラー: モードは {', '.join(VALID_MODES)} のいずれかを指定してください。")
        sys.exit(1)

    old_mode = state["mode"]
    state["mode"] = new_mode
    save_state(state)

    append_session_log(state["current_ai"], f"モード変更: {old_mode} → {new_mode} ({MODE_LABELS[new_mode]})")
    print(f"✅ モードを変更しました")
    print(f"   {MODE_LABELS.get(old_mode, old_mode)} → {MODE_LABELS.get(new_mode, new_mode)}")


def cmd_task(args) -> None:
    """現在のタスクを設定する（既存タスクは自動的に完了扱いにする）"""
    state = load_state()

    # 前のタスクを完了済みに移動
    if state.get("current_task"):
        old_task = state["current_task"]
        old_task["completed_at"] = get_timestamp()
        state["completed_tasks"].append(old_task)

    task_id = f"task-{len(state['completed_tasks']) + 1:03d}"
    new_task = {
        "id": task_id,
        "title": args.title,
        "description": args.description or "",
        "started_at": get_timestamp(),
        "started_by": state["current_ai"],
        "files_modified": [],
    }

    state["current_task"] = new_task
    save_state(state)

    append_session_log(state["current_ai"], f"タスク開始: [{task_id}] {args.title}")
    print(f"✅ タスクを設定しました")
    print(f"   [{task_id}] {args.title}")


def cmd_add_task(args) -> None:
    """保留タスクキューにタスクを追加する"""
    state = load_state()

    task = {
        "id": f"pending-{len(state['pending_tasks']) + 1:03d}",
        "title": args.title,
        "description": args.description or "",
        "added_at": get_timestamp(),
        "added_by": state["current_ai"],
    }

    state["pending_tasks"].append(task)
    save_state(state)

    append_session_log(state["current_ai"], f"タスク追加（保留）: {args.title}")
    print(f"✅ 保留タスクに追加しました: {args.title}")


def cmd_file(args) -> None:
    """現在のタスクに作業ファイルを記録する"""
    state = load_state()

    if not state.get("current_task"):
        print("エラー: 現在のタスクが設定されていません。")
        print("  → 先に 'python multiai_relay.py task \"タスク名\"' でタスクを設定してください。")
        sys.exit(1)

    fp = args.file_path
    if fp not in state["current_task"]["files_modified"]:
        state["current_task"]["files_modified"].append(fp)
        save_state(state)
        append_session_log(state["current_ai"], f"ファイル記録: {fp}")
        print(f"✅ ファイルを記録しました: {fp}")
    else:
        print(f"ℹ️  既に記録済みです: {fp}")


def cmd_note(args) -> None:
    """メモをセッションに追加する"""
    state = load_state()

    note = {
        "timestamp": get_timestamp(),
        "ai": state["current_ai"],
        "text": args.message,
    }
    state["notes"].append(note)
    save_state(state)

    append_session_log(state["current_ai"], f"メモ: {args.message}")
    print(f"✅ メモを追加しました")


def cmd_decision(args) -> None:
    """重要な設計・実装の決定事項を記録する"""
    state = load_state()

    decision = {
        "timestamp": get_timestamp(),
        "ai": state["current_ai"],
        "title": args.title,
        "content": args.content,
    }
    state["key_decisions"].append(decision)
    save_state(state)

    append_session_log(state["current_ai"], f"決定事項記録: {args.title}")
    print(f"✅ 決定事項を記録しました: {args.title}")


def cmd_issue(args) -> None:
    """既知の問題・注意点を記録する"""
    state = load_state()

    entry = f"[{get_timestamp()[:10]}] ({state['current_ai'].upper()}) {args.message}"
    state["known_issues"].append(entry)
    save_state(state)

    append_session_log(state["current_ai"], f"問題記録: {args.message}")
    print(f"✅ 問題を記録しました")

#endregion

#region ハンドオフ文書生成

def generate_handoff_document(state: dict, from_ai: str, to_ai: str) -> str:
    """ハンドオフ用マークダウンドキュメントを生成する"""
    now = get_display_time()
    mode_label = MODE_LABELS.get(state["mode"], state["mode"])

    lines = [
        f"# AI協働開発 ハンドオフドキュメント",
        f"",
        f"> **引き継ぎ元:** {from_ai.upper()}　→　**引き継ぎ先:** {to_ai.upper()}",
        f"> **日時:** {now}　｜　**プロジェクト:** {state['project_name']}",
        f"> **モード:** {mode_label}　｜　**セッション:** #{state['session_count']}",
        f"",
        f"---",
        f"",
        f"## 現在のタスク",
        f"",
    ]

    # 現在のタスク
    if state.get("current_task"):
        task = state["current_task"]
        lines += [
            f"**タスクID:** `{task['id']}`",
            f"**タイトル:** {task['title']}",
        ]
        if task.get("description"):
            lines.append(f"**詳細:** {task['description']}")
        lines.append(f"**開始:** {task['started_at'][:16]}  担当: {task.get('started_by', '?').upper()}")

        if task.get("files_modified"):
            lines += ["", "**変更済みファイル:**"]
            for fp in task["files_modified"]:
                lines.append(f"- `{fp}`")
    else:
        lines.append("*タスクは設定されていません。*")

    # 保留中タスク
    lines += ["", "---", "", "## 保留中のタスク", ""]
    if state.get("pending_tasks"):
        for t in state["pending_tasks"]:
            lines.append(f"- [ ] **{t['title']}**" + (f" — {t['description']}" if t.get("description") else ""))
    else:
        lines.append("*なし*")

    # 最近のメモ（最新10件）
    lines += ["", "---", "", "## 最近のメモ", ""]
    recent_notes = state.get("notes", [])[-10:]
    if recent_notes:
        for n in recent_notes:
            lines.append(f"- `{n['timestamp'][:16]}` ({n['ai'].upper()}) {n['text']}")
    else:
        lines.append("*なし*")

    # 重要な決定事項
    lines += ["", "---", "", "## 重要な決定事項", ""]
    decisions = state.get("key_decisions", [])
    if decisions:
        for dec in decisions:
            lines += [
                f"### {dec['title']}",
                f"*{dec['timestamp'][:10]}  by {dec['ai'].upper()}*",
                f"",
                dec["content"],
                f"",
            ]
    else:
        lines.append("*なし*")

    # 既知の問題
    lines += ["", "---", "", "## 既知の問題・注意点", ""]
    if state.get("known_issues"):
        for issue in state["known_issues"]:
            lines.append(f"- ⚠️ {issue}")
    else:
        lines.append("*なし*")

    # 完了済みタスク（最新5件）
    lines += ["", "---", "", "## 完了済みタスク（最近5件）", ""]
    completed = state.get("completed_tasks", [])
    if completed:
        for t in completed[-5:]:
            done_at = t.get("completed_at", "?")[:10]
            lines.append(f"- ✅ `{t['id']}` {t['title']} ({done_at})")
    else:
        lines.append("*なし*")

    # 引き継ぎ先へのアクション指示
    lines += [
        "",
        "---",
        "",
        f"## {to_ai.upper()} セッション開始手順",
        "",
        "このドキュメントを読み終わったら、以下のコマンドを実行して状態を確認してください:",
        "",
        "```sh",
        "python multiai_relay.py status",
        "```",
        "",
        "作業中はこまめにメモを追加してください:",
        "",
        "```sh",
        'python multiai_relay.py note "気づいたことや進捗"',
        "```",
        "",
        "重要な実装判断をしたらすぐに記録してください:",
        "",
        "```sh",
        'python multiai_relay.py decision "判断タイトル" "判断の内容と理由"',
        "```",
        "",
        "セッション終了時・レートリミット前にハンドオフを生成してください:",
        "",
        "```sh",
        f"python multiai_relay.py handoff {from_ai}",
        "```",
    ]

    return "\n".join(lines) + "\n"

#endregion

#region エントリポイント

def main():
    parser = argparse.ArgumentParser(
        description="AI協働開発管理ツール — ClaudeとCodexのハンドオフを管理します",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="コマンド")

    # init
    p = sub.add_parser("init", help="システムを初期化する")
    p.add_argument("--project-name", "-p", help="プロジェクト名（省略時はディレクトリ名）")
    p.add_argument("--start-ai", choices=VALID_AI, help="最初の担当AI（デフォルト: claude）")
    p.add_argument("--force", "-f", action="store_true", help="既存の状態を強制上書き")
    p.set_defaults(func=cmd_init)

    # status
    p = sub.add_parser("status", help="現在の状態を表示する")
    p.set_defaults(func=cmd_status)

    # handoff
    p = sub.add_parser("handoff", help="ハンドオフを生成して担当AIを切り替える")
    p.add_argument("to_ai", choices=VALID_AI, help="引き継ぎ先のAI")
    p.set_defaults(func=cmd_handoff)

    # mode
    p = sub.add_parser("mode", help="作業モードを変更する")
    p.add_argument("new_mode", choices=VALID_MODES, help=f"新しいモード: {' | '.join(VALID_MODES)}")
    p.set_defaults(func=cmd_mode)

    # task
    p = sub.add_parser("task", help="現在のタスクを設定する")
    p.add_argument("title", help="タスクのタイトル")
    p.add_argument("--description", "-d", help="タスクの詳細説明")
    p.set_defaults(func=cmd_task)

    # add-task
    p = sub.add_parser("add-task", help="保留タスクキューにタスクを追加する")
    p.add_argument("title", help="タスクのタイトル")
    p.add_argument("--description", "-d", help="タスクの詳細説明")
    p.set_defaults(func=cmd_add_task)

    # file
    p = sub.add_parser("file", help="作業中のファイルを現在のタスクに記録する")
    p.add_argument("file_path", help="記録するファイルパス")
    p.set_defaults(func=cmd_file)

    # note
    p = sub.add_parser("note", help="メモを追加する")
    p.add_argument("message", help="メモの内容")
    p.set_defaults(func=cmd_note)

    # decision
    p = sub.add_parser("decision", help="重要な決定事項を記録する")
    p.add_argument("title", help="決定事項のタイトル")
    p.add_argument("content", help="決定事項の内容と理由")
    p.set_defaults(func=cmd_decision)

    # issue
    p = sub.add_parser("issue", help="既知の問題・注意点を記録する")
    p.add_argument("message", help="問題の内容")
    p.set_defaults(func=cmd_issue)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()

#endregion
