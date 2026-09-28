---
name: protocol
description: Graph-based project context management (protocol skill of the `graph` plugin, invoked as /graph:protocol). Keeps dependency_graph.json as a schema-validated index over a project's components, design documents and decision/issue registries, forces 1-hop/2-hop hydration before code changes, and gates every pause so that current_node alone is the handover. Commands are /graph:install, /graph:uninstall, /graph:init, /graph:hydrate <node_id>, /graph:handover, /graph:compact. Also triggers on "dependency graph", "hydrate node", "handover", "WIP handover", "context graph", "graph init", "compact graph".
---

# graph-context

> Status: **v3.3.0-dev.4 (2026-09-25 — fold hides (D31, D37: FOLDED, --history, restore-folds), config command, add-node entity files; dev.3: append --section, strip-graph-copies, decision status = implementation state; dev.2: D36 integrity-first store: entity files, add / append / attach / migrate / render; dev.1: D33 Backlog view, issue_status / PLANNED / next, backlog/set-next/set-issue/close; v3.2.0 2026-09-24 — D26 protocol as code: `tools/graph_tool.py` executes R1, hydrate, check, handover tables, fold, split; rule R9; v3.1.1 = D24/D25; v3.1.0 = plugin `graph`; v3.0.0 = plugin packaging)**
> Long-form material (full data model, public decision register D1–D37) lives in `${CLAUDE_SKILL_DIR}/references/`.

## Purpose

Two failure modes this skill exists to prevent, both of which become untrackable once a codebase is
large enough that "just read the code" stops working:

1. **Duplicate or similar implementations**, typically because a session did not know an existing
   component or function already covered the need.
2. **Forgotten updates**: code changed, the design document or decision that governs it did not.

It does so by keeping an explicit, machine-checkable **index graph** over the project. The graph never
holds content; it holds references to where the content lives and the relations between them.

## Files

| Path | Role |
|------|------|
| `dependency_graph.json` (project root) | The graph. Must validate against the schema. |
| `${CLAUDE_SKILL_DIR}/schema/graph_schema.json` | JSON Schema, draft 2020-12. Authoritative for shapes. Shipped in the plugin, never copied into the project. |
| `${CLAUDE_SKILL_DIR}/templates/graph_context.template.json` | Minimal valid seed graph. |
| `${CLAUDE_SKILL_DIR}/references/` | Full data model, public decision register, sync notes. |
| `${CLAUDE_SKILL_DIR}/tools/graph_tool.py` | **The executable protocol (D26).** Read-only: `validate`, `gate`, `check`, `lint-prose`, `hydrate --dry-run`. Writing: `hydrate <node>` (current_node), `fold`, `split`, `set-status`, `add-edge`, `set-current`, `add-node`, `add-doc`, `add-code`. Every number, id, hop, path status and timestamp shown to the user comes from this tool (R9). Full list: `tools/README.md`. |
| `${CLAUDE_PLUGIN_ROOT}/skills/{install,uninstall,init,hydrate,handover,compact}/SKILL.md` | Six thin delegating skills → `/graph:<name>` (D16, D21). Each reads this file and executes the matching section. |
| `.context/graph_tool.log` | Operations log: one line per accepted write (graph md5 before → after). Fixed path since D30 (`config.handover_path` retired; `migrate --drop-handover-path`). |

## Data model (summary; schema is authoritative)

**Root** is closed: `current_node`, `nodes`, `config` only.

**Hierarchy**: Root → `component` → `feature` → `function`. `decision` and `issue` nodes attach to a
component, feature or function. `task` exists for manual use and is never generated.

