from __future__ import annotations

import io
from pathlib import Path

import pytest

from candidate_parser import CandidateParserRuntime, CandidateResultKind
from media_contracts import (
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    ObservationStatus,
    RecoveryAction,
)
from media_recovery_actions import MediaRecoveryActions


VALID_PARSER = r'''
const input = JSON.parse(await new Response(Deno.stdin.readable).text());
const page = JSON.parse(input.body);
console.log(JSON.stringify({
  kind: "candidates",
  candidates: [{url: page.media_url, type: "media"}],
  diagnostic: "parsed"
}));
'''


async def test_real_deno_boundary_denies_env_file_network_and_process(tmp_path):
    runtime = CandidateParserRuntime(temp_dir=tmp_path)
    if not runtime.available:
        pytest.skip("Deno is not installed")

    assert await runtime.verify_boundary() is True


async def test_candidate_parser_is_stdin_stdout_only_and_source_is_deleted(tmp_path):
    runtime = CandidateParserRuntime(temp_dir=tmp_path)
    if not runtime.available:
        pytest.skip("Deno is not installed")

    result = await runtime.run(VALID_PARSER, {
        "body": '{"media_url":"https://cdn.example.com/audio.m4a"}',
    })

    assert result.kind is CandidateResultKind.CANDIDATES
    assert result.candidates[0].url == "https://cdn.example.com/audio.m4a"
    assert list(tmp_path.glob("candidate_*.js")) == []


@pytest.mark.parametrize("source", [
    'await fetch("https://example.com");',
    'console.log(Deno.env.get("HOME"));',
    'new Deno.Command("echo").outputSync();',
    'console.log(Deno.readTextFileSync("/etc/passwd"));',
    'import "https://example.com/x.js";',
])
async def test_candidate_source_requesting_forbidden_capability_is_rejected(tmp_path, source):
    runtime = CandidateParserRuntime(temp_dir=tmp_path)

    with pytest.raises(ValueError, match="未允许能力"):
        await runtime.run(source, {})


class _FakeVideoProcessor:
    def recovery_profile_names(self, _url):
        return ("youtube_android_anonymous", "youtube_web_ejs", "youtube_browser_session")

    def browser_session_available(self):
        return False

    async def download_and_convert(self, url, temp_dir, *, recovery_profile=None):
        self.used_profile = recovery_profile
        output = Path(temp_dir) / "youtube-recovered.m4a"
        output.write_bytes(b"host artifact")
        return str(output), "Recovered title"


def _failure(platform="bilibili", kind=ExtractionFailureKind.MEDIA_DOWNLOAD_FAILED):
    return ExtractionFailure(
        platform=platform,
        stage=ExtractionStage.MEDIA_DOWNLOAD,
        kind=kind,
        sanitized_summary="page structure changed",
        deno_available=True,
    )


class _FakeResponse:
    status = 200

    def __init__(self, body=b"fake media bytes"):
        self._body = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self._body.read(size)


class _FakeOpener:
    def open(self, request, timeout=0):
        return _FakeResponse()


async def test_simulated_bilibili_structure_change_parser_download_and_host_validation(tmp_path, monkeypatch):
    runtime = CandidateParserRuntime(temp_dir=tmp_path)
    if not runtime.available:
        pytest.skip("Deno is not installed")
    actions = MediaRecoveryActions(
        source_url="https://www.bilibili.com/video/BV1test",
        failure=_failure(),
        video_processor=_FakeVideoProcessor(),
        temp_dir=tmp_path,
    )
    actions._http_bodies["response_1"] = (
        b'{"media_url":"https://upos-sz-mirrorcos.bilivideo.com/audio/test.m4a"}'
    )
    monkeypatch.setattr("media_recovery_actions.urllib.request.build_opener", lambda *args: _FakeOpener())
    monkeypatch.setattr("media_recovery_actions.probe_duration", lambda path: 42.0)

    parsed = await actions.execute(RecoveryAction.RUN_CANDIDATE_PARSER, {
        "response_id": "response_1",
        "source": VALID_PARSER,
    })
    downloaded = await actions.execute(RecoveryAction.DOWNLOAD_CANDIDATE, {
        "candidate_id": "candidate_1",
    })
    validated = await actions.execute(RecoveryAction.VALIDATE_MEDIA, {})

    assert parsed.code == "candidate_resources"
    assert downloaded.code == "candidate_downloaded"
    assert validated.code == "media_valid"
    assert actions.verified_result((parsed, downloaded, validated)) is not None


@pytest.mark.parametrize("kind", [
    ExtractionFailureKind.PERMISSION_DENIED,
    ExtractionFailureKind.AUTH_REQUIRED,
    ExtractionFailureKind.CHALLENGE_REQUIRED,
    ExtractionFailureKind.DRM_PROTECTED,
])
async def test_access_control_failure_cannot_use_candidate_parser(tmp_path, kind):
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=private",
        failure=_failure("youtube", kind),
        video_processor=_FakeVideoProcessor(),
        temp_dir=tmp_path,
    )
    actions._http_bodies["response_1"] = b"{}"

    result = await actions.execute(RecoveryAction.RUN_CANDIDATE_PARSER, {
        "response_id": "response_1",
        "source": "console.log('{}')",
    })

    assert result.status is ObservationStatus.FAILURE
    assert result.code == "access_control_not_parseable"


async def test_simulated_youtube_failure_uses_only_named_profile_and_host_verification(tmp_path, monkeypatch):
    processor = _FakeVideoProcessor()
    actions = MediaRecoveryActions(
        source_url="https://www.youtube.com/watch?v=test",
        failure=_failure("youtube", ExtractionFailureKind.CHALLENGE_REQUIRED),
        video_processor=processor,
        temp_dir=tmp_path,
    )
    monkeypatch.setattr("media_recovery_actions.probe_duration", lambda path: 30.0)

    recovered = await actions.execute(RecoveryAction.RUN_YTDLP, {
        "profile": "youtube_android_anonymous",
    })
    rejected = await actions.execute(RecoveryAction.RUN_YTDLP, {
        "profile": "youtube_arbitrary_flags",
    })

    assert recovered.code == "media_downloaded"
    assert processor.used_profile == "youtube_android_anonymous"
    assert actions.verified_result((recovered,)) is not None
    assert rejected.code == "invalid_arguments"


def test_platform_media_domain_allowlist_rejects_unrelated_host(tmp_path):
    actions = MediaRecoveryActions(
        source_url="https://www.bilibili.com/video/BV1test",
        failure=_failure(),
        video_processor=_FakeVideoProcessor(),
        temp_dir=tmp_path,
    )

    actions._validate_url("https://cdn.bilivideo.com/audio.m4a")
    with pytest.raises(ValueError, match="域名白名单"):
        actions._validate_url("https://attacker.example/audio.m4a")
