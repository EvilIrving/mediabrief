"""桌面窗口退出：确认文案、语言探测、是否弹窗。

确认框是 pywebview 的原生 NSAlert，不走 React i18n。
空闲退出不打扰；有进行中任务才说明「任务会停止」。
"""
from __future__ import annotations

import locale
import os
from typing import Mapping

UI_LANGS = ("en", "zh", "ja", "ko")

# pywebview 只给 messageText 一行。写后果，不问「真的要退出吗」。
_QUIT_COPY: dict[str, dict[str, str]] = {
    "en": {
        "global.quitConfirmation": "Running tasks will stop.",
        "global.quit": "Quit",
        "global.cancel": "Cancel",
        "global.ok": "OK",
        "cocoa.menu.quit": "Quit",
        "cocoa.menu.hide": "Hide",
        "cocoa.menu.hideOthers": "Hide Others",
        "cocoa.menu.showAll": "Show All",
        "cocoa.menu.about": "About",
    },
    "zh": {
        "global.quitConfirmation": "进行中的任务会停止。",
        "global.quit": "退出",
        "global.cancel": "取消",
        "global.ok": "好",
        "cocoa.menu.quit": "退出",
        "cocoa.menu.hide": "隐藏",
        "cocoa.menu.hideOthers": "隐藏其他",
        "cocoa.menu.showAll": "全部显示",
        "cocoa.menu.about": "关于",
    },
    "ja": {
        "global.quitConfirmation": "実行中のタスクは停止します。",
        "global.quit": "終了",
        "global.cancel": "キャンセル",
        "global.ok": "OK",
        "cocoa.menu.quit": "終了",
        "cocoa.menu.hide": "隠す",
        "cocoa.menu.hideOthers": "ほかを隠す",
        "cocoa.menu.showAll": "すべてを表示",
        "cocoa.menu.about": "このアプリについて",
    },
    "ko": {
        "global.quitConfirmation": "진행 중인 작업이 중지됩니다.",
        "global.quit": "종료",
        "global.cancel": "취소",
        "global.ok": "확인",
        "cocoa.menu.quit": "종료",
        "cocoa.menu.hide": "가리기",
        "cocoa.menu.hideOthers": "기타 가리기",
        "cocoa.menu.showAll": "모두 보기",
        "cocoa.menu.about": "정보",
    },
}


def normalize_ui_lang(value: object) -> str:
    if not isinstance(value, str):
        return "en"
    code = value.strip().lower().replace("-", "_")
    if code in UI_LANGS:
        return code
    prefix = code.split("_", 1)[0]
    return prefix if prefix in UI_LANGS else "en"


def detect_ui_lang(env: Mapping[str, str] | None = None) -> str:
    """系统语言作启动默认；前端随后用 set_ui_lang 对齐界面语言。"""
    use_system_locale = env is None
    environ = os.environ if env is None else env
    candidates: list[str | None] = [
        environ.get("LC_ALL"),
        environ.get("LC_MESSAGES"),
        environ.get("LANG"),
    ]
    if use_system_locale:
        for getter in (locale.getlocale, locale.getdefaultlocale):
            try:
                loc, _ = getter()
                candidates.append(loc)
            except Exception:
                pass
    for raw in candidates:
        if not raw:
            continue
        prefix = raw.strip().lower().replace("-", "_").split("_", 1)[0]
        if prefix in UI_LANGS:
            return prefix
    return "en"


def quit_localization(lang: str) -> dict[str, str]:
    return dict(_QUIT_COPY[normalize_ui_lang(lang)])


def should_confirm_close(active_count: int) -> bool:
    """有进行中任务才确认。排队项在 SQLite，下次启动仍在。"""
    return active_count > 0
