---
name: protocol
description: Graph-based project context management (protocol skill of the `graph` plugin, invoked as /graph:protocol). Keeps dependency_graph.json as a schema-validated index over a project's components, design documents and decision/issue registries, forces 1-hop/2-hop hydration before code changes, and writes lossless handovers. Commands are /graph:install, /graph:uninstall, /graph:init, /graph:hydrate <node_id>, /graph:handover, /graph:compact. Also triggers on "dependency graph", "hydrate node", "handover", "WIP handover", "context graph", "graph init", "compact graph".
---

# graph-context

> Status: **v3.2.0 (2026-09-24 — D26 protocol as code: `tools/graph_tool.py` executes R1, hydrate, check, handover tables, fold, split; rule R9; v3.1.1 = D24/D25; v3.1.0 = plugin `graph`; v3.0.0 = plugin packaging)**
> Long-form material (full data model, public decision register D1–D34) lives in `${CLAUDE_SKILL_DIR}/references/`.

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
| `${CLAUDE_SKILL_DIR}/tools/graph_tool.py` | **The executable protocol (D26).** Read-only: `validate`, `check`, `handover-tables [--verify F]`, `lint-prose`, `lint-handover F`, `hydrate --dry-run`. Writing: `hydrate <node>` (current_node), `fold`, `split`, `set-status`, `add-edge`, `set-current`, `add-node`, `add-doc`, `add-code`. Every number, id, hop, path status and timestamp shown to the user comes from this tool (R9). Full list: `tools/README.md`. |
| `${CLAUDE_PLUGIN_ROOT}/skills/{install,uninstall,init,hydrate,handover,compact}/SKILL.md` | Six thin delegating skills → `/graph:<name>` (D16, D21). Each reads this file and executes the matching section. |
| `config.handover_path` (default `.context/WIP_HANDOVER.md`) | Handover written by `/graph:handover`. |

## Data model (summary; schema is authoritative)

**Root** is closed: `current_node`, `nodes`, `config` only.

**Hierarchy**: Root → `component` → `feature` → `function`. `decision` and `issue` nodes attach to a
component, feature or function. `task` exists for manual use and is never generated.

**Node fields**: required `id`, `type`, `name`, `docs[]`, `code_targets[]`. Optional edges:
`part_of` (≤1, child → parent), `depends_on`, `affects`, `resolves` (decision → issue only),
`supersedes` (decision → decision only). Optional `source_ref` (registry id, decision/issue only,
single-valued), `folded[]` (registry ids absorbed by compaction, decision only), `wip_status`.

**Edge direction conventions**

| Relation | Edge |
|----------|------|
| feature belongs to component / function belongs to feature | child `part_of` parent |
| feature needs another feature | `depends_on` |
| feature/function expects something from another component | `depends_on` → that component's function/feature node |
| issue impacts a feature/function/component | issue `affects` target |
| decision constrains a feature/function/component | decision `affects` target |
| decision resolves an issue | decision `resolves` issue |
| decision replaces or refines an earlier decision | decision `supersedes` earlier decision |
| issue was raised by a decision | issue `depends_on` decision |

**`config` keys**

| Key | Default | Meaning |
|-----|---------|---------|
| `interaction_language` | inferred | language for every question, recommendation, approval, checklist shown to the user |
| `handover_path` | `.context/WIP_HANDOVER.md` | where `/graph:handover` writes |
| `design_root` | detected | directory whose document structure the feature/function layer mirrors |
| `docs_scope` | `<design_root>/**/*.md` | globs `/graph:init` reads |
| `registries[]` | `[]` | `{type, id_pattern, file}`: how decision/issue ids are recognised and where their text lives |
| `growth_threshold` | 5 | attached decision+issue count at which a split is proposed |
| `install` | set by install | sha256 snapshots for uninstall verification |

