#!/usr/bin/env python3
"""
後方互換シム — mcp_server.py

旧設定ファイル（claude_desktop_config.json / config.toml）から
直接このファイルを指定している場合でも動作するよう維持する。
新しい実体は src/multiai_relay_mcp/server.py にある。
"""

import sys
from pathlib import Path

try:
    # パッケージとしてインストール済み（uvx / pip install -e .）の場合
    from multiai_relay_mcp.server import main
except ImportError:
    # 未インストールの場合は src/ を直接参照する
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from multiai_relay_mcp.server import main

if __name__ == "__main__":
    main()
