"""Unified BYOK LLM router for Gemini, Claude, and Ollama with Pydantic structured output."""

import json
import os
import re
from typing import Literal, Optional, Type, TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

T = TypeVar("T", bound=BaseModel)

ProviderType = Literal["gemini", "claude", "ollama"]


class LLMRouterConfig(BaseModel):
    provider: ProviderType = "gemini"
    model: str = "gemini-3.8-flash"
    api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434"
    temperature: float = Field(0.1, ge=0.0, le=1.0)
    max_retries: int = Field(2, ge=0, le=5)


class LLMRouter:
    """Unified BYOK client enforcing Pydantic JSON schema validation + automatic retry."""

    def __init__(self, config: Optional[LLMRouterConfig] = None):
        self.config = config or LLMRouterConfig()

    def _resolve_api_key(self) -> str:
        if self.config.api_key:
            return self.config.api_key
        if self.config.provider == "gemini":
            key = (
                os.getenv("GEMINI_API_KEY")
                or os.getenv('"GEMINI_API_KEY"')
                or os.getenv("GOOGLE_API_KEY")
                or os.getenv('"GOOGLE_API_KEY"')
            )
            if not key:
                raise ValueError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY) in environment/.env.")
            return key.strip().strip('"').strip("'")
        if self.config.provider == "claude":
            key = os.getenv("ANTHROPIC_API_KEY") or os.getenv('"ANTHROPIC_API_KEY"')
            if not key:
                raise ValueError("Missing ANTHROPIC_API_KEY in environment/.env.")
            return key.strip().strip('"').strip("'")
        return ""

    def generate_structured(
        self,
        role: str,
        system_prompt: str,
        user_payload: str,
        response_model: Type[T],
    ) -> T:
        """Call the configured LLM provider and validate output against `response_model`."""
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        augmented_system = (
            f"{system_prompt.strip()}\n\n"
            "OUTPUT CONTRACT:\n"
            "Return ONLY a valid JSON object matching this exact JSON Schema (no markdown fences, no commentary):\n"
            f"{schema_json}"
        )

        last_error: Optional[Exception] = None
        current_payload = user_payload

        for attempt in range(self.config.max_retries + 1):
            raw_text = self._call_provider(augmented_system, current_payload, response_model)
            cleaned = _extract_json_object(raw_text)
            try:
                return response_model.model_validate_json(cleaned)
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                current_payload = (
                    f"{user_payload}\n\n"
                    f"[RETRY {attempt + 1}] Your previous JSON failed schema validation:\n{exc}\n"
                    "Return ONLY corrected valid JSON matching the schema."
                )

        raise RuntimeError(
            f"Agent '{role}' failed structured output validation after {self.config.max_retries + 1} attempts: {last_error}"
        )

    def _call_provider(
        self,
        system_prompt: str,
        user_payload: str,
        response_model: Type[T],
    ) -> str:
        if self.config.provider == "gemini":
            return self._call_gemini(system_prompt, user_payload, response_model)
        if self.config.provider == "claude":
            return self._call_claude(system_prompt, user_payload)
        if self.config.provider == "ollama":
            return self._call_ollama(system_prompt, user_payload)
        raise ValueError(f"Unsupported provider: {self.config.provider}")

    def _call_gemini(
        self,
        system_prompt: str,
        user_payload: str,
        response_model: Type[T],
    ) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._resolve_api_key())
        response = client.models.generate_content(
            model=self.config.model,
            contents=user_payload,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self.config.temperature,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""

    def _call_claude(self, system_prompt: str, user_payload: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self._resolve_api_key())
        msg = client.messages.create(
            model=self.config.model,
            max_tokens=4096,
            temperature=self.config.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_payload}],
        )
        return "".join(block.text for block in msg.content if hasattr(block, "text"))

    def _call_ollama(self, system_prompt: str, user_payload: str) -> str:
        url = f"{self.config.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.config.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": self.config.temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
        }
        resp = httpx.post(url, json=payload, timeout=120.0)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")


def _extract_json_object(text: str) -> str:
    """Strip optional markdown code fences around JSON."""
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped
