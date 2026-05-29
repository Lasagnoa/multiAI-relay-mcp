"""CLI integration helpers for calling peer AI tools."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from .i18n import t
from .state import (
    DEFAULT_CLI_CONFIG,
    _get_project_dir,
    _load_state,
)

#region CLI呼び出しユーティリティ

# CLIが標準出力に出力するノイズ行（stdin確認メッセージなど）
_NOISE_LINES: frozenset[str] = frozenset({
    "Reading additional input from stdin...",
})


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
                loaded = json.load(f)
                # JSON がオブジェクト（dict）でない場合は無視する
                if isinstance(loaded, dict):
                    for ai, cfg in loaded.items():
                        if isinstance(cfg, dict):
                            config.setdefault(ai, {}).update(cfg)
    except Exception:
        # プロジェクト未設定・ファイル破損・JSON不正 等はすべてデフォルト設定で続行
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
        return t("cli.no_config", ai=ai)

    cli_path = _resolve_cli_path(ai, cfg["command"])
    if not cli_path:
        return t("cli.not_found", AI=ai.upper(), cmd=cfg["command"])

    cmd = [cli_path] + cfg.get("args_before", []) + [prompt] + cfg.get("args_after", [])

    # プロジェクトディレクトリをCWDに設定する（Codex はgitリポジトリ内での実行が必要）
    # ContextVar override を優先する（project_path 指定時も正しいCWDで実行するため）
    try:
        effective_project = _get_project_dir()
        cwd = str(effective_project) if effective_project.exists() else None
    except RuntimeError:
        cwd = None

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
            return t("cli.no_response", AI=ai.upper(), ai=ai)
        return response
    except subprocess.TimeoutExpired:
        return t("cli.timeout", AI=ai.upper(), timeout=timeout)
    except FileNotFoundError:
        return t("cli.exec_not_found", path=cli_path)
    except Exception as e:
        return t("cli.exception", AI=ai.upper(), err=e)


def _build_consult_prompt(question: str) -> str:
    """現在のプロジェクト文脈を付加した相談プロンプトを生成する"""
    try:
        state = _load_state()
        task_title = (
            state["current_task"]["title"]
            if state.get("current_task")
            else t("consult.task_none")
        )
        lines = [
            t("consult.header"),
            t("consult.project", name=state["project_name"]),
            t("consult.task", title=task_title),
            t("consult.from_ai", ai=state["current_ai"].upper()),
        ]
        if state.get("key_decisions"):
            lines += ["", t("consult.decisions")]
            for dec in state["key_decisions"][-3:]:
                lines.append(f"- {dec['title']}: {dec['content'][:200]}")
        lines += ["", "---", "", t("consult.question", question=question)]
        return "\n".join(lines)
    except Exception:
        return question

#endregion