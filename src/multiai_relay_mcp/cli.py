"""CLI integration helpers for calling peer AI tools."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from .state import (
    DEFAULT_CLI_CONFIG,
    _get_project_dir,
    _load_state,
    get_current_project_raw,
)

#region CLI呼び出しユーティリティ

def _cli_config_file() -> Path:
    """CLI設定ファイルのパスを返す（プロジェクトフォルダ内）"""
    return _get_project_dir() / "cli_config.json"


def _load_cli_config() -> dict:
    """CLI設定を読み込む（プロジェクトフォルダ内の cli_config.json を参照）"""
    config = {k: dict(v) for k, v in DEFAULT_CLI_CONFIG.items()}
    try:
        cfg_file = _cli_config_file()
        if cfg_file.exists():
            with open(cfg_file, "r", encoding="utf-8-sig") as f:
                for ai, cfg in json.load(f).items():
                    config.setdefault(ai, {}).update(cfg)
    except RuntimeError:
        # プロジェクト未設定の場合はデフォルト設定を返す
        pass
    return config


def _resolve_cli_path(ai: str, command: str) -> str | None:
    """CLIの実行ファイルパスを解決する"""
    found = shutil.which(command)
    if found:
        return found
    if ai == "codex":
        env_path = os.environ.get("CODEX_CLI_PATH")
        if env_path and Path(env_path).exists():
            return env_path
        codex_bin = Path.home() / "AppData" / "Local" / "OpenAI" / "Codex" / "bin"
        if codex_bin.exists():
            matches = sorted(codex_bin.rglob("codex.exe"), reverse=True)
            if matches:
                return str(matches[0])
    return None


def _call_ai_cli(ai: str, prompt: str, timeout: int = 180) -> str:
    """指定 AI の CLI をサブプロセスとして呼び出し、回答テキストを返す"""
    config = _load_cli_config()
    cfg = config.get(ai)
    if not cfg:
        return f"エラー: '{ai}' のCLI設定がありません。"

    cli_path = _resolve_cli_path(ai, cfg["command"])
    if not cli_path:
        return (
            f"エラー: {ai.upper()} CLI が見つかりません。\n"
            f"・'{cfg['command']}' が PATH に存在するか確認してください。\n"
            f"・または collab_setup_cli() で設定してください。"
        )

    cmd = [cli_path] + cfg.get("args_before", []) + [prompt] + cfg.get("args_after", [])

    # プロジェクトディレクトリをCWDに設定する（Codex はgitリポジトリ内での実行が必要）
    current_project = get_current_project_raw()
    cwd = str(current_project) if current_project and current_project.exists() else None

    # CLIが標準出力に出力するノイズ行（stdin確認メッセージなど）
    _NOISE_LINES: set[str] = {
        "Reading additional input from stdin...",
    }

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            stdin=subprocess.DEVNULL,  # MCP stdio パイプが stdin に流れ込んでブロックするのを防ぐ
            cwd=cwd,  # プロジェクトディレクトリで実行（git repo チェック対応）
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        # ノイズ行を除去してから応答テキストを構築
        cleaned_lines = [
            line for line in result.stdout.splitlines()
            if line.strip() not in _NOISE_LINES
        ]
        response = "\n".join(cleaned_lines).strip() or result.stderr.strip()
        if not response:
            # 応答が空の場合は対話TUIが起動した可能性がある
            return (
                f"（{ai.upper()} CLI から応答がありませんでした）\n"
                f"Codex CLI が対話モードで起動している可能性があります。\n"
                f"collab_setup_cli('{ai}', ...) で非対話引数を設定してください。"
            )
        return response
    except subprocess.TimeoutExpired:
        return f"エラー: {ai.upper()} CLI が {timeout}秒 以内に応答しませんでした。"
    except FileNotFoundError:
        return f"エラー: 実行ファイルが見つかりません: {cli_path}"
    except Exception as e:
        return f"エラー: {ai.upper()} CLI 呼び出し中に問題が発生しました: {e}"


def _build_consult_prompt(question: str) -> str:
    """現在のプロジェクト文脈を付加した相談プロンプトを生成する"""
    try:
        state = _load_state()
        task_title = state["current_task"]["title"] if state.get("current_task") else "未設定"
        lines = [
            "[AI協働開発システムからの相談]",
            f"プロジェクト : {state['project_name']}",
            f"現在のタスク : {task_title}",
            f"相談元の AI  : {state['current_ai'].upper()}",
        ]
        if state.get("key_decisions"):
            lines += ["", "## 既存の設計決定事項（参考）"]
            for dec in state["key_decisions"][-3:]:
                lines.append(f"- {dec['title']}: {dec['content'][:200]}")
        lines += ["", "---", "", f"## 相談内容\n{question}"]
        return "\n".join(lines)
    except Exception:
        return question

#endregion