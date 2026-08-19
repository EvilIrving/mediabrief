from desktop_shutdown import (
    detect_ui_lang,
    normalize_ui_lang,
    quit_localization,
    should_confirm_close,
)


def test_normalize_ui_lang_accepts_known_codes():
    assert normalize_ui_lang("zh") == "zh"
    assert normalize_ui_lang("zh-CN") == "zh"
    assert normalize_ui_lang("ja_JP") == "ja"
    assert normalize_ui_lang("ko") == "ko"
    assert normalize_ui_lang("en-US") == "en"
    assert normalize_ui_lang("fr") == "en"
    assert normalize_ui_lang(None) == "en"


def test_detect_ui_lang_reads_env_before_fallback():
    assert detect_ui_lang({"LANG": "zh_CN.UTF-8"}) == "zh"
    assert detect_ui_lang({"LC_ALL": "ja_JP.UTF-8", "LANG": "en_US.UTF-8"}) == "ja"
    assert detect_ui_lang({"LANG": "C"}) == "en"
    assert detect_ui_lang({"LANG": ""}) == "en"


def test_quit_localization_covers_pywebview_keys():
    keys = {
        "global.quitConfirmation",
        "global.quit",
        "global.cancel",
        "global.ok",
        "cocoa.menu.quit",
    }
    for lang in ("en", "zh", "ja", "ko"):
        loc = quit_localization(lang)
        assert keys <= set(loc)
        assert loc["global.quitConfirmation"].strip()
        assert loc["global.quit"].strip()
        assert loc["global.cancel"].strip()
    assert quit_localization("zh")["global.quitConfirmation"] != quit_localization("en")[
        "global.quitConfirmation"
    ]
    assert "really want to quit" not in quit_localization("en")["global.quitConfirmation"].lower()


def test_should_confirm_close_only_when_busy():
    assert should_confirm_close(0) is False
    assert should_confirm_close(1) is True
    assert should_confirm_close(3) is True
