# トラブルシューティング / Troubleshooting

このドキュメントでは、multiAI-relay-mcp の既知制限・よくあるエラーと解決法をまとめます。

---

## 1. 既知の設計制限

### 1プロセス = 1セッションデフォルトプロジェクト

**制限の内容:**  
MCP サーバーは Desktop アプリごとに独立したプロセスとして起動されます。  
`collab_switch_project()` はプロセス内のセッションデフォルトを変更します。

| 状況 | 問題 |
|------|------|
| Claude Desktop の同じウィンドウで別プロジェクトに切り替えた | `collab_switch_project()` を呼ぶと、それ以降の全呼び出しが新プロジェクトを参照する |
| 複数チャットで同じ Desktop を共有している | どちらかの `collab_switch_project()` がプロセス全体に影響する |

**v1.0.21 以降の推奨解決策（`project_path` パラメータ）:**

ほぼ全てのツールに `project_path: str = ''` パラメータが追加されました。  
セッションデフォルトを変えずに、1回の呼び出しだけ別プロジェクトへ作用させることができます。

```
# セッションデフォルト = ProjectA のまま、ProjectB の情報を取得
collab_status(project_path="D:\\projects\\ProjectB")
collab_add_note("B専用メモ", project_path="D:\\projects\\ProjectB")
```

**それでも複数プロジェクトを並行する場合の推奨構成:**

```
プロジェクトA → Claude Desktop ウィンドウ A（または別の Desktop インスタンス）
プロジェクトB → Claude Desktop ウィンドウ B（または別の Desktop インスタンス）
```

**旧来の回避策（同一ウィンドウで切り替える場合）:**  
各ツール呼び出しの前に `collab_switch_project()` で明示的に切り替えてください。

---

## 2. AI_STATE.json が壊れたときの復旧手順

### ステップ 1: まず診断

```
collab_doctor()
```

BOM・スキーマ不一致・破損issue・ロック残留を自動検出します。

### ステップ 2: バックアップを作成

```
collab_export_state()
```

SHA-256 チェックサム付きで現在の状態をエクスポートします。

### ステップ 3: 状態を検証

```
collab_import_state("パス/to/exported.json", mode="validate")
```

インポートせずに整合性を確認できます。

### ステップ 4: 必要なら状態を置換

```
collab_import_state("パス/to/exported.json", mode="replace", backup=True)
```

`backup=True` で既存の `AI_STATE.json` を `AI_STATE_before_import_YYYYMMDD_HHMMSS.json` 形式でバックアップしてから置換します。

### ステップ 5: 再接続

```
collab_switch_project("D:\\path\\to\\project")
collab_status()
```

---

## 3. よくあるエラーと解決法

### 3-1. BOM 付き AI_STATE.json

**症状:** `collab_doctor()` で `⚠️ WARN  AI_STATE.json に UTF-8 BOM が含まれています` と表示される。

**原因:** Windows の PowerShell や メモ帳で手動編集した場合、UTF-8 BOM 付きで保存されることがある。

**対処:**  
v1.0.15 以降は BOM 付き JSON を透過的に読み込めます。  
次回 `collab_add_note()` などでファイルを書き込むと自動的に BOM なしへ正規化されます。  
即座に直したい場合は `collab_export_state()` → `collab_import_state("...", mode="replace")` で再保存してください。

---

### 3-2. AI_STATE.lock が残留している

**症状:** `collab_doctor()` で `⚠️ WARN  ロックファイルあり` と表示される。

**原因:** プロセスがクラッシュした場合、ロックファイルが残留することがある。

**対処:**  
- PID が「不在」と表示された場合 → 次回書き込み時に自動解除されます。待ってください。
- PID が「生存中」と表示された場合 → 別プロセスが書き込み中です。しばらく待ってください。
- それでも残る場合 → プロジェクトフォルダの `AI_STATE.lock` を手動削除してください。

---