**Node fields**: required `id`, `type`, `name`, `docs[]`, `code_targets[]`. Optional edges:
`part_of` (≤1, child → parent), `depends_on`, `affects`, `resolves` (decision → issue only),
`supersedes` (decision → decision only), `refines` (decision → decision only; the target stays in force, never a fold candidate — u46). Optional `source_ref` (registry id, decision/issue only,
single-valued), `wip_status`
(`PLANNED` | `IN_PROGRESS` | `BLOCKED` | `DONE`; not on issues), `next` (bool, the item to take up next;
not on component/decision). Issue nodes require `issue_status` (`open` | `resolved` | `transferred`) and may
carry `owner` (`user` | `claude`) and `trigger`; `closed_by` is required when not open (D33). Types `plan` and `rule`
and the fields `file` + `sha256` (entity text file, written by graph_tool only) belong to the integrity-first store
(private plan integrity-store, in progress).

**Edge direction conventions**

| Relation | Edge |
|----------|------|
| feature belongs to component / function belongs to feature | child `part_of` parent |
| feature needs another feature | `depends_on` |
| feature/function expects something from another component | `depends_on` → that component's function/feature node |
| issue impacts a feature/function/component | issue `affects` target |
| decision constrains a feature/function/component | decision `affects` target |
| decision resolves an issue | decision `resolves` issue |
| decision replaces an earlier decision | decision `supersedes` earlier decision |
| decision narrows or details an earlier decision that stays in force | decision `refines` earlier decision |
| issue was raised by a decision | issue `depends_on` decision |

**`config` keys**

| Key | Default | Meaning |
|-----|---------|---------|
| `interaction_language` | inferred | language for every question, recommendation, approval, checklist shown to the user |
| `design_root` | detected | directory whose document structure the feature/function layer mirrors |
| `docs_scope` | `<design_root>/**/*.md` | globs `/graph:init` reads |
| `registries[]` | `[]` | `{type, id_pattern, file}`: how decision/issue ids are recognised and where their text lives |
| `growth_threshold` | 5 | attached decision+issue count at which a split is proposed |
| `backlog_filter` | absent | default filter for the open issues the Backlog lists (`owner`, `next_only`, `component`); hidden ones are counted (D33) |
| `install` | set by install | sha256 snapshots for uninstall verification |

Not in config, by decision: `code_roots` (derived: union of component nodes' `code_targets`),
`project_name`, `version` (git / CLAUDE.md own them).

## Integrity-first store (3.3.0-dev, D36)

Every node's text lives in exactly one entity file, `docs/entities/<id>.md`; status and edges live only in
`dependency_graph.json`; the node `name` is a copy of the file's heading. Documents people read (`config.views`:
registers, `current.md`, plans, the public register) are generated. Therefore:
- **Never edit `docs/entities/*` or a view by hand.** `validate` detects it (sha256, drift) and refuses further writes.
- **New fact → `graph_tool.py add <id> <type> "<name>" --section 'Heading=text' …`.** It first lists every existing entity of
  that type; read the list, then state `--new-not-duplicate "<why>"` or `--duplicate-of <id>` (then `append`). Duplicates
  written in other words are only caught by that reading.
- **Correction or later note → `graph_tool.py append <id> "<text>"`** (entity files are append-only); name change → `rename`.
- **Newer version of a section → `append <id> "<text>" --section <Heading>`.** When a heading appears more than once in an
  entity file, the **last** section with that heading is the current one (hydrate and views read it that way).
- **Decision `wip_status` = implementation state**: PLANNED = decided, not yet implemented; IN_PROGRESS; DONE = implemented.
- **Existing records → `migrate`** (reproducible: registry rows copied verbatim, first matching registry = primary),
  `migrate --plans` (plan documents into plan entities), `migrate --retire-registry <file>` (hand-written register into
  entity logs, then removed).
- Every write is validated before it is saved; a refused write changes nothing.
- **Everything through a command (rule r2):** config edits with `config set <key> <json>`; structure nodes with `add-node … --summary`
  (it writes the entity file too). If an operation has no command, add the command (with a test) first — no ad-hoc scripts.
- Claude memory holds preferences and pointers only, never project facts (P5).
- Hydrate lists each subgraph node's entity file first — read those before anything else.

