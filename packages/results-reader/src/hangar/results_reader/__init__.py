"""hangar-results-reader: read-only access to the hangar analysis DB.

Dependency-free seam over the SQLite analysis/provenance database written
by ``hangar.omd``. Lets consumers read run results and provenance without
OpenMDAO as a transitive dependency.
"""

from __future__ import annotations

from hangar.results_reader.db import (
    KNOWN_ENTITY_TYPES,
    KNOWN_PROV_RELATIONS,
    get_db_path,
    init_analysis_db,
    query_entity,
    query_provenance_dag,
    query_run_results,
)

__all__ = [
    "KNOWN_ENTITY_TYPES",
    "KNOWN_PROV_RELATIONS",
    "get_db_path",
    "init_analysis_db",
    "query_entity",
    "query_provenance_dag",
    "query_run_results",
]
