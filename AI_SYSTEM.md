# AI Change Planning & Transactional Apply

## Plan first, mutate never

Every conversational AI pack request goes through **`plan_ai_change`**
(`engine/plan.py`) — a deterministic, non-mutating planner:

1. interprets the request (`add more bosses` → verb `add`, feature `bosses`)
2. diffs against the pack's current features and identity
3. proposes concrete changes: mods added / removed, shader change, RAM target
4. estimates impact: mods, dependencies, RAM, **confidence**, **risk**
5. records what is **preserved** (core theme, locked mods)

The UI shows the plan (Ask AI → plan preview with **APPLY & TEST** /
**MODIFY PLAN** / **CANCEL**) before anything is built.

## Transactional apply

`apply_ai_change(build_id, prompt)` implements the §14 transaction rule:

1. **snapshot** the current pack (`before-ai-edit`)
2. **start a candidate build** (a child build marked `candidateOf`)
3. the candidate runs the full real pipeline (search → solve → download →
   test → repair → export)
4. **on PASS**: `_promote_candidate` merges the validated state into the
   parent (selections, graph, test evidence, identity, instance files) and
   records a `promote` entry in `aiHistory`
5. **on FAIL**: the parent is untouched and a `rejected` entry is recorded
   with the reason

Because the candidate is a real build with its own build dir, a failed edit
leaves the working pack exactly as it was — the definition of a transaction.
All of this is deterministic; no LLM is required for the safety machinery.

Implementation: `engine/plan.py` + `PyEngine.apply_ai_change` /
`_promote_candidate` in `engine/service.py`. Tested in
`identity_snapshots_test.py` (promotion + rejection paths) and the UI test.
