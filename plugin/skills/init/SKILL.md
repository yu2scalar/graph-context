---
name: init
description: Create or refresh dependency_graph.json: analyse the project, recommend and ask for config (design root, registries, language, components), derive the graph from design docs and registries. Idempotent. Flags: --reconfigure, --reset-structure. Part of the `graph` plugin.
arguments: [flags]
---

# /graph:init

> Status: v3.3.0-dev.9 (2026-09-28) — the pointer is the handover: entity files, generated views, issues as nodes, completion gate, fold hides. What changed and why: the decision register `references/40-decision-register.md` (protocol skill).

Thin delegating command. Do not improvise its behaviour here.

0. The protocol folder for this run is `${CLAUDE_PLUGIN_ROOT}/skills/protocol` (if the variable was not expanded in this
   line, it is `../protocol` relative to this skill's base directory). Protocol SKILL.md is opened with Read, where
   `${CLAUDE_PLUGIN_ROOT}` is not expanded: in every path and command it shows, replace `${CLAUDE_PLUGIN_ROOT}/skills/protocol`
   with that folder (e.g. `python3 <that folder>/tools/graph_tool.py …`).
1. Read `${CLAUDE_PLUGIN_ROOT}/skills/protocol/SKILL.md` in full.
2. Execute the section titled `/graph:init` exactly as written there. `$ARGUMENTS` may contain `--reconfigure` and/or `--reset-structure`.
3. All enforced rules R1–R12 of that file apply, including R4 (questions, proposals and checklists in
   `config.interaction_language`) and R6 (writes only inside the footprint).
