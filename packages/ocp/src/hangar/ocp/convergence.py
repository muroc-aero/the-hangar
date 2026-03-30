"""Optimization convergence tracking for OpenConcept."""

from __future__ import annotations

from typing import Any

import openmdao.api as om


def extract_convergence_data(prob: om.Problem) -> dict:
    """Extract convergence information from an optimization run.

    Returns a dict with iteration count, objective history, and constraint status.
    """
    data: dict = {}

    driver = prob.driver
    if hasattr(driver, "iter_count"):
        data["num_iterations"] = driver.iter_count

    return data
