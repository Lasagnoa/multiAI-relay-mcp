# multiAI-relay-mcp

**日本語** | [English](#english)

Claude Desktop と Codex Desktop が MCP を通じて状態を共有し、セッションをまたいで作業を引き継げる協調開発システムです。

---

## 特徴

- 🔁 **セッションリレー** — レートリミットや作業交代のタイミングで、担当 AI を切り替えながら作業を継続
- 📝 **永続的な共有状態** — メモ・決定事項・タスク・既知の問題を `AI_STATE.json` に記録し、セッションをまたいで保持
- 🔍 **横断検索** — メモ・決定・問題・タスクをキーワードで一括検索
- 🔒 **安全な並行書き込み** — ファイルロック＋アトミック書き込みで、Claude/Codex が同時に更新しても状態が壊れない
- 🌐 **多言語対応 (i18n)** — `MULTIAI_LANG=en` で全ツールの出力・HANDOFF.md を英語に切り替え（デフォルトは日本語）
- 🌿 **Git 統合** — `collab_status` / `collab_switch_project` でブランチ名と最新コミットを自動表示
- 📦 **プロジェクトフォルダ外への書き込みゼロ** — ホームディレクトリを汚さない

> **設計上の制約:** MCP サーバーは Desktop アプリごとに独立したプロセスとして起動されます。  
> **1 プロセス = 1 セッションデフォルトプロジェクト** です。`collab_switch_project()` でセッション既定を設定し、個別ツール呼び出しでは `project_path=` で別プロジェクトを一時指定できます。  
> 詳細・復旧手順 → リポジトリ内 `docs/TROUBLESHOOTING.md` を参照

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
  "args": ["--index-url", "https://test.pypi.org/simple/", "--extra-index-url", "https://pypi.org/simple/", "multiai-relay-mcp==1.1.1"]
}
```

> `uvx` のフルパスが必要な場合は `where uvx`（Windows）または `which uvx`（Mac/Linux）で確認。  
> 追加後は Claude Desktop を再起動。

### 2. Codex Desktop の設定

`~/.codex/config.toml` の末尾に追加:

```toml
[mcp_servers.multiai-relay-mcp]
command = 'uvx'
args = ['--index-url', 'https://test.pypi.org/simple/', '--extra-index-url', 'https://pypi.org/simple/', 'multiai-relay-mcp==1.1.1']
```

> 追加後は Codex Desktop を再起動。

### バージョンアップ手順

1. 両設定ファイルのバージョン番号を新バージョンに書き換え
2. キャッシュをクリア: `uv cache clean multiai-relay-mcp --force`
3. Desktop を再起動
4. `collab_version()` でバージョンを確認

### 英語モードを有効にする（オプション）

環境変数 `MULTIAI_LANG=en` を設定すると、全ツールの返答・HANDOFF.md の見出しが英語になります。

**Claude Desktop の場合** — 設定に `env` を追加:

```json
"multiai-relay-mcp": {
  "command": "uvx",
  "args": ["--index-url", "https://test.pypi.org/simple/", "--extra-index-url", "https://pypi.org/simple/", "multiai-relay-mcp==1.1.1"],
  "env": { "MULTIAI_LANG": "en" }
}
```

**Codex Desktop の場合** — `[mcp_servers.multiai-relay-mcp.env]` セクションを追加:

```toml
[mcp_servers.multiai-relay-mcp.env]
MULTIAI_LANG = "en"
```

---

## 使い方

### セッション開始時（毎回必須）

```
collab_switch_project("D:\\path\\to\\your-project")
collab_status()
```

`collab_switch_project()` は接続後に現在のタスク・問題件数・Git ブランチを自動表示します。

### 作業中

```
collab_add_note("気づいたことや進捗")
collab_record_decision("採用技術", "FastAPI を選択。非同期処理が必要なため")
collab_record_issue("ログイン後のリダイレクトが未実装")
collab_set_task("認証機能の実装")
collab_record_file("src/auth.py")
```

> **メモの蓄積について:** メモが 200 件を超えると整理を促すヒントが表示され、300 件を超えると警告が出ます。  
> `collab_cleanup_history()` で古いメモをアーカイブできます。

### マルチプロジェクト操作（`project_path` パラメータ）

ほぼ全てのツールに `project_path: str = ''` パラメータが追加されています。  
`project_path` を指定すると、**セッションデフォルトを変えずに**、そのツール呼び出しだけ別プロジェクトに作用します。

```
# セッションデフォルト: ProjectA
collab_switch_project("D:\\projects\\ProjectA")

