"""Unit tests for convergence tracking enhancements.

Migration: upstream/OpenAeroStruct/oas_mcp/tests/test_convergence.py
Import mapping:
    oas_mcp.core.convergence → hangar.oas.convergence
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import numpy as np
import pytest

from hangar.oas.convergence import OptimizationTracker, summarize_convergence_history


# ---------------------------------------------------------------------------
# summarize_convergence_history
# ---------------------------------------------------------------------------


class TestSummarizeConvergenceHistory:
    def test_truncates_long_history(self):
        n = 200
        history = {
            "num_iterations": n,
            "objective_values": list(range(n)),
            "dv_history": {"twist": [list(range(3))] * n},
            "constraint_history": {"CL": [0.5] * n},
            "solver_history": {"solver_iterations": [{"driver_iter": i, "residuals": [1e-3]} for i in range(n)]},
        }
        result = summarize_convergence_history(history, max_iters=50)

        assert result["truncated"] is True
        assert result["full_num_iterations"] == 200
        assert len(result["objective_values"]) == 50
        assert len(result["dv_history"]["twist"]) == 50
        assert len(result["constraint_history"]["CL"]) == 50
        # Solver history excluded from summary
        assert "solver_history" not in result
        # Last 50 entries preserved
        assert result["objective_values"][0] == 150

    def test_no_truncation_when_under_limit(self):
        history = {
            "num_iterations": 30,
            "objective_values": list(range(30)),
            "dv_history": {"alpha": [[5.0]] * 30},
            "constraint_history": {"CL": [0.5] * 30},
        }
        result = summarize_convergence_history(history, max_iters=50)

        assert "truncated" not in result
        assert len(result["objective_values"]) == 30

    def test_does_not_mutate_input(self):
        history = {
            "num_iterations": 100,
            "objective_values": list(range(100)),
            "dv_history": {},
            "constraint_history": {},
            "solver_history": {"solver_iterations": []},
        }
        original_len = len(history["objective_values"])
        summarize_convergence_history(history, max_iters=20)
        assert len(history["objective_values"]) == original_len
        assert "solver_history" in history

    def test_empty_history(self):
        history = {
            "num_iterations": 0,
            "objective_values": [],
            "dv_history": {},
            "constraint_history": {},
        }
        result = summarize_convergence_history(history)
        assert result["num_iterations"] == 0
        assert result["objective_values"] == []


# ---------------------------------------------------------------------------
# OptimizationTracker — unit tests with mocking
# ---------------------------------------------------------------------------


class TestOptimizationTrackerWarnings:
    @pytest.fixture(autouse=True)
    def _enable_propagation(self):
        """Ensure the hangar logger propagates so caplog can capture."""
        hangar_logger = logging.getLogger("hangar")
        old = hangar_logger.propagate
        hangar_logger.propagate = True
        yield
        hangar_logger.propagate = old

    def test_record_initial_logs_warning_on_failure(self, caplog):
        """record_initial should log a warning when a DV path fails."""
        tracker = OptimizationTracker()

        class FakeProb:
            def get_val(self, path):
                raise KeyError(f"Unknown variable: {path}")

        with caplog.at_level(logging.WARNING):
            result = tracker.record_initial(FakeProb(), {"twist": "wing.twist_cp"})

        assert result == {}
        assert any("Failed to read initial DV" in msg for msg in caplog.messages)

    def test_attach_logs_warning_when_recorder_unavailable(self, caplog):
        """attach should log a warning when SqliteRecorder import fails."""
        tracker = OptimizationTracker()

        with patch.dict("sys.modules", {"openmdao": None, "openmdao.api": None}):
            with caplog.at_level(logging.WARNING):
                success = tracker.attach(object())

        assert success is False
        assert any("SqliteRecorder unavailable" in msg for msg in caplog.messages)

    def test_extract_logs_warning_on_failure(self, caplog):
        """extract should log a warning (not silently return) on failure."""
        tracker = OptimizationTracker()
        # Set a recorder but no valid tmp_path
        tracker._recorder = object()
        tracker._tmp_path = "/nonexistent/path.sql"

        with caplog.at_level(logging.WARNING):
            result = tracker.extract({"twist": "wing.twist_cp"}, "aero.CD")

        assert result["num_iterations"] == 0


class TestConstraintArrayReduction:
    def test_array_constraint_reduced_to_max_abs(self):
        """Array-valued constraints (e.g. failure) should be reduced to max(abs())."""
        # We test the reduction logic directly
        arr = np.array([[-0.3, 0.8], [0.1, -0.9], [0.2, 0.5]])
        # The tracker should store max(abs(arr)) = 0.9
        scalar = float(np.max(np.abs(arr)))
        assert scalar == pytest.approx(0.9)

    def test_scalar_constraint_passes_through(self):
        """Single-element constraints should pass through as-is."""
        arr = np.array([0.5])
        scalar = float(arr.ravel()[0])
        assert scalar == pytest.approx(0.5)


class TestBackwardCompatNoConstraints:
    def test_extract_without_constraint_path_map(self):
        """Calling extract() without constraint_path_map should return old-style dict."""
        tracker = OptimizationTracker()
        # No recorder attached — should return empty dict with constraint_history
        result = tracker.extract({"twist": "wing.twist_cp"}, "aero.CD")
        assert "num_iterations" in result
        assert "objective_values" in result
        assert "dv_history" in result
        assert "constraint_history" in result
        assert result["constraint_history"] == {}
