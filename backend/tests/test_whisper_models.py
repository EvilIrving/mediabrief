"""whisper_models 的纯逻辑单元测试：本地模型判定与模型选择契约。

不联网、不加载 mlx——只验证目录/权重名判定，确保默认大模型尚未就绪时不会被
静默改成 base。
"""
from __future__ import annotations

import json

import pytest

import whisper_models as wm
from transcriber import parse_detected_language


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    """把 MODEL_DIR 指向临时目录，隔离真实数据目录。"""
    monkeypatch.setattr(wm, "MODEL_DIR", tmp_path)
    return tmp_path


def _seed(model_dir, size: str, weight_name: str | None):
    """在 MODEL_DIR/<size> 下写入 config.json（+ 可选权重），模拟已下载布局。"""
    d = model_dir / size
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"n_mels": 80}))
    if weight_name:
        (d / weight_name).write_bytes(b"\x00")
    return d


def test_is_downloaded_accepts_safetensors(model_dir):
    # turbo 的权重是 safetensors，必须被认（Codex 修正：不能只查 .npz）。
    _seed(model_dir, "large-v3-turbo", "weights.safetensors")
    assert wm.is_downloaded("large-v3-turbo") is True


def test_is_downloaded_accepts_npz(model_dir):
    # base/small/medium/large-v3 的权重是 npz。
    _seed(model_dir, "base", "weights.npz")
    assert wm.is_downloaded("base") is True


def test_is_downloaded_requires_weights(model_dir):
    # 只有 config.json、缺权重 → 视为未完整下载。
    _seed(model_dir, "small", None)
    assert wm.is_downloaded("small") is False


def test_is_downloaded_requires_config(model_dir):
    # 只有权重、缺 config.json → 未完整。
    d = model_dir / "medium"
    d.mkdir(parents=True)
    (d / "weights.npz").write_bytes(b"\x00")
    assert wm.is_downloaded("medium") is False


def test_is_downloaded_unknown_size(model_dir):
    assert wm.is_downloaded("does-not-exist") is False


def test_resolve_keeps_default_when_missing(model_dir):
    # 默认 turbo 尚未下载时仍保持默认模型，由惰性门闩等待后台准备。
    assert wm._resolve_available_size("large-v3-turbo") == wm.DEFAULT_MODEL


def test_resolve_unknown_size_uses_default(model_dir):
    # 未知尺寸统一回到最佳默认模型，不得静默降级。
    assert wm._resolve_available_size("bogus") == wm.DEFAULT_MODEL


def test_resolve_uses_downloaded_model(model_dir):
    # 用户已显式下载的尺寸按其选择使用，不回退。
    _seed(model_dir, "large-v3-turbo", "weights.safetensors")
    assert wm._resolve_available_size("large-v3-turbo") == "large-v3-turbo"


def test_resolve_builtin_always_available(model_dir):
    # base 即便目录为空也视为可用（打包内嵌 / mlx 仓库兜底）。
    assert wm._resolve_available_size("base") == "base"


def test_catalog_repos_are_mlx_community(model_dir):
    # 引擎已换 mlx：所有 repo 必须指向 mlx-community。
    assert all(repo.startswith("mlx-community/") for repo in wm.CATALOG.values())
    assert wm.DEFAULT_MODEL in wm.CATALOG
    assert wm.BUILTIN_MODEL in wm.CATALOG


def test_get_transcriber_uses_repo_when_not_downloaded(model_dir):
    # 未下载尺寸 → model_path 传 HF 仓库名，让 mlx 首次转录时自动拉取。
    wm._registry.clear()
    t = wm.get_transcriber("base")
    assert t.model_path == wm.CATALOG["base"]


def test_get_transcriber_uses_local_dir_when_downloaded(model_dir):
    wm._registry.clear()
    _seed(model_dir, "large-v3-turbo", "weights.safetensors")
    t = wm.get_transcriber("large-v3-turbo")
    assert t.model_path == str(model_dir / "large-v3-turbo")


def test_download_endpoints_official_then_china_mirror():
    assert wm.download_endpoints_for(None)[0] == wm.OFFICIAL_DOWNLOAD_ENDPOINT
    assert wm.download_endpoints_for("")[1] == "https://hf-mirror.com"
    assert wm.download_endpoints_for("https://custom.example/hf/") == ("https://custom.example/hf",)


def test_next_download_endpoint_cycles_without_waiting():
    endpoints = wm.DEFAULT_DOWNLOAD_ENDPOINTS
    assert wm.next_download_endpoint(1, endpoints) == ""
    assert wm.next_download_endpoint(2, endpoints) == "https://hf-mirror.com"
    assert wm.next_download_endpoint(3, endpoints) == ""
    assert wm.completed_endpoint_cycle(1, endpoints) is False
    assert wm.completed_endpoint_cycle(2, endpoints) is True


def test_ensure_default_model_switches_to_mirror_immediately(model_dir, monkeypatch):
    wm._default_ready.clear()
    wm._default_degraded.clear()
    wm._default_retry_now.clear()
    wm._default_worker = None
    wm._set_default_state(
        "pending", error=None, attempt=0, next_retry_at=None,
        endpoint=None, tried_endpoints=(),
    )
    calls: list[str] = []

    def fake_download(size, endpoint=None):
        calls.append(endpoint or "")
        if not endpoint:
            raise RuntimeError("official huggingface blocked")
        _seed(model_dir, size, "weights.safetensors")

    monkeypatch.setattr(wm, "download", fake_download)
    wm.ensure_default_model_async()
    worker = wm._default_worker
    assert worker is not None
    worker.join(timeout=2)
    assert worker.is_alive() is False
    assert calls == ["", "https://hf-mirror.com"]
    status = wm.default_model_status()
    assert status["ready"] is True
    assert status["endpoint"] == "https://hf-mirror.com"
    assert status["tried_endpoints"] == ["official", "https://hf-mirror.com"]


def test_explicit_hf_endpoint_does_not_auto_switch():
    endpoints = wm.download_endpoints_for("https://custom.example/hf/")
    assert endpoints == ("https://custom.example/hf",)
    assert wm.next_download_endpoint(1, endpoints) == "https://custom.example/hf"
    assert wm.next_download_endpoint(2, endpoints) == "https://custom.example/hf"
    assert wm.completed_endpoint_cycle(1, endpoints) is True


def test_parse_detected_language_placeholder_probability():
    # 组装出的 Markdown 用 — 占位语言概率，parse 仍能取出语言、不被占位污染。
    md = (
        "# Video Transcription\n\n"
        "**Detected Language:** ja\n"
        "**Language Probability:** —\n\n"
        "## Transcription Content\n"
    )
    assert parse_detected_language(md) == "ja"
