"""Provider-independent structured model calls. Credentials/endpoints stay in the environment."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote, urlsplit

from .providers import JsonClient, ProviderError

PROVIDERS = {"openai", "anthropic", "gemini", "openai_compatible"}
KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
           "gemini": "GEMINI_API_KEY", "openai_compatible": "OPENAI_COMPATIBLE_API_KEY"}


@dataclass(frozen=True, slots=True)
class ModelProfile:
    provider: str
    model: str
    api_key_env: str
    base_url_env: str = ""
    max_output_tokens: int = 6000
    structured_output: str = "json_schema"

    @classmethod
    def parse(cls, data: dict) -> ModelProfile:
        if not isinstance(data, dict) or set(data) - {"provider", "model", "api_key_env", "base_url_env", "max_output_tokens", "structured_output"}:
            raise ValueError("A model profile must use only supported fields; put secrets in environment variables.")
        provider, model = data.get("provider"), data.get("model")
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise ValueError("Model provider must be openai, anthropic, gemini, or openai_compatible.")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError("Each model profile requires a model ID (1–200 characters).")
        env = data.get("api_key_env", KEY_ENV[provider])
        base = data.get("base_url_env", "OPENAI_COMPATIBLE_BASE_URL" if provider == "openai_compatible" else "")
        if not isinstance(env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*_API_KEY", env):
            raise ValueError("api_key_env must name an environment variable ending in _API_KEY.")
        if not isinstance(base, str) or (base and not re.fullmatch(r"[A-Z][A-Z0-9_]*_BASE_URL", base)):
            raise ValueError("base_url_env must name an environment variable ending in _BASE_URL.")
        if provider != "openai_compatible" and base:
            raise ValueError("Custom endpoints are supported only by openai_compatible profiles.")
        limit = data.get("max_output_tokens", 6000)
        if type(limit) is not int or not 256 <= limit <= 32000:
            raise ValueError("max_output_tokens must be an integer between 256 and 32000.")
        mode = data.get("structured_output", "json_schema")
        if mode not in ("json_schema", "json_object") or (mode == "json_object" and provider != "openai_compatible"):
            raise ValueError("json_object mode is supported only for compatible endpoints.")
        return cls(provider, model.strip(), env, base, limit, mode)


class ModelBackend(Protocol):
    usage: dict[str, int]

    def complete(self, instructions: str, data: dict, schema: dict, name: str) -> dict: ...


@dataclass
class StructuredModel:
    profile: ModelProfile
    api_key: str = field(repr=False)
    client: JsonClient = field(default_factory=JsonClient, repr=False)
    base_url: str = ""
    usage: dict[str, int] = field(default_factory=dict, init=False)

    @classmethod
    def from_profile(cls, profile: ModelProfile, timeout: float = 30) -> StructuredModel:
        key = os.environ.get(profile.api_key_env, "").strip()
        base = ""
        if profile.provider == "openai_compatible":
            base = os.environ.get(profile.base_url_env, "").strip().rstrip("/")
            try:
                parts = urlsplit(base)
                local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
                valid = parts.scheme == "https" or (parts.scheme == "http" and local)
                if not valid or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                    raise ValueError()
                _ = parts.port
            except ValueError:
                raise ValueError(f"Set {profile.base_url_env} to an HTTPS API base URL, or HTTP on localhost.") from None
            if not key and not local:
                raise ValueError(f"Set {profile.api_key_env} for this remote endpoint.")
        elif not key:
            raise ValueError(f"Set {profile.api_key_env} to use {profile.provider} models.")
        return cls(profile, key, JsonClient(timeout), base)

    def complete(self, instructions: str, data: dict, schema: dict, name: str) -> dict:
        self.usage = {}
        p = self.profile
        prompt = json.dumps(data)
        if p.provider == "openai":
            result = self.client.post("https://api.openai.com/v1/responses", self.api_key, {
                "model": p.model, "store": False, "max_output_tokens": p.max_output_tokens,
                "instructions": instructions, "input": prompt,
                "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
            })
        elif p.provider == "anthropic":
            result = self.client.post("https://api.anthropic.com/v1/messages", "", {
                "model": p.model, "max_tokens": p.max_output_tokens, "system": instructions,
                "messages": [{"role": "user", "content": prompt}],
                "output_config": {"format": {"type": "json_schema", "schema": schema}},
            }, headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        elif p.provider == "gemini":
            model = quote(p.model.removeprefix("models/"), safe="")
            result = self.client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", "", {
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": p.max_output_tokens,
                                     "responseMimeType": "application/json", "responseJsonSchema": schema},
            }, headers={"x-goog-api-key": self.api_key})
        else:
            output_format = {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
            if p.structured_output == "json_object":
                output_format = {"type": "json_object"}
                instructions += "\nReturn JSON matching this schema: " + json.dumps(schema)
            result = self.client.post(self.base_url + "/chat/completions", self.api_key, {
                "model": p.model, "max_tokens": p.max_output_tokens,
                "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": prompt}],
                "response_format": output_format,
            })
        try:
            raw_usage = result.get("usageMetadata" if p.provider == "gemini" else "usage") or {}
            keys = {"gemini": ("promptTokenCount", "candidatesTokenCount"),
                    "openai_compatible": ("prompt_tokens", "completion_tokens")}.get(p.provider, ("input_tokens", "output_tokens"))
            self.usage = {label: raw_usage[key] for label, key in zip(("input_tokens", "output_tokens"), keys)
                          if type(raw_usage.get(key)) is int and raw_usage[key] >= 0}
            if p.provider == "openai":
                if result.get("status") != "completed":
                    raise ValueError()
                text = "".join(part["text"] for item in result["output"] if item.get("type") == "message"
                               for part in item.get("content", []) if part.get("type") == "output_text")
            elif p.provider == "anthropic":
                if result.get("stop_reason") != "end_turn":
                    raise ValueError()
                text = "".join(part["text"] for part in result["content"] if part.get("type") == "text")
            elif p.provider == "gemini":
                candidate = result["candidates"][0]
                if candidate.get("finishReason") != "STOP":
                    raise ValueError()
                text = "".join(part["text"] for part in candidate["content"]["parts"]
                               if "text" in part and not part.get("thought"))
            else:
                choice = result["choices"][0]
                if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                    raise ValueError()
                text = choice["message"]["content"]
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError()
            return parsed
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ProviderError(f"{p.provider} returned refused, incomplete, or invalid structured output.") from None
