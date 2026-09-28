---
name: hydrate
description: Load a node and its 1-hop/2-hop neighbourhood from dependency_graph.json, read every referenced file, and output the Impact Assessment Checklist. Required before modifying code. Usage: /graph:hydrate <node_id>. Part of the `graph` plugin.
arguments: [node_id]
---

# /graph:hydrate

> Status: v3.3.0-dev.8 (2026-09-28) — the pointer is the handover: entity files, generated views, issues as nodes, completion gate, fold hides. What changed and why: the decision register `references/40-decision-register.md` (protocol skill).

Thin delegating command. Do not improvise its behaviour here.

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/protocol/SKILL.md` in full.
2. Execute the section titled `/graph:hydrate` exactly as written there. `$node_id` (the first argument) is the node to hydrate.
3. All enforced rules R1–R12 of that file apply, including R4 (questions, proposals and checklists in
   `config.interaction_language`) and R6 (writes only inside the footprint).