# ProjectB の状態を確認（A は変わらない）
collab_status(project_path="D:\\projects\\ProjectB")

# ProjectB にメモを追加（A は汚れない）
collab_add_note("B専用メモ", project_path="D:\\projects\\ProjectB")

# 次のツール呼び出しは A に戻る
collab_status()  # → ProjectA を表示
```

### タスク終了時

```
collab_complete_task()
```

### セッション終了・引き継ぎ時

```
collab_checkpoint("認証の実装完了。次はテストを書く必要あり", "codex")
```

`HANDOFF.md` が生成されます。Codex Desktop の新しいセッションで「HANDOFF.md を読んで続きをお願いします」と伝えてください。

---

## MCPツール一覧

### プロジェクト管理

| ツール | 用途 |
|--------|------|
| `collab_switch_project(path, project_name?)` | プロジェクトを設定・新規作成（毎セッション必須） |
| `collab_current_project()` | 現在のプロジェクトパスを表示 |
| `collab_list_projects()` | 最近使用したプロジェクト一覧を表示 |
| `collab_status(calling_ai?)` | 状態を詳細表示（Git ブランチ・担当AI不一致を警告） |
| `collab_summary()` | 状態を4行でコンパクトに表示 |

### タスク・作業記録

| ツール | 用途 |
|--------|------|
| `collab_set_task(title, description?)` | 現在タスクを設定 |
| `collab_complete_task()` | 現在のタスクを完了済みにする |
| `collab_add_note(message)` | メモを追加（200件・300件でソフトキャップ警告） |
| `collab_record_decision(title, content)` | 決定事項を記録 |
| `collab_record_file(path)` | 変更ファイルを記録 |
| `collab_change_mode(mode)` | モード変更（plan / implement / review / debug） |
| `collab_add_pending_task(title, description?)` | 保留タスクを追加 |
| `collab_close_pending_task(task_id)` | 保留タスクを完了扱いに |

### 問題管理

| ツール | 用途 |
|--------|------|
| `collab_record_issue(message, severity?, category?, tags?, related_files?)` | 問題を記録（深刻度P0〜P3、issue-NNN ID 付き） |
| `collab_update_issue(issue_id, ...)` | 既存 issue のメタデータを更新（タグ増減も可） |
| `collab_resolve_issue(issue_id, note?)` | 問題を解決済みにする |
| `collab_list_resolved()` | 解決済み問題の一覧を表示 |

### 検索・履歴

| ツール | 用途 |
|--------|------|
| `collab_search(query)` | キーワードで全データを横断検索 |
| `collab_timeline(limit?, since?, actor?, event_type?)` | プロジェクトの更新イベントを時系列で表示 |

### 引き継ぎ

| ツール | 用途 |
|--------|------|
| `collab_generate_handoff(to_ai, dry_run?)` | 引き継ぎ文書を生成して担当AIを切り替え（dry_run でプレビューのみ） |
| `collab_checkpoint(message, to_ai?, dry_run?)` | メモ追加と引き継ぎを一度に実行 |
| `collab_set_handoff_template(preset)` | HANDOFF.md テンプレートを切り替え（full / minimal / review / debug） |

### AI連携（CLI 要設定）

| ツール | 用途 |
|--------|------|
| `collab_consult(ai, question)` | 相手AIのCLIに相談 |
| `collab_discuss(ai, topic)` | 相手AIと複数ラウンド議論 |
| `collab_request_review(ai, focus?, scope?)` | 相手AIにコードレビューを依頼 |
| `collab_setup_cli(ai, command, ...)` | CLIパス・引数設定をカスタマイズ |

### メンテナンス

| ツール | 用途 |
|--------|------|
| `collab_version()` | バージョン情報を表示 |
| `collab_doctor()` | 環境の健全性を診断（OK/WARN/ERR） |
| `collab_cleanup_sessions(keep_per_ai?)` | 古いセッションログを削除 |
| `collab_cleanup_history(keep_notes?, keep_completed_tasks?, archive?, dry_run?)` | 古いメモ・完了タスクをアーカイブ |
| `collab_export_state(output_path)` | 状態を SHA-256 チェックサム付き JSON でエクスポート |
| `collab_import_state(input_path, mode?)` | エクスポート JSON から状態をインポート（validate/merge/replace） |

---

## プロジェクトフォルダ内に生成されるファイル

| ファイル | 用途 |
|----------|------|
| `AI_STATE.json` | 共有状態（タスク・メモ・決定事項など） |
| `AI_STATE.archive.json` | アーカイブ済みの古いメモ・完了タスク（`collab_cleanup_history` で生成） |
| `HANDOFF.md` | 引き継ぎ文書 |
| `ai_sessions/` | セッションログ |
| `AI_STATE.lock` | 一時ロックファイル（処理後即削除） |
| `cli_config.json` | CLI設定（`collab_setup_cli()` 呼び出し時のみ生成） |

> これらはプロジェクトフォルダ内にのみ書き込まれます。ホームディレクトリへの書き込みは一切ありません。

---

## ライセンス

MIT License

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
- 🌐 **i18n Support** — Set `MULTIAI_LANG=en` to switch all tool output and HANDOFF.md to English (default: Japanese)
- 🌿 **Git Integration** — `collab_status` / `collab_switch_project` automatically show branch name and latest commit
- 📦 **Zero writes outside project folder** — No home directory pollution

> **Design constraint:** The MCP server runs as a separate process per Desktop app.  
> **1 process = 1 session-default project.** Use `collab_switch_project()` to set the session default. For individual calls targeting a different project, pass `project_path=` to any tool — the session default stays unchanged.

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
  "args": ["--index-url", "https://test.pypi.org/simple/", "--extra-index-url", "https://pypi.org/simple/", "multiai-relay-mcp==1.1.1"]
}
```

