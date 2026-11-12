"""Native Gemini REST adapter: one bounded call, no redirects, retries or fallback."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from reviewops.ai.kimi import (
    MAX_RESPONSE_BYTES,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    Completion,
    InvestigationError,
    NoRedirects,
)
from reviewops.ai.models import Draft, ModelRun, ModelUsage


class GeminiClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport or build_opener(NoRedirects()).open

    def analyse(self, evidence):
        settings = self.settings
        key = settings.gemini_api_key
        if not key or not key.get_secret_value().strip():
            raise InvestigationError(
                "model_not_configured", "Set GEMINI_API_KEY in your local .env to run Gemini.", 503
            )
        generation = {"responseMimeType": "application/json", "maxOutputTokens": 8192}
        if settings.gemini_model.startswith("gemini-3"):
            generation["thinkingConfig"] = {"thinkingLevel": "low"}
        body = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": SYSTEM_PROMPT
                        + "\nJSON schema: "
                        + json.dumps(Draft.model_json_schema())
                    }
                ]
            },
            "contents": [
                {"role": "user", "parts": [{"text": json.dumps(evidence, ensure_ascii=False)}]}
            ],
            "generationConfig": generation,
        }
        request = Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + settings.gemini_model
            + ":generateContent",
            data=json.dumps(body).encode("utf-8"),
            headers={"x-goog-api-key": key.get_secret_value(), "Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with self.transport(request, timeout=settings.gemini_timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Oversized response")
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise ValueError("Invalid envelope")
            feedback = envelope.get("promptFeedback") or {}
            if not isinstance(feedback, dict):
                raise ValueError("Invalid feedback")
            if feedback.get("blockReason"):
                raise InvestigationError("provider_refusal", "Gemini blocked this request.")
            candidate = envelope["candidates"][0]
            if not isinstance(candidate, dict):
                raise ValueError("Invalid candidate")
            if candidate.get("finishReason") != "STOP":
                raise InvestigationError(
                    "incomplete_model_output", "Gemini did not finish a complete report."
                )
            content = candidate["content"]
            if not isinstance(content, dict) or not isinstance(content.get("parts"), list):
                raise ValueError("Invalid content")
            texts = []
            for part in content["parts"]:
                if not isinstance(part, dict) or "functionCall" in part:
                    raise ValueError("Unexpected response part")
                if part.get("thought") is True:
                    continue
                if not isinstance(part.get("text"), str):
                    raise ValueError("Non-text response")
                texts.append(part["text"])
            draft = Draft.model_validate_json("".join(texts))
            usage = envelope.get("usageMetadata") or {}
            if not isinstance(usage, dict):
                raise ValueError("Invalid usage")
            # Candidate tokens exclude thinking. Preserve the provider's total separately.
            run = ModelRun(
                provider="google",
                model=settings.gemini_model,
                prompt_version=PROMPT_VERSION,
                latency_ms=round((time.monotonic() - started) * 1000),
                usage=ModelUsage(
                    prompt_tokens=usage.get("promptTokenCount"),
                    completion_tokens=usage.get("candidatesTokenCount"),
                    total_tokens=usage.get("totalTokenCount"),
                ),
            )
            return Completion(draft, run)
        except HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                raise InvestigationError(
                    "provider_authentication", "Gemini rejected the API key or model access.", 503
                ) from None
            if exc.code == 429:
                raise InvestigationError(
                    "provider_rate_limit",
                    "Gemini rate limit or quota reached; check your project's AI Studio limits.",
                    503,
                ) from None
            if exc.code == 404:
                raise InvestigationError(
                    "provider_model_unavailable",
                    "Gemini model unavailable; check GEMINI_MODEL and AI Studio model access.",
                    503,
                ) from None
            raise InvestigationError("provider_error", "Gemini request failed.") from None
        except TimeoutError:
            raise InvestigationError("provider_timeout", "Gemini request timed out.", 504) from None
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise InvestigationError(
                    "provider_timeout", "Gemini request timed out.", 504
                ) from None
            raise InvestigationError(
                "provider_unavailable", "Could not reach Gemini.", 503
            ) from None
        except OSError:
            raise InvestigationError(
                "provider_unavailable", "Could not reach Gemini.", 503
            ) from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise InvestigationError(
                "invalid_model_output", "Gemini returned an invalid report."
            ) from None
