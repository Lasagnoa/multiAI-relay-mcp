import json
import tempfile
import unittest
from pathlib import Path

from multiai_relay_mcp.server import (
    collab_add_note,
    collab_record_issue,
    collab_setup_cli,
    collab_switch_project,
    collab_update_issue,
)


class ToolValidationTests(unittest.TestCase):
    def setUp(self):
        self.marker = Path.home() / ".multiai_current_project.json"
        self.registry = Path.home() / ".multiai_projects.json"
        self.marker_backup = self.marker.read_bytes() if self.marker.exists() else None
        self.registry_backup = self.registry.read_bytes() if self.registry.exists() else None
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        collab_switch_project(str(self.project), project_name="ValidationTest")

    def tearDown(self):
        self.tmp.cleanup()
        self._restore_file(self.marker, self.marker_backup)
        self._restore_file(self.registry, self.registry_backup)

    @staticmethod
    def _restore_file(path: Path, backup: bytes | None) -> None:
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(backup)

    def test_non_string_inputs_return_errors(self):
        for result in (
            collab_add_note(123, project_path=str(self.project)),
            collab_record_issue("probe", category=123, project_path=str(self.project)),
            collab_update_issue("issue-999", category=123, project_path=str(self.project)),
        ):
            self.assertIn("文字列", result)

    def test_setup_cli_rejects_non_string_arg_elements_before_write(self):
        for kwargs in (
            {"args_before": ["exec", 123]},
            {"args_before": "exec"},
            {"args_after": [123]},
            {"args_after": "--json"},
        ):
            result = collab_setup_cli("codex", "codex", project_path=str(self.project), **kwargs)
            self.assertIn("文字列のリスト", result)
            self.assertFalse((self.project / "cli_config.json").exists())

    def test_setup_cli_accepts_string_arg_lists(self):
        result = collab_setup_cli(
            "codex",
            "codex",
            args_before=["exec"],
            args_after=[],
            project_path=str(self.project),
        )

        self.assertIn("CLI設定を保存しました", result)
        config = json.loads((self.project / "cli_config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["codex"]["args_before"], ["exec"])


if __name__ == "__main__":
    unittest.main()
