"""HANDOFF.md rendering helpers."""

import re

from .i18n import mode_label, t
from .state import (
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
    template    = state.get("handoff_template", "full")
    cur_mode    = mode_label(state["mode"])

    # ── 共通ヘッダ ──────────────────────────────────────────────────────
    lines = [
        t("handoff.title"), "",
        t("handoff.from_to",       from_ai=from_ai.upper(), to_ai=to_ai.upper()),
        t("handoff.datetime_proj", dt=_now_display(), project=state["project_name"]),
        t("handoff.mode_session",  mode=cur_mode, session=state["session_count"]),
        t("handoff.template_line", template=template),
        "", "---", "", t("handoff.sec_current_task"), "",
    ]

    if state.get("current_task"):
        task = state["current_task"]
        # issue-009: タスクタイトル/詳細もユーザー入力なのでタグでラップする
        lines += [
            t("handoff.task_id",    id=task["id"]),
            t("handoff.task_title", title=task["title"]),
        ]
        if task.get("description"):
            lines.append(t("handoff.task_desc", desc=task["description"]))
        lines.append(t("handoff.task_started",
                       ts=task["started_at"][:16], ai=task.get("started_by", "?").upper()))
        if task.get("files_modified"):
            # issue-016: files_modified もユーザー入力なのでタグでラップする
            lines += ["", t("handoff.task_files")] + [
                f"- <!-- USER INPUT -->`{fp}`<!-- /USER INPUT -->" for fp in task["files_modified"]
            ]
    else:
        lines.append(t("handoff.task_none"))

    # ── セクション構築ヘルパー ──────────────────────────────────────────
    _empty = t("handoff.empty_item")

    def section(title, items, empty=None):
        return ["", "---", "", f"## {title}", ""] + (items if items else [empty or _empty])

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
            nl.append(t("handoff.notes_omitted", n=len(notes) - limit))
        nl += [
            f"- `{n['timestamp'][:16]}` ({n['ai'].upper()}) <!-- USER INPUT -->{n['text']}<!-- /USER INPUT -->"
            for n in notes[-limit:]
        ]
        return nl

    def _decisions_section(decisions, limit: int = 10) -> list[str]:
        sec_title = t("handoff.sec_decisions")
        if not decisions:
            return ["", "---", "", f"## {sec_title}", "", _empty]
        out = ["", "---", "", f"## {sec_title}", ""]
        if len(decisions) > limit:
            out.append(t("handoff.decisions_omitted", n=len(decisions) - limit))
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

    # ── 共通ヘルパー：pending_tasks をフォーマット ─────────────────────
    def _pending_items() -> list[str]:
        return [
            f"- [ ] <!-- USER INPUT -->{pt['title']}<!-- /USER INPUT -->"
            + (f" — <!-- USER INPUT -->{pt['description']}<!-- /USER INPUT -->"
               if pt.get("description") else "")
            for pt in state.get("pending_tasks", [])
        ]

    def _done_task_items(lst) -> list[str]:
        return [
            f"- ✅ `{tt['id']}` <!-- USER INPUT -->{tt['title']}<!-- /USER INPUT -->"
            f" ({tt.get('completed_at', '?')[:10]})"
            for tt in lst
        ]

    if template == "minimal":
        # 現在タスク（ヘッダ済み）＋ 最新メモ3件 ＋ 既知の問題のみ
        lines += section(t("handoff.sec_notes", n=3), _note_lines(notes, 3))
        lines += section(t("handoff.sec_issues"), [_fmt_issue(i) for i in issues])

    elif template == "review":
        # full ＋ レビューポイントセクション
        lines += section(t("handoff.sec_pending"), _pending_items())
        lines += section(t("handoff.sec_notes", n=10), _note_lines(notes, 10))
        lines += _decisions_section(decisions)
        lines += section(t("handoff.sec_issues"), [_fmt_issue(i) for i in issues])
        lines += section(t("handoff.sec_done_tasks"),
                         _done_task_items(state.get("completed_tasks", [])[-5:]))
        lines += section(t("handoff.sec_done_pending"),
                         _done_task_items(state.get("completed_pending_tasks", [])[-5:]))
        # レビュー専用セクション
        lines += [
            "", "---", "", t("handoff.sec_review"), "",
            t("handoff.review_intro"),
            t("handoff.review_1"),
            t("handoff.review_2"),
            t("handoff.review_3"),
            t("handoff.review_4"),
        ]

    elif template == "debug":
        # full ＋ デバッグ情報セクション
        lines += section(t("handoff.sec_pending"), _pending_items())
        lines += section(t("handoff.sec_notes", n=10), _note_lines(notes, 10))
        lines += _decisions_section(decisions)
        lines += section(t("handoff.sec_issues"), [_fmt_issue(i) for i in issues])
        lines += section(t("handoff.sec_done_tasks"),
                         _done_task_items(state.get("completed_tasks", [])[-5:]))
        lines += section(t("handoff.sec_done_pending"),
                         _done_task_items(state.get("completed_pending_tasks", [])[-5:]))
        # デバッグ専用セクション
        task_files = state.get("current_task", {}) or {}
        all_files  = task_files.get("files_modified", [])
        lines += [
            "", "---", "", t("handoff.sec_debug"), "",
            t("handoff.debug_files"),
        ] + ([f"- `{fp}`" for fp in all_files] if all_files else [f"- {_empty}"]) + [
            "",
            t("handoff.debug_issues"),
        ] + ([_fmt_issue(i) for i in issues if isinstance(i, dict) and not i.get("resolved")]
             if issues else [f"- {_empty}"]) + [
            "",
            t("handoff.debug_priority"),
        ]

    else:
        # full（デフォルト）: 全セクション
        lines += section(t("handoff.sec_pending"), _pending_items())
        # 外部入力（ユーザーが記録した内容）はタグで囲んで信頼済み指示と区別する
        lines += section(t("handoff.sec_notes", n=10), _note_lines(notes, 10))
        lines += _decisions_section(decisions)
        lines += section(t("handoff.sec_issues"), [_fmt_issue(i) for i in issues])
        # issue-016: 完了タスクのタイトルもユーザー入力なのでタグでラップする
        lines += section(t("handoff.sec_done_tasks"),
                         _done_task_items(state.get("completed_tasks", [])[-5:]))
        lines += section(t("handoff.sec_done_pending"),
                         _done_task_items(state.get("completed_pending_tasks", [])[-5:]))

    # ── 共通フッタ（セッション開始手順） ────────────────────────────────
    lines += [
        "", "---", "", t("handoff.sec_footer", ai=to_ai.upper()), "",
        t("handoff.step1"),
        "```", f'collab_switch_project("{_get_project_dir()}")', "```", "",
        t("handoff.step2"),
        "```", "collab_status()", "```", "",
        t("handoff.step3"),
        "```", t("handoff.step3_code"), "```", "",
        t("handoff.step4"),
        "```", t("handoff.step4_code", from_ai=from_ai), "```",
    ]
    return "\n".join(lines) + "\n"

#endregion