"""Tests for PAT resolution: env > config file > per-call override > error."""

from __future__ import annotations

import json

import pytest

from oura_ring_mcp import auth
from oura_ring_mcp.auth import PATNotConfigured, resolve_pat


def test_override_wins_over_env_and_file(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"pat": "file-token"}))
    monkeypatch.setattr(auth, "CONFIG_PATH", cfg)
    monkeypatch.setenv("OURA_PAT", "env-token")
    assert resolve_pat("override-token") == "override-token"


def test_env_var_used_when_no_override(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "CONFIG_PATH", tmp_path / "absent.json")
    monkeypatch.setenv("OURA_PAT", "env-token")
    assert resolve_pat() == "env-token"


def test_env_beats_file(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"pat": "file-token"}))
    monkeypatch.setattr(auth, "CONFIG_PATH", cfg)
    monkeypatch.setenv("OURA_PAT", "env-token")
    assert resolve_pat() == "env-token"


def test_config_file_used_when_no_env(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"pat": "file-token"}))
    monkeypatch.setattr(auth, "CONFIG_PATH", cfg)
    monkeypatch.delenv("OURA_PAT", raising=False)
    assert resolve_pat() == "file-token"


def test_missing_everywhere_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "CONFIG_PATH", tmp_path / "absent.json")
    monkeypatch.delenv("OURA_PAT", raising=False)
    with pytest.raises(PATNotConfigured):
        resolve_pat()


def test_invalid_config_json_raises(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("not valid json{")
    monkeypatch.setattr(auth, "CONFIG_PATH", cfg)
    monkeypatch.delenv("OURA_PAT", raising=False)
    with pytest.raises(PATNotConfigured):
        resolve_pat()


def test_missing_pat_key_in_config_raises(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"something_else": "x"}))
    monkeypatch.setattr(auth, "CONFIG_PATH", cfg)
    monkeypatch.delenv("OURA_PAT", raising=False)
    with pytest.raises(PATNotConfigured):
        resolve_pat()


def test_error_message_does_not_echo_token(monkeypatch, tmp_path):
    """Per spec §4.1: never echo the offending value in errors."""
    monkeypatch.setattr(auth, "CONFIG_PATH", tmp_path / "absent.json")
    monkeypatch.delenv("OURA_PAT", raising=False)
    try:
        resolve_pat()
    except PATNotConfigured as e:
        # Error message should mention where to set the PAT, not contain a token.
        assert "Bearer" not in str(e)
        assert "OURA_PAT" in str(e)
