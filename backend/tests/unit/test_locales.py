from locales import t


def test_locale_fallback():
    """Unsupported locale falls back to the key itself."""
    result = t("test.key", locale="fr")  # unsupported
    assert result == "test.key"


def test_locale_zh():
    """Chinese translation returns expected text."""
    result = t("api.browse.path_not_found", locale="zh")
    assert "未找到" in result or "路径" in result
