# Changelog

All notable changes to this project will be documented in this file.

## [1.1.1] — 2026-05-29

### Fixed

- **Crash hardening for corrupted `AI_STATE.json`**: tools no longer raise an
  unhandled `TypeError` / `AttributeError` when the state file's top level is not
  a JSON object (e.g. an array or string from a manual edit or corruption).
  `_load_state` and `collab_doctor` now report a clear error instead of crashing —
  important because `collab_doctor` is the very tool you reach for when state is broken.
- **`collab_doctor` recovery check**: fixed a glob that never matched the actual
  backup filenames (`AI_STATE_backup_*.json`, `AI_STATE_before_import_*.json`),
  so backup files are now detected and reported correctly.
- **CLI config robustness**: a corrupted `cli_config.json` no longer crashes
  `collab_consult` / `collab_discuss` / `collab_request_review` / `collab_setup_cli`;
  invalid content now falls back to defaults (was: only `RuntimeError` caught,
  so `json.JSONDecodeError` propagated and killed the call).
- **`collab_record_issue`**: passing `category=None` no longer raises `TypeError`.
- **`collab_update_issue`**: `add_tags` / `add_related_files` that would exceed the
  limit now return a clear error instead of silently truncating the list.
- **`collab_timeline`**: the `since` parameter is now validated as ISO 8601;
  malformed values return an error instead of producing misleading string-order results.
- BOM stripping in the raw state reader no longer risks removing body bytes that
  happen to match BOM bytes (now strips exactly the 3-byte BOM when present).

### Changed

- `collab_doctor` reads the raw state file once and caches it across all check
  blocks (previously read up to three times).
- New projects created by `collab_switch_project` now include an explicit
  `version` field, matching the schema validator's expectations (no spurious
  `collab_doctor` schema warning right after creation).
- `_STATE_DEFAULTS["version"]` now references `_STATE_SCHEMA_VERSION` to avoid drift.
- Removed a dead filter in the debug HANDOFF template (`known_issues` never carries
  a `resolved` flag).
- Fixed a stray non-Japanese character in a docstring; minor variable-name consistency
  cleanup in `collab_doctor`.

## [1.1.0] — 2026-05-28

### Added

- **i18n support** (`MULTIAI_LANG` env var, default `"ja"`):
  - New `i18n.py` module with `t(key, **kwargs)`, `get_lang()`, and `mode_label()` functions
  - All user-facing strings in `server.py`, `state.py`, `cli.py`, `rendering.py` replaced with `t()` calls
  - Full English string table (`"en"`) with 200+ translation keys
  - Mode labels switch to English: "Plan/Design", "Implement", "Review", "Debug"
  - HANDOFF.md rendered in the active language (headers, section titles, footer procedure)
  - Set `MULTIAI_LANG=en` in your shell to enable English mode

- **Git integration in `collab_status` and `collab_switch_project`**:
  - `collab_status` shows current Git branch and latest commit hash
  - `collab_switch_project` shows Git branch when connecting to a project
  - Reads `HEAD` via subprocess; gracefully omitted when project is not a Git repo

- **Notes soft-cap warnings in `collab_add_note`**:
  - ≥ 200 notes: info tip suggesting `collab_cleanup_history()`
  - ≥ 300 notes: warning urging cleanup

- **Auto-status in `collab_switch_project`**:
  - After connecting to an existing project, a condensed status summary
    (current task, open issues, pending task count) is appended automatically

- **`collab_list_projects` tool** (new):
  - Lists recently used projects from `~/.multiai_relay_mcp/projects.json`
  - Shows existence check ✅ / ❌, last-used timestamp, and reconnect command

- **`test_i18n.py`**: comprehensive test suite for i18n — string table completeness,
  `t()` / `mode_label()` behaviour, English mode integration tests for 20+ tools,
  and HANDOFF.md rendering in both languages

### Fixed

- `collab_update_issue`: loop variable `t` in `add_tags` / remove_tags branches
  shadowed the imported `t()` i18n function, causing `UnboundLocalError` when
  `status="resolved"` validation ran before the loop (`t` in `add_tags` loop
  renamed to `tg`)

### Changed

- All hardcoded Japanese strings in tool return values moved to i18n string table
- `rendering.py` footer (session start procedure) now respects active language
- `_validate_input` default field label changed from `"入力"` to `"input"`
  (neutral; callers always pass an explicit field name anyway)

---

## [1.0.21] — 2026-05-27

- `collab_update_issue` — add `status` field support (`open` / `deferred`)
- `collab_update_issue` — add `add_tags` / `remove_tags` / `add_related_files` / `remove_related_files` incremental-edit params
- `collab_record_issue` — add `category` field (slug format, max 30 chars)
- `collab_list_resolved` — new tool to list resolved issues
- `collab_cleanup_sessions` — `keep_per_ai` param (default 5); per-AI cleanup
- `collab_cleanup_history` — `archive` flag and `dry_run` mode
- `collab_export_state` / `collab_import_state` — JSON export/import with SHA-256 checksum
- `collab_set_handoff_template` — choose `full` / `minimal` / `review` / `debug` template
- `collab_generate_handoff` — `dry_run` mode (returns JSON preview)
- `collab_checkpoint` — `dry_run` mode
- `collab_doctor` — schema version check, duplicate ID check, tag/category format check, stale lock detection
- `project_path` context parameter added to all tools (per-call project override)
- CWD fallback: auto-detect project from current working directory when no project is set
- File locking (`_StateLock`) + atomic write via `tempfile` + `os.replace`

## [1.0.0] — 2026-05-01

Initial release.
