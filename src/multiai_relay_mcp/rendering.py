"""HANDOFF.md rendering helpers."""

import re

from .state import (
    MODE_LABELS,
    VALID_SEVERITIES,
    _SEVERITY_EMOJI,
    _get_project_dir,
    _now_display,
)

#region ハンドオフ文書生成

def _build_handoff(state: dict, from_ai: str, to_ai: str) -> str:
    """
    ハンドオフ用マークダウン文書を生成する。
    state['handoff_template'] に従い出力内容を切り替える。
    - full    : 全セクション（デフォルト）
    - minimal : 現在タスク＋最新メモ3件＋既知の問題のみ
    - review  : full ＋ レビューポイントセクション
    - debug   : full ＋ デバッグ情報セクション
    """
    template = state.get("handoff_template", "full")
    mode_label = MODE_LABELS.get(state["mode"], state["mode"])

    # ── 共通ヘッダ ──────────────────────────────────────────────────────
    lines = [
        "# AI協働開発 ハンドオフドキュメント", "",
        f"> **引き継ぎ元:** {from_ai.upper()}　→　**引き継ぎ先:** {to_ai.upper()}",
        f"> **日時:** {_now_display()}　｜　**プロジェクト:** {state['project_name']}",
        f"> **モード:** {mode_label}　｜　**セッション:** #{state['session_count']}",
        f"> **テンプレート:** {template}",
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

    # ── セクション構築ヘルパー ──────────────────────────────────────────
    def section(title, items, empty="*なし*"):
        return ["", "---", "", f"## {title}", ""] + (items if items else [empty])

    def _fmt_issue(iss) -> str:
        if isinstance(iss, dict):
            emoji = _SEVERITY_EMOJI.get(iss.get("severity", "P2"), "⚠️")
            sev   = iss.get("severity", "?")
            stat  = "" if iss.get("status", "open") == "open" else f" [{iss['status']}]"
            tags  = f" ({', '.join(iss['tags'])})" if iss.get("tags") else ""
            # 旧テキストに [P0]〜[P3] プレフィックスが残っている場合は表示上だけ除去する
            text  = re.sub(r'^\[P[0-3]\]\s*', '', iss['text'])
            return (f"- {emoji} [{iss['id']}][{sev}]{stat} "
                    f"<!-- USER INPUT -->{text}<!-- /USER INPUT -->{tags}")
        return f"- ⚠️ <!-- USER INPUT -->{iss}<!-- /USER INPUT -->"

    def _note_lines(notes, limit: int) -> list[str]:
        nl = []
        if len(notes) > limit:
            nl.append(f"- *過去{len(notes) - limit}件のメモを省略*")
        nl += [
            f"- `{n['timestamp'][:16]}` ({n['ai'].upper()}) <!-- USER INPUT -->{n['text']}<!-- /USER INPUT -->"
            for n in notes[-limit:]
        ]
        return nl

    def _decisions_section(decisions, limit: int = 10) -> list[str]:
        if not decisions:
            return ["", "---", "", "## 重要な決定事項", "", "*なし*"]
        out = ["", "---", "", "## 重要な決定事項", ""]
        if len(decisions) > limit:
            out.append(f"*過去{len(decisions) - limit}件の決定事項を省略*")
            out.append("")
        for dec in decisions[-limit:]:
            out += [
                f"### <!-- USER INPUT -->{dec['title']}<!-- /USER INPUT -->",
                f"*{dec['timestamp'][:10]}  by {dec['ai'].upper()}*",
                "",
                "<!-- USER INPUT -->",
                dec["content"],
                "<!-- /USER INPUT -->",
                "",
            ]
        return out

    # ── テンプレート別セクション組み立て ───────────────────────────────
    notes     = state.get("notes", [])
    decisions = state.get("key_decisions", [])
    # severity 昇順（P0優先）でソート済みのリストを全テンプレートで共用する
    issues = sorted(
        state.get("known_issues", []),
        key=lambda i: VALID_SEVERITIES.index(i.get("severity", "P2"))
        if isinstance(i, dict) and i.get("severity") in VALID_SEVERITIES else 99
    )

    if template == "minimal":
        # 現在タスク（ヘッダ済み）＋ 最新メモ3件 ＋ 既知の問題のみ
        lines += section("最近のメモ（最新3件）", _note_lines(notes, 3))
        lines += section("既知の問題・注意点", [_fmt_issue(i) for i in issues])

    elif template == "review":
        # full ＋ レビューポイントセクション
        lines += section("保留中のタスク",
            [f"- [ ] <!-- USER INPUT -->{t['title']}<!-- /USER INPUT -->"
             + (f" — <!-- USER INPUT -->{t['description']}<!-- /USER INPUT -->" if t.get("description") else "")
             for t in state.get("pending_tasks", [])])
        lines += section("最近のメモ（最新10件）", _note_lines(notes, 10))
        lines += _decisions_section(decisions)
        lines += section("既知の問題・注意点", [_fmt_issue(i) for i in issues])
        lines += section("完了済みタスク（最近5件）",
            [f"- ✅ `{t['id']}` <!-- USER INPUT -->{t['title']}<!-- /USER INPUT --> ({t.get('completed_at', '?')[:10]})"
             for t in state.get("completed_tasks", [])[-5:]])
        lines += section("完了した保留タスク（最近5件）",
            [f"- ✅ `{t['id']}` <!-- USER INPUT -->{t['title']}<!-- /USER INPUT --> ({t.get('completed_at', '?')[:10]})"
             for t in state.get("completed_pending_tasks", [])[-5:]])
        # レビュー専用セクション
        lines += [
            "", "---", "", "## 📋 レビューポイント", "",
            "以下の観点でレビューしてください:",
            "- 実装が決定事項と一致しているか",
            "- 既知の問題が解決されているか",
            "- コードの品質・セキュリティ・パフォーマンス",
            "- 次のフェーズに進む前に確認すべき点",
        ]

    elif template == "debug":
        # full ＋ デバッグ情報セクション
        lines += section("保留中のタスク",
            [f"- [ ] <!-- USER INPUT -->{t['title']}<!-- /USER INPUT -->"
             + (f" — <!-- USER INPUT -->{t['description']}<!-- /USER INPUT -->" if t.get("description") else "")
             for t in state.get("pending_tasks", [])])
        lines += section("最近のメモ（最新10件）", _note_lines(notes, 10))
        lines += _decisions_section(decisions)
        lines += section("既知の問題・注意点", [_fmt_issue(i) for i in issues])
        lines += section("完了済みタスク（最近5件）",
            [f"- ✅ `{t['id']}` <!-- USER INPUT -->{t['title']}<!-- /USER INPUT --> ({t.get('completed_at', '?')[:10]})"
             for t in state.get("completed_tasks", [])[-5:]])
        lines += section("完了した保留タスク（最近5件）",
            [f"- ✅ `{t['id']}` <!-- USER INPUT -->{t['title']}<!-- /USER INPUT --> ({t.get('completed_at', '?')[:10]})"
             for t in state.get("completed_pending_tasks", [])[-5:]])
        # デバッグ専用セクション
        task_files = state.get("current_task", {}) or {}
        all_files  = task_files.get("files_modified", [])
        lines += [
            "", "---", "", "## 🐛 デバッグ情報", "",
            "**直近の変更ファイル:**",
        ] + ([f"- `{fp}`" for fp in all_files] if all_files else ["- *なし*"]) + [
            "",
            "**未解決の問題 (issue-NNN形式):**",
        ] + ([_fmt_issue(i) for i in issues if isinstance(i, dict) and not i.get("resolved")]
             if issues else ["- *なし*"]) + [
            "",
            "**デバッグ優先事項:** 既知の問題から着手し、変更ファイルを重点的に確認してください。",
        ]

    else:
        # full（デフォルト）: 全セクション
        lines += section("保留中のタスク",
            [f"- [ ] <!-- USER INPUT -->{t['title']}<!-- /USER INPUT -->"
             + (f" — <!-- USER INPUT -->{t['description']}<!-- /USER INPUT -->" if t.get("description") else "")
             for t in state.get("pending_tasks", [])])
        # 外部入力（ユーザーが記録した内容）はタグで囲んで信頼済み指示と区別する
        lines += section("最近のメモ（最新10件）", _note_lines(notes, 10))
        lines += _decisions_section(decisions)
        lines += section("既知の問題・注意点", [_fmt_issue(i) for i in issues])
        # issue-016: 完了タスクのタイトルもユーザー入力なのでタグでラップする
        lines += section("完了済みタスク（最近5件）",
            [f"- ✅ `{t['id']}` <!-- USER INPUT -->{t['title']}<!-- /USER INPUT --> ({t.get('completed_at', '?')[:10]})"
             for t in state.get("completed_tasks", [])[-5:]])
        lines += section("完了した保留タスク（最近5件）",
            [f"- ✅ `{t['id']}` <!-- USER INPUT -->{t['title']}<!-- /USER INPUT --> ({t.get('completed_at', '?')[:10]})"
             for t in state.get("completed_pending_tasks", [])[-5:]])

    # ── 共通フッタ（セッション開始手順） ────────────────────────────────
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