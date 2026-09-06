import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.decision_unified import _tree_is_frozen_for
from core.state_repository import UnifiedStateRepository
from core.unified_schema import (
    DecisionEntry,
    DecisionLog,
    EvaluationSpec,
    HypothesisTreeState,
    LatestTreeUpdate,
    ResearchQuestion,
    ScientificConstraints,
    ScientificTask,
    ScientificTaskPayload,
)


class TreeFreezeGuardTest(unittest.TestCase):
    def test_decision_log_keeps_post_process_tree_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = UnifiedStateRepository(Path(tmp))
            task = ScientificTask(
                task_id="ST_FREEZE_1",
                payload=ScientificTaskPayload(
                    research_question=ResearchQuestion(
                        text="shadow offset predicts solar wind?",
                        target="Vsw",
                        question_type="forecasting",
                    ),
                    evaluation=EvaluationSpec(
                        primary_metric="RMSE",
                        secondary_metrics=["Pearson_r"],
                    ),
                    constraints=ScientificConstraints(),
                ),
            )
            tree = HypothesisTreeState(
                tree_id=f"{task.task_id}_tree",
                task_id=task.task_id,
                current_round=1,
                root_question=task.payload.research_question.text,
                latest_update=LatestTreeUpdate(
                    round=1,
                    event="state_machine_reconciliation",
                    description="reconcile ran after questioning",
                ),
            )
            repo.save_hypothesis_tree(tree)
            _ = repo.load_hypothesis_tree()

            decision_log = DecisionLog(
                task_id=task.task_id,
                decisions=[
                    DecisionEntry(
                        timestamp=datetime.now(),
                        round_id=1,
                        decision_type="hypothesis_tree_confirmed",
                        made_by="human_pi",
                        summary="tree frozen",
                    )
                ],
            )
            repo.save_decision_log(decision_log)
            loaded_log = repo.load_decision_log()

            self.assertTrue(_tree_is_frozen_for(tree, 1, loaded_log))
            self.assertFalse(_tree_is_frozen_for(tree, 2, loaded_log))


if __name__ == "__main__":
    unittest.main()
