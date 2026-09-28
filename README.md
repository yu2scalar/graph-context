# graph-context

A [Claude Code](https://claude.com/claude-code) plugin for graph-based project context management.

It exists to prevent two failure modes that become untrackable once a codebase is too large to "just read the
code": **duplicate or similar implementations** written because a session did not know an existing component
already covered the need, and **forgotten updates** where code changed but the design document or decision
governing it did not.

The plugin keeps `dependency_graph.json`, a schema-validated **index** over your project (never a copy of its
content): components, design-document structure, decisions, issues, and the relations between them. It forces
the relevant 1-hop / 2-hop neighbourhood to be loaded before any code change and gates every pause so that
`current_node` alone is the handover.

Current version: **3.3.0-dev.8** (development pre-release; last release 3.2.0). Plugin name `graph`, marketplace `graph-context` (this repository).

## Commands

| Command | What it does |
|---------|--------------|
| `/graph:install` | Seed `dependency_graph.json`, append one marked block each to `CLAUDE.md` and `.gitignore`, snapshot checksums (`graph_tool.py install`, shown with `--dry-run` first). Nothing else is written to your project until `/graph:init`. |
| `/graph:init [--reconfigure] [--reset-structure]` | Analyse the project, recommend and ask for `config` (design root, registries, language, components), derive the graph from design docs and registries. Idempotent; preserves human decisions unless `--reset-structure`. |
| `/graph:hydrate <node_id>` | Load the node plus 1-hop / 2-hop neighbours over every edge kind, read every referenced file, and emit the Impact Assessment Checklist: components, subgraph, inherited decision constraints, decisions to re-examine, existing capabilities, stale docs, blast radius. Required before modifying code. |
| `/graph:handover` | Completion gate (D30): record the state on the graph, propose splits (growth) and folds (compaction), run the staleness check, commit, and finish only when `graph_tool.py gate` passes. No handover document: the next session runs `/graph:hydrate <current_node>`. |
| `/graph:compact` | Run the fold check on demand. |
| `/graph:uninstall` | Remove the footprint, strip the marked blocks, verify byte-identical restoration, then tell you how to remove the plugin. |

Questions, recommendations and approvals are asked in your project's language (`config.interaction_language`);
graph contents, entity files and views are English.

## Install

The plugin is installed **per project, with project scope** — once in each project you want to index, from that
project's folder:

```bash
# At the Claude Code prompt, started in the project's folder
/plugin marketplace add yu2scalar/graph-context   # once per machine
/plugin install graph@graph-context               # choose the "project" scope when asked
/reload-plugins                                   # or restart the session
# commands are now /graph:install, /graph:init, /graph:hydrate <node_id>, /graph:handover, /graph:compact, /graph:uninstall
```

If `/graph:install` is not offered in a project, the plugin is not installed for that project yet (another project's
project-scope install does not count). Then, in the project: `/graph:install` followed by `/graph:init`.

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
| `docs/entities/<id>.md` | one entity file per node: the text of decisions, issues, plans, rules and structure nodes (written by the tool only) |
| each `config.views[].path` (e.g. `docs/views/*.md`) | generated registers, current specification and plan views (never edited by hand) |
| `.context/graph_tool.log` | the operations log (one line per write) |
| one marked block in `CLAUDE.md` | the protocol instructions for Claude |
| one marked block in `.gitignore` | ignores `.context/` |

The skill files themselves stay in the plugin cache.

## Graph model

**Hierarchy**: Root → `component` → `feature` → `function`. `decision` and `issue` nodes attach to the
structure. Root holds only `current_node`, `nodes`, `config`.

**Edges**: `part_of` (child → parent, at most one), `depends_on`, `affects`, `resolves` (decision → issue),
`supersedes` (decision → decision it replaces), `refines` (decision → decision it narrows; the target stays in force).

**Entity files**: every node's text lives in exactly one append-only file, `docs/entities/<id>.md`; status and
edges live only in the graph. Readable registers are generated from both (`config.views`).

**Issues and plans are nodes**: an issue carries `issue_status`, `owner` and `trigger`; a plan is a `plan` node whose
steps are `PLANNED` nodes, the next one flagged `next`. `/graph:handover` is a gate that passes only when all of
this is recorded and committed, so the next session needs nothing but `current_node`.

**Registry linkage**: decision / issue nodes created from an existing register carry `source_ref` (e.g. `D-022`,
`TBD-24`); `config.registries` says how such ids are recognised, and the register row is copied verbatim into the
node's entity file.

**Growth and compaction**: a feature starts as one node and is split into `function` children when attached
decisions and issues reach `config.growth_threshold`; a superseded decision can be folded into the surviving one — it
stays as a hidden history node (`FOLDED`), shown with `hydrate --history`. Both are proposals that need your approval.

Full data model and the public decision register: `plugin/skills/protocol/references/`.

## Repository layout

```
.claude-plugin/marketplace.json
plugin/
├── .claude-plugin/plugin.json
└── skills/
    ├── protocol/                # /graph:protocol — SKILL.md, schema/, templates/, references/, tools/
    ├── install/  uninstall/  init/  hydrate/  handover/  compact/   # thin delegating commands
```

## Executable protocol

`plugin/skills/protocol/tools/graph_tool.py` performs the mechanical parts (validation, hop computation, growth /
fold candidates, staleness in both layers, the completion gate, fold, split) and is the only writer of the graph,
entity files and views. Claude runs it and presents the output; rule R9 forbids retyping any id, count or timestamp by
hand, rule R12 forbids changing the store any other way. See `tools/README.md`.

## Enforced rules

R1 cross-reference validation · R2 hydrate before modifying code · R3 handover fidelity ·
R4 interaction language · R5 structure follows design docs · R6 bounded footprint ·
R7 components always visible · R8 no reinvention · R9 numbers come from the tool · R10 record, then ask ·
R11 plans are nodes · R12 everything through a command. Full text in `plugin/skills/protocol/SKILL.md`.
