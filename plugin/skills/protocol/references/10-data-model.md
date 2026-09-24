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
| `install` | set by install | `{installed_at, skill_version, claude_md_sha256_before, gitignore_sha256_before}` |

Deliberately absent: `code_roots` (derived: union of component nodes' `code_targets`), `project_name`, `version`.

## Node — closed object
| Field | Required | Type | Definition |
|-------|----------|------|------------|
| `id` | yes | `^[a-z0-9][a-z0-9_-]*$` | equals the key in `nodes` |
| `type` | yes | enum | `component` \| `feature` \| `function` \| `decision` \| `issue` \| `task` (task: manual only, never generated) |
| `name` | yes | string | human name |
| `docs` | yes | path[] | documents describing the node; may be empty |
| `code_targets` | yes | path[] | files/dirs the node owns. component: its root dir(s). others: must fall under some component's roots |
| `part_of` | no | nodeId[] ≤ 1 | parent. feature→component; function→feature/function; decision/issue→where attached. Components have none |
| `depends_on` | no | nodeId[] | prerequisite / expectation (incl. cross-component: → providing component's function) ; issue→decision that raised it |
| `affects` | no | nodeId[] | decision/issue → component/feature/function it constrains or impacts |
| `resolves` | no | nodeId[] | decision → issue only |
| `supersedes` | no | nodeId[] | decision → decision only |
| `source_ref` | no | string | registry id verbatim (`D-022`, `TBD-24`); decision/issue only; single-valued |
| `folded` | no | string[] | registry ids absorbed by compaction; decision only |
| `wip_status` | no | enum | `DONE` \| `IN_PROGRESS` \| `BLOCKED` |

## Hierarchy and growth
Root → component → feature → function. A feature starts as one node; when attached decisions+issues reach
`growth_threshold`, or a decision applies to only part of it, handover proposes splitting into `function`
children and the parent becomes an index node. Superseded decisions and resolved issues are folded into the
surviving decision (`folded[]`) on approval; text stays in the registry.

## Invariants enforced by the skill (R1), not expressible in JSON Schema
key == id · every edge target exists · no self-edges · `part_of` acyclic · `resolves` decision→issue ·
`supersedes` decision→decision · `source_ref` matches a registry pattern when registries exist ·
non-component `code_targets` under some component's roots.
