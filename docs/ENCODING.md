# 日本語文字コード運用メモ

このMCPでは、Claude Desktop / Codex Desktop / 各CLIをまたいで日本語を扱うため、
保存形式と表示環境を分けて考える。

## 基本方針

- `AI_STATE.json`、`HANDOFF.md`、`ai_sessions/*.md`、`cli_config.json` はUTF-8で保存する。
- JSON読み込み時はUTF-8 BOM付きも受け入れる。
- MCPのstdio通信とAI CLI連携はUTF-8を前提にする。
- WindowsのPowerShellやcmdの表示コードページがcp932でも、保存ファイルまでcp932に寄せない。

## よくある文字化けパターン

### 画面だけ化ける

ファイルをUTF-8で読めるのに、PowerShellの表示だけが `繧`、`縺`、`譁` のように見えるケース。
これは多くの場合、データ破損ではなく表示側のコードページ問題。

確認:

```powershell
[Console]::OutputEncoding.WebName
chcp
```

一時的にUTF-8表示へ寄せる:

```powershell
chcp 65001
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
```

### ファイル自体に文字化けが保存されている

`collab_encoding_report()` で `文字化け疑い` が出る場合は、すでに化けた文字列が
`AI_STATE.json` や `HANDOFF.md` に保存されている可能性がある。
この場合、表示設定を直しても文字列は戻らないため、元の入力やバックアップから復元する。

## MCP側の対策

`collab_encoding_report()` を追加して、以下をまとめて確認できるようにした。

- Pythonの入出力エンコーディング
- OS既定エンコーディング
- Windows ANSI / console output code page
- `PYTHONUTF8` / `PYTHONIOENCODING` / `LANG` / `LC_ALL`
- 主要ファイルがUTF-8として読めるか
- 文字化けしやすい文字列が保存済みファイルに含まれるか

AI CLI呼び出しでは、子プロセスに以下の環境変数を渡す。

```text
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
LANG=C.UTF-8
LC_ALL=C.UTF-8
```

また、CLI出力はbytesで受け取り、UTF-8を優先してデコードする。
UTF-8として読めない場合はOS既定エンコーディング、Windowsではcp932にもフォールバックする。

## 推奨運用

1. 文字化けを見つけたら、まず `collab_encoding_report()` を実行する。
2. `UTF-8 OK` なら、ファイルではなく表示側を疑う。
3. `文字化け疑い` が出るなら、保存済みデータに化けた文字列が混入している。
4. Claude / Codex へ渡す引継ぎ資料は、MCPが生成したUTF-8の `HANDOFF.md` をそのまま使う。
5. 手動編集する場合は、エディタの保存形式をUTF-8に固定する。
