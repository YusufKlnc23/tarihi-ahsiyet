from __future__ import annotations

from tarih_pdf_analyzer.config import load_settings


def test_load_settings_prefers_gemini(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")

    settings = load_settings()

    assert settings.llm_provider == "gemini"
    assert settings.gemini_api_key == "gemini-key"
    assert settings.gemini_model == "gemini-2.5-flash"


def test_load_settings_defaults_to_gemini_when_key_is_unset(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    settings = load_settings()

    assert settings.llm_provider == "gemini"
    assert settings.gemini_api_key is None
