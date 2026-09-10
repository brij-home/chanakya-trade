"""Tests for agent/core.py — provider selection, model defaults, message helpers."""

import pytest
from unittest.mock import patch, MagicMock

from agent.core import (
    _default_model,
    _user_msg,
    _assistant_msg,
    _auto_detect_provider,
    get_provider,
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
    PROVIDER_ANTHROPIC,
    PROVIDER_CLAUDE_CLI,
    PROVIDER_OLLAMA,
    PROVIDER_GEMINI_SUB,
    OPENAI_DEFAULT_MODEL,
    GEMINI_DEFAULT_MODEL,
    ANTHROPIC_DEFAULT_MODEL,
    OLLAMA_DEFAULT_MODEL,
    ClaudeCLIProvider,
    OpenAIProvider,
    MAX_TOOL_ROUNDS,
    ALL_PROVIDERS,
    _print_tool_call,
)


# ── Default model selection ──────────────────────────────────


@pytest.fixture(autouse=True)
def clean_model_env(monkeypatch):
    """Ensure local .env model configurations do not contaminate default model unit tests."""
    for var in [
        "AI_MODEL",
        "AI_FAST_MODEL",
        "AI_DEEP_MODEL",
        "AI_FAST_PROVIDER",
        "AI_DEEP_PROVIDER",
        "ANTHROPIC_MODEL",
        "GEMINI_MODEL",
        "OPENAI_MODEL",
        "OLLAMA_MODEL",
    ]:
        monkeypatch.delenv(var, raising=False)


class TestDefaultModel:
    def test_openai(self):

        assert _default_model(PROVIDER_OPENAI) == OPENAI_DEFAULT_MODEL

    def test_gemini(self):
        assert _default_model(PROVIDER_GEMINI) == GEMINI_DEFAULT_MODEL

    def test_anthropic(self):
        assert _default_model(PROVIDER_ANTHROPIC) == ANTHROPIC_DEFAULT_MODEL

    def test_ollama(self):
        assert _default_model(PROVIDER_OLLAMA) == OLLAMA_DEFAULT_MODEL

    def test_unknown_falls_back_to_anthropic(self):
        assert _default_model("unknown") == ANTHROPIC_DEFAULT_MODEL

    def test_claude_cli_gets_anthropic_model(self):
        assert _default_model(PROVIDER_CLAUDE_CLI) == ANTHROPIC_DEFAULT_MODEL

    def test_gemini_sub(self):
        assert _default_model(PROVIDER_GEMINI_SUB) == GEMINI_DEFAULT_MODEL


def _clear_all_ai_keys(monkeypatch):
    keys = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GEMINI_API_KEYS",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "NVIDIA_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_SESSION_TOKEN",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "AI_PROVIDER",
        "AI_MODEL",
    ]
    for k in keys:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("config.credentials.get_credential", lambda *a, **kw: None)


# ── Auto-detect provider ────────────────────────────────────


