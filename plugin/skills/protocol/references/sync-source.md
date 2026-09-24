# sync-source

- `10-data-model.md` mirrors `../schema/graph_schema.json`. The schema is authoritative; update the schema first,
  then this file.
- `40-decision-register.md` is the public projection of the maintainer's local planning documents
  (`docs/plan-*.md`, not published). User quotes and session logs are intentionally omitted here.
- Version: `plugin/.claude-plugin/plugin.json` → `version`; each SKILL.md repeats it in its `> Status:` line.
- `../schema/fixtures/run_fixtures.py` is the schema self-test (positive + negative fixtures). Run it after any schema change.
- Template `$schema` is pinned to the release tag (`v<version>`); bump it together with `plugin.json`.
- `../tools/test_graph_tool.py` is the tool self-test on a synthetic graph. Run it with the schema fixtures after any tool or schema change.
