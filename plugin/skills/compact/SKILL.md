---
name: compact
description: Run the fold check over the whole dependency_graph.json and propose folding superseded decisions / resolved issues into their surviving decision. Part of the `graph` plugin.
---

# /graph:compact

> Status: v3.2.0 (2026-09-24 — protocol as code: the protocol section you execute now starts by running `${CLAUDE_PLUGIN_ROOT}/skills/protocol/tools/graph_tool.py` (D26); v3.1.1 = D24/D25; v3.1.0 = plugin `graph`)

Thin delegating command. Do not improvise its behaviour here.

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/protocol/SKILL.md` in full.
2. Execute the section titled `/graph:compact` exactly as written there. This command takes no arguments.
3. All enforced rules R1–R8 of that file apply, including R4 (questions, proposals and checklists in
   `config.interaction_language`) and R6 (writes only inside the footprint).