class TestAutoDetectProvider:
    def test_openai_key_detected(self, monkeypatch):
        _clear_all_ai_keys(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert _auto_detect_provider() == PROVIDER_OPENAI

    def test_anthropic_key_detected(self, monkeypatch):
        _clear_all_ai_keys(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert _auto_detect_provider() == PROVIDER_ANTHROPIC

    def test_gemini_key_detected(self, monkeypatch):
        _clear_all_ai_keys(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
        assert _auto_detect_provider() == PROVIDER_GEMINI


# ── Message helpers ──────────────────────────────────────────


class TestMessageHelpers:
    def test_user_msg(self):
        msg = _user_msg("hello")
        assert msg["role"] == "user"
        assert msg["content"] == "hello"

    def test_assistant_msg(self):
        msg = _assistant_msg("response")
        assert msg["role"] == "assistant"
        assert msg["content"] == "response"

    def test_user_msg_empty(self):
        msg = _user_msg("")
        assert msg["content"] == ""

    def test_assistant_msg_multiline(self):
        msg = _assistant_msg("line1\nline2")
        assert "\n" in msg["content"]


# ── Provider constants ───────────────────────────────────────


class TestProviderConstants:
    def test_all_providers_list(self):
        assert PROVIDER_ANTHROPIC in ALL_PROVIDERS
        assert PROVIDER_OPENAI in ALL_PROVIDERS
        assert PROVIDER_GEMINI in ALL_PROVIDERS
        assert PROVIDER_CLAUDE_CLI in ALL_PROVIDERS
        assert PROVIDER_OLLAMA in ALL_PROVIDERS

    def test_max_tool_rounds(self):
        assert MAX_TOOL_ROUNDS > 0
        assert isinstance(MAX_TOOL_ROUNDS, int)


# ── OpenAI provider (mocked) ────────────────────────────────


class TestOpenAIProvider:
    def test_construction_with_env_key(self, monkeypatch):
        """OpenAIProvider should construct when OPENAI_API_KEY is set."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        # Mock the openai import
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.core import OpenAIProvider
            from agent.tools import build_registry

            reg = build_registry()
            p = OpenAIProvider(
                model="gpt-4o",
                registry=reg,
                system_prompt="test",
            )
            assert "OpenAI" in p.provider_name

    def test_custom_base_url_in_provider_name(self, monkeypatch):
        """Custom base URL should show in provider_name."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.core import OpenAIProvider
            from agent.tools import build_registry

            reg = build_registry()
            p = OpenAIProvider(
                model="llama3",
                registry=reg,
                system_prompt="test",
                base_url="http://localhost:11434/v1",
            )
            assert "localhost" in p.provider_name

    def test_multi_key_pooling(self, monkeypatch):
        """OpenAIProvider should support multiple comma-separated keys and show pooled count."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key1, sk-key2, sk-key3")
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.core import OpenAIProvider
            from agent.tools import build_registry

            reg = build_registry()
            p = OpenAIProvider(
                model="gpt-4o",
                registry=reg,
                system_prompt="test",
            )
            assert len(p._api_keys) == 3
            assert "3 keys pooled" in p.provider_name

            # Test round-robin client retrieval
            idx1, _ = p._get_active_client()
            idx2, _ = p._get_active_client()
            assert idx1 != idx2

    def test_pool_cooldown_circuit_breaker(self, monkeypatch):
        """OpenAIProvider should detect pool cooldown and fast-fail without calling API."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-single-key")
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.core import OpenAIProvider
            from agent.tools import build_registry

            reg = build_registry()
            p = OpenAIProvider(
                model="gpt-4o",
                registry=reg,
                system_prompt="test",
            )
            assert p.is_pool_available() is True

            # Put the key on cooldown
            p._mark_key_cooldown(0, cooldown_seconds=60.0)
            assert p.is_pool_available() is False

            # Attempting chat must fast-fail with RuntimeError and ZERO calls to openai client
            with pytest.raises(RuntimeError, match="Rate limit cooldown active across all pooled API keys"):
                p.chat(messages=[{"role": "user", "content": "hello"}], stream=False)

            # Verify no chat completions were dispatched over the network
            assert mock_sdk.OpenAI.return_value.chat.completions.create.call_count == 0

    def test_max_tokens_passed_to_completions(self, monkeypatch):
        """OpenAIProvider should pass max_tokens to completions.create to avoid default 4096 reservation."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_sdk = MagicMock()
        mock_client = MagicMock()
        mock_sdk.OpenAI.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="result text", tool_calls=None))]
        mock_client.chat.completions.create.return_value = mock_resp

        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.core import OpenAIProvider
            from agent.tools import build_registry

            p = OpenAIProvider(model="gpt-4o", registry=build_registry(), system_prompt="test")
            res = p.chat([{"role": "user", "content": "hi"}], stream=False, max_tokens=250)
            assert res == "result text"
            assert mock_client.chat.completions.create.call_count == 1
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs.get("max_tokens") == 250


# ── Anthropic provider (mocked) ──────────────────────────────


class TestAnthropicProvider:
    def test_missing_key_raises(self, monkeypatch):
        """AnthropicProvider should raise when no API key available."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("_CLI_BATCH_MODE", "1")  # prevent interactive prompt
        mock_sdk = MagicMock()
        with (
            patch.dict("sys.modules", {"anthropic": mock_sdk}),
            patch("config.credentials._kr_get", return_value=None),
        ):
            from agent.core import AnthropicProvider
            from agent.tools import build_registry

            reg = build_registry()
            with pytest.raises(RuntimeError):
                AnthropicProvider(
                    model="claude-opus-4-5",
                    registry=reg,
                    system_prompt="test",
                )


# ── Claude CLI provider ─────────────────────────────────────


class TestClaudeCLIProvider:
    def test_missing_cli_raises(self, monkeypatch):
        """ClaudeCLIProvider should raise if claude CLI is not found."""
        import shutil

        with patch.object(shutil, "which", return_value=None):
            from agent.tools import build_registry

            reg = build_registry()
            with pytest.raises(RuntimeError, match="Claude CLI not found"):
                ClaudeCLIProvider(
                    model="claude-opus-4-5",
                    registry=reg,
                    system_prompt="test",
                )

    def test_provider_name(self, monkeypatch):
        """Provider name should mention subscription."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            from agent.tools import build_registry

            reg = build_registry()
            p = ClaudeCLIProvider(
                model="claude-opus-4-5",
                registry=reg,
                system_prompt="test",
            )
            assert "Subscription" in p.provider_name or "CLI" in p.provider_name


# ── Print tool call ──────────────────────────────────────────


class TestPrintToolCall:
    def test_does_not_raise(self):
        """_print_tool_call should not raise on any input."""
        _print_tool_call("get_quote", {"symbol": "RELIANCE"})
        _print_tool_call("unknown_tool", {})
        _print_tool_call("tool", {"a": 1, "b": [1, 2, 3]})


# ── Ollama provider ──────────────────────────────────────────


class TestOllamaProvider:
    """Ollama routes through OpenAIProvider with a local base_url. No API key needed."""

    def _mock_sdk(self):
        return MagicMock()

    def test_get_provider_ollama_returns_openai_provider(self, monkeypatch):
        """get_provider('ollama') should return an OpenAIProvider instance."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mock_sdk = self._mock_sdk()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.tools import build_registry

            p = get_provider(provider="ollama", registry=build_registry())
        assert isinstance(p, OpenAIProvider)

    def test_default_model_is_llama31(self):
        """Default Ollama model should be llama3.1 or llama3.3."""
        assert _default_model(PROVIDER_OLLAMA) == OLLAMA_DEFAULT_MODEL
        assert OLLAMA_DEFAULT_MODEL in ("llama3.1", "llama3.3")

    def test_default_base_url_is_localhost(self, monkeypatch):
        """Without OLLAMA_BASE_URL set, should use localhost:11434."""
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mock_sdk = self._mock_sdk()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.tools import build_registry

            p = get_provider(provider="ollama", registry=build_registry())
        assert "localhost" in p.provider_name
        assert "11434" in p.provider_name

    def test_custom_base_url_via_env(self, monkeypatch):
        """OLLAMA_BASE_URL env var should override the default endpoint."""
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.10:11434/v1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mock_sdk = self._mock_sdk()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.tools import build_registry

            p = get_provider(provider="ollama", registry=build_registry())
        assert "192.168.1.10" in p.provider_name

    def test_custom_model_via_env(self, monkeypatch):
        """OLLAMA_MODEL env var should override the default model."""
        monkeypatch.setenv("OLLAMA_MODEL", "mistral-nemo")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mock_sdk = self._mock_sdk()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.tools import build_registry

            p = get_provider(provider="ollama", registry=build_registry())
        assert p.model == "mistral-nemo"

    def test_auto_detect_from_ollama_base_url(self, monkeypatch):
        """Setting OLLAMA_BASE_URL should auto-detect Ollama as the provider."""
        _clear_all_ai_keys(monkeypatch)
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        assert _auto_detect_provider() == PROVIDER_OLLAMA

    def test_auto_detect_from_ollama_model_env(self, monkeypatch):
        """Setting OLLAMA_MODEL should auto-detect Ollama as the provider."""
        _clear_all_ai_keys(monkeypatch)
        monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder")
        assert _auto_detect_provider() == PROVIDER_OLLAMA

    def test_provider_name_includes_model(self, monkeypatch):
        """provider_name should show host and model for Ollama."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        mock_sdk = self._mock_sdk()
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.tools import build_registry

            p = get_provider(provider="ollama", registry=build_registry())
        # Should look like "localhost:11434 / llama3.1"
        assert OLLAMA_DEFAULT_MODEL in p.provider_name

    def test_no_api_key_required(self, monkeypatch):
        """Ollama should construct without any API key in the environment."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        mock_sdk = self._mock_sdk()
        # Should not raise even with no keys set
        with patch.dict("sys.modules", {"openai": mock_sdk}):
            from agent.tools import build_registry

            p = get_provider(provider="ollama", registry=build_registry())
        assert p is not None


class TestExtractSymbol:
    """Verify symbol extraction for leading digits, natural names, and noise filtering."""

    def test_extract_leading_digit_symbols(self):
        from agent.core import extract_symbol

        assert extract_symbol("analyze 63MOONS") == "63MOONS"
        assert extract_symbol("what about 3MINDIA?") == "3MINDIA"
        assert extract_symbol("check 5PAISA") == "5PAISA"
        assert extract_symbol("20MICRONS technicals") == "20MICRONS"

    def test_extract_natural_names(self):
        from agent.core import extract_symbol

        assert extract_symbol("63 moons technologies") == "63MOONS"
        assert extract_symbol("analyze reliance") == "RELIANCE"
        assert extract_symbol("hdfc bank report") == "HDFCBANK"

    def test_extract_explicit_prefix(self):
        from agent.core import extract_symbol

        assert extract_symbol("look at NSE:63MOONS") == "63MOONS"
        assert extract_symbol("quote for BSE:RELIANCE") == "RELIANCE"

    def test_extract_noise_suppression(self):
        from agent.core import extract_symbol

        assert extract_symbol("outlook for 2026") == ""
        assert extract_symbol("what is 100?") == ""

    def test_extract_user_context_sentence(self):
        from agent.core import extract_symbol

        msg = "when analyzing I see I don’t have access to real‑time market data for **63MOONS (NSE)** at the moment"
        assert extract_symbol(msg) == "63MOONS"