## Command recognition

Plugin skills are always namespaced (Claude Code rule); the plugin is named `graph` so the commands read
`/graph:install`, `/graph:uninstall`, `/graph:init [--reconfigure] [--reset-structure]`,
`/graph:hydrate <node_id>`, `/graph:handover`, `/graph:compact` (D16, D21, D23).
Invoking this protocol skill directly with a sub-command word (`/graph:protocol hydrate x`) is equivalent.
In prose below, `/graph:<name>` is abbreviated to `/<name>` where unambiguous. Natural-language
equivalents ("rebuild the dependency graph", "hydrate the commit-protocol node", "write the handover",
"compact the decisions") map to the same commands.

---

## `/graph:install`

Purpose: put the skill into a host project with a bounded, reversible footprint (rule R6).

1. Nothing is copied: the skill lives in the plugin cache (`/plugin install graph@graph-context`).
   Confirm the plugin is loaded (this file is being read from `${CLAUDE_PLUGIN_ROOT}`).
2. Record sha256 of the target's `CLAUDE.md` and `.gitignore` as they are now (null if absent).
3. Create `dependency_graph.json` from `${CLAUDE_SKILL_DIR}/templates/graph_context.template.json` if absent.
4. Append to `CLAUDE.md` (create if absent) exactly one marked block:
   ```markdown
   <!-- graph-context:begin -->
   ## CRITICAL PROTOCOL (graph-context)
   - You must strictly follow the protocol of the `graph` plugin (skill `graph:protocol`, installed via `/plugin`).
   - Before modifying any feature or fixing bugs, verify if `dependency_graph.json` exists. If so, run `/graph:hydrate <node_id>` to load 1-hop/2-hop dependencies first.
   - When ending a session or pausing work, run `/graph:handover`: record the state on the graph through `graph_tool.py` and finish only when `graph_tool.py gate` prints `RESULT: OK`. No handover document is written; the next session starts with `/graph:hydrate <current_node>`.
   - Registry mapping (decision / issue ids → files) = `dependency_graph.json` → `config.registries`.
   <!-- graph-context:end -->
   ```
5. Append to `.gitignore` (create if absent) exactly one marked block:
   ```
   # graph-context:begin
   .context/
   # graph-context:end
   ```
   `.context/` holds only the operations log `graph_tool.log`; omit the line if the log should be tracked; keep the markers.
6. Write `config.install` `{installed_at, skill_version, claude_md_sha256_before, gitignore_sha256_before}`; `skill_version` = `version` in `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`.
7. Print the footprint (every path created or modified). Ask, in the interaction language, before writing anything.

## `/graph:uninstall`

1. Compute the footprint: `dependency_graph.json`, the entity files and generated views the tool wrote
   (`docs/entities/`, every `config.views[].path`), `.context/graph_tool.log` (and `.context/` if it is otherwise empty),
   the marked block in `CLAUDE.md`, the marked block in `.gitignore`. A leftover `.context/WIP_HANDOVER.md` from a
   version before D30 is listed too.
2. Show the list with a per-path action (delete file / strip block / delete empty dir) and whether the path
   is git-tracked. Ask for approval.
3. On approval: delete files and dirs the skill created; strip exactly the text between and including the
   markers (plus one trailing newline) from `CLAUDE.md` and `.gitignore`; if a file becomes empty and the
   skill created it, delete it.
4. Verify: sha256 of `CLAUDE.md` and `.gitignore` now equal `config.install.*_before` (null = file should
   not exist). Report "restored byte-identical" or list differences (which can only come from user edits
   outside the markers; those are kept).
5. Warn once if any removed path was git-tracked so the user can `git rm` in the same commit.
6. Finally tell the user: the plugin itself is removed with `/plugin uninstall graph@graph-context`
   (and `/plugin marketplace remove graph-context` if desired); a skill cannot uninstall itself.

