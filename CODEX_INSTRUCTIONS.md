# Codex セッション開始手順

このドキュメントはCodexが新しいセッションを開始するときに参照する手順書です。

---

## 書き込み先ファイルについて

このシステムが書き込むファイルは**プロジェクトフォルダ内のみ**です。
プロジェクトフォルダ外には何も書き込みません。

| ファイル | 用途 |
|---|---|
| `AI_STATE.json` | 状態ファイル（担当AI・タスク・メモ・決定事項など） |
| `HANDOFF.md` | 引き継ぎ文書 |
| `ai_sessions/` | セッションログ |
| `AI_STATE.lock` | 一時ロックファイル（処理後即削除） |
| `cli_config.json` | CLI設定（`collab_setup_cli()` を呼んだ場合のみ生成） |

---

## MCP セットアップ（初回のみ）

### Codex Desktop の設定

`~/.codex/config.toml` の末尾に追加（シングルクォート必須）:

```toml
[mcp_servers.multiai-relay-mcp]
command = 'uvx'
args = ['--index-url', 'https://test.pypi.org/simple/', '--extra-index-url', 'https://pypi.org/simple/', 'multiai-relay-mcp==1.0.21']
```

> **バージョンアップ手順:** `==1.0.11` を新バージョンに書き換え → `clear-multiai-cache.sh` 実行 → Codex Desktop 再起動 → `collab_summary()` で確認。

> `uvx` のフルパスが必要な場合は `where uvx`（Windows）または `which uvx`（Mac/Linux）で確認。
> 追加後は Codex Desktop を再起動。

---

## セッション開始時（必須）

プロジェクトルートの `HANDOFF.md` を読んでから、MCPツールでプロジェクトを設定:

### 1. プロジェクトを設定する（毎セッション必須）

```
collab_switch_project("D:\\path\\to\\project")
```

> プロジェクトパスはプロセスのメモリ内にのみ保持されます。
> 新しいセッションでは毎回呼び出してください。
> HANDOFF.md にパスが記載されているのでそれを使ってください。

### 2. 状態を確認する

```
collab_status()
```

---

## マルチプロジェクト操作（`project_path` パラメータ）

v1.0.21 以降、ほぼ全てのツールに `project_path: str = ''` パラメータが追加されました。  
`project_path` を指定すると、セッションデフォルト（`collab_switch_project()` で設定）を変えずに、  
そのツール呼び出しだけ別プロジェクトに作用させることができます。

```
# セッションデフォルト: ProjectA（collab_switch_project で設定済み）

# ProjectB の状態をチェック（A は変わらない）
collab_status(project_path="D:\\projects\\ProjectB")

# ProjectB にメモを追加（A は汚れない）
collab_add_note("B専用メモ", project_path="D:\\projects\\ProjectB")

# 次の呼び出しは A に戻る
collab_status()  # → ProjectA
```

---

## 作業中（随時）

こまめに記録するほど、次のAIへの引き継ぎ精度が上がります。

```
collab_add_note("バリデーション処理をUserService側に移動した")
collab_record_decision("DB接続方式", "ORMを使わず生SQLを採用。パフォーマンス要件のため")
collab_record_issue("テスト環境でのマイグレーションが未対応")
collab_record_file("src/models/user.py")
collab_change_mode("plan")   # plan / implement / review / debug
collab_close_pending_task("pending-001", "対応完了")
```

---

## タスク完了時

新しいタスクを開始せずに現在のタスクを完了させる:

```
collab_complete_task("実装完了。レビュー待ち")
```

## セッション終了時（必須）

レートリミット前・引き継ぎ時:

```
collab_checkpoint("ここまで完了: ○○の実装。次は△△が必要", "claude")
```

`HANDOFF.md` が生成されます。Claude Desktop で「HANDOFF.md を読んで続きをお願いします」と伝えてください。

---

## MCPツール 早見表

| ツール | 用途 |
|--------|------|
| `collab_switch_project(path, project_name)` | プロジェクトを設定・新規作成する（セッション開始時に必ず呼ぶ） |
| `collab_status(calling_ai)` | 現在の状態を確認（calling_ai を渡すと担当AI不一致を警告） |
| `collab_summary()` | 状態を4行でコンパクトに表示（ヘッダ確認用） |
| `collab_current_project()` | 現在のプロジェクトパスを表示 |
| `collab_set_task(title)` | タスクを設定 |
| `collab_add_note(message)` | メモを追加 |
| `collab_record_file(path)` | 作業ファイルを記録 |
| `collab_record_decision(title, content)` | 決定事項を記録 |
| `collab_record_issue(message)` | 問題・注意点を記録（issue-NNN IDが付く） |
| `collab_resolve_issue(issue_id, note)` | 既知の問題を解決済みにする |
| `collab_list_resolved()` | 解決済みの問題一覧を表示する |
| `collab_search(query)` | キーワードで全データを横断検索する |
| `collab_change_mode(mode)` | モードを変更 |
| `collab_add_pending_task(title)` | 保留タスクを追加 |
| `collab_close_pending_task(task_id, note)` | 完了した保留タスクを一覧から取り除く |
| `collab_complete_task(note)` | 現在のタスクを完了済みにする（新タスクなしで完了させる場合） |
| `collab_generate_handoff(to_ai)` | 引き継ぎ文書を生成して担当AIを切り替える |
| `collab_checkpoint(message, to_ai)` | メモ追加と引き継ぎを1回で実行 |
| `collab_consult(ai, question)` | 相手AIのCLIに相談する（要CLI設定） |
| `collab_discuss(ai, topic)` | 相手AIと複数ラウンド議論する（要CLI設定） |
| `collab_setup_cli(ai, command, ...)` | CLI呼び出し設定をカスタマイズ |
| `collab_cleanup_sessions(keep_per_ai)` | 古いセッションログを削除する |

---

## 仕様検討モードのワークフロー

Codexが仕様を考えてClaudeがレビューする場合:

```
# 1. 仕様検討モードに切り替え
collab_change_mode("plan")

# 2. 仕様ドキュメントを作成・記録
collab_record_file("docs/spec_feature_x.md")
collab_add_note("docs/spec_feature_x.md に機能Xの仕様を作成。Claudeのレビューを求む")

# 3. Claudeにレビューモードで引き継ぐ
collab_change_mode("review")
collab_generate_handoff("claude")
```

---

## トラブルシューティング

問題が発生したらまず診断を実行:

```
collab_doctor()
```

詳細なエラー解決手順・既知の制限・状態復旧方法 → **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**

---

## Codex Desktop での開始プロンプト

セッション開始時:

```
HANDOFF.md を読んで続きをお願いします。
```
