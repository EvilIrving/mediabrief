"""config 的单元测试：冻结不可变、派生属性、默认值约束。"""
from __future__ import annotations

import dataclasses

import pytest

from config import Settings, settings


def test_settings_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.upload_max_mb = 999  # type: ignore[misc]


def test_upload_max_bytes_derived():
    s = Settings(upload_max_mb=200)
    assert s.upload_max_bytes == 200 * 1024 * 1024


def test_allowed_ext_includes_common_media():
    for ext in (".mp3", ".mp4", ".wav", ".txt"):
        assert ext in settings.upload_allowed_ext


def test_default_whisper_model():
    # 与 whisper_models.DEFAULT_MODEL 保持一致的契约。
    assert settings.whisper_model_size == "large-v3-turbo"


def test_llm_timeouts_positive():
    assert settings.llm_timeout_sec > 0
    assert settings.llm_request_timeout_sec > 0
    assert settings.llm_max_retries >= 0
