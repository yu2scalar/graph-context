# Data model

## Root (`dependency_graph.json`) — closed object
| Key | Required | Type | Definition |
|-----|----------|------|------------|
| `$schema` | no | string | editor hint; ignored by the skill |
| `current_node` | yes | nodeId \| null | the single node being worked on now; must exist in `nodes`; written by hydrate and handover only |
| `nodes` | yes | object<nodeId, node> | all nodes; key must equal `node.id` |
| `config` | yes | object (closed) | project-wide settings written by the init Q&A, editable by hand |

## `config`
| Key | Default | Definition |
|-----|---------|------------|
| `interaction_language` | inferred | BCP-47; language for every question, recommendation, approval, checklist shown to the user. Artifacts stay English |
| `handover_path` | `.context/WIP_HANDOVER.md` | file the handover command writes |
| `design_root` | detected | directory whose document structure the feature/function layer mirrors |
| `docs_scope` | `<design_root>/**/*.md` | globs init reads |
| `registries[]` | `[]` | `{type: decision\|issue, id_pattern: <regex>, file: <path>}` — how registry ids are recognised and where their text lives |
| `growth_threshold` | 5 | attached decision+issue count at which a split is proposed |
| `backlog_filter` | absent (= all open issues) | `{owner: user\|claude, next_only: bool, component: <id>}` — project default for which open issues the Backlog lists; excluded ones are counted per component; command options override (D33) |
| `install` | set by install | `{installed_at, skill_version, claude_md_sha256_before, gitignore_sha256_before}` |

Deliberately absent: `code_roots` (derived: union of component nodes' `code_targets`), `project_name`, `version`.

## Node — closed object
| Field | Required | Type | Definition |
|-------|----------|------|------------|
| `id` | yes | `^[a-z0-9][a-z0-9_-]*$` | equals the key in `nodes` |
| `type` | yes | enum | `component` \| `feature` \| `function` \| `decision` \| `issue` \| `plan` \| `rule` \| `task` (plan: what was planned, its steps are nodes `part_of` it; rule: a working rule set by the user; task: manual only, never generated) |
| `name` | yes | string | human name |
| `docs` | yes | path[] | documents describing the node; may be empty |
| `code_targets` | yes | path[] | files/dirs the node owns. component: its root dir(s). others: must fall under some component's roots |
| `part_of` | no | nodeId[] ≤ 1 | parent. feature→component; function→feature/function; decision/issue→where attached. Components have none |
| `depends_on` | no | nodeId[] | prerequisite / expectation (incl. cross-component: → providing component's function) ; issue→decision that raised it |
| `affects` | no | nodeId[] | decision/issue → component/feature/function it constrains or impacts |
| `resolves` | no | nodeId[] | decision → issue only |
| `supersedes` | no | nodeId[] | decision → decision only |
| `source_ref` | no | string | registry id verbatim (`D-022`, `TBD-24`); decision/issue only; single-valued |
| `wip_status` | no | enum | `PLANNED` \| `IN_PROGRESS` \| `BLOCKED` \| `DONE` \| `FOLDED`; `PLANNED` = not-yet-started plan step (D33, D34 R-b); on decisions the implementation state, `FOLDED` = absorbed by the superseding decision, hidden history (D31, D37; set only by `fold`); never on issue nodes |
| `next` | no | bool | the item to take up next (D33); feature/function/task/issue only |
| `issue_status` | issue: yes | enum | `open` \| `resolved` \| `transferred`; issue only |
| `owner` | no | enum | `user` \| `claude` — who resolves the issue; issue only |
| `trigger` | no | string | when / on what event the issue is taken up; issue only |
| `file` | no | path | entity file holding the node's text (`docs/entities/<id>.md`); decision / issue / plan / rule only; written by graph_tool only, append-only |
| `sha256` | with `file` | hex64 | sha256 of `file` as last written by graph_tool; a mismatch = edited outside the tool |
| `closed_by` | when not open | string | decision id, commit hash or short action text that closed the issue; issue only |

## Hierarchy and growth
Root → component → feature → function. A feature starts as one node; when attached decisions+issues reach
`growth_threshold`, or a decision applies to only part of it, handover proposes splitting into `function`
children and the parent becomes an index node. A superseded decision is folded into the surviving
decision on approval: it stays as a node with `wip_status: FOLDED`, linked by the survivor's `supersedes`, hidden by default
(D31, D37). Resolved issues are hidden by their `issue_status`. Nothing is deleted.

## Invariants enforced by the skill (R1), not expressible in JSON Schema
key == id · every edge target exists · no self-edges · `part_of` acyclic · `resolves` decision→issue (target `issue_status: resolved`) ·
`supersedes` decision→decision · `source_ref` matches a registry pattern when registries exist ·
non-component `code_targets` under some component's roots.
