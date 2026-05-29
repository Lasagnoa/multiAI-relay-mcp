"""
Internationalization (i18n) モジュール。

MULTIAI_LANG 環境変数（"ja" または "en"）で言語を切り替える。
デフォルトは "ja"（日本語）。

使い方:
    from .i18n import t, mode_label
    return t("switch_project.created", path=path, name=name, mode=mode_label("plan"))
"""

import os

#region 言語設定・公開API

def get_lang() -> str:
    """MULTIAI_LANG 環境変数から現在の言語コードを返す（デフォルト: ja）"""
    lang = os.environ.get("MULTIAI_LANG", "ja").lower()
    return lang if lang in _STRINGS else "ja"


def t(key: str, **kwargs) -> str:
    """
    翻訳文字列を返す。変数は {name} プレースホルダで指定する。

    Args:
        key:    文字列キー（例: "err.absolute_path"）
        kwargs: プレースホルダに埋め込む値

    Returns:
        言語に応じた翻訳文字列。キーが未定義の場合は "[key]" を返す。
    """
    lang = get_lang()
    strings = _STRINGS.get(lang, _STRINGS["ja"])
    template = strings.get(key) or _STRINGS["ja"].get(key, f"[{key}]")
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template
    return template


# ── モードラベル（言語対応版） ──────────────────────────────────────────────

_MODE_LABELS_I18N: dict[str, dict[str, str]] = {
    "ja": {
        "plan":      "仕様検討・設計",
        "implement": "実装",
        "review":    "レビュー",
        "debug":     "デバッグ",
    },
    "en": {
        "plan":      "Plan/Design",
        "implement": "Implement",
        "review":    "Review",
        "debug":     "Debug",
    },
}


def mode_label(mode: str) -> str:
    """モードの表示名を返す（MULTIAI_LANG に応じて言語切り替え）"""
    lang = get_lang()
    labels = _MODE_LABELS_I18N.get(lang, _MODE_LABELS_I18N["ja"])
    return labels.get(mode, mode)

#endregion

#region 文字列テーブル

