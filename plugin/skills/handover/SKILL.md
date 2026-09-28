---
name: handover
description: Completion gate for pausing or ending work (D30): record the state on dependency_graph.json (current_node, wip_status, edges, next, issues with owner + trigger), propose splits and folds, run the staleness check, commit, and finish only when graph_tool.py gate prints RESULT: OK. No handover document is written. Part of the `graph` plugin.
---

# /graph:handover

> Status: v3.3.0-dev.5 (2026-09-28 — completion gate (D30): gate command, no authored handover (handover-tables / lint-handover / template removed), config.handover_path retired (migrate --drop-handover-path, fixed .context/graph_tool.log), refines edge + remove-edge (u46), hydrate no-op when current_node is unchanged (u48); dev.4: fold hides (D31, D37: FOLDED, --history, restore-folds), config command, add-node entity files; dev.3: append --section, strip-graph-copies, decision status = implementation state; dev.2: D36 integrity-first store: entity files, add / append / attach / migrate / render; dev.1: D33 Backlog view, issue_status / PLANNED / next, backlog/set-next/set-issue/close; v3.2.0 2026-09-24 — protocol as code: the protocol section you execute now starts by running `${CLAUDE_PLUGIN_ROOT}/skills/protocol/tools/graph_tool.py` (D26); v3.1.1 = D24/D25; v3.1.0 = plugin `graph`)

Thin delegating command. Do not improvise its behaviour here.

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/protocol/SKILL.md` in full.
2. Execute the section titled `/graph:handover` exactly as written there. This command takes no arguments.
3. All enforced rules R1–R8 of that file apply, including R4 (questions, proposals and checklists in
   `config.interaction_language`) and R6 (writes only inside the footprint).