> Use `where uvx` (Windows) or `which uvx` (Mac/Linux) to find the full path if needed.  
> Restart Claude Desktop after editing.

### 2. Codex Desktop configuration

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.multiai-relay-mcp]
command = 'uvx'
args = ['--index-url', 'https://test.pypi.org/simple/', '--extra-index-url', 'https://pypi.org/simple/', 'multiai-relay-mcp==1.1.1']
```

> Restart Codex Desktop after editing.

### Upgrading

1. Change the version number in both config files
2. Clear the cache: `uv cache clean multiai-relay-mcp --force`
3. Restart Desktop apps
4. Confirm with `collab_version()`

### Enabling English mode (optional)

Set `MULTIAI_LANG=en` to switch all tool responses and HANDOFF.md headings to English.

**Claude Desktop** — add `env` to your config:

```json
"multiai-relay-mcp": {
  "command": "uvx",
  "args": ["--index-url", "https://test.pypi.org/simple/", "--extra-index-url", "https://pypi.org/simple/", "multiai-relay-mcp==1.1.1"],
  "env": { "MULTIAI_LANG": "en" }
}
```

**Codex Desktop** — add an env section:

```toml
[mcp_servers.multiai-relay-mcp.env]
MULTIAI_LANG = "en"
```

---

## Usage

### Start of every session

```
collab_switch_project("/path/to/your-project")
collab_status()
```

`collab_switch_project()` automatically displays current task, issue count, and Git branch after connecting.

### During work

```
collab_add_note("Finished auth module, moving to tests")
collab_record_decision("Framework", "Using FastAPI — async support required")
collab_record_issue("Redirect after login not yet implemented")
collab_set_task("Write auth tests")
collab_record_file("src/auth.py")
```

> **Note accumulation:** A tip appears when notes exceed 200, and a warning at 300.  
> Use `collab_cleanup_history()` to archive old notes.

### Multi-project operations (`project_path` parameter)

Almost all tools accept an optional `project_path: str = ''` parameter.  
When provided, that single call operates on the specified project **without changing the session default**.

```
# Session default: ProjectA
collab_switch_project("/projects/ProjectA")