### 3-3. CLI が見つからない（collab_consult / collab_discuss が動かない）

**症状:** `⚠️ WARN  CLAUDE CLI 未検出` または `⚠️ WARN  CODEX CLI 未検出`

**対処:**

```
collab_setup_cli("claude", "C:\\フルパス\\to\\claude.exe")
collab_setup_cli("codex",  "C:\\フルパス\\to\\codex.exe")
```

フルパスの確認方法:
- Windows: `where claude` / `where codex`
- Mac/Linux: `which claude` / `which codex`

---

### 3-4. uvx がバージョンを見つけられない

**症状:** `No solution found when resolving ... multiai-relay-mcp==X.X.X`

**原因:** uvx のキャッシュが古い、または Test PyPI への反映が遅延している。

**対処:**

```sh
# キャッシュをクリア
uv cache clean

# または手動でキャッシュフォルダを削除
# Windows: %LOCALAPPDATA%\uv\cache\sdists-v9\
```

その後 Claude Desktop / Codex Desktop を再起動してください。

---

### 3-5. バージョンが上がらない（再起動後も古いバージョンのまま）

**症状:** `collab_version()` で古いバージョンが返る。

**対処順:**

1. `uv cache clean` を実行（またはキャッシュを手動削除）
2. Claude Desktop / Codex Desktop を再起動
3. `collab_version()` で確認

手動でキャッシュを削除する場合: Windows は `%LOCALAPPDATA%\uv\cache\` 以下の該当フォルダを削除してください。

---

### 3-6. プロジェクトが未設定エラー

**症状:** `現在のプロジェクトが設定されていません`

**原因:** セッション開始時に `collab_switch_project()` を呼んでいない（プロジェクトパスはメモリ内にのみ保持され、再起動でリセットされる）。

**対処:**

```
collab_switch_project("D:\\path\\to\\project")
```

セッション開始時に毎回呼ぶ必要があります。

---

### 3-7. スキーマバージョン不一致

**症状:** `collab_doctor()` で `⚠️ WARN  スキーマバージョン不一致` と表示される。

**原因:** 古いバージョンで作成した AI_STATE.json を新しいバージョンで読み込んだ場合。

**対処:**  
通常は `collab_switch_project()` で再接続するだけで必須キーが自動補完されます。  
問題が続く場合は `collab_doctor()` → `collab_export_state()` → `collab_import_state(mode="validate")` の順で確認してください。

---

## 4. Git にコミットしてはいけないファイル

以下のファイルはプロジェクトフォルダ内に生成されますが、**Git にコミットすべきではありません**。

| ファイル | 理由 |
|---------|------|
| `AI_STATE.json` | AI セッション状態（個人・チーム固有の情報を含む） |
| `AI_STATE.archive.json` | アーカイブ済み状態（同上） |
| `HANDOFF.md` | 引き継ぎ文書（セッション依存） |
| `ai_sessions/*.md` | セッションログ（セッション依存） |
| `AI_STATE.lock` | 一時ロックファイル |
| `cli_config.json` | CLI パス設定（環境依存・パスが含まれる） |

`.gitignore` への追加例:

```
# multiAI-relay-mcp
AI_STATE.json
AI_STATE.archive.json
AI_STATE.lock
AI_STATE_backup_*.json
AI_STATE_before_import_*.json
HANDOFF.md
ai_sessions/
cli_config.json
```

---

## 5. collab_doctor の使い方

```
# 標準診断（すべてのチェックを実行）
collab_doctor()

# JSON 形式で取得（スクリプトや自動化向け）
collab_doctor(output="json")

# CLI チェックをスキップして高速診断
collab_doctor(check_cli=False, check_ai_call=False)

# 特定の項目だけ診断
collab_doctor(check_encoding=True, check_schema=True, check_issues=True,
              check_cli=False, check_state=False, check_lock=False, check_recovery=False)
```

---

*詳細は [README.md](../README.md) を参照してください。*
