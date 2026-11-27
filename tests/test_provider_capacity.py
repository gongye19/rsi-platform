from __future__ import annotations

import pytest

from harnesslens.infrastructure.provider_capacity import (
    provider_trial_concurrency,
    provider_trial_slot,
)


def test_provider_trial_concurrency_is_bounded(monkeypatch):
    monkeypatch.setenv("HAI_PROVIDER_TRIAL_MAX_CONCURRENCY", "8")
    assert provider_trial_concurrency() == 8
    monkeypatch.setenv("HAI_PROVIDER_TRIAL_MAX_CONCURRENCY", "999")
    assert provider_trial_concurrency() == 64


def test_provider_trial_slot_waits_outside_the_trial(monkeypatch, tmp_path):
    monkeypatch.setenv("HAI_PROVIDER_TRIAL_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("HAI_PROVIDER_TRIAL_SLOT_DIR", str(tmp_path))

    with provider_trial_slot() as first:
        assert first["slot"] == 0
        with pytest.raises(TimeoutError, match="provider trial capacity"):
            with provider_trial_slot(timeout_s=0.05):
                raise AssertionError("second lease must not be acquired")

    with provider_trial_slot(timeout_s=0.05) as second:
        assert second["slot"] == 0