# Check ProjectB status (A is unchanged)
collab_status(project_path="/projects/ProjectB")

# Add a note to ProjectB (A is not affected)
collab_add_note("B-specific note", project_path="/projects/ProjectB")

# Next call goes back to A
collab_status()  # → shows ProjectA
```

### Completing a task

```
collab_complete_task()
```

### End of session / handoff

```
collab_checkpoint("Auth done. Next: write tests", "codex")
```

A `HANDOFF.md` is generated. In a new Codex Desktop session, say: "Please read HANDOFF.md and continue."

---

## MCP Tools

### Project management

| Tool | Description |
|------|-------------|
| `collab_switch_project(path, project_name?)` | Set or create a project (required every session) |
| `collab_current_project()` | Show current project path |
| `collab_list_projects()` | List recently used projects |
| `collab_status(calling_ai?)` | Show full status (Git branch, AI mismatch warning) |
| `collab_summary()` | Show compact 4-line status |

### Tasks & work

| Tool | Description |
|------|-------------|
| `collab_set_task(title, description?)` | Set current task |
| `collab_complete_task()` | Mark current task as done |
| `collab_add_note(message)` | Add a note (soft-cap warning at 200/300 notes) |
| `collab_record_decision(title, content)` | Record a decision |
| `collab_record_file(path)` | Record a modified file |
| `collab_change_mode(mode)` | Switch mode (plan / implement / review / debug) |
| `collab_add_pending_task(title, description?)` | Add a pending task |
| `collab_close_pending_task(task_id)` | Mark pending task as done |

### Issue tracking

| Tool | Description |
|------|-------------|
| `collab_record_issue(message, severity?, category?, tags?, related_files?)` | Record an issue (P0–P3 severity, issue-NNN ID) |
| `collab_update_issue(issue_id, ...)` | Update issue metadata (incremental tag edits supported) |
| `collab_resolve_issue(issue_id, note?)` | Mark issue as resolved |
| `collab_list_resolved()` | List resolved issues |

### Search & history

| Tool | Description |
|------|-------------|
| `collab_search(query)` | Cross-search all data by keyword |
| `collab_timeline(limit?, since?, actor?, event_type?)` | Show project events in chronological order |

### Handoff

| Tool | Description |
|------|-------------|
| `collab_generate_handoff(to_ai, dry_run?)` | Generate handoff doc and switch AI (dry_run for preview) |
| `collab_checkpoint(message, to_ai?, dry_run?)` | Add note + generate handoff in one call |
| `collab_set_handoff_template(preset)` | Switch HANDOFF.md template (full / minimal / review / debug) |

### AI collaboration (requires CLI setup)

| Tool | Description |
|------|-------------|
| `collab_consult(ai, question)` | Consult the other AI's CLI |
| `collab_discuss(ai, topic)` | Multi-round discussion with the other AI's CLI |
| `collab_request_review(ai, focus?, scope?)` | Request a code review from the other AI |
| `collab_setup_cli(ai, command, ...)` | Customize CLI path and arguments |

### Maintenance

| Tool | Description |
|------|-------------|
| `collab_version()` | Show version info |
| `collab_doctor()` | Diagnose environment health (OK/WARN/ERR) |
| `collab_cleanup_sessions(keep_per_ai?)` | Delete old session logs |
| `collab_cleanup_history(keep_notes?, keep_completed_tasks?, archive?, dry_run?)` | Archive old notes and completed tasks |
| `collab_export_state(output_path)` | Export state as SHA-256-checksummed JSON |
| `collab_import_state(input_path, mode?)` | Import exported state (validate/merge/replace) |

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

## Troubleshooting

Run `collab_doctor()` first if something seems wrong:

```
collab_doctor()
```

For common errors and recovery steps, see `docs/TROUBLESHOOTING.md` in the repository.

---

## License

MIT License
