---
name: uninstall
description: Remove the graph-context footprint from this project (dependency_graph.json, entity files, generated views, operations log, marked blocks) and verify CLAUDE.md and .gitignore are restored byte-identical; then tells you how to remove the plugin itself. Part of the `graph` plugin.
disable-model-invocation: true
---

# /graph:uninstall

> Status: v3.3.0-dev.6 (2026-09-28) — the pointer is the handover: entity files, generated views, issues as nodes, completion gate, fold hides. What changed and why: the decision register `references/40-decision-register.md` (protocol skill).

Thin delegating command. Do not improvise its behaviour here.

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/protocol/SKILL.md` in full.
2. Execute the section titled `/graph:uninstall` exactly as written there. This command takes no arguments.
3. All enforced rules R1–R12 of that file apply, including R4 (questions, proposals and checklists in
   `config.interaction_language`) and R6 (writes only inside the footprint).
