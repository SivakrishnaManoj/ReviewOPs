import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from pydantic import ValidationError

from reviewops.ai.gemini import GeminiClient
from reviewops.ai.investigate import configured_model
from reviewops.ai.kimi import MAX_RESPONSE_BYTES, InvestigationError, KimiClient
from reviewops.config import Settings

EMPTY = {"reported_complaints": [], "suggested_explanations": [], "recommended_actions": []}


def settings(**kwargs):
    return Settings(_env_file=None, gemini_api_key="synthetic-secret", **kwargs)


def response(**kwargs):
    return {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(EMPTY)}]}}
        ],
        **kwargs,
    }


def test_gemini_request_and_usage():
    transport = Mock(
        return_value=io.BytesIO(
            json.dumps(
                response(
                    usageMetadata={
                        "promptTokenCount": 100,
                        "candidatesTokenCount": 80,
                        "thoughtsTokenCount": 20,
                        "totalTokenCount": 200,
                    }
                )
            ).encode()
        )
    )
    result = GeminiClient(settings(), transport).analyse({"evidence": ["untrusted review"]})
    sent = transport.call_args.args[0]
    body = json.loads(sent.data)
    assert sent.full_url.endswith("/models/gemini-3.8-flash:generateContent")
    assert "synthetic-secret" not in sent.full_url
    assert sent.get_header("X-goog-api-key") == "synthetic-secret"
    assert body["generationConfig"] == {
        "responseMimeType": "application/json",
        "maxOutputTokens": 8192,
        "thinkingConfig": {"thinkingLevel": "low"},
    }
    assert "untrusted" in body["systemInstruction"]["parts"][0]["text"]
    assert "tools" not in body
    assert result.run.provider == "google"
    assert result.run.usage.completion_tokens == 80
    assert result.run.usage.total_tokens == 200
    assert result.run.calls == 1
    transport.assert_called_once()


@pytest.mark.parametrize(
    "raw",
    [
        b"invalid",
        b"[]",
        b"{}",
        b"x" * (MAX_RESPONSE_BYTES + 1),
        json.dumps(response(candidates=[{"finishReason": "MAX_TOKENS"}])).encode(),
        json.dumps(response(promptFeedback={"blockReason": "SAFETY"})).encode(),
        json.dumps(
            response(
                candidates=[
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"functionCall": {"name": "delete"}}]},
                    }
                ]
            )
        ).encode(),
        json.dumps(
            response(
                candidates=[
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps(EMPTY | {"metrics": {}})}]},
                    }
                ]
            )
        ).encode(),
        json.dumps(response(usageMetadata={"totalTokenCount": -1})).encode(),
        json.dumps(response(candidates=[None])).encode(),
        json.dumps(response(candidates=[{"finishReason": "STOP", "content": []}])).encode(),
    ],
)
def test_bad_output_fails_closed(raw):
    transport = Mock(return_value=io.BytesIO(raw))
    with pytest.raises(InvestigationError):
        GeminiClient(settings(), transport).analyse({})
    transport.assert_called_once()


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            HTTPError("https://example", 401, "synthetic-secret", {}, None),
            "provider_authentication",
        ),
        (
            HTTPError("https://example", 403, "synthetic-secret", {}, None),
            "provider_authentication",
        ),
        (
            HTTPError("https://example", 404, "synthetic-secret", {}, None),
            "provider_model_unavailable",
        ),
        (HTTPError("https://example", 429, "synthetic-secret", {}, None), "provider_rate_limit"),
        (HTTPError("https://example", 500, "synthetic-secret", {}, None), "provider_error"),
        (TimeoutError("synthetic-secret"), "provider_timeout"),
        (URLError(TimeoutError("synthetic-secret")), "provider_timeout"),
        (URLError("synthetic-secret"), "provider_unavailable"),
    ],
)
def test_errors_are_redacted_without_retry(error, code):
    transport = Mock(side_effect=error)
    with pytest.raises(InvestigationError) as caught:
        GeminiClient(settings(), transport).analyse({})
    assert caught.value.code == code
    assert "synthetic-secret" not in str(caught.value)
    transport.assert_called_once()


def test_provider_selection_and_no_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    config = Settings(_env_file=None, moonshot_api_key="other-provider-secret")
    assert isinstance(configured_model(config), GeminiClient)
    assert isinstance(configured_model(settings(llm_provider="moonshot")), KimiClient)
    transport = Mock()
    with pytest.raises(InvestigationError, match="GEMINI_API_KEY"):
        GeminiClient(config, transport).analyse({})
    transport.assert_not_called()


def test_dotenv_and_secret_redaction(monkeypatch, tmp_path):
    for name in ("LLM_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=gemini\nGEMINI_API_KEY=synthetic-secret\n", encoding="utf-8")
    config = Settings(_env_file=env)
    assert config.gemini_api_key.get_secret_value() == "synthetic-secret"
    assert "synthetic-secret" not in repr(config)


@pytest.mark.parametrize("model", ["../evil", "gemini-x?key=x", "gemini-x/path"])
def test_model_id_cannot_change_endpoint(model):
    with pytest.raises(ValidationError):
        settings(gemini_model=model)


def test_thought_parts_are_not_report_text_and_missing_usage_stays_unknown():
    envelope = response()
    envelope["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "internal"})
    transport = Mock(return_value=io.BytesIO(json.dumps(envelope).encode()))
    result = GeminiClient(settings(), transport).analyse({})
    assert result.draft.reported_complaints == []
    assert result.run.usage.total_tokens is None
