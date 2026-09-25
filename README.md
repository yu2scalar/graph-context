# graph-context

A [Claude Code](https://claude.com/claude-code) plugin for graph-based project context management.

It exists to prevent two failure modes that become untrackable once a codebase is too large to "just read the
code": **duplicate or similar implementations** written because a session did not know an existing component
already covered the need, and **forgotten updates** where code changed but the design document or decision
governing it did not.

The plugin keeps `dependency_graph.json`, a schema-validated **index** over your project (never a copy of its
content): components, design-document structure, decisions, issues, and the relations between them. It forces
the relevant 1-hop / 2-hop neighbourhood to be loaded before any code change and writes lossless handovers when
work pauses.

Current version: **3.3.0-dev.3** (development pre-release; last release 3.2.0). Plugin name `graph`, marketplace `graph-context` (this repository).

## Commands

| Command | What it does |
|---------|--------------|
| `/graph:install` | Seed `dependency_graph.json`, append one marked block each to `CLAUDE.md` and `.gitignore`, snapshot checksums. Nothing else is written to your project. |
| `/graph:init [--reconfigure] [--reset-structure]` | Analyse the project, recommend and ask for `config` (design root, registries, handover path, language, components), derive the graph from design docs and registries. Idempotent; preserves human decisions unless `--reset-structure`. |
| `/graph:hydrate <node_id>` | Load the node plus 1-hop / 2-hop neighbours over every edge kind, read every referenced file, and emit the Impact Assessment Checklist: components, subgraph, inherited decision constraints, decisions to re-examine, existing capabilities, stale docs, blast radius. Required before modifying code. |
| `/graph:handover` | Update the graph, propose splits (growth) and folds (compaction), run the staleness check, write the handover: Active Task Pointer, Components + Subgraph, Hard Decisions Log, Unresolved Edges, Immediate Resume Trigger, Decision Drift, Staleness. |
| `/graph:compact` | Run the fold check on demand. |
| `/graph:uninstall` | Remove the footprint, strip the marked blocks, verify byte-identical restoration, then tell you how to remove the plugin. |

Questions, recommendations and approvals are asked in your project's language (`config.interaction_language`);
graph contents and handover files are English.

## Install

```bash
# At the Claude Code prompt
/plugin marketplace add yu2scalar/graph-context
/plugin install graph@graph-context
/reload-plugins                # or restart the session
# commands are now /graph:install, /graph:init, /graph:hydrate <node_id>, /graph:handover, /graph:compact, /graph:uninstall
```

Then, inside the project you want to index: `/graph:install` followed by `/graph:init`.

## Update

```bash
/plugin marketplace update graph-context   # fetch the latest from GitHub
/reload-plugins                                  # apply it to the session
```

## Uninstall

```bash
# inside each project first (reversible footprint):
/graph:uninstall
# then the plugin itself:
/plugin uninstall graph@graph-context
/plugin marketplace remove graph-context
/reload-plugins
```

## What gets written into your project

Only these, all removable by `/graph:uninstall`:

| Path | Purpose |
|------|---------|
| `dependency_graph.json` | the graph and its `config` |
| `config.handover_path` (default `.context/WIP_HANDOVER.md`) | the handover |
| one marked block in `CLAUDE.md` | the protocol instructions for Claude |
| one marked block in `.gitignore` | ignores `.context/` |

The skill files themselves stay in the plugin cache.

## Graph model

**Hierarchy**: Root → `component` → `feature` → `function`. `decision` and `issue` nodes attach to the
structure. Root holds only `current_node`, `nodes`, `config`.

**Edges**: `part_of` (child → parent, at most one), `depends_on`, `affects`, `resolves` (decision → issue),
`supersedes` (decision → decision).

**Registry linkage**: decision / issue nodes carry `source_ref` (e.g. `D-022`, `TBD-24`); `config.registries`
says how such ids are recognised and which file holds their text.

**Growth and compaction**: a feature starts as one node and is split into `function` children when attached
decisions and issues reach `config.growth_threshold`; superseded decisions and resolved issues are folded into
the surviving decision (`folded`). Both are proposals that need your approval.

Full data model and the public decision register: `plugin/skills/protocol/references/`.

## Repository layout

```
.claude-plugin/marketplace.json
plugin/
├── .claude-plugin/plugin.json
└── skills/
    ├── protocol/                # /graph:protocol — SKILL.md, schema/, templates/, references/
    ├── install/  uninstall/  init/  hydrate/  handover/  compact/   # thin delegating commands
```

## Executable protocol

`plugin/skills/protocol/tools/graph_tool.py` performs the mechanical parts (validation, hop computation, growth /
fold candidates, staleness in both layers, handover tables, fold, split). Claude runs it and presents the output;
rule R9 forbids retyping any id, count or timestamp by hand. See `tools/README.md`.

## Enforced rules

R1 cross-reference validation · R2 hydrate before modifying code · R3 handover fidelity ·
R4 interaction language · R5 structure follows design docs · R6 bounded footprint ·
R7 components always visible · R8 no reinvention · R9 numbers come from the tool. Full text in `plugin/skills/protocol/SKILL.md`.