Nothing outside the footprint is ever touched. Anything Claude stored in its own memory cannot be
uninstalled, so the skill never writes memory (R6).

---

## `/graph:init [--reconfigure] [--reset-structure]`

Purpose: create or refresh `dependency_graph.json`. Idempotent (F8).

### Step 0 — project analysis and configuration Q&A
Run when `config` is incomplete or `--reconfigure` is given.

1. Detect and tabulate, then **recommend and ask** (interaction language):
   - `design_root`: candidates `docs/design/`, `design/`, `docs/`, `doc/`; prefer the one with a README or
     index and the most cross-references.
   - `docs_scope`: default `<design_root>/**/*.md`; offer to add plan / handover docs if found.
   - `registries`: files matching `decision-log*`, `adr*`, `decisions*` → type decision; `tbd*`, `issues*`,
     `open-questions*` → type issue. Derive `id_pattern` from ids actually present (e.g. `^D-\d{3}$`,
     `^TBD-\d{2}$`) and show three sample ids per registry as evidence.
   - `interaction_language`: infer from `CLAUDE.md` and recent user messages; confirm.
   - `growth_threshold`: default 5; state that it can be changed later and the graph rebuilt.
   - **components**: top-level directories that contain build files or sources, excluding `build/`,
     `.gradle/`, `.idea/`, `node_modules/`, `target/`, `dist/`, `.git/`, docs folders. Propose one
     `component` node each with `code_targets` = that directory; the primary source tree (e.g. `src/`)
     becomes `core` unless the user names it otherwise. The user confirms names, paths, and may add or
     remove components. Proposing a component is always a user decision (R8).
     Scope note (D17): component detection is a *listing of top-level directory names* only. It never
     reads source files. The "no blind source walk" rule (S3) governs how `code_targets` are derived in
     Step 2 (from paths referenced by design documents), not this listing.
2. Persist answers to `config` and create the component nodes.

### Step 1 — load and preserve
If the graph exists, validate it (R1). Preserve `current_node`, `wip_status`, `part_of`, `config`
unless `--reset-structure` (which discards `part_of` and re-proposes splits/folds under the
current `growth_threshold`). Never drop a node because a scan did not rediscover it; report it instead.

### Step 2 — derive structure from design docs (R5)
For each document in `docs_scope`:
- One `feature` node per design document, `part_of` the component whose `code_targets` its referenced
  code falls under (ask if ambiguous; an index/overview document becomes `docs` of the component instead
  of a feature).
- A document with clearly separate top-level sections may yield `function` children; do **not** split on
  first init unless the structure is explicit. Splitting is normally a growth proposal at handover.
- Collect project-relative code paths mentioned in the document (code spans, tables, links) into
  `code_targets`; each must fall under some component's roots, otherwise report it as unplaced.
- Never generate `task` nodes.

### Step 3 — decisions and issues (R5, OP1 = C)
Scan the documents in scope and the registry files for ids matching `config.registries[].id_pattern`.
Create a `decision` / `issue` node **only** when the id is referenced from a document in scope or from the
registry text of another referenced id. Set `source_ref` verbatim; `docs` = the registry file; `part_of`
= the feature/function/component whose document referenced it (component when cross-cutting).

### Step 4 — edges
- `affects`: decision/issue → the nodes whose documents reference it.
- `resolves`: from registry text such as "resolves TBD-24", "closes", "決定により解消", or a TBD entry that
  names the D-id that closed it.
- `supersedes`: from registry text such as "supersedes D-010", "replaces", "上書き", "置き換え".
- `refines`: from registry text such as "refines D-010", "narrows", "details", "補足", "詳細化" (the earlier decision stays in force).
- `depends_on`: from explicit "depends on / requires / after / blocked by / 前提" phrasing; for
  cross-component expectations, target the providing component's function/feature; create a stub node under
  the **providing** component if it does not exist (never under the requesting one).
- Every edge target must exist; create stubs rather than dangling edges.

