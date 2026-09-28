---
name: handover
description: Completion gate for pausing or ending work (D30): record the state on dependency_graph.json (current_node, wip_status, edges, next, issues with owner + trigger), propose splits and folds, run the staleness check, commit, and finish only when graph_tool.py gate prints RESULT: OK. No handover document is written. Part of the `graph` plugin.
---

# /graph:handover

> Status: v3.3.0-dev.7 (2026-09-28) — the pointer is the handover: entity files, generated views, issues as nodes, completion gate, fold hides. What changed and why: the decision register `references/40-decision-register.md` (protocol skill).

Thin delegating command. Do not improvise its behaviour here.

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/protocol/SKILL.md` in full.
2. Execute the section titled `/graph:handover` exactly as written there. This command takes no arguments.
3. All enforced rules R1–R12 of that file apply, including R4 (questions, proposals and checklists in
   `config.interaction_language`) and R6 (writes only inside the footprint).