Not in config, by decision: `code_roots` (derived: union of component nodes' `code_targets`),
`project_name`, `version` (git / CLAUDE.md own them).

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
   - When ending a session or pausing work, run `/graph:handover` to generate the handover at `config.handover_path`. Never write lossy, generic summaries.
   - Registry mapping (decision / issue ids → files) = `dependency_graph.json` → `config.registries`.
   <!-- graph-context:end -->
   ```
5. Append to `.gitignore` (create if absent) exactly one marked block:
   ```
   # graph-context:begin
   .context/
   # graph-context:end
   ```
   Omit the `.context/` line if `config.handover_path` will live in a tracked directory; keep the markers.
6. Write `config.install` `{installed_at, skill_version, claude_md_sha256_before, gitignore_sha256_before}`; `skill_version` = `version` in `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`.
7. Print the footprint (every path created or modified). Ask, in the interaction language, before writing anything.

## `/graph:uninstall`

1. Compute the footprint: `dependency_graph.json`, the file at `config.handover_path`, `graph_tool.log` in the same directory
   (and `.context/` if that is its directory and it is otherwise empty), the marked block in `CLAUDE.md`,
   the marked block in `.gitignore`.
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
   - `handover_path`: if the repo already commits handover documents under a docs folder, recommend
     `<that folder>/WIP_HANDOVER.md` (tracked); otherwise `.context/WIP_HANDOVER.md` (ignored).
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
If the graph exists, validate it (R1). Preserve `current_node`, `wip_status`, `part_of`, `folded`, `config`
unless `--reset-structure` (which discards `part_of` and `folded` and re-proposes splits/folds under the
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
   (`part_of` both directions, `depends_on`, `affects`, `resolves`, `supersedes`); hop 2 = same expansion
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
         nodes whose `source_ref` is absent from the file → "orphan source_ref"; a node whose `folded[]` id is
         absent from the file → "folded id lost".
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

### Subgraph
| hop | id | type | wip_status | path from origin |
|-----|----|------|------------|------------------|

### Files loaded
| node | kind | path | status (read / MISSING) |
|------|------|------|--------------------------|

### Constraints inherited from decisions
- <one bullet per decision in hops 0–2: source_ref, what it fixes verbatim, folded ids if any>

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

Purpose: persist the exact state of work so a fresh session resumes with zero re-discovery.

0. **Tool sequence, in this order** (the tables must be generated *after* the graph is final):
   (i) graph updates via the tool — `set-status`, `add-edge`, `set-current`, `add-node`, `add-doc`, `add-code`
   (no hand edit of the JSON in the normal flow; if one is ever needed, run `validate` right after) →
   (ii) `check` (growth / fold / staleness; proposals in the interaction language) → (iii) approved proposals via
   `fold <victim> <survivor>` / `split <node> <child>=<ids>` → (iv) `validate` → (v) `handover-tables`, pasted verbatim
   into §2, §6, §7 (D25) → (vi) `handover-tables --verify <handover file>` must print `RESULT: OK` before the handover
   is declared written (U14: it compares the pasted blocks and the footer md5 with the current graph) →
   (vii) `lint-handover <handover file>` must print `RESULT: OK` (free-text cross-checks: §1 states current_node and
   mentions every commit since the footer HEAD, §5 names current_node, §4 lists no resolved id that still has a row, one
   footer, header stamped by the tool, no empty action on a flagged §7 row) → (viii) `lint-prose` whenever skill prose
   was edited this session (U15). **Generation is the last step**: any commit *or any edit of a docs / code path* after (v) moves
   timestamps and (vi) will report drift (as WARN with a diagnosis when the graph md5 is unchanged). Before regenerating,
   copy the previous handover to `<handover>.prev.md` and run `lint-handover --prev` so no U-id disappears silently. Every write appends to `graph_tool.log` (with graph md5 before → after) next to the handover file;
   `handover-tables` prints that log as the session history for §6. The header `Generated:` line is copied from the
   stamp `handover-tables` prints, never typed. Free text (§1, §3, §4, §5, the "why it matters" / "note" / "action"
   columns) is written by hand, from the session.
1. **Update the graph**: `current_node` (or null if complete); `wip_status` of touched nodes; new edges,
   nodes, `docs`, `code_targets` discovered this session; validate (R1) with `graph_tool.py validate`.
2. **Growth check (F2')**: for each feature/function in the subgraph, propose a split when
   (a) attached decision+issue nodes ≥ `config.growth_threshold` — computed by `check`; or (b) a decision's scope covers
   only part of the node's `code_targets`, or (c) its design document gained ≥ 2 top-level sections describing separate
   behaviours — (b) and (c) are judged by hand and, when proposed, marked `(manual)`. On approval: create `function` children with `part_of` the node, move the relevant `docs`,
   `code_targets` and decision/issue attachments to them, leave the parent with overview docs only.
3. **Fold check (F7 = C)**: candidates are (i) a decision that is a `supersedes` target and has no other live
   in-edges, (ii) an issue that is a `resolves` target and has no other live in-edges. Never fold a node with
   `wip_status` IN_PROGRESS or BLOCKED. On approval: survivor.`folded` += folded `source_ref`s;
   survivor.`affects` ∪= folded.`affects`; survivor.`docs` ∪= folded.`docs`; delete the folded node and edges
   to it. Text stays in the registry, so nothing is lost overall.
4. **Staleness (F10 + D24)** as in hydrate step 5 (both layers), over the touched nodes.
5. **Write the handover** to `config.handover_path` (create the directory if needed; overwrite; the graph is
   the durable history, the handover is the live pointer) using the template below.
   **Generated, not hand-written (D25)**: the Components table and the Subgraph table of §2, the node counts and
   the growth / fold result lines of §6, and the timestamp columns of §7 are derived mechanically from
   `dependency_graph.json` (same hop algorithm as hydrate step 2, all edge kinds both directions). The writer
   may fill only the free-text columns ("why it matters", "note", "action"). Never retype ids, hop numbers, counts
   or timestamps by hand; if a row is added manually it must be marked `(manual)`.
6. **Fidelity (R3)**: preserve verbatim every explicit technical decision and its reason, every identifier
   chosen or renamed (variable, function, class, file, config key, schema field, enum value, CLI flag), and
   every edge discussed but not resolved. Name the option chosen and the options rejected. Never write
   "refactored X" or "various fixes". Empty sections are written as `- none`.

Growth and fold are proposals in the interaction language; they are never applied silently.

### Handover template

```markdown
# WIP HANDOVER — <project name>
Generated: <copied verbatim from the `Generated:` stamp line that `handover-tables` prints — ISO time, `by graph_tool @<head>`, graph md5>
Schema: plugin graph v<version> `schema/graph_schema.json`

## 1. Active Task Pointer
- current_node: `<node_id>` (`<type>`, wip_status: `<status>`), part_of: `<parent>` → `<component>`
- Name: <node.name>
- Goal in one sentence, as stated by the user: "<verbatim>"
- Work completed this session (file-level):
  - `<path>`: <what changed>
- Work NOT yet done:
  - <item> (if it depends on a file that is untracked / local-only, say so: a fresh session may not have it)

## 2. Components and Subgraph Context Range
### Components (R7)
| id | name | roots | overview doc | wip |
|----|------|-------|--------------|-----|
### Subgraph (re-hydrate with `/graph:hydrate <current_node>`) — pasted from `handover-tables`
| hop | id | type | wip_status | path from origin | why it matters |
|-----|----|------|------------|------------------|----------------|
Files read outside the subgraph (candidates to add to the graph):
- `<path>` — <reason>

## 3. Hard Decisions Log
Legend: `#` = order reached this session (not a registry id). `—` in "Fixed identifiers" = no new identifier introduced. Quote the user verbatim in "Reason"; a paraphrase must be marked as such.
| # | Decision | Chosen | Rejected alternatives | Reason (as stated) | Fixed identifiers | Registry id (if logged) |
|---|----------|--------|-----------------------|--------------------|-------------------|-------------------------|

## 4. Unresolved Edges
Resolved this session and removed from this table: <ids and how, or `- none`>
| # | From node | To node / file | Kind | What is unresolved | Who or what resolves it (and when / on what trigger) |
|---|-----------|----------------|------|--------------------|-------------------------|

## 5. Immediate Resume Trigger
1. Run `/graph:hydrate <current_node>` and confirm the checklist matches section 2.
2. Open `<path>` at `<symbol or line>`; the next edit is: <precise description>.
3. Run: `<command>`; expect: <expected output>.
4. Blocking question for the user, if any: "<verbatim question>"

## 6. Decision Drift
Decisions changed this session and their re-examine sets (see hydrate "Decisions to re-examine").
| changed decision | related node | resolved / unresolved | note |
|------------------|--------------|-----------------------|------|
Current state (from `handover-tables`): node counts · growth check · fold check.
Session history (from `handover-tables` → operations log): every fold / split / set-status / add-edge / set-current this session, with accepted / declined noted by hand for proposals that were not applied.

## 7. Staleness
| node | code last changed | docs last changed | finding | action |
|------|-------------------|-------------------|---------|--------|
```

## `/graph:compact`

`graph_tool.py check` → present fold candidates in the interaction language → on approval
`graph_tool.py fold <victim> <survivor>` per candidate (each run re-validates). Useful after a batch of registry updates.

---

## Enforced rules

| Rule | Content |
|------|---------|
| **R1 Cross-reference validation** | Executed by `graph_tool.py validate`; the checks are: `nodes[k].id == k` (fix the key, never the id). Every target of `part_of` / `depends_on` / `affects` / `resolves` / `supersedes` and `current_node` exists. No self-edges. `part_of` ≤ 1 and acyclic. `resolves` only decision → issue; `supersedes` only decision → decision. `source_ref` matches some `config.registries[].id_pattern` when registries are defined. Non-component `code_targets` fall under the union of component `code_targets`. Schema-valid (run `python3 -c "import json,jsonschema;jsonschema.Draft202012Validator(json.load(open('${CLAUDE_SKILL_DIR}/schema/graph_schema.json'))).validate(json.load(open('dependency_graph.json')));print('OK')"` when available; otherwise check manually and say so). Schema self-test: `python3 ${CLAUDE_SKILL_DIR}/schema/fixtures/run_fixtures.py` (positive + negative fixtures; must print all PASS). |
| **R2 Hydration** | If `dependency_graph.json` exists, never modify code before `/graph:hydrate <node_id>` of the relevant node with every pre-modification check ticked. If the node does not exist, create it first (init refresh or manual addition passing R1). If the user explicitly asks to skip, state the risk in one sentence, log the skip in Unresolved Edges, proceed. |
| **R3 Handover fidelity** | Sections 1–7 mandatory; verbatim decisions, identifiers, unresolved edges; empty = `- none`. §3 carries its legend; §4 opens with the "Resolved this session" line; every "who resolves" names a trigger or says none (D19). §2 tables, §6 counts/results and §7 timestamps are generated from the graph, never retyped (D25). |
| **R4 Interaction language** | Every question, recommendation table, approval request, proposal (split / fold / component) and checklist shown to the user is written in `config.interaction_language` (inferred from CLAUDE.md and the user's messages when unset). Graph contents, handover file, SKILL text stay English. |
| **R5 Structure follows design docs** | `/graph:init` never generates `task`. Decision / issue nodes exist only when referenced from a document in scope or from registry text of a referenced id. Every decision / issue is attached (`part_of`) to ≥ 1 component / feature / function. |
| **R6 Footprint** | The skill writes only to: `dependency_graph.json`, `graph_tool.log` and `<handover>.prev.md` (next to the handover file), the file at `config.handover_path`, the marked block in `CLAUDE.md`, the marked block in `.gitignore`. Never design docs, registries, source code, other handover files, `.claude/settings*.json`, or Claude memory. A write outside the footprint is refused and reported. |
| **R7 Always-visible top layer** | Hydrate output and handover §2 begin with the table of all `component` nodes, regardless of hop distance. |
| **R9 Numbers come from the tool** | Any id, hop, count, path status, timestamp or candidate list shown in a checklist, proposal or handover must be copied from `graph_tool.py` output, never retyped or recomputed by hand. Keep exactly one tool footer line (`<!-- graph_tool <cmd> @<head> graph md5 … -->`) at the end of the handover, the one printed by the final `handover-tables` run, so the paste can be traced to a graph state; `handover-tables --verify` checks it mechanically. If the tool cannot run (no python3), say so and mark every such value `(manual)`. |
| **R8 No reinvention** | Before proposing any new feature or function, search `nodes` (name, docs, code_targets) across all components and present matches. Never propose a new component autonomously; that is a user decision. Violations are logged in Unresolved Edges. |
