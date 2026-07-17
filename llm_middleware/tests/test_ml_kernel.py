"""Tests for the ML modules of the Agent Runtime Kernel."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from llm_middleware.core.persistence import PersistenceConfig, PersistenceLayer
from llm_middleware.ml.needs_engine import NeedsEngine, NeedPriority, Need
from llm_middleware.ml.reward_model import RewardModel, RewardSignal
from llm_middleware.ml.pattern_learner import PatternLearner
from llm_middleware.ml.training_loop import TrainingLoop
from llm_middleware.ml.self_improvement import SelfImprovementController


class TestMLKernel(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="llm_mw_ml_test_")
        self.config = PersistenceConfig(
            framework_dir=Path(self.tmpdir) / "db",
            db_filename="mw.db"
        )
        self.persistence = PersistenceLayer(self.config)
        self.persistence.create_project("ml_test_proj")
        
        self.needs_engine = NeedsEngine(self.persistence, "ml_test_proj")
        self.reward_model = RewardModel(self.persistence, "ml_test_proj")
        self.pattern_learner = PatternLearner(self.persistence, "ml_test_proj")
        self.training_loop = TrainingLoop(self.persistence, "ml_test_proj")
        self.controller = SelfImprovementController(self.persistence, "ml_test_proj")

    def tearDown(self):
        self.persistence.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ─── Needs Engine Tests ───────────────────────────────────────────────

    def test_needs_engine_detects_failure_patterns(self):
        # Insert execution logs indicating high failure rate for task "test_task"
        for _ in range(5):
            self.persistence.add_log_entry("ml_test_proj", {
                "task": "test_task",
                "outcome": "failure",
                "agent": "test_agent"
            })
            
        needs = self.needs_engine.scan()
        # Should detect correctness need
        self.assertTrue(any(n.category == "correctness" for n in needs))
        
        active = self.needs_engine.get_active_needs()
        self.assertTrue(len(active) >= 1)
        self.assertEqual(active[0].category, "correctness")
        self.assertTrue("failure_detector" in active[0].source)

    def test_needs_engine_resolve_and_escalate(self):
        need = Need(
            need_id="test_need_123",
            project="ml_test_proj",
            category="knowledge",
            description="Test need",
            priority=NeedPriority.OPTIONAL,
            source="manual",
            evidence={}
        )
        self.needs_engine._persist(need)
        
        active_before = self.needs_engine.get_active_needs()
        self.assertEqual(len(active_before), 1)
        
        # Resolve it
        self.needs_engine.resolve(need.need_id)
        active_after = self.needs_engine.get_active_needs()
        self.assertEqual(len(active_after), 0)

    # ─── Reward Model Tests ───────────────────────────────────────────────

    def test_reward_model_scores_success_highly(self):
        signal = RewardSignal(
            project="ml_test_proj",
            task="evaluation",
            outcome="success",
            gate_passed=True,
            duration_seconds=2.0
        )
        breakdown = self.reward_model.score(signal)
        self.assertGreaterEqual(breakdown.final, 0.8)

    def test_reward_model_scores_failure_lowly(self):
        signal = RewardSignal(
            project="ml_test_proj",
            task="evaluation",
            outcome="failure",
            gate_passed=False,
            duration_seconds=50.0
        )
        breakdown = self.reward_model.score(signal)
        self.assertLessEqual(breakdown.final, 0.4)

    # ─── Pattern Learner Tests ────────────────────────────────────────────

    def test_pattern_learner_stores_and_retrieves(self):
        self.pattern_learner.store(
            task="optimize database performance",
            skill_used="db-opt",
            approach="added index",
            outcome="success",
            score=0.85
        )

        matches = self.pattern_learner.retrieve("optimizing database index")
        self.assertEqual(len(matches), 1)
        record, sim = matches[0]
        self.assertEqual(record.skill_used, "db-opt")
        self.assertEqual(record.approach, "added index")

    # ─── Training Loop & Self-Improvement Controller Tests ────────────────

    def test_training_loop_cycle(self):
        # Create a need manually
        need = Need(
            need_id="stale_need",
            project="ml_test_proj",
            category="knowledge",
            description="Stale domain: data",
            priority=NeedPriority.IMPORTANT,
            source="manual",
            evidence={"domain": "data", "stale_count": 5}
        )
        self.needs_engine._persist(need)
        
        # Run one cycle
        result = self.training_loop.run_cycle()
        self.assertEqual(result.needs_addressed, 1)
        self.assertEqual(result.needs_resolved, 1)
        
        # Check if the fact "stale_flag:data" was set in the ml domain
        flag = self.persistence.get_fact("ml_test_proj", "ml", "stale_flag:data")
        self.assertIsNotNone(flag)
        self.assertTrue(flag["needs_refresh"])

    def test_controller_safety_stop_on_degrading_rewards(self):
        """
        Integration test — not just _compute_trend, but the full loop.

        We patch RewardModel.score so every cycle returns a low score
        (below SAFETY_THRESHOLD=0.20). After 3 consecutive low-reward cycles,
        run() must:
          1. Break early (cycles_run < requested cycles).
          2. Persist a CRITICAL Need of category "runtime" in the DB.
        """
        from unittest.mock import patch
        from llm_middleware.ml.reward_model import ScoreBreakdown
        from llm_middleware.ml.needs_engine import NeedPriority

        # Create enough Needs so the loop has fuel for 3+ reward-recording cycles.
        # MAX_NEEDS_PER_CYCLE=5, so we need > 5 to survive past cycle 1.
        for i in range(12):
            need = Need(
                need_id=f"degrading_need_{i}",
                project="ml_test_proj",
                category="knowledge",
                description=f"Low-reward need {i}",
                priority=NeedPriority.IMPORTANT,
                source="manual",
                evidence={"domain": f"domain_{i}"}
            )
            # Inject into the controller's own needs_engine (same instance used by run())
            self.controller.needs_engine._persist(need)

        # Every RewardModel.score call returns 0.05 — well below the 0.20 threshold
        low_breakdown = ScoreBreakdown(
            outcome_score=0.0,
            gate_score=0.0,
            efficiency_score=0.1,
            knowledge_score=0.0,
            feedback_score=0.5,
            final=0.05,
        )

        with patch.object(
            self.controller.training_loop.reward_model, "score", return_value=low_breakdown
        ):
            summary = self.controller.run(cycles=10)

        # 1. Loop must have stopped early — requested 10 but safety triggered by cycle 3+
        self.assertLessEqual(summary.cycles_run, 7,
            "Safety stop should break the loop well before 10 cycles")

        # 2. A CRITICAL need of category 'runtime' must exist in the DB.
        #    Read from the same NeedsEngine instance the controller used.
        active = self.controller.needs_engine.get_active_needs()
        critical = [n for n in active
                    if n.priority == NeedPriority.CRITICAL and n.category == "runtime"]
        self.assertTrue(
            len(critical) >= 1,
            f"Expected a CRITICAL runtime Need after safety stop, got: {active}"
        )
        self.assertIn("Human review required", critical[0].description)


    def test_compute_trend_degrading(self):
        """Unit test for the private trend calculator — kept separately."""
        self.assertEqual(self.controller._compute_trend([0.9, 0.5, 0.2]), "degrading")
        self.assertEqual(self.controller._compute_trend([0.2, 0.5, 0.8]), "improving")
        self.assertEqual(self.controller._compute_trend([0.5, 0.5, 0.5]), "stable")


if __name__ == "__main__":
    unittest.main()
