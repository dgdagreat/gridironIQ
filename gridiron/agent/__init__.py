"""GridironIQ scouting agent — natural-language questions over the warehouse.

Claude answers cap/roster questions by writing read-only SQL against the DuckDB
warehouse (the dbt marts) through a `run_sql` tool, then explaining the numbers.
"""
from gridiron.agent.scout import ScoutAgent, ScoutResult

__all__ = ["ScoutAgent", "ScoutResult"]