_STRINGS: dict[str, dict[str, str]] = {

    # ══════════════════════════════════════════════════════════════════════
    # 日本語
    # ══════════════════════════════════════════════════════════════════════
    "ja": {

        # ── 共通エラー ────────────────────────────────────────────────────
        "err.runtime":          "エラー: {msg}",
        "err.absolute_path":    "エラー: 絶対パスを指定してください（相対パスは不可）: {path}",
        "err.dir_not_found":    "エラー: ディレクトリが存在しません: {path}",
        "err.invalid_ai":       "エラー: ai は 'claude' または 'codex' を指定してください。",
        "err.invalid_ai_long":  "エラー: AIは 'claude' または 'codex' を指定してください。",
        "err.file_write":       "エラー: ファイルの書き込みに失敗しました: {err}",
        "err.file_read":        "エラー: ファイルの読み込みに失敗しました: {err}",
        "err.backup_failed":    "エラー: バックアップの作成に失敗しました: {err}",

        # ── validate_project_dir ──────────────────────────────────────────
        "validate.path_not_found": (
            "{label}が見つかりません: {path}\n"
            "ディレクトリが削除・移動された可能性があります。\n"
            "collab_switch_project() で正しいパスを再設定してください。"
        ),
        "validate.path_not_dir": (
            "{label}がディレクトリではありません: {path}\n"
            "collab_switch_project() で正しいパスを再設定してください。"
        ),

        # ── _get_project_dir ──────────────────────────────────────────────
        "project.not_set": (
            "現在のプロジェクトが設定されていません。\n"
            "collab_switch_project('プロジェクトのフルパス') を呼び出してください。"
        ),

        # ── _load_state ───────────────────────────────────────────────────
        "load_state.not_found": (
            "AI_STATE.json が見つかりません: {sf}\n"
            "collab_switch_project(path, project_name='プロジェクト名') を呼び出して初期化してください。"
        ),

        # ── _validate_tags ────────────────────────────────────────────────
        "validate.tags.not_list":     "エラー: {field} はリストで指定してください。",
        "validate.tags.too_many":     "エラー: {field} は最大{max}件です（現在{count}件）。",
        "validate.tags.elem_not_str": "エラー: {field} の各要素は文字列である必要があります。",
        "validate.tags.empty":        "エラー: {field} に空のタグは指定できません。",
        "validate.tags.too_long":     "エラー: {field} の各タグは最大{max}文字です: {tag!r}",
        "validate.tags.invalid_chars":(
            "エラー: {field} はアルファベット・数字・ハイフン・アンダースコアのみ使用できます: {tag!r}"
        ),

        # ── _validate_related_files ───────────────────────────────────────
        "validate.files.not_list":     "エラー: related_files はリストで指定してください。",
        "validate.files.too_many":     "エラー: related_files は最大{max}件です（現在{count}件）。",
        "validate.files.elem_not_str": "エラー: related_files の各要素は文字列である必要があります。",
        "validate.files.empty":        "エラー: related_files に空のパスは指定できません。",
        "validate.files.too_long":     "エラー: ファイルパスが長すぎます（最大{max}文字）。",
        "validate.files.control_chars":"エラー: ファイルパスに制御文字を含めることはできません: {fp!r}",
        "validate.files.dotdot":       "エラー: ファイルパスに「..」を含めることはできません: {fp!r}",
        "validate.files.absolute":     "エラー: related_files には相対パスを指定してください（絶対パス不可）: {fp!r}",

        # ── _validate_input ───────────────────────────────────────────────
        "validate.input.too_long": "エラー: {field}が長すぎます（最大{max}文字、現在{count}文字）。",
        "validate.input.injection":"エラー: {field}に使用できない文字列が含まれています。",

        # ── validate_project_dir ラベル名 ─────────────────────────────────
        "label.project_path":       "指定されたプロジェクトパス",
        "label.project_dir":        "プロジェクトディレクトリ",

        # ── _resolve_project_path ─────────────────────────────────────────
        "resolve_path.not_found": (
            "指定されたプロジェクトパスが見つかりません: {path}\n"
            "collab_switch_project() で正しいパスを先に登録してください。"
        ),
        "resolve_path.not_dir": (
            "指定されたプロジェクトパスがディレクトリではありません: {path}\n"
            "ディレクトリのパスを指定してください。"
        ),

        # ── _StateLock ────────────────────────────────────────────────────
        "lock.timeout": (
            "AI_STATE.json のロック取得がタイムアウトしました（{sec}秒）。\n"
            "ロックファイルが残っている場合は手動で削除してください: {lock}"
        ),

        # ── cli.py ────────────────────────────────────────────────────────
        "cli.no_config":    "エラー: '{ai}' のCLI設定がありません。",
        "cli.not_found": (
            "エラー: {AI} CLI が見つかりません。\n"
            "・'{cmd}' が PATH に存在するか確認してください。\n"
            "・または collab_setup_cli() で設定してください。"
        ),
        "cli.no_response": (
            "（{AI} CLI から応答がありませんでした）\n"
            "Codex CLI が対話モードで起動している可能性があります。\n"
            "collab_setup_cli('{ai}', ...) で非対話引数を設定してください。"
        ),
        "cli.timeout":      "エラー: {AI} CLI が {timeout}秒 以内に応答しませんでした。",
        "cli.exec_not_found":"エラー: 実行ファイルが見つかりません: {path}",
        "cli.exception":    "エラー: {AI} CLI 呼び出し中に問題が発生しました: {err}",

        # collab_consult プロンプト用ラベル
        "consult.header":       "[AI協働開発システムからの相談]",
        "consult.project":      "プロジェクト : {name}",
        "consult.task":         "現在のタスク : {title}",
        "consult.from_ai":      "相談元の AI  : {ai}",
        "consult.decisions":    "## 既存の設計決定事項（参考）",
        "consult.question":     "## 相談内容\n{question}",
        "consult.task_none":    "未設定",

        # ── collab_switch_project ─────────────────────────────────────────
        "switch.not_found": (
            "AI_STATE.json が見つかりません: {path}\n"
            "新規プロジェクトとして初期化する場合は project_name を指定してください:\n"
            "  collab_switch_project(\"{path}\", project_name=\"プロジェクト名\")"
        ),
        "switch.created": (
            "新規プロジェクトを作成しました\n"
            "  パス          : {path}\n"
            "  プロジェクト名: {name}\n"
            "  担当AI        : CLAUDE\n"
            "  モード        : {mode}\n"
            "  現在のタスク : 未設定\n"
            "  未解決issue  : 0件  保留タスク: 0件"
        ),
        "switch.connected":       "プロジェクトを設定しました{absorbed}",
        "switch.absorbed_note":   "（既存を吸収して接続）",
        "switch.path_line":       "  パス          : {path}",
        "switch.name_line":       "  プロジェクト名: {name}",
        "switch.ai_line":         "  担当AI        : {ai}",
        "switch.mode_line":       "  モード        : {mode}",
        "switch.session_line":    "  セッション    : #{session}",
        "switch.task_line":       "  現在のタスク : [{id}] {title}",
        "switch.task_none":       "  現在のタスク : 未設定",
        "switch.issue_pending":   "  未解決issue  : {issues}件  保留タスク: {pending}件",
        "switch.recent_note":     "  最新メモ     : [{ts}] {text}",
        "switch.git_branch":      "  Git ブランチ : {branch}",

        # ── collab_current_project ────────────────────────────────────────
        "current.not_set":    "現在のプロジェクトは設定されていません。collab_switch_project() を呼び出してください。",
        "current.dir_missing":(
            "⚠️ プロジェクトディレクトリが見つかりません: {path}\n"
            "ディレクトリが削除・移動された可能性があります。\n"
            "collab_switch_project() で正しいパスを再設定してください。"
        ),
        "current.not_dir":    (
            "⚠️ 設定パスがディレクトリではありません: {path}\n"
            "collab_switch_project() で正しいパスを再設定してください。"
        ),
        "current.ok": (
            "現在のプロジェクト: {path}\n"
            "  状態ファイル: {state_status}"
        ),
        "current.state_ok":      "存在 ✅",
        "current.state_missing": "未作成 ⚠️（collab_switch_project で初期化してください）",

        # ── collab_list_projects ──────────────────────────────────────────
        "list_projects.empty": (
            "最近使用したプロジェクトはありません。\n"
            "collab_switch_project('プロジェクトのフルパス') でプロジェクトを設定してください。"
        ),
        "list_projects.header":     "# 最近使用したプロジェクト（{count}件）",
        "list_projects.exists_ok":  "✅",
        "list_projects.exists_ng":  "❌（見つかりません）",
        "list_projects.last_used":  "    最終使用: {ts}",
        "list_projects.path":       "    パス: {path}",
        "list_projects.connect":    "接続するには: collab_switch_project('パス')",

        # ── collab_version ────────────────────────────────────────────────
        "version.pkg":       "パッケージバージョン    : {ver}",
        "version.schema":    "状態スキーマバージョン  : {ver}",
        "version.python":    "Python バージョン       : {ver}",
        "version.executable":"実行ファイル            : {path}",
        "version.proj_path": "プロジェクトパス        : {path}",
        "version.state_path":"AI_STATE.json           : {path}",
        "version.cli_path":  "cli_config.json         : {path}",
        "version.unset":     "（未設定）",

        # ── collab_doctor ─────────────────────────────────────────────────
        "doctor.header":     "# 診断結果 — OK: {ok}件  WARN: {warn}件  ERR: {err}件",
        "doctor.suggestion": " → {sug}",
        # プロジェクトフォルダ確認
        "doctor.project_unset":        "プロジェクト未設定",
        "doctor.project_unset_sug":    "collab_switch_project() を呼んでください",
        "doctor.project_missing":      "プロジェクトフォルダが存在しない: {proj}",
        "doctor.project_missing_sug":  "collab_switch_project() で正しいパスを再設定してください",
        "doctor.project_dir_ok":       "プロジェクトフォルダ: {proj}",
        # エンコーディング確認
        "doctor.encoding_parse_err":   "AI_STATE.json のパースに失敗: {err}",
        "doctor.encoding_parse_sug":   "collab_export_state/import_state replace で復旧できます",
        "doctor.bom_detected":         "AI_STATE.json に UTF-8 BOM が含まれています",
        "doctor.bom_detected_sug":     "読み込みは可能ですが、次回保存時に自動でBOMなしへ正規化されます",
        "doctor.encoding_ok":          "AI_STATE.json エンコーディング正常（BOMなし UTF-8）",
        # スキーマ確認
        "doctor.schema_version_mismatch":     "スキーマバージョン不一致: ファイル={file_ver}, 期待={expected}",
        "doctor.schema_version_mismatch_sug": "collab_import_state validate で検証できます",
        "doctor.schema_version_ok":           "スキーマバージョン: {ver}",
        "doctor.schema_missing_keys":         "必須キーが欠落: {keys}",
        "doctor.schema_missing_keys_sug":     "collab_switch_project() で再接続すると自動補完されます",
        "doctor.schema_bad_types":            "型不一致（リストが期待されるキー）: {keys}",
        "doctor.schema_bad_types_sug":        "AI_STATE.json を手動修正するか collab_import_state replace で復旧してください",
        "doctor.schema_keys_ok":              "必須キーと型は正常",
        # 状態ファイル確認
        "doctor.state_missing":       "AI_STATE.json が未作成",
        "doctor.state_missing_sug":   "collab_switch_project() で新規作成できます",
        "doctor.state_load_ok":       "AI_STATE.json 正常 (担当: {ai}, セッション: #{session})",
        "doctor.state_load_fail":     "AI_STATE.json 読み込み失敗: {err}",
        "doctor.state_load_fail_sug": "collab_import_state replace で復旧できます",
        # Issue 整合性確認
        "doctor.issues_non_dict":              "{list_key}[{idx}]: dict でない要素あり（旧フォーマット）",
        "doctor.issues_non_dict_sug":          "collab_switch_project() で再接続すると自動マイグレーションされます",
        "doctor.issues_bad_severity":          "{list_key}: 無効な severity — {ids}",
        "doctor.issues_bad_severity_sug":      "collab_update_issue で P0/P1/P2/P3 に修正してください",
        "doctor.issues_duplicate_id":          "{list_key}: 重複する issue ID — {ids}",
        "doctor.issues_duplicate_id_sug":      "AI_STATE.json を手動確認して重複を解消してください",
        "doctor.issues_bad_text":              "{list_key}: text フィールドが空または非文字列 — {ids}",
        "doctor.issues_bad_text_sug":          "AI_STATE.json を手動確認して text を文字列で設定してください",
        "doctor.issues_bad_tags":              "{list_key}: tags 形式不正 — {ids}",
        "doctor.issues_bad_tags_sug":          "タグはスラッグ形式（英数字・ハイフン・アンダースコア）で指定してください",
        "doctor.issues_bad_related_files":     "{list_key}: related_files に危険なパスあり — {ids}",
        "doctor.issues_bad_related_files_sug": "related_files はプロジェクト相対パスのみ。「..」や絶対パスは使用できません",
        "doctor.issues_bad_id":                "{list_key}: id フィールドが空・非文字列またはスラッグ形式外 — {ids}",
        "doctor.issues_bad_id_sug":            "id は英数字・ハイフン・アンダースコアのみの非空文字列にしてください",
        "doctor.issues_bad_category":          "{list_key}: category フィールドが不正 — {ids}",
        "doctor.issues_bad_category_sug":      "category は slug 形式（英数字・ハイフン・アンダースコア）で指定してください",
        "doctor.issues_ok":                    "{list_key}: {count}件 正常",
        # ロックファイル確認
        "doctor.lock_bad_content":     "ロックファイル内容が不正: {content!r}",
        "doctor.lock_bad_content_sug": "手動削除を検討: AI_STATE.lock",
        "doctor.lock_alive":           "ロックファイルあり (PID {pid} は生存中, {age}秒経過)",
        "doctor.lock_alive_sug":       "別プロセスが書き込み中の可能性",
        "doctor.lock_stale":           "古いロックファイル (PID {pid} は不在, {age}秒経過)",
        "doctor.lock_stale_sug":       "次回書き込み時に自動解除されます",
        "doctor.lock_parse_fail":      "ロックファイル解析失敗: {err}",
        "doctor.lock_parse_fail_sug":  "手動削除を検討: AI_STATE.lock",
        "doctor.lock_clean":           "ロックファイルなし（正常）",
        # CLI コマンド確認
        "doctor.cli_ok":          "{AI} CLI: {path}",
        "doctor.cli_missing":     "{AI} CLI 未検出 ({cmd})",
        "doctor.cli_missing_sug": "collab_setup_cli() で設定してください",
        # AI 呼び出し確認
        "doctor.ai_call_skip": "{AI} CLI 呼び出しテストをスキップ（コマンド未検出）",
        "doctor.ai_call_err":  "{AI} CLI 応答エラー: {resp}",
        "doctor.ai_call_ok":   "{AI} CLI 呼び出し成功",
        "doctor.ai_call_exc":  "{AI} CLI 呼び出し例外: {err}",
        # 復旧関連ファイル確認
        "doctor.recovery_archive": "AI_STATE.archive.json あり ({size_kb}KB)",
        "doctor.recovery_export":  "エクスポートファイル: {count}件",

        # ── collab_status ─────────────────────────────────────────────────
        "status.header":       "# AI協働開発 現在の状態",
        "status.project":      "プロジェクト : {name}",
        "status.path":         "パス         : {path}",
        "status.ai":           "担当AI       : {ai}",
        "status.mode":         "モード       : {mode}",
        "status.session":      "セッション   : #{session}",
        "status.last_updated": "最終更新     : {ts}",
        "status.git_branch":   "Git ブランチ : {branch}",
        "status.git_commit":   "直近コミット : {commit}",
        "status.git_dirty":    " *（未コミット変更あり）",
        "status.warn_ai_mismatch": "⚠️ 担当AI不一致の警告",
        "status.warn_current_ai":  "  現在の担当: {ai}",
        "status.warn_calling_ai":  "  呼び出し元: {ai}",
        "status.warn_handoff":     "  → 必要なら collab_generate_handoff() で担当AIを切り替えてください。",
        "status.task_header":      "## 現在のタスク",
        "status.task_id":          "ID      : {id}",
        "status.task_title":       "タイトル: {title}",
        "status.task_desc":        "詳細    : {desc}",
        "status.task_started":     "開始    : {ts}  担当: {ai}",
        "status.task_files":       "変更済みファイル:",
        "status.task_none":        "未設定",
        "status.pending_header":   "## 保留中のタスク",
        "status.notes_header":     "## 最近のメモ（最新5件 / 合計{count}件）",
        "status.notes_warn_300":   "⚠️ メモが{count}件あります。collab_cleanup_history() でアーカイブを推奨します。",
        "status.notes_warn_200":   "💡 メモが{count}件に達しました。collab_cleanup_history() でアーカイブできます。",
        "status.decisions_header": "## 重要な決定事項",
        "status.issues_header":    "## 既知の問題・注意点",

        # ── collab_set_task ───────────────────────────────────────────────
        "set_task.done":  "タスクを設定しました: [{id}] {title}",
        "set_task.log":   "タスク開始: [{id}] {title}",

        # ── collab_add_note ───────────────────────────────────────────────
        "add_note.done":      "メモを追加しました: {text}",
        "add_note.warn_300":  "\n⚠️ メモが{count}件に達しました。collab_cleanup_history() でアーカイブしてください。",
        "add_note.log":       "メモ: {text}",

        # ── collab_record_decision ────────────────────────────────────────
        "record_decision.done": "決定事項を記録しました: {title}",
        "record_decision.log":  "決定事項記録: {title}",

        # ── collab_record_issue ───────────────────────────────────────────
        "record_issue.done":        "問題を記録しました: {emoji} [{id}][{sev}] {text}",
        "record_issue.log":         "問題記録: [{id}][{sev}] {text}",
        "record_issue.err_severity":"エラー: severity は {valid} のいずれかを指定してください。",
        "record_issue.err_category_slug":  "エラー: category はslug形式（英数字・ハイフン・アンダースコア）で指定してください: {cat!r}",
        "record_issue.err_category_long":  "エラー: category は最大{max}文字です。",

        # ── collab_resolve_issue ──────────────────────────────────────────
        "resolve_issue.not_found": "エラー: 問題が見つかりません: {id}（collab_status で ID を確認してください）",
        "resolve_issue.done":      "問題を解決済みにしました: [{id}] {text}",
        "resolve_issue.log":       "問題解決: [{id}] {text}",

        # ── collab_update_issue ───────────────────────────────────────────
        "update_issue.err_tags_conflict":  "エラー: tags と add_tags/remove_tags は同時に指定できません。",
        "update_issue.err_files_conflict": "エラー: related_files と add_related_files/remove_related_files は同時に指定できません。",
        "update_issue.err_severity":       "エラー: severity は {valid} のいずれかを指定してください。",
        "update_issue.err_category_slug":  "エラー: category はslug形式で指定してください: {cat!r}",
        "update_issue.err_category_long":  "エラー: category は最大{max}文字です。",
        "update_issue.err_status":         "エラー: status は {valid} のいずれかを指定してください（resolved 化は collab_resolve_issue を使ってください）。",
        "update_issue.not_found":          "エラー: 未解決の問題が見つかりません: {id}（解決済み issue は更新不可）",
        "update_issue.not_found_inner":    "エラー: 問題が見つかりません: {id}",
        "update_issue.done":               "問題を更新しました: {emoji} [{id}][{sev}] {text}\n  category: {cat}  tags: {tags}  status: {status}",
        "update_issue.log":                "問題更新: [{id}]",

        # ── collab_list_resolved ──────────────────────────────────────────
        "list_resolved.empty":   "解決済みの問題はありません。",
        "list_resolved.header":  "# 解決済みの問題一覧（{count}件）",
        "list_resolved.resolved_by": "  解決: {ts}  by {ai}",
        "list_resolved.note":    "  メモ: {note}",

        # ── collab_record_file ────────────────────────────────────────────
        "record_file.err_control":  "エラー: file_path に改行・制御文字は使用できません。",
        "record_file.err_no_task":  "エラー: 現在のタスクが設定されていません。先に collab_set_task を呼び出してください。",
        "record_file.already":      "既に記録済みです: {path}",
        "record_file.done":         "ファイルを記録しました: {path}",
        "record_file.log":          "ファイル記録: {path}",

        # ── collab_change_mode ────────────────────────────────────────────
        "change_mode.err":  "エラー: モードは {valid} のいずれかを指定してください。",
        "change_mode.done": "モードを変更しました: {old} → {new}",
        "change_mode.log":  "モード変更: {old} → {new}",

        # ── collab_add_pending_task ───────────────────────────────────────
        "add_pending.done": "保留タスクに追加しました: [{id}] {title}",
        "add_pending.log":  "保留タスク追加: {title}",

        # ── collab_close_pending_task ─────────────────────────────────────
        "close_pending.not_found": "エラー: 保留タスクが見つかりません: {id}",
        "close_pending.done":      "保留タスクを完了しました: [{id}] {title}",
        "close_pending.log":       "保留タスク完了: [{id}] {title}",

        # ── collab_complete_task ──────────────────────────────────────────
        "complete_task.err_no_task": "エラー: 現在のタスクが設定されていません。collab_set_task() で先にタスクを設定してください。",
        "complete_task.done":        "タスクを完了しました: [{id}] {title}",
        "complete_task.log":         "タスク完了: [{id}] {title}",

        # ── collab_generate_handoff ───────────────────────────────────────
        "generate_handoff.err_ai": "エラー: AIは 'claude' または 'codex' を指定してください。",
        "generate_handoff.done": (
            "ハンドオフを生成しました: {from_ai} → {to_ai}\n"
            "ファイル: {file}\n\n"
            "{app} の新しいセッションで\n"
            "「HANDOFF.md を読んで続きをお願いします」と伝えてください。"
        ),
        "generate_handoff.app_claude": "Claude",
        "generate_handoff.app_codex":  "Codex",
        "generate_handoff.log":        "ハンドオフ: {from_ai} → {to_ai}",

        # ── collab_checkpoint ─────────────────────────────────────────────
        "checkpoint.err_ai": "エラー: AIは 'claude' または 'codex' を指定してください。",
        "checkpoint.done": (
            "チェックポイントを生成しました: {from_ai} → {to_ai}\n"
            "メモ: {msg}\n"
            "ファイル: {file}"
        ),
        "checkpoint.log_note":    "メモ: {text}",
        "checkpoint.log_handoff": "チェックポイント/ハンドオフ: {from_ai} → {to_ai}",

        # ── collab_consult ────────────────────────────────────────────────
        "consult.result":      "【{AI} CLI の回答】\n\n{response}",
        "consult.save_failed": "\n\n⚠️ メモへの保存に失敗しました",
        "consult.note_label":  "[{AI}に相談] {question}",
        "consult.log":         "{AI}CLIへの相談: {question}",

        # ── collab_discuss ────────────────────────────────────────────────
        "discuss.result_header": "【{AI} CLI との議論結果】（{rounds}ラウンド）",
        "discuss.round_header":  "### ラウンド {n} — {ai}",
        "discuss.save_failed":   "\n⚠️ メモへの保存に失敗しました",
        "discuss.note_label":    "[{AI}と議論] {topic}",
        "discuss.log":           "{AI}CLIとの議論: {topic}",
        "discuss.followup":      "以下の回答を踏まえて、さらに深掘りした質問や意見を述べてください:\n\n{response}",
        "discuss.history_header":"## これまでの議論の流れ",

        # ── collab_setup_cli ──────────────────────────────────────────────
        "setup_cli.err_cmd": (
            "エラー: command に設定できるのは 'claude' または 'codex' の実行ファイルのみです。\n"
            "指定値: {cmd}（ファイル名: {stem}）"
        ),
        "setup_cli.path_ok":      "見つかりました: {path}",
        "setup_cli.path_missing": "⚠ 見つかりません。パスを確認してください。",
        "setup_cli.done": (
            "CLI設定を保存しました: {file}\n"
            "  AI      : {AI}\n"
            "  command : {cmd}  →  {status}\n"
            "  実行例  : {cmd} {args_before} \"<プロンプト>\" {args_after}"
        ),

        # ── collab_request_review ─────────────────────────────────────────
        "request_review.question": (
            "[レビュー依頼]\n"
            "対象スコープ: {scope}\n"
            "重点事項: {focus}\n\n"
            "問題点・改善点・リスクを指摘してください。"
        ),
        "request_review.focus_default": "全般",
        "request_review.scope_default": "現在の実装全体",
        "request_review.result":        "【{AI} CLI のレビュー】\n\n{response}",
        "request_review.save_failed":   "\n\n⚠️ メモへの保存に失敗しました",
        "request_review.note_label":    "[{AI}にレビュー依頼] {scope}",
        "request_review.log":           "[{AI}にレビュー依頼] {scope}",

        # ── collab_summary ────────────────────────────────────────────────
        "summary.task_none": "未設定",
        "summary.line1":     "📋 {project} | {ai} | {mode} | セッション#{session}",
        "summary.line2":     "🔧 タスク : {task}",
        "summary.line3":     "⏳ 保留  : {pending}件  ⚠️ 問題: {issues}件",
        "summary.line4":     "🕐 最終更新: {ts}",

        # ── collab_search ─────────────────────────────────────────────────
        "search.not_found":  "「{query}」に一致する項目は見つかりませんでした。",
        "search.header":     "# 検索結果: 「{query}」（{count}件）",
        "search.note":       "[メモ]   {ts} ({ai}) {text}",
        "search.decision":   "[決定]   {ts} {title}: {content}",
        "search.issue":      "[問題]   {emoji}[{id}][{sev}] {text}",
        "search.resolved":   "[解決済] {emoji}[{id}][{sev}] {text}",
        "search.pending":    "[保留]   [{id}] {title}",
        "search.task":       "[タスク] [{id}] {title}",
        "search.task_done":  "[完了タスク] [{id}] {title} ({ts})",
        "search.pending_done":"[完了保留] [{id}] {title} ({ts})",

        # ── collab_timeline ───────────────────────────────────────────────
        "timeline.empty":          "（表示できるイベントがありません）",
        "timeline.header":         "# タイムライン（{count}件）",
        "timeline.kind.note":      "📝 メモ    ",
        "timeline.kind.decision":  "📌 決定    ",
        "timeline.kind.issue":     "⚠️  問題    ",
        "timeline.kind.resolved":  "✅ 問題解決",
        "timeline.kind.task":      "🔧 タスク  ",
        "timeline.kind.task_done": "✅ タスク完",
        "timeline.kind.pending":   "⏳ 保留    ",
        "timeline.kind.pending_done":"✅ 保留完了",
        # timeline イベントラベル（state 内データは日本語固定のままにして OK）
        "timeline.issue_resolved_label":  "解決: {text}",
        "timeline.task_done_label":       "完了: {title}",
        "timeline.pending_done_label":    "完了: {title}",

        # ── collab_cleanup_sessions ───────────────────────────────────────
        "cleanup_sessions.err":          "エラー: keep_per_ai は 1 以上を指定してください。",
        "cleanup_sessions.no_dir":       "ai_sessions/ フォルダが存在しません。",
        "cleanup_sessions.no_target":    "削除対象なし（各AI最新{keep}件以内）。\n現在のログ数:\n{summary}",
        "cleanup_sessions.summary_item": "{AI}: {count}件",
        "cleanup_sessions.done":         "{count}件のセッションログを削除しました。\n残存ログ:\n{kept}\n削除ファイル:\n{files}",
        "cleanup_sessions.kept_item":    "{AI}: {count}件残存",

        # ── collab_cleanup_history ────────────────────────────────────────
        "cleanup_history.err":    "エラー: keep_notes / keep_completed_tasks は 1 以上を指定してください。",
        "cleanup_history.no_need":(
            "整理不要です。\n"
            "  メモ: {notes}件（上限 {keep_notes}件）\n"
            "  完了タスク: {tasks}件（上限 {keep_tasks}件）"
        ),
        "cleanup_history.dry_run":(
            "[dry_run] 実行すると以下が整理されます:\n"
            "  メモ: {notes}件 → {notes_after}件残存（{notes_trim}件アーカイブ）\n"
            "  完了タスク: {tasks}件 → {tasks_after}件残存（{tasks_trim}件アーカイブ）\n"
            "  アーカイブ先: {archive_dest}\n"
            "dry_run=False で実行してください。"
        ),
        "cleanup_history.archive_dest":   "AI_STATE.archive.json",
        "cleanup_history.delete_dest":    "（単純削除）",
        "cleanup_history.done": (
            "履歴を整理しました。\n"
            "  メモ: {notes}件 → {notes_after}件（{notes_trim}件を{dest}）\n"
            "  完了タスク: {tasks}件 → {tasks_after}件（{tasks_trim}件を{dest}）"
        ),
        "cleanup_history.archive_note":   "AI_STATE.archive.json に退避",
        "cleanup_history.delete_note":    "単純削除",

        # ── collab_export_state ───────────────────────────────────────────
        "export.err_path":           "エラー: output_path は絶対パスを指定してください。",
        "export.err_write":          "エラー: ファイルの書き込みに失敗しました: {err}",
        "export.session_read_error": "（読み込み失敗）",
        "export.done": (
            "状態をエクスポートしました。\n"
            "  出力ファイル: {out}\n"
            "  SHA-256: {checksum}...\n"
            "  メモ: {notes}件  決定事項: {decisions}件  問題: {issues}件\n"
            "復元: collab_import_state('{out}')"
        ),

        # ── collab_import_state ───────────────────────────────────────────
        "import.err_mode":       "エラー: mode は 'validate' / 'merge' / 'replace' のいずれかを指定してください。",
        "import.err_path":       "エラー: input_path は絶対パスを指定してください。",
        "import.err_not_found":  "エラー: ファイルが見つかりません: {path}",
        "import.err_read":       "エラー: ファイルの読み込みに失敗しました: {err}",
        "import.err_no_checksum":"エラー: チェックサムが見つかりません。このファイルはエクスポートされたものではない可能性があります。",
        "import.err_checksum_mismatch": (
            "エラー: チェックサムが一致しません。ファイルが破損または改ざんされています。\n"
            "  格納値: {stored}...\n"
            "  計算値: {calc}..."
        ),
        "import.err_backup":     "エラー: バックアップの作成に失敗しました: {err}",
        "import.validated": (
            "チェックサム検証: OK ✅\n"
            "  エクスポート日時: {exported_at}\n"
            "  ソースプロジェクト: {source}\n"
            "  メモ: {notes}件  決定事項: {decisions}件  "
            "問題: {issues}件  完了タスク: {tasks}件\n"
            "インポートするには mode='merge' または mode='replace' を指定してください。"
        ),
        "import.replaced": (
            "状態を完全置換しました。{backup}\n"
            "  エクスポート日時: {exported_at}\n"
            "  ソースプロジェクト: {source}"
        ),
        "import.replaced_backup": "（バックアップ: {name}）",
        "import.merged": (
            "状態をマージしました。\n"
            "  追加メモ: {notes}件  "
            "追加決定事項: {decisions}件  "
            "追加問題: {issues}件\n"
            "  エクスポート日時: {exported_at}"
        ),
        "import.unknown": "不明",

        # ── collab_set_handoff_template ───────────────────────────────────
        "set_template.err": (
            "エラー: preset は {valid} のいずれかを指定してください。\n"
            "指定値: '{preset}'"
        ),
        "set_template.desc.full":    "全セクション（デフォルト）",
        "set_template.desc.minimal": "現在タスク＋最新3件＋既知の問題のみ",
        "set_template.desc.review":  "full＋レビューポイントセクション",
        "set_template.desc.debug":   "full＋デバッグ情報セクション",
        "set_template.done": (
            "ハンドオフテンプレートを変更しました。\n"
            "  {old} → {new}\n"
            "  内容: {desc}\n"
            "次回の collab_generate_handoff() / collab_checkpoint() から反映されます。"
        ),

        # ── rendering.py（HANDOFF.md テンプレート） ───────────────────────
        "handoff.title":           "# AI協働開発 ハンドオフドキュメント",
        "handoff.from_to":         "> **引き継ぎ元:** {from_ai}　→　**引き継ぎ先:** {to_ai}",
        "handoff.datetime_proj":   "> **日時:** {dt}　｜　**プロジェクト:** {project}",
        "handoff.mode_session":    "> **モード:** {mode}　｜　**セッション:** #{session}",
        "handoff.template_line":   "> **テンプレート:** {template}",
        "handoff.sec_current_task":"## 現在のタスク",
        "handoff.task_id":         "**タスクID:** `{id}`",
        "handoff.task_title":      "**タイトル:** <!-- USER INPUT -->{title}<!-- /USER INPUT -->",
        "handoff.task_desc":       "**詳細:** <!-- USER INPUT -->{desc}<!-- /USER INPUT -->",
        "handoff.task_started":    "**開始:** {ts}  担当: {ai}",
        "handoff.task_files":      "**変更済みファイル:**",
        "handoff.task_none":       "*タスクは設定されていません。*",
        "handoff.sec_pending":     "保留中のタスク",
        "handoff.sec_notes":       "最近のメモ（最新{n}件）",
        "handoff.sec_decisions":   "重要な決定事項",
        "handoff.sec_issues":      "既知の問題・注意点",
        "handoff.sec_done_tasks":  "完了済みタスク（最近5件）",
        "handoff.sec_done_pending":"完了した保留タスク（最近5件）",
        "handoff.sec_review":      "## 📋 レビューポイント",
        "handoff.review_intro":    "以下の観点でレビューしてください:",
        "handoff.review_1":        "- 実装が決定事項と一致しているか",
        "handoff.review_2":        "- 既知の問題が解決されているか",
        "handoff.review_3":        "- コードの品質・セキュリティ・パフォーマンス",
        "handoff.review_4":        "- 次のフェーズに進む前に確認すべき点",
        "handoff.sec_debug":       "## 🐛 デバッグ情報",
        "handoff.debug_files":     "**直近の変更ファイル:**",
        "handoff.debug_issues":    "**未解決の問題 (issue-NNN形式):**",
        "handoff.debug_priority":  "**デバッグ優先事項:** 既知の問題から着手し、変更ファイルを重点的に確認してください。",
        "handoff.empty_item":      "*なし*",
        "handoff.notes_omitted":   "- *過去{n}件のメモを省略*",
        "handoff.decisions_omitted":"*過去{n}件の決定事項を省略*",
        "handoff.sec_footer":      "## {ai} セッション開始手順",
        "handoff.step1":           "**1. プロジェクトを設定する（毎セッション必須）**",
        "handoff.step2":           "**2. 状態を確認する**",
        "handoff.step3":           "**3. 作業中はこまめにメモを残す**",
        "handoff.step3_code":      'collab_add_note("気づいたことや進捗")',
        "handoff.step4":           "**4. セッション終了・レートリミット前にチェックポイントを生成する**",
        "handoff.step4_code":      'collab_checkpoint("ここまでの進捗と次の作業", "{from_ai}")',
    },

    # ══════════════════════════════════════════════════════════════════════
    # English
    # ══════════════════════════════════════════════════════════════════════
    "en": {

        # ── Common errors ─────────────────────────────────────────────────
        "err.runtime":          "Error: {msg}",
        "err.absolute_path":    "Error: An absolute path is required (relative paths are not allowed): {path}",
        "err.dir_not_found":    "Error: Directory does not exist: {path}",
        "err.invalid_ai":       "Error: ai must be 'claude' or 'codex'.",
        "err.invalid_ai_long":  "Error: AI must be 'claude' or 'codex'.",
        "err.file_write":       "Error: Failed to write file: {err}",
        "err.file_read":        "Error: Failed to read file: {err}",
        "err.backup_failed":    "Error: Failed to create backup: {err}",

        # ── validate_project_dir ──────────────────────────────────────────
        "validate.path_not_found": (
            "{label} not found: {path}\n"
            "The directory may have been deleted or moved.\n"
            "Please call collab_switch_project() to set the correct path."
        ),
        "validate.path_not_dir": (
            "{label} is not a directory: {path}\n"
            "Please call collab_switch_project() to set the correct path."
        ),

        # ── _get_project_dir ──────────────────────────────────────────────
        "project.not_set": (
            "No project is currently set.\n"
            "Please call collab_switch_project('/path/to/project')."
        ),

        # ── _load_state ───────────────────────────────────────────────────
        "load_state.not_found": (
            "AI_STATE.json not found: {sf}\n"
            "Please call collab_switch_project(path, project_name='Project Name') to initialize."
        ),

        # ── _validate_tags ────────────────────────────────────────────────
        "validate.tags.not_list":     "Error: {field} must be a list.",
        "validate.tags.too_many":     "Error: {field} exceeds the maximum of {max} items (current: {count}).",
        "validate.tags.elem_not_str": "Error: Each element in {field} must be a string.",
        "validate.tags.empty":        "Error: Empty tags are not allowed in {field}.",
        "validate.tags.too_long":     "Error: Each tag in {field} must be at most {max} characters: {tag!r}",
        "validate.tags.invalid_chars":(
            "Error: {field} may only contain letters, digits, hyphens, and underscores: {tag!r}"
        ),

        # ── _validate_related_files ───────────────────────────────────────
        "validate.files.not_list":     "Error: related_files must be a list.",
        "validate.files.too_many":     "Error: related_files exceeds the maximum of {max} items (current: {count}).",
        "validate.files.elem_not_str": "Error: Each element in related_files must be a string.",
        "validate.files.empty":        "Error: Empty paths are not allowed in related_files.",
        "validate.files.too_long":     "Error: File path is too long (max {max} characters).",
        "validate.files.control_chars":"Error: File path must not contain control characters: {fp!r}",
        "validate.files.dotdot":       "Error: File path must not contain '..': {fp!r}",
        "validate.files.absolute":     "Error: related_files must use relative paths (absolute paths are not allowed): {fp!r}",

        # ── _validate_input ───────────────────────────────────────────────
        "validate.input.too_long": "Error: {field} is too long (max {max} characters, current: {count}).",
        "validate.input.injection":"Error: {field} contains an invalid character sequence.",

        # ── validate_project_dir label names ──────────────────────────────
        "label.project_path":       "Specified project path",
        "label.project_dir":        "Project directory",

        # ── _resolve_project_path ─────────────────────────────────────────
        "resolve_path.not_found": (
            "Specified project path not found: {path}\n"
            "Please register the correct path first with collab_switch_project()."
        ),
        "resolve_path.not_dir": (
            "Specified project path is not a directory: {path}\n"
            "Please specify a directory path."
        ),

        # ── _StateLock ────────────────────────────────────────────────────
        "lock.timeout": (
            "Timed out waiting for AI_STATE.json lock ({sec} seconds).\n"
            "If a lock file remains, delete it manually: {lock}"
        ),

        # ── cli.py ────────────────────────────────────────────────────────
        "cli.no_config":    "Error: No CLI configuration found for '{ai}'.",
        "cli.not_found": (
            "Error: {AI} CLI not found.\n"
            "· Verify that '{cmd}' exists in PATH.\n"
            "· Or configure it with collab_setup_cli()."
        ),
        "cli.no_response": (
            "({AI} CLI returned no response)\n"
            "The Codex CLI may have launched in interactive mode.\n"
            "Set non-interactive arguments with collab_setup_cli('{ai}', ...)."
        ),
        "cli.timeout":       "Error: {AI} CLI did not respond within {timeout} seconds.",
        "cli.exec_not_found":"Error: Executable not found: {path}",
        "cli.exception":     "Error: Exception while calling {AI} CLI: {err}",

        # Consult prompt labels
        "consult.header":       "[AI Collaborative Development — Consultation]",
        "consult.project":      "Project      : {name}",
        "consult.task":         "Current Task : {title}",
        "consult.from_ai":      "Requesting AI: {ai}",
        "consult.decisions":    "## Existing Design Decisions (for reference)",
        "consult.question":     "## Question\n{question}",
        "consult.task_none":    "Not set",

        # ── collab_switch_project ─────────────────────────────────────────
        "switch.not_found": (
            "AI_STATE.json not found: {path}\n"
            "To initialize as a new project, specify project_name:\n"
            "  collab_switch_project(\"{path}\", project_name=\"My Project\")"
        ),
        "switch.created": (
            "New project created\n"
            "  Path          : {path}\n"
            "  Project Name  : {name}\n"
            "  AI Assignee   : CLAUDE\n"
            "  Mode          : {mode}\n"
            "  Current Task  : Not set\n"
            "  Open Issues   : 0  Pending Tasks: 0"
        ),
        "switch.connected":      "Project connected{absorbed}",
        "switch.absorbed_note":  " (existing state loaded)",
        "switch.path_line":      "  Path          : {path}",
        "switch.name_line":      "  Project Name  : {name}",
        "switch.ai_line":        "  AI Assignee   : {ai}",
        "switch.mode_line":      "  Mode          : {mode}",
        "switch.session_line":   "  Session       : #{session}",
        "switch.task_line":      "  Current Task  : [{id}] {title}",
        "switch.task_none":      "  Current Task  : Not set",
        "switch.issue_pending":  "  Open Issues   : {issues}  Pending Tasks: {pending}",
        "switch.recent_note":    "  Latest Note   : [{ts}] {text}",
        "switch.git_branch":     "  Git Branch    : {branch}",

        # ── collab_current_project ────────────────────────────────────────
        "current.not_set":    "No project is currently set. Please call collab_switch_project().",
        "current.dir_missing":(
            "⚠️ Project directory not found: {path}\n"
            "The directory may have been deleted or moved.\n"
            "Please call collab_switch_project() to set the correct path."
        ),
        "current.not_dir":    (
            "⚠️ The configured path is not a directory: {path}\n"
            "Please call collab_switch_project() to set the correct path."
        ),
        "current.ok": (
            "Current project: {path}\n"
            "  State file: {state_status}"
        ),
        "current.state_ok":      "exists ✅",
        "current.state_missing": "not created ⚠️ (initialize with collab_switch_project)",

        # ── collab_list_projects ──────────────────────────────────────────
        "list_projects.empty": (
            "No recently used projects.\n"
            "Set a project with collab_switch_project('/path/to/project')."
        ),
        "list_projects.header":     "# Recently Used Projects ({count})",
        "list_projects.exists_ok":  "✅",
        "list_projects.exists_ng":  "❌ (not found)",
        "list_projects.last_used":  "    Last used: {ts}",
        "list_projects.path":       "    Path: {path}",
        "list_projects.connect":    "Connect with: collab_switch_project('path')",

        # ── collab_version ────────────────────────────────────────────────
        "version.pkg":       "Package version         : {ver}",
        "version.schema":    "State schema version    : {ver}",
        "version.python":    "Python version          : {ver}",
        "version.executable":"Executable              : {path}",
        "version.proj_path": "Project path            : {path}",
        "version.state_path":"AI_STATE.json           : {path}",
        "version.cli_path":  "cli_config.json         : {path}",
        "version.unset":     "(not set)",

        # ── collab_doctor ─────────────────────────────────────────────────
        "doctor.header":     "# Diagnostics — OK: {ok}  WARN: {warn}  ERR: {err}",
        "doctor.suggestion": " → {sug}",
        # Project folder check
        "doctor.project_unset":        "Project not set",
        "doctor.project_unset_sug":    "Please call collab_switch_project()",
        "doctor.project_missing":      "Project folder does not exist: {proj}",
        "doctor.project_missing_sug":  "Please call collab_switch_project() with the correct path",
        "doctor.project_dir_ok":       "Project folder: {proj}",
        # Encoding check
        "doctor.encoding_parse_err":   "Failed to parse AI_STATE.json: {err}",
        "doctor.encoding_parse_sug":   "Recover with collab_export_state/import_state replace",
        "doctor.bom_detected":         "AI_STATE.json contains UTF-8 BOM",
        "doctor.bom_detected_sug":     "Readable, but will be normalized to BOM-less on next save",
        "doctor.encoding_ok":          "AI_STATE.json encoding OK (BOM-less UTF-8)",
        # Schema check
        "doctor.schema_version_mismatch":     "Schema version mismatch: file={file_ver}, expected={expected}",
        "doctor.schema_version_mismatch_sug": "Validate with collab_import_state validate",
        "doctor.schema_version_ok":           "Schema version: {ver}",
        "doctor.schema_missing_keys":         "Missing required keys: {keys}",
        "doctor.schema_missing_keys_sug":     "Reconnect with collab_switch_project() to auto-fill missing keys",
        "doctor.schema_bad_types":            "Type mismatch (keys expected to be lists): {keys}",
        "doctor.schema_bad_types_sug":        "Fix AI_STATE.json manually or recover with collab_import_state replace",
        "doctor.schema_keys_ok":              "Required keys and types are correct",
        # State file check
        "doctor.state_missing":       "AI_STATE.json not created",
        "doctor.state_missing_sug":   "Create it with collab_switch_project()",
        "doctor.state_load_ok":       "AI_STATE.json OK (assignee: {ai}, session: #{session})",
        "doctor.state_load_fail":     "Failed to load AI_STATE.json: {err}",
        "doctor.state_load_fail_sug": "Recover with collab_import_state replace",
        # Issue integrity check
        "doctor.issues_non_dict":              "{list_key}[{idx}]: non-dict entries found (old format)",
        "doctor.issues_non_dict_sug":          "Reconnect with collab_switch_project() to auto-migrate",
        "doctor.issues_bad_severity":          "{list_key}: invalid severity — {ids}",
        "doctor.issues_bad_severity_sug":      "Fix with collab_update_issue using P0/P1/P2/P3",
        "doctor.issues_duplicate_id":          "{list_key}: duplicate issue IDs — {ids}",
        "doctor.issues_duplicate_id_sug":      "Manually inspect AI_STATE.json to resolve duplicates",
        "doctor.issues_bad_text":              "{list_key}: text field is empty or non-string — {ids}",
        "doctor.issues_bad_text_sug":          "Manually fix AI_STATE.json to set text as a string",
        "doctor.issues_bad_tags":              "{list_key}: invalid tags format — {ids}",
        "doctor.issues_bad_tags_sug":          "Tags must be in slug format (letters, digits, hyphens, underscores)",
        "doctor.issues_bad_related_files":     "{list_key}: unsafe paths in related_files — {ids}",
        "doctor.issues_bad_related_files_sug": "related_files must be project-relative paths; '..' and absolute paths are not allowed",
        "doctor.issues_bad_id":                "{list_key}: id field is empty, non-string, or not slug format — {ids}",
        "doctor.issues_bad_id_sug":            "id must be a non-empty string of letters, digits, hyphens, and underscores",
        "doctor.issues_bad_category":          "{list_key}: invalid category field — {ids}",
        "doctor.issues_bad_category_sug":      "category must be in slug format (letters, digits, hyphens, underscores)",
        "doctor.issues_ok":                    "{list_key}: {count} entries OK",
        # Lock file check
        "doctor.lock_bad_content":     "Lock file content is invalid: {content!r}",
        "doctor.lock_bad_content_sug": "Consider manual deletion: AI_STATE.lock",
        "doctor.lock_alive":           "Lock file found (PID {pid} is alive, {age} seconds elapsed)",
        "doctor.lock_alive_sug":       "Another process may be writing",
        "doctor.lock_stale":           "Stale lock file (PID {pid} is gone, {age} seconds elapsed)",
        "doctor.lock_stale_sug":       "Will be auto-removed on next write",
        "doctor.lock_parse_fail":      "Failed to parse lock file: {err}",
        "doctor.lock_parse_fail_sug":  "Consider manual deletion: AI_STATE.lock",
        "doctor.lock_clean":           "No lock file (normal)",
        # CLI command check
        "doctor.cli_ok":          "{AI} CLI: {path}",
        "doctor.cli_missing":     "{AI} CLI not detected ({cmd})",
        "doctor.cli_missing_sug": "Configure with collab_setup_cli()",
        # AI call check
        "doctor.ai_call_skip": "{AI} CLI call test skipped (command not found)",
        "doctor.ai_call_err":  "{AI} CLI response error: {resp}",
        "doctor.ai_call_ok":   "{AI} CLI call successful",
        "doctor.ai_call_exc":  "{AI} CLI call exception: {err}",
        # Recovery file check
        "doctor.recovery_archive": "AI_STATE.archive.json found ({size_kb}KB)",
        "doctor.recovery_export":  "Export files found: {count}",

        # ── collab_status ─────────────────────────────────────────────────
        "status.header":       "# AI Collaborative Development — Current State",
        "status.project":      "Project      : {name}",
        "status.path":         "Path         : {path}",
        "status.ai":           "AI Assignee  : {ai}",
        "status.mode":         "Mode         : {mode}",
        "status.session":      "Session      : #{session}",
        "status.last_updated": "Last Updated : {ts}",
        "status.git_branch":   "Git Branch   : {branch}",
        "status.git_commit":   "Latest Commit: {commit}",
        "status.git_dirty":    " *(uncommitted changes)",
        "status.warn_ai_mismatch": "⚠️ AI Assignee Mismatch Warning",
        "status.warn_current_ai":  "  Current assignee: {ai}",
        "status.warn_calling_ai":  "  Calling AI      : {ai}",
        "status.warn_handoff":     "  → Use collab_generate_handoff() to switch the AI assignee if needed.",
        "status.task_header":      "## Current Task",
        "status.task_id":          "ID      : {id}",
        "status.task_title":       "Title   : {title}",
        "status.task_desc":        "Details : {desc}",
        "status.task_started":     "Started : {ts}  by {ai}",
        "status.task_files":       "Modified Files:",
        "status.task_none":        "Not set",
        "status.pending_header":   "## Pending Tasks",
        "status.notes_header":     "## Recent Notes (latest 5 / total {count})",
        "status.notes_warn_300":   "⚠️ {count} notes accumulated. Consider archiving with collab_cleanup_history().",
        "status.notes_warn_200":   "💡 {count} notes accumulated. You can archive with collab_cleanup_history().",
        "status.decisions_header": "## Key Decisions",
        "status.issues_header":    "## Known Issues",

        # ── collab_set_task ───────────────────────────────────────────────
        "set_task.done":  "Task set: [{id}] {title}",
        "set_task.log":   "Task started: [{id}] {title}",

        # ── collab_add_note ───────────────────────────────────────────────
        "add_note.done":      "Note added: {text}",
        "add_note.warn_300":  "\n⚠️ {count} notes accumulated. Please archive with collab_cleanup_history().",
        "add_note.log":       "Note: {text}",

        # ── collab_record_decision ────────────────────────────────────────
        "record_decision.done": "Decision recorded: {title}",
        "record_decision.log":  "Decision recorded: {title}",

        # ── collab_record_issue ───────────────────────────────────────────
        "record_issue.done":             "Issue recorded: {emoji} [{id}][{sev}] {text}",
        "record_issue.log":              "Issue recorded: [{id}][{sev}] {text}",
        "record_issue.err_severity":     "Error: severity must be one of {valid}.",
        "record_issue.err_category_slug":"Error: category must be in slug format (letters, digits, hyphens, underscores): {cat!r}",
        "record_issue.err_category_long":"Error: category must be at most {max} characters.",

        # ── collab_resolve_issue ──────────────────────────────────────────
        "resolve_issue.not_found": "Error: Issue not found: {id} (check IDs with collab_status)",
        "resolve_issue.done":      "Issue resolved: [{id}] {text}",
        "resolve_issue.log":       "Issue resolved: [{id}] {text}",

        # ── collab_update_issue ───────────────────────────────────────────
        "update_issue.err_tags_conflict":  "Error: tags and add_tags/remove_tags cannot be specified together.",
        "update_issue.err_files_conflict": "Error: related_files and add_related_files/remove_related_files cannot be specified together.",
        "update_issue.err_severity":       "Error: severity must be one of {valid}.",
        "update_issue.err_category_slug":  "Error: category must be in slug format: {cat!r}",
        "update_issue.err_category_long":  "Error: category must be at most {max} characters.",
        "update_issue.err_status":         "Error: status must be one of {valid} (use collab_resolve_issue to resolve).",
        "update_issue.not_found":          "Error: Open issue not found: {id} (resolved issues cannot be updated)",
        "update_issue.not_found_inner":    "Error: Issue not found: {id}",
        "update_issue.done":               "Issue updated: {emoji} [{id}][{sev}] {text}\n  category: {cat}  tags: {tags}  status: {status}",
        "update_issue.log":                "Issue updated: [{id}]",

        # ── collab_list_resolved ──────────────────────────────────────────
        "list_resolved.empty":    "No resolved issues.",
        "list_resolved.header":   "# Resolved Issues ({count})",
        "list_resolved.resolved_by": "  Resolved: {ts}  by {ai}",
        "list_resolved.note":     "  Note: {note}",

        # ── collab_record_file ────────────────────────────────────────────
        "record_file.err_control": "Error: file_path must not contain newlines or control characters.",
        "record_file.err_no_task": "Error: No current task is set. Please call collab_set_task first.",
        "record_file.already":     "Already recorded: {path}",
        "record_file.done":        "File recorded: {path}",
        "record_file.log":         "File recorded: {path}",

        # ── collab_change_mode ────────────────────────────────────────────
        "change_mode.err":  "Error: mode must be one of {valid}.",
        "change_mode.done": "Mode changed: {old} → {new}",
        "change_mode.log":  "Mode changed: {old} → {new}",

        # ── collab_add_pending_task ───────────────────────────────────────
        "add_pending.done": "Pending task added: [{id}] {title}",
        "add_pending.log":  "Pending task added: {title}",

        # ── collab_close_pending_task ─────────────────────────────────────
        "close_pending.not_found": "Error: Pending task not found: {id}",
        "close_pending.done":      "Pending task completed: [{id}] {title}",
        "close_pending.log":       "Pending task completed: [{id}] {title}",

        # ── collab_complete_task ──────────────────────────────────────────
        "complete_task.err_no_task": "Error: No current task is set. Please call collab_set_task() first.",
        "complete_task.done":        "Task completed: [{id}] {title}",
        "complete_task.log":         "Task completed: [{id}] {title}",

        # ── collab_generate_handoff ───────────────────────────────────────
        "generate_handoff.err_ai": "Error: AI must be 'claude' or 'codex'.",
        "generate_handoff.done": (
            "Handoff generated: {from_ai} → {to_ai}\n"
            "File: {file}\n\n"
            "Open a new {app} Desktop session and say:\n"
            "'Please read HANDOFF.md and continue.'"
        ),
        "generate_handoff.app_claude": "Claude",
        "generate_handoff.app_codex":  "Codex",
        "generate_handoff.log":        "Handoff: {from_ai} → {to_ai}",

        # ── collab_checkpoint ─────────────────────────────────────────────
        "checkpoint.err_ai": "Error: AI must be 'claude' or 'codex'.",
        "checkpoint.done": (
            "Checkpoint generated: {from_ai} → {to_ai}\n"
            "Note: {msg}\n"
            "File: {file}"
        ),
        "checkpoint.log_note":    "Note: {text}",
        "checkpoint.log_handoff": "Checkpoint/Handoff: {from_ai} → {to_ai}",

        # ── collab_consult ────────────────────────────────────────────────
        "consult.result":      "[{AI} CLI Response]\n\n{response}",
        "consult.save_failed": "\n\n⚠️ Failed to save as note",
        "consult.note_label":  "[Consulted {AI}] {question}",
        "consult.log":         "Consulted {AI} CLI: {question}",

        # ── collab_discuss ────────────────────────────────────────────────
        "discuss.result_header": "[Discussion with {AI} CLI] ({rounds} rounds)",
        "discuss.round_header":  "### Round {n} — {ai}",
        "discuss.save_failed":   "\n⚠️ Failed to save as note",
        "discuss.note_label":    "[Discussion with {AI}] {topic}",
        "discuss.log":           "Discussion with {AI} CLI: {topic}",
        "discuss.followup":      "Based on the response below, please provide deeper questions or opinions:\n\n{response}",
        "discuss.history_header":"## Discussion History",

        # ── collab_setup_cli ──────────────────────────────────────────────
        "setup_cli.err_cmd": (
            "Error: command must be a 'claude' or 'codex' executable.\n"
            "Specified: {cmd} (filename: {stem})"
        ),
        "setup_cli.path_ok":      "found: {path}",
        "setup_cli.path_missing": "⚠ not found. Please verify the path.",
        "setup_cli.done": (
            "CLI configuration saved: {file}\n"
            "  AI      : {AI}\n"
            "  command : {cmd}  →  {status}\n"
            "  Example : {cmd} {args_before} \"<prompt>\" {args_after}"
        ),

        # ── collab_request_review ─────────────────────────────────────────
        "request_review.question": (
            "[Review Request]\n"
            "Scope: {scope}\n"
            "Focus: {focus}\n\n"
            "Please identify issues, improvements, and risks."
        ),
        "request_review.focus_default": "General",
        "request_review.scope_default": "Current entire implementation",
        "request_review.result":        "[{AI} CLI Review]\n\n{response}",
        "request_review.save_failed":   "\n\n⚠️ Failed to save as note",
        "request_review.note_label":    "[Review requested from {AI}] {scope}",
        "request_review.log":           "[Review requested from {AI}] {scope}",

        # ── collab_summary ────────────────────────────────────────────────
        "summary.task_none": "Not set",
        "summary.line1":     "📋 {project} | {ai} | {mode} | Session #{session}",
        "summary.line2":     "🔧 Task    : {task}",
        "summary.line3":     "⏳ Pending : {pending}  ⚠️ Issues: {issues}",
        "summary.line4":     "🕐 Updated : {ts}",

        # ── collab_search ─────────────────────────────────────────────────
        "search.not_found":  "No results found for '{query}'.",
        "search.header":     "# Search Results: '{query}' ({count} found)",
        "search.note":       "[Note]    {ts} ({ai}) {text}",
        "search.decision":   "[Decision]{ts} {title}: {content}",
        "search.issue":      "[Issue]   {emoji}[{id}][{sev}] {text}",
        "search.resolved":   "[Resolved]{emoji}[{id}][{sev}] {text}",
        "search.pending":    "[Pending] [{id}] {title}",
        "search.task":       "[Task]    [{id}] {title}",
        "search.task_done":  "[Done Task] [{id}] {title} ({ts})",
        "search.pending_done":"[Done Pending] [{id}] {title} ({ts})",

        # ── collab_timeline ───────────────────────────────────────────────
        "timeline.empty":          "(No events to display)",
        "timeline.header":         "# Timeline ({count} events)",
        "timeline.kind.note":      "📝 Note    ",
        "timeline.kind.decision":  "📌 Decision",
        "timeline.kind.issue":     "⚠️  Issue   ",
        "timeline.kind.resolved":  "✅ Resolved",
        "timeline.kind.task":      "🔧 Task    ",
        "timeline.kind.task_done": "✅ Task Done",
        "timeline.kind.pending":   "⏳ Pending ",
        "timeline.kind.pending_done":"✅ Pending Done",
        "timeline.issue_resolved_label":  "Resolved: {text}",
        "timeline.task_done_label":       "Done: {title}",
        "timeline.pending_done_label":    "Done: {title}",

        # ── collab_cleanup_sessions ───────────────────────────────────────
        "cleanup_sessions.err":          "Error: keep_per_ai must be at least 1.",
        "cleanup_sessions.no_dir":       "ai_sessions/ folder does not exist.",
        "cleanup_sessions.no_target":    "Nothing to delete (each AI has at most {keep} logs).\nCurrent log counts:\n{summary}",
        "cleanup_sessions.summary_item": "{AI}: {count}",
        "cleanup_sessions.done":         "Deleted {count} session log(s).\nRemaining logs:\n{kept}\nDeleted files:\n{files}",
        "cleanup_sessions.kept_item":    "{AI}: {count} remaining",

        # ── collab_cleanup_history ────────────────────────────────────────
        "cleanup_history.err":    "Error: keep_notes and keep_completed_tasks must each be at least 1.",
        "cleanup_history.no_need":(
            "No cleanup needed.\n"
            "  Notes: {notes} (limit {keep_notes})\n"
            "  Completed tasks: {tasks} (limit {keep_tasks})"
        ),
        "cleanup_history.dry_run":(
            "[dry_run] The following would be archived:\n"
            "  Notes: {notes} → {notes_after} remaining ({notes_trim} archived)\n"
            "  Completed tasks: {tasks} → {tasks_after} remaining ({tasks_trim} archived)\n"
            "  Destination: {archive_dest}\n"
            "Run with dry_run=False to apply."
        ),
        "cleanup_history.archive_dest":   "AI_STATE.archive.json",
        "cleanup_history.delete_dest":    "(deleted)",
        "cleanup_history.done": (
            "History cleaned up.\n"
            "  Notes: {notes} → {notes_after} ({notes_trim} {dest})\n"
            "  Completed tasks: {tasks} → {tasks_after} ({tasks_trim} {dest})"
        ),
        "cleanup_history.archive_note":   "archived to AI_STATE.archive.json",
        "cleanup_history.delete_note":    "deleted",

        # ── collab_export_state ───────────────────────────────────────────
        "export.err_path":           "Error: output_path must be an absolute path.",
        "export.err_write":          "Error: Failed to write file: {err}",
        "export.session_read_error": "(read failed)",
        "export.done": (
            "State exported.\n"
            "  Output file: {out}\n"
            "  SHA-256: {checksum}...\n"
            "  Notes: {notes}  Decisions: {decisions}  Issues: {issues}\n"
            "Restore with: collab_import_state('{out}')"
        ),

        # ── collab_import_state ───────────────────────────────────────────
        "import.err_mode":       "Error: mode must be 'validate', 'merge', or 'replace'.",
        "import.err_path":       "Error: input_path must be an absolute path.",
        "import.err_not_found":  "Error: File not found: {path}",
        "import.err_read":       "Error: Failed to read file: {err}",
        "import.err_no_checksum":"Error: No checksum found. This file may not have been created by collab_export_state.",
        "import.err_checksum_mismatch": (
            "Error: Checksum mismatch. The file may be corrupted or tampered with.\n"
            "  Stored : {stored}...\n"
            "  Computed: {calc}..."
        ),
        "import.err_backup":     "Error: Failed to create backup: {err}",
        "import.validated": (
            "Checksum verification: OK ✅\n"
            "  Exported at: {exported_at}\n"
            "  Source project: {source}\n"
            "  Notes: {notes}  Decisions: {decisions}  "
            "Issues: {issues}  Completed tasks: {tasks}\n"
            "To import, specify mode='merge' or mode='replace'."
        ),
        "import.replaced": (
            "State replaced completely. {backup}\n"
            "  Exported at: {exported_at}\n"
            "  Source project: {source}"
        ),
        "import.replaced_backup": "(Backup: {name})",
        "import.merged": (
            "State merged.\n"
            "  Notes added: {notes}  "
            "Decisions added: {decisions}  "
            "Issues added: {issues}\n"
            "  Exported at: {exported_at}"
        ),
        "import.unknown": "unknown",

        # ── collab_set_handoff_template ───────────────────────────────────
        "set_template.err": (
            "Error: preset must be one of {valid}.\n"
            "Specified: '{preset}'"
        ),
        "set_template.desc.full":    "All sections (default)",
        "set_template.desc.minimal": "Current task + latest 3 notes + known issues only",
        "set_template.desc.review":  "Full + review points section",
        "set_template.desc.debug":   "Full + debug information section",
        "set_template.done": (
            "Handoff template changed.\n"
            "  {old} → {new}\n"
            "  Description: {desc}\n"
            "Takes effect on the next collab_generate_handoff() / collab_checkpoint() call."
        ),

        # ── rendering.py (HANDOFF.md template) ───────────────────────────
        "handoff.title":           "# AI Collaborative Development — Handoff Document",
        "handoff.from_to":         "> **From:** {from_ai}　→　**To:** {to_ai}",
        "handoff.datetime_proj":   "> **Date:** {dt}　｜　**Project:** {project}",
        "handoff.mode_session":    "> **Mode:** {mode}　｜　**Session:** #{session}",
        "handoff.template_line":   "> **Template:** {template}",
        "handoff.sec_current_task":"## Current Task",
        "handoff.task_id":         "**Task ID:** `{id}`",
        "handoff.task_title":      "**Title:** <!-- USER INPUT -->{title}<!-- /USER INPUT -->",
        "handoff.task_desc":       "**Details:** <!-- USER INPUT -->{desc}<!-- /USER INPUT -->",
        "handoff.task_started":    "**Started:** {ts}  by {ai}",
        "handoff.task_files":      "**Modified Files:**",
        "handoff.task_none":       "*No task is currently set.*",
        "handoff.sec_pending":     "Pending Tasks",
        "handoff.sec_notes":       "Recent Notes (latest {n})",
        "handoff.sec_decisions":   "Key Decisions",
        "handoff.sec_issues":      "Known Issues",
        "handoff.sec_done_tasks":  "Completed Tasks (latest 5)",
        "handoff.sec_done_pending":"Completed Pending Tasks (latest 5)",
        "handoff.sec_review":      "## 📋 Review Points",
        "handoff.review_intro":    "Please review from the following perspectives:",
        "handoff.review_1":        "- Is the implementation consistent with the key decisions?",
        "handoff.review_2":        "- Are the known issues resolved?",
        "handoff.review_3":        "- Code quality, security, and performance",
        "handoff.review_4":        "- What should be verified before moving to the next phase?",
        "handoff.sec_debug":       "## 🐛 Debug Information",
        "handoff.debug_files":     "**Recently Modified Files:**",
        "handoff.debug_issues":    "**Open Issues (issue-NNN format):**",
        "handoff.debug_priority":  "**Debug Priority:** Start from known issues and focus on the modified files.",
        "handoff.empty_item":      "*None*",
        "handoff.notes_omitted":   "- *{n} earlier notes omitted*",
        "handoff.decisions_omitted":"*{n} earlier decisions omitted*",
        "handoff.sec_footer":      "## {ai} Session Start Procedure",
        "handoff.step1":           "**1. Set the project (required at every session)**",
        "handoff.step2":           "**2. Check the current state**",
        "handoff.step3":           "**3. Add notes frequently during work**",
        "handoff.step3_code":      'collab_add_note("Progress notes and observations")',
        "handoff.step4":           "**4. Generate a checkpoint before ending the session or hitting rate limits**",
        "handoff.step4_code":      'collab_checkpoint("Progress so far and next steps", "{from_ai}")',
    },
}

#endregion
