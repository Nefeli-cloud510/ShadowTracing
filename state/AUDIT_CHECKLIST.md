# Two-Round Audit Checklist

Use this checklist after completing two full rounds of the closed loop:

`candidate -> protocol -> execution -> evaluation -> disagreement_updates -> next planner_input -> next candidate`

## Required State Files

- `hypothesis_tree.json`
- `uncertainties.json`
- `experiment_memory.json`
- `decision_log.json`
- `planner_input.json`
- `planner_output.json`

## File-Level Consistency Checks

### `hypothesis_tree.json`

- `task_id` matches the current scientific task.
- `nodes` is non-empty and every node has a unique `hypothesis_id`.
- `active_hypotheses`, `pruned_hypotheses`, and `pending_hypotheses` only reference ids present in `nodes`.
- After planner writeback, `latest_update.event` is `planner_output_applied`.
- At least one hypothesis remains in `active_hypotheses` to keep the next round explorable.

### `uncertainties.json`

- `task_id` matches `hypothesis_tree.json`.
- Every `related_hypotheses` id exists in `hypothesis_tree.json`.
- `resolution_status`, when present, is one of `resolved`, `partially_resolved`, or `unresolved`.
- If an uncertainty is `resolved`, `resolving_experiment` and `resolved_at_round` are both present.
- Every item in `priority_queue.queue` points to an uncertainty whose `status` is not `resolved` or `deprecated`.
- `history` contains evaluation or disagreement-related updates after execution.

### `experiment_memory.json`

- Contains entries for the executed experiment ids from round 1 and round 2.
- Each executed entry has `reasoning_traces`.
- Trace-linked hypothesis ids and uncertainty ids exist in `hypothesis_tree.json` and `uncertainties.json`.

### `decision_log.json`

- Includes at least two `round_review_requested` decisions.
- Includes at least two `planner_input_prepared` decisions.
- Includes at least two `planner_output_generated` decisions.
- Includes at least two `planner_output_applied` decisions.
- Includes both a human adjustment path such as `round_adjusted` and a continuation path such as `continue_next_round`.

### `planner_input.json`

- `source_round_id` equals the just-finished round.
- `next_round_id` equals `source_round_id + 1`.
- `recent_disagreement_updates` is non-empty after the second round.
- `unresolved_uncertainties` is non-empty and each `uncertainty_id` exists in `uncertainties.json`.

### `planner_output.json`

- `source_round_id` and `next_round_id` match `planner_input.json`.
- `candidate_supplements`, `interpretation_enhancements`, and `protocol_refinements` are all present.
- Every supplemented candidate id exists in the rebuilt `candidate_experiments.json`.

## Cross-File Closure Checks

- The executed experiment ids referenced in `experiment_memory.json`, `decision_log.json`, and evaluation traces are the same ids produced from approved candidates.
- The uncertainty ids mentioned by `planner_input.json.recent_disagreement_updates` exist in `uncertainties.json`.
- Planner interpretation updates leave auditable traces in both `experiment_memory.json` and `decision_log.json`.
- The next-round candidate plan still references valid uncertainty ids and hypothesis-derived context.

## Automated Verification

Run:

```bash
python -m unittest tests.test_system_audit_closure -v
```

This test suite checks the two-round closure and the file self-consistency rules above.
