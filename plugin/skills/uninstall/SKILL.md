---
name: uninstall
description: Remove the graph-context footprint from this project (dependency_graph.json, handover file, marked blocks) and verify CLAUDE.md and .gitignore are restored byte-identical; then tells you how to remove the plugin itself. Part of the `graph` plugin.
disable-model-invocation: true
---

# /graph:uninstall

> Status: v3.3.0-dev.3 (2026-09-25 — append --section, strip-graph-copies, decision status = implementation state; dev.2: D36 integrity-first store: entity files, add / append / attach / migrate / render; dev.1: D33 Backlog view, issue_status / PLANNED / next, backlog/set-next/set-issue/close; v3.2.0 2026-09-24 — protocol as code: the protocol section you execute now starts by running `${CLAUDE_PLUGIN_ROOT}/skills/protocol/tools/graph_tool.py` (D26); v3.1.1 = D24/D25; v3.1.0 = plugin `graph`)

Thin delegating command. Do not improvise its behaviour here.

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/protocol/SKILL.md` in full.
2. Execute the section titled `/graph:uninstall` exactly as written there. This command takes no arguments.
3. All enforced rules R1–R8 of that file apply, including R4 (questions, proposals and checklists in
   `config.interaction_language`) and R6 (writes only inside the footprint).
