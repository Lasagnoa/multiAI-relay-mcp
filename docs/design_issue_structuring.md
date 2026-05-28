# 背景情報: Issue 構造化（設計はCodexが担当）

作成者: Claude（背景情報のみ。設計・実装はCodexが行う）  
ステータス: **Codex 設計待ち**

---

## 現状

`known_issues` の各エントリは以下の最小構造しか持っていない:

```json
{
  "id": "issue-001",
  "text": "ログイン後のリダイレクトが未実装",
  "added_at": "2026-05-01T10:00:00",
  "added_by": "claude"
}
```

`resolved_issues` への移行は `collab_resolve_issue()` で行われる。

---

## 解決したい課題（Whyのみ。Howは Codex が設計する）

- 問題の深刻度が分からず、どれを優先すべきか判断できない
- 問題と関連ファイルを紐付けられない
- HANDOFF.md で全問題が同列に並んで埋もれやすい
- タグ等で分類・検索ができない

---

## Codex へのお願い

以下を設計して実装してください:

1. `known_issues` エントリの構造拡張（フィールド設計はCodexに一任）
2. `collab_record_issue()` の引数拡張
3. 既存 issue を後から更新する新規ツール（名前・引数もCodexが決める）
4. `collab_status()` / HANDOFF.md の表示更新
5. 後方互換性（既存データの自動マイグレーション）

実装後は `collab_checkpoint()` でClaudeにレビューを依頼してください。
