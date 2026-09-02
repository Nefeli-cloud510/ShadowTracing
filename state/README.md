This directory stores project-relative workflow state snapshots.

Generated files:
- `task.json`
- `hypothesis_tree.json`
- `uncertainties.json`
- `uncertainty_priority.json`
- `experiment_memory.json`
- `process.json`
- `decision_log.json`
- `candidate_experiments.json`
- `planner_input.json`
- `planner_output.json`

These files are written by the unified state repository and updater so the
execution/evaluation pipeline can feed the knowledge-memory layer, the
reasoning planner, and the next-round candidate generator.

Audit guidance:
- Use `AUDIT_CHECKLIST.md` after two full rounds of execution.
- The required audit targets are `hypothesis_tree.json`, `uncertainties.json`,
  `experiment_memory.json`, `decision_log.json`, `planner_input.json`, and
  `planner_output.json`.
- The end-to-end audit can be verified with:

```bash
python -m unittest tests.test_system_audit_closure -v
```
