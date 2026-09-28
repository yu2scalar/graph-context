---
name: install
description: Install graph-context into this project with a bounded, reversible footprint: seed dependency_graph.json, append marked blocks to CLAUDE.md and .gitignore, snapshot sha256. Nothing else is written. Use when adding the graph to a project for the first time. Part of the `graph` plugin.
---

# /graph:install

> Status: v3.3.0-dev.8 (2026-09-28) — the pointer is the handover: entity files, generated views, issues as nodes, completion gate, fold hides. What changed and why: the decision register `references/40-decision-register.md` (protocol skill).

Thin delegating command. Do not improvise its behaviour here.

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/protocol/SKILL.md` in full.
2. Execute the section titled `/graph:install` exactly as written there. This command takes no arguments.
3. All enforced rules R1–R12 of that file apply, including R4 (questions, proposals and checklists in
   `config.interaction_language`) and R6 (writes only inside the footprint).
