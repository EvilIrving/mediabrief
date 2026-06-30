"""transcriber 的重复幻觉过滤测试。"""
from __future__ import annotations

from transcriber import filter_repeated_hallucinations


def test_filter_repeated_hallucinations_drops_fixed_step_short_text():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "真实开场"},
        {"start": 10.0, "end": 11.0, "text": "我可以做的"},
        {"start": 12.0, "end": 13.0, "text": "我可以做的"},
        {"start": 14.0, "end": 15.0, "text": "我可以做的"},
        {"start": 16.0, "end": 17.0, "text": "我可以做的"},
        {"start": 30.0, "end": 31.0, "text": "真实结尾"},
    ]

    assert filter_repeated_hallucinations(segments) == [
        {"start": 0.0, "end": 1.0, "text": "真实开场"},
        {"start": 30.0, "end": 31.0, "text": "真实结尾"},
    ]


def test_filter_repeated_hallucinations_keeps_short_non_fixed_repeat():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "好"},
        {"start": 1.2, "end": 2.0, "text": "好"},
        {"start": 3.8, "end": 4.2, "text": "好"},
        {"start": 8.0, "end": 8.4, "text": "好"},
    ]

    assert filter_repeated_hallucinations(segments) == segments
