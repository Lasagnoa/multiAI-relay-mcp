# multiAI-relay-mcp

**日本語** | [English](#english)

Claude Desktop と Codex Desktop が MCP を通じて状態を共有し、セッションをまたいで作業を引き継げる協調開発システムです。

---

## 特徴

- 🔁 **セッションリレー** — レートリミットや作業交代のタイミングで、担当 AI を切り替えながら作業を継続
- 📝 **永続的な共有状態** — メモ・決定事項・タスク・既知の問題を `AI_STATE.json` に記録し、セッションをまたいで保持
- 🔍 **横断検索** — メモ・決定・問題・タスクをキーワードで一括検索
- 🔒 **安全な並行書き込み** — ファイルロック＋アトミック書き込みで、Claude/Codex が同時に更新しても状態が壊れない
- 📦 **プロジェクトフォルダ外への書き込みゼロ** — ホームディレクトリを汚さない

> **設計上の制約:** MCP サーバーは Desktop アプリごとに独立したプロセスとして起動されます。  
> **1 プロセス = 1 アクティブプロジェクト** の前提です。複数プロジェクトを並行して扱う場合は、それぞれ別の Desktop インスタンス（または別の MCP サーバー設定）を使用してください。  
> 詳細・復旧手順 → [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

---

## セットアップ

### 前提条件

- [uv](https://docs.astral.sh/uv/) がインストール済みであること
- Claude Desktop または Codex Desktop

### 1. Claude Desktop の設定

`%APPDATA%\Claude\claude_desktop_config.json` の `mcpServers` に追加:

```json
"multiai-relay-mcp": {
  "command": "uvx",
  "args": ["--index-url", "https://test.pypi.org/simple/", "--extra-index-url", "https://pypi.org/simple/", "multiai-relay-mcp==1.0.14"]
}
```

> `uvx` のフルパスが必要な場合は `where uvx`（Windows）または `which uvx`（Mac/Linux）で確認。
> 追加後は Claude Desktop を再起動。

### 2. Codex Desktop の設定

`~/.codex/config.toml` の末尾に追加:

```toml
[mcp_servers.multiai-relay-mcp]
command = 'uvx'
args = ['--index-url', 'https://test.pypi.org/simple/', '--extra-index-url', 'https://pypi.org/simple/', 'multiai-relay-mcp==1.0.14']
```

> 追加後は Codex Desktop を再起動。

> **バージョンアップ手順:** 設定の `==1.0.11` を新バージョンに書き換え → `clear-multiai-cache.sh` 実行（またはキャッシュ手動削除）→ Desktop 再起動 → `collab_summary()` でバージョン確認。

---

## 使い方

### セッション開始時（毎回必須）

```
collab_switch_project("D:\\path\\to\\your-project")
collab_status()
```

### 作業中

```
collab_add_note("気づいたことや進捗")
collab_record_decision("採用技術", "FastAPI を選択。非同期処理が必要なため")
collab_record_issue("ログイン後のリダイレクトが未実装")
collab_set_task("認証機能の実装")
collab_record_file("src/auth.py")
```

### タスク終了時

```
collab_complete_task("実装完了。レビュー済み")
```

### セッション終了・引き継ぎ時

```
collab_checkpoint("認証の実装完了。次はテストを書く必要あり", "codex")
```

`HANDOFF.md` が生成されます。Codex Desktop の新しいセッションで「HANDOFF.md を読んで続きをお願いします」と伝えてください。

---

## MCPツール一覧

| ツール | 用途 |
|--------|------|
| `collab_switch_project(path, project_name?)` | プロジェクトを設定・新規作成（毎セッション必須） |
| `collab_status(calling_ai?)` | 状態を詳細表示（担当AI不一致を警告） |
| `collab_summary()` | 状態を4行でコンパクトに表示 |
| `collab_set_task(title)` | 現在タスクを設定 |
| `collab_add_note(message)` | メモを追加 |
| `collab_record_decision(title, content)` | 決定事項を記録 |
| `collab_record_issue(message, severity?, category?, tags?, related_files?)` | 問題・注意点を記録（issue-NNN ID 付き、深刻度P0〜P3） |
| `collab_update_issue(issue_id, severity?, category?, tags?, add_tags?, remove_tags?, ...)` | 既存 issue のメタデータを更新 |
| `collab_resolve_issue(issue_id, note?)` | 問題を解決済みにする |
| `collab_list_resolved()` | 解決済み問題の一覧を表示 |
| `collab_search(query)` | キーワードで全データを横断検索 |
| `collab_record_file(path)` | 変更ファイルを記録 |
| `collab_change_mode(mode)` | モード変更（plan / implement / review / debug） |
| `collab_add_pending_task(title)` | 保留タスクを追加 |
| `collab_close_pending_task(task_id, note?)` | 保留タスクを完了扱いに |
| `collab_complete_task(note?)` | 現在のタスクを完了済みにする（新タスクなしで完了させる場合） |
| `collab_generate_handoff(to_ai, dry_run?)` | 引き継ぎ文書を生成して担当AIを切り替え（dry_run でプレビューのみ） |
| `collab_checkpoint(message, to_ai?, dry_run?)` | メモ追加と引き継ぎを一度に実行（dry_run でプレビューのみ） |
| `collab_consult(ai, question)` | 相手AIのCLIに相談（要CLI設定） |
| `collab_discuss(ai, topic)` | 相手AIと複数ラウンド議論（要CLI設定） |
| `collab_request_review(ai, focus?, scope?)` | 相手AIにコードレビューを依頼（consult の薄いラッパー） |
| `collab_setup_cli(ai, command, ...)` | CLIパス・引数設定をカスタマイズ |
| `collab_version()` | MCPサーバーと実行環境のバージョン情報を表示 |
| `collab_doctor(check_cli?, check_state?, ...)` | MCPサーバーと環境の健全性を診断（OK/WARN/ERR） |
| `collab_timeline(limit?, since?, actor?, event_type?)` | プロジェクトの更新イベントを時系列で表示 |
| `collab_cleanup_sessions(keep_per_ai?)` | 古いセッションログを削除 |
| `collab_cleanup_history(keep_notes?, keep_completed_tasks?, archive?, dry_run?)` | 古いメモ・完了タスクを整理してアーカイブ |
| `collab_export_state(output_path?, include_sessions?, redact_cli_config?)` | 状態をSHA-256チェックサム付きJSONでエクスポート |
| `collab_import_state(input_path, mode?, backup?)` | エクスポートJSONから状態をインポート（validate/merge/replace） |
| `collab_set_handoff_template(preset)` | HANDOFF.md テンプレートを切り替え（full/minimal/review/debug） |
| `collab_current_project()` | 現在のプロジェクトパスを表示 |

---

## プロジェクトフォルダ内に生成されるファイル

| ファイル | 用途 |
|----------|------|
| `AI_STATE.json` | 共有状態（タスク・メモ・決定事項など） |
| `AI_STATE.archive.json` | アーカイブ済みの古いメモ・完了タスク（collab_cleanup_history で生成） |
| `HANDOFF.md` | 引き継ぎ文書 |
| `ai_sessions/` | セッションログ |
| `AI_STATE.lock` | 一時ロックファイル（処理後即削除） |
| `cli_config.json` | CLI設定（`collab_setup_cli()` 呼び出し時のみ生成） |

> これらはプロジェクトフォルダ内にのみ書き込まれます。ホームディレクトリへの書き込みは一切ありません。

---

## ライセンス

MIT License — 詳細は [LICENSE](LICENSE) を参照。

---

<a name="english"></a>

# multiAI-relay-mcp

[日本語](#) | **English**

A collaborative development system that lets Claude Desktop and Codex Desktop share state via MCP and hand off work across sessions.

---

## Features

- 🔁 **Session Relay** — Switch between AI assistants at rate limits or handoff points, keeping work continuous
- 📝 **Persistent Shared State** — Notes, decisions, tasks, and issues are stored in `AI_STATE.json` and survive across sessions
- 🔍 **Cross-search** — Search notes, decisions, issues, and tasks by keyword in one call
- 🔒 **Safe Concurrent Writes** — File locking + atomic writes prevent state corruption when Claude and Codex update simultaneously
- 📦 **Zero writes outside project folder** — No home directory pollution

> **Design constraint:** The MCP server runs as a separate process per Desktop app.  
> **1 process = 1 active project.** To work on multiple projects in parallel, use separate Desktop instances or separate MCP server configurations.

---

## Setup

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) installed
- Claude Desktop and/or Codex Desktop

### 1. Claude Desktop configuration

Add to `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) under `mcpServers`:

```json
"multiai-relay-mcp": {
  "command": "uvx",
  "args": ["--index-url", "https://test.pypi.org/simple/", "--extra-index-url", "https://pypi.org/simple/", "multiai-relay-mcp==1.0.14"]
}
```

> Use `where uvx` (Windows) or `which uvx` (Mac/Linux) to find the full path if needed.
> Restart Claude Desktop after editing.

### 2. Codex Desktop configuration

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.multiai-relay-mcp]
command = 'uvx'
args = ['--index-url', 'https://test.pypi.org/simple/', '--extra-index-url', 'https://pypi.org/simple/', 'multiai-relay-mcp==1.0.14']
```

> Restart Codex Desktop after editing.

> **Upgrading:** Change `==1.0.11` to the new version in your config → run `clear-multiai-cache.sh` (or delete cached `.rkyv` files manually) → restart Desktop → confirm with `collab_summary()`.

---

## Usage

### Start of every session

```
collab_switch_project("/path/to/your-project")
collab_status()
```

### During work

```
collab_add_note("Finished auth module, moving to tests")
collab_record_decision("Framework", "Using FastAPI — async support required")
collab_record_issue("Redirect after login not yet implemented")
collab_set_task("Write auth tests")
collab_record_file("src/auth.py")
```

### Completing a task

```
collab_complete_task("Implementation done, reviewed")
```

### End of session / handoff

```
collab_checkpoint("Auth done. Next: write tests", "codex")
```

A `HANDOFF.md` is generated. In a new Codex Desktop session, say: "Please read HANDOFF.md and continue."

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `collab_switch_project(path, project_name?)` | Set or create a project (required every session) |
| `collab_status(calling_ai?)` | Show full status (warns on AI mismatch) |
| `collab_summary()` | Show compact 4-line status |
| `collab_set_task(title)` | Set current task |
| `collab_add_note(message)` | Add a note |
| `collab_record_decision(title, content)` | Record a decision |
| `collab_record_issue(message, severity?, category?, tags?, related_files?)` | Record an issue (P0–P3 severity, tags, related files) |
| `collab_update_issue(issue_id, severity?, category?, tags?, add_tags?, remove_tags?, ...)` | Update existing issue metadata |
| `collab_resolve_issue(issue_id, note?)` | Mark issue as resolved |
| `collab_list_resolved()` | List resolved issues |
| `collab_search(query)` | Cross-search all data by keyword |
| `collab_record_file(path)` | Record a modified file |
| `collab_change_mode(mode)` | Switch mode (plan / implement / review / debug) |
| `collab_add_pending_task(title)` | Add a pending task |
| `collab_close_pending_task(task_id, note?)` | Mark pending task as done |
| `collab_complete_task(note?)` | Mark current task as done (without starting a new one) |
| `collab_generate_handoff(to_ai, dry_run?)` | Generate handoff doc and switch AI (dry_run for preview only) |
| `collab_checkpoint(message, to_ai?, dry_run?)` | Add note + generate handoff in one call (dry_run for preview only) |
| `collab_consult(ai, question)` | Consult the other AI's CLI (requires CLI setup) |
| `collab_discuss(ai, topic)` | Multi-round discussion with the other AI's CLI |
| `collab_request_review(ai, focus?, scope?)` | Request a code/design review from the other AI |
| `collab_setup_cli(ai, command, ...)` | Customize CLI path and arguments |
| `collab_version()` | Show MCP server and runtime version info |
| `collab_doctor(check_cli?, check_state?, ...)` | Diagnose MCP server and environment health (OK/WARN/ERR) |
| `collab_timeline(limit?, since?, actor?, event_type?)` | Show project events in chronological order |
| `collab_cleanup_sessions(keep_per_ai?)` | Delete old session logs |
| `collab_cleanup_history(keep_notes?, keep_completed_tasks?, archive?, dry_run?)` | Archive old notes and completed tasks |
| `collab_export_state(output_path?, include_sessions?, redact_cli_config?)` | Export state as SHA-256-checksummed JSON |
| `collab_import_state(input_path, mode?, backup?)` | Import exported state (validate/merge/replace) |
| `collab_set_handoff_template(preset)` | Switch HANDOFF.md template (full/minimal/review/debug) |
| `collab_current_project()` | Show current project path |

---

## Files generated in your project folder

| File | Purpose |
|------|---------|
| `AI_STATE.json` | Shared state (tasks, notes, decisions, etc.) |
| `AI_STATE.archive.json` | Archived old notes/tasks (created by `collab_cleanup_history()`) |
| `HANDOFF.md` | Handoff document |
| `ai_sessions/` | Session logs |
| `AI_STATE.lock` | Temporary lock file (auto-deleted after use) |
| `cli_config.json` | CLI config (created only when `collab_setup_cli()` is called) |

> All writes are contained within your project folder. Nothing is written to your home directory.

---

## Troubleshooting / Known Limitations

問題が発生したら、まず `collab_doctor()` を実行してください。

```
collab_doctor()
```

よくあるエラー・復旧手順の詳細は **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** を参照してください。

---

## License

MIT License — see [LICENSE](LICENSE) for details.
