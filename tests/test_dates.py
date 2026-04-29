"""Tests for _dates.resolve_date_params."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from oura_mcp._dates import resolve_date_params


def test_single_date_maps_to_start_and_end():
    p = resolve_date_params("2026-04-01", None, None)
    assert p == {"start_date": "2026-04-01", "end_date": "2026-04-01"}


def test_explicit_range_passes_through():
    p = resolve_date_params(None, "2026-04-01", "2026-04-07")
    assert p == {"start_date": "2026-04-01", "end_date": "2026-04-07"}


def test_only_start_date_defaults_end_to_today():
    with patch("oura_mcp._dates._date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 29)
        p = resolve_date_params(None, "2026-04-01", None)
    assert p == {"start_date": "2026-04-01", "end_date": "2026-04-29"}


def test_only_end_date_defaults_start_to_today():
    with patch("oura_mcp._dates._date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 29)
        p = resolve_date_params(None, None, "2026-04-29")
    assert p == {"start_date": "2026-04-29", "end_date": "2026-04-29"}


def test_no_args_defaults_both_to_today():
    with patch("oura_mcp._dates._date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 29)
        p = resolve_date_params(None, None, None)
    assert p == {"start_date": "2026-04-29", "end_date": "2026-04-29"}


def test_date_and_start_date_raises():
    with pytest.raises(ValueError, match="not both"):
        resolve_date_params("2026-04-01", "2026-04-01", None)


def test_date_and_end_date_raises():
    with pytest.raises(ValueError, match="not both"):
        resolve_date_params("2026-04-01", None, "2026-04-07")
