"""Compatibility wrapper exposing SQL-first tidy dataset writer."""

from __future__ import annotations

from app.sql_dataset_store import SqlDatasetStore


class TidyDatasetWriter(SqlDatasetStore):
    """Backward-compatible alias for the SQL-backed dataset writer."""