### Step 5 — validate, diff, write, report
Run `graph_tool.py validate` (R1 + schema). Show a before/after diff (nodes added / updated / removed / merged; edges added) in the interaction
language and ask before writing. Write with 2-space indentation, key order `$schema`, `current_node`,
`nodes`, `config`. Report nodes not rediscovered and code paths not placed under any component.

---

## `/graph:hydrate <node_id>`

Purpose: load the full 1-hop / 2-hop neighbourhood and produce the Impact Assessment Checklist
**before any code modification** (R2).

0. **Run the tool first**: `python3 ${CLAUDE_SKILL_DIR}/tools/graph_tool.py hydrate <node_id>` from the project root
   (`--dry-run` for a review that must not move `current_node`).
   It prints the whole checklist below (components, subgraph, files, constraints, re-examine set, existing
   capabilities, staleness in both layers, blast radius, unticked checks) and writes `current_node`. Present its
   output verbatim; then do the human part: read every `exists` file it listed (the tool reports `exists` /
   `MISSING`; "read" is your act, not the tool's), judge the re-examine rows, decide whether any "existing
   capabilities" candidate (name / path overlap, computed by the tool) actually covers the task, and tick the boxes.
   The "Constraints inherited" bullets carry `source_ref` + node name; the verbatim registry text is what you read
   in the `registry entry` rows of Files loaded. Steps 1–6 describe what the tool computes; do not recompute them (R9).
1. Resolve `<node_id>`; if absent, list the closest ids and stop. Do not guess.
2. Subgraph: hop 0 = the node; hop 1 = every target and every source of any edge kind
   (`part_of` both directions, `depends_on`, `affects`, `resolves`, `supersedes`, `refines`); hop 2 = same expansion
   from hop 1. Record hop distance and the edge path.
3. Read every `docs` and `code_targets` path of every node in hops 0–2 in full (ranges for large files).
   For `decision`/`issue` nodes, read the `source_ref` entry in the registry file. Note missing paths.
4. Set `current_node` = `<node_id>`.
5. Staleness (F10 + D24). Two layers:
   - **Timestamp layer**: for each node in the subgraph, compare the newest git commit touching any
     `code_targets` with the newest touching any `docs` (registry file for decision/issue). Fall back to mtime
     without git. Flag code-newer-than-docs and missing paths.
   - **Content layer (D24)** — (a) and (c) compare registry *content* with the graph; (b) is a second timestamp
     comparison against related code (reported as "parent-code layer"), not a content check:
     (a) *Registry ↔ graph*: for every `config.registries[]` entry, scan its file for ids matching `id_pattern`.
         Ids present in the file and referenced from a document in `docs_scope` but with no node → "unindexed";
         nodes whose `source_ref` is absent from the file → "orphan source_ref".
     (b) *Docs-only structural nodes* (feature / function with empty `code_targets`): compared against the newest
         change in the `code_targets` of its non-component `part_of` parent and of every node it `affects`; if that
         code is newer than the node's `docs`, flag "docs-only node behind related code" naming the source node.
         Component parents are excluded (their roots change on every commit). Decisions / issues are excluded
         (drift is tracked by the re-examine set).
     (c) *Shipped registers*: when a registry file lives inside `code_targets` of some node (e.g. a
         `references/` register shipped with code), treat it as both code and registry — (a) applies and a
         mismatch is reported against that node.
6. Output the checklist in exactly this shape:

```markdown
## Impact Assessment Checklist — <node_id>

### Components (always shown — R7)
| id | name | roots | overview doc | wip |
|----|------|-------|--------------|-----|

### Backlog (graph-wide, always shown — D33)
| kind | id | name | component | state | owner | trigger / parent | next |
|------|----|------|-----------|-------|-------|------------------|------|
Filter line + excluded counts per component; WARNING when nothing carries `next`.

### Subgraph
| hop | id | type | wip_status | path from origin |
|-----|----|------|------------|------------------|

### Files loaded
| node | kind | path | status (read / MISSING) |
|------|------|------|--------------------------|

### Constraints inherited from decisions
- <one bullet per visible decision in hops 0–2: source_ref and its Statement; folded decisions and resolved issues are hidden and
  counted ("History hidden …"); `hydrate --history` shows them>

### Decisions to re-examine
For each decision D in hops 0–1: affects(D) ∪ resolves(D) ∪ decisions that supersede / are superseded by D
∪ decisions attached (part_of) to the same feature/function.
| decision | why it may drift | related |
|----------|------------------|---------|

### Existing capabilities (R8)
Nodes across ALL components whose name / docs / code_targets overlap the task at hand.
| id | component | what it already provides |
|----|-----------|--------------------------|

### Stale docs (F10)
| node | code last changed | docs last changed | finding |
|------|-------------------|-------------------|---------|

### Blast radius
- Shared code_targets with other nodes: ...
- IN_PROGRESS / BLOCKED nodes in the subgraph: ...

### Pre-modification checks
- [ ] All hop-1 and hop-2 files read (or each MISSING row acknowledged)
- [ ] Existing capabilities reviewed; no duplicate implementation planned
- [ ] Decisions to re-examine acknowledged
- [ ] Stale docs acknowledged (will be updated in this change or logged as unresolved)
- [ ] No conflicting IN_PROGRESS work on shared code_targets
- [ ] current_node set
```

Only after every box can be ticked may code modification begin.

---

## `/graph:handover`

Purpose: the **completion gate** (D30). No handover document is written: `current_node` is the handover and the
successor's `/graph:hydrate <current_node>` output is the view. A pause is complete when `graph_tool.py gate` prints
`RESULT: OK`; until then it is not.

1. **Update the graph through the tool** (no hand edit of the JSON): `wip_status` of touched nodes (`set-status`); new
   nodes, edges, `docs`, `code_targets` found this session (`add` / `add-node`, `add-edge`, `add-doc`, `add-code`);
   `current_node` = where the next session starts (`set-current`; null only when nothing is PLANNED / IN_PROGRESS /
   BLOCKED); the `next` flag on the next item (`set-next`). Work-in-progress state goes onto nodes, never into prose
   elsewhere: what is done and the exact next edit into the node's entity (`append <node>`), anything unresolved as an
   issue with owner and trigger (`add <id> issue … --owner --trigger`, or `set-issue`).
2. **Growth check (F2')**: for each feature/function in the subgraph, propose a split when
   (a) attached decision+issue nodes ≥ `config.growth_threshold` — computed by `check`; or (b) a decision's scope covers
   only part of the node's `code_targets`, or (c) its design document gained ≥ 2 top-level sections describing separate
   behaviours — (b) and (c) are judged by hand and, when proposed, marked `(manual)`. On approval: create `function` children with `part_of` the node, move the relevant `docs`,
   `code_targets` and decision/issue attachments to them, leave the parent with overview docs only.
3. **Fold check (D31, D37)**: a candidate is a decision that is a `supersedes` target, has no other live in-edges (a `refines` in-edge is live, u46) and
   is not IN_PROGRESS / BLOCKED / FOLDED. On approval, `graph_tool.py fold <victim> <survivor>` **hides** it: the victim
   keeps its node and entity file, gets `wip_status: FOLDED`, the survivor `supersedes` it and inherits its `affects`.
   Folded decisions are hidden from hydrate by default (history count; `--history` shows them). Resolved issues need no
   fold — they are hidden by `issue_status: resolved`; transferred issues stay visible. Nothing is deleted.
4. **Staleness (F10 + D24)** as in hydrate step 5 (both layers), over the touched nodes.
5. **Fidelity (R3)** in the entity files: every explicit technical decision and its reason, every identifier chosen
   or renamed (variable, function, class, file, config key, schema field, enum value, CLI flag), the option chosen and
   the options rejected, the user's words quoted verbatim (`append`). Never "refactored X" or "various fixes".
6. **Commit** every change (the user pushes).
7. **Run `graph_tool.py gate`.** On `RESULT: FAIL` fix each FAIL row and run it again; never report the pause as
   complete while it fails. Report the gate table, every WARN row, and the resume command
   `/graph:hydrate <current_node>` to the user.

Growth and fold are proposals in the interaction language; they are never applied silently.

## `/graph:compact`

`graph_tool.py check` → present fold candidates in the interaction language → on approval
`graph_tool.py fold <victim> <survivor>` per candidate (each run re-validates). Useful after a batch of registry updates.

---

## Enforced rules

| Rule | Content |
|------|---------|
| **R1 Cross-reference validation** | Executed by `graph_tool.py validate`; the checks are: `nodes[k].id == k` (fix the key, never the id). Every target of `part_of` / `depends_on` / `affects` / `resolves` / `supersedes` / `refines` and `current_node` exists. No self-edges. `part_of` ≤ 1 and acyclic. `resolves` only decision → issue, and its target has `issue_status: resolved`; `supersedes` and `refines` only decision → decision. `source_ref` matches some `config.registries[].id_pattern` when registries are defined. Non-component `code_targets` fall under the union of component `code_targets`. Schema-valid (run `python3 -c "import json,jsonschema;jsonschema.Draft202012Validator(json.load(open('${CLAUDE_SKILL_DIR}/schema/graph_schema.json'))).validate(json.load(open('dependency_graph.json')));print('OK')"` when available; otherwise check manually and say so). Schema self-test: `python3 ${CLAUDE_SKILL_DIR}/schema/fixtures/run_fixtures.py` (positive + negative fixtures; must print all PASS). |
| **R2 Hydration** | If `dependency_graph.json` exists, never modify code before `/graph:hydrate <node_id>` of the relevant node with every pre-modification check ticked. If the node does not exist, create it first (init refresh or manual addition passing R1). If the user explicitly asks to skip, state the risk in one sentence, log the skip in Unresolved Edges, proceed. |
| **R3 Handover fidelity** | Nothing a successor needs lives outside the graph and its entity files (D30): verbatim decisions and reasons, identifiers chosen or renamed, options rejected and the user's words go into the entity of the node they concern; anything unresolved is an issue node with owner and trigger. |
| **R4 Interaction language** | Every question, recommendation table, approval request, proposal (split / fold / component) and checklist shown to the user is written in `config.interaction_language` (inferred from CLAUDE.md and the user's messages when unset). Graph contents, entity files, generated views and SKILL text stay English. |
| **R5 Structure follows design docs** | `/graph:init` never generates `task`. Decision / issue nodes exist only when referenced from a document in scope or from registry text of a referenced id. Every decision / issue is attached (`part_of`) to ≥ 1 component / feature / function. |
| **R6 Footprint** | The skill writes only to: `dependency_graph.json`, the entity files under `docs/entities/`, the generated views (`config.views[].path`), `.context/graph_tool.log`, the marked block in `CLAUDE.md`, the marked block in `.gitignore`. Never design docs, registries, source code, handover documents, `.claude/settings*.json`, or Claude memory. A write outside the footprint is refused and reported. |
| **R7 Always-visible top layer** | Hydrate output begins with the table of all `component` nodes, regardless of hop distance. |
| **R9 Numbers come from the tool** | Any id, hop, count, path status, timestamp or candidate list shown in a checklist or proposal must be copied from `graph_tool.py` output, never retyped or recomputed by hand. A pause is complete only when `graph_tool.py gate` prints `RESULT: OK` (D30). If the tool cannot run (no python3), say so and mark every such value `(manual)`. |
| **R8 No reinvention** | Before proposing any new feature or function, search `nodes` (name, docs, code_targets) across all components and present matches. Never propose a new component autonomously; that is a user decision. Violations are logged in Unresolved Edges. |
