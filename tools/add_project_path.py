"""
server.py の対象 MCP ツール関数に project_path: str = '' パラメータと
try / with state_mod.project_context(project_path): / except RuntimeError ラッパーを
自動追加するスクリプト。

使い方: python tools/add_project_path.py

変換後の構造:
    def func(..., project_path: str = '') -> str:
        \"\"\"docstring\"\"\"
        try:
            with state_mod.project_context(project_path):
                # 元の body（+8スペース インデント）
        except RuntimeError as _pp_e:
            return f"エラー: {_pp_e}"
"""
import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src/multiai_relay_mcp/server.py"

# project_path を追加する対象関数
TARGETS = {
    'collab_current_project', 'collab_version', 'collab_doctor',
    'collab_status', 'collab_set_task', 'collab_add_note',
    'collab_record_decision', 'collab_record_issue', 'collab_resolve_issue',
    'collab_update_issue', 'collab_list_resolved', 'collab_record_file',
    'collab_change_mode', 'collab_add_pending_task', 'collab_close_pending_task',
    'collab_complete_task', 'collab_generate_handoff', 'collab_checkpoint',
    'collab_search', 'collab_timeline', 'collab_summary',
    'collab_cleanup_sessions', 'collab_cleanup_history',
    'collab_export_state', 'collab_import_state', 'collab_set_handoff_template',
    # issue-028: CLI系ツールを追加
    'collab_consult', 'collab_discuss', 'collab_request_review', 'collab_setup_cli',
}

source = SRC.read_text(encoding='utf-8')
tree   = ast.parse(source)
lines  = source.split('\n')

mods: list[dict] = []
for node in ast.walk(tree):
    if not isinstance(node, ast.FunctionDef):
        continue
    if node.name not in TARGETS:
        continue

    # 既に project_path がある場合はスキップ
    has_pp = any(a.arg == 'project_path' for a in node.args.args)
    if has_pp:
        print(f"  SKIP (already has project_path): {node.name}")
        continue

    # def の最初の行（0-indexed）
    def_start_idx    = node.lineno - 1
    # def の最後の行（閉じ括弧の行）: 0-indexed
    func_def_end_idx = node.body[0].lineno - 2
    # multi-line def か
    is_multi_line    = def_start_idx < func_def_end_idx

    # body の開始位置（docstring の次の行）: 0-indexed
    first_stmt = node.body[0]
    if isinstance(first_stmt, ast.Expr) and isinstance(first_stmt.value, ast.Constant):
        # docstring あり: end_lineno（1-indexed）をそのまま 0-indexed として使うと「次の行」になる
        body_first_idx = first_stmt.end_lineno
    else:
        body_first_idx = first_stmt.lineno - 1   # 0-indexed

    # 関数の最終行番号（1-indexed, AST 由来）
    func_end = node.end_lineno

    mods.append({
        'name':             node.name,
        'func_def_end_idx': func_def_end_idx,
        'is_multi_line':    is_multi_line,
        'body_first_idx':   body_first_idx,
        'func_end':         func_end,
    })

# ボトムアップで処理（行番号のズレを防ぐ）
mods.sort(key=lambda m: m['func_def_end_idx'], reverse=True)

processed: list[str] = []
for m in mods:
    name             = m['name']
    func_def_end_idx = m['func_def_end_idx']
    is_multi_line    = m['is_multi_line']
    body_first_idx   = m['body_first_idx']
    func_end         = m['func_end']

    # ─── Step 1: シグネチャに project_path: str = '' を追加 ──────────
    if is_multi_line:
        # 末尾パラメータにカンマがなければ追加
        last_param_idx = func_def_end_idx - 1
        lp = lines[last_param_idx].rstrip()
        if lp and not lp.endswith(','):
            lines[last_param_idx] = lp + ','
        # `)` 行の前に project_path 行を挿入
        lines.insert(func_def_end_idx, "    project_path: str = '',")
        inserted_def = 1
    else:
        # 単一行 def: 最後の `)` の前に project_path を挿入
        def_line  = lines[func_def_end_idx]
        close_idx = def_line.rfind(')')
        open_idx  = def_line[:close_idx].rfind('(') if close_idx != -1 else -1
        if close_idx == -1 or open_idx == -1:
            print(f"  ERROR (括弧が見つからない): {name}")
            continue
        between = def_line[open_idx + 1 : close_idx].strip()
        if between:
            lines[func_def_end_idx] = (
                def_line[:close_idx] + ", project_path: str = ''" + def_line[close_idx:]
            )
        else:
            lines[func_def_end_idx] = (
                def_line[:close_idx] + "project_path: str = ''" + def_line[close_idx:]
            )
        inserted_def = 0

    # 行番号を調整（Step 1 の挿入分）
    body_first_idx += inserted_def
    func_end       += inserted_def   # 1-indexed 最終行（調整後）

    # ─── Step 2: try: と with: を 2行挿入 ───────────────────────────
    lines.insert(body_first_idx,     '    try:')
    lines.insert(body_first_idx + 1, '        with state_mod.project_context(project_path):')

    # ─── Step 3: 元の body を +8スペース インデント ──────────────────
    # 挿入後の元 body 範囲: body_first_idx+2 ～ func_end+1（0-indexed inclusive）
    # range は exclusive なので: range(body_first_idx+2, func_end+2)
    for i in range(body_first_idx + 2, func_end + 2):
        if lines[i]:   # 空行はスキップ
            lines[i] = '        ' + lines[i]

    # ─── Step 4: 末尾に except 節を追加 ────────────────────────────
    # func_end+1 (0-indexed) = 最後の body line（+2 shift 後）
    # func_end+2 (0-indexed) = その直後（次の blank or decorator の前）
    except_idx = func_end + 2
    lines.insert(except_idx,     '    except RuntimeError as _pp_e:')
    lines.insert(except_idx + 1, '        return f"エラー: {_pp_e}"')

    processed.append(name)
    print(f"  OK: {name}")

SRC.write_text('\n'.join(lines), encoding='utf-8')
print(f"\n処理完了: {len(processed)} 関数")
print(processed)
