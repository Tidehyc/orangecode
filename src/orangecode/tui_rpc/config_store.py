"""TUI 运行时模型与凭证配置存储。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from orangecode.config import settings


@dataclass
class ProviderSpec:
    """单个模型供应商的元信息与可选模型列表。"""

    slug: str
    name: str
    key_env: str
    models: list[str] = field(default_factory=list)
    needs_api_base: bool = False
    auth_type: str = "api_key"
    default_api_base: str | None = None


_BUILTIN_PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        slug="deepseek",
        name="DeepSeek",
        key_env="DEEPSEEK_API_KEY",
        models=["deepseek/deepseek-chat", "deepseek/deepseek-reasoner"],
    ),
    ProviderSpec(
        slug="openai",
        name="OpenAI",
        key_env="OPENAI_API_KEY",
        models=["gpt-4o", "gpt-4.1", "o3-mini"],
    ),
    ProviderSpec(
        slug="anthropic",
        name="Anthropic",
        key_env="ANTHROPIC_API_KEY",
        models=["anthropic/claude-sonnet-4-6", "anthropic/claude-opus-4-6"],
    ),
    ProviderSpec(
        slug="openrouter",
        name="OpenRouter",
        key_env="OPENROUTER_API_KEY",
        models=[
            "openrouter/anthropic/claude-sonnet-4",
            "openrouter/deepseek/deepseek-chat",
        ],
    ),
    ProviderSpec(
        slug="google",
        name="Google Gemini",
        key_env="GEMINI_API_KEY",
        models=["gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash"],
    ),
    ProviderSpec(
        slug="custom",
        name="Custom OpenAI-Compatible",
        key_env="ORANGECODE_API_KEY",
        models=["openai/gpt-4o-mini"],
        needs_api_base=True,
    ),
)


def infer_provider_slug(model_name: str) -> str:
    """根据 LiteLLM 模型名推断供应商标识。"""
    lower = (model_name or "").strip().lower()
    if "/" in lower:
        prefix = lower.split("/", 1)[0]
        if prefix in {"deepseek", "openai", "anthropic", "openrouter", "google"}:
            return prefix
        if prefix == "gemini":
            return "google"
        return "custom"
    if lower.startswith("claude"):
        return "anthropic"
    if lower.startswith("gemini"):
        return "google"
    if lower.startswith("deepseek"):
        return "deepseek"
    return "openai"


class TuiConfigStore:
    """管理 TUI 会话使用的活跃模型、供应商密钥与自定义模型目录。"""

    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir or settings.state_dir
        self.config_path = self.state_dir / "tui_config.json"
        self.model: str = settings.default_model
        self.provider: str = infer_provider_slug(self.model)
        self.reasoning_effort: str | None = None
        self._keys: dict[str, dict[str, str]] = {}
        self._custom_models: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Failed to read {self.config_path}: {exc}")
            return

        if isinstance(data.get("model"), str) and data["model"].strip():
            self.model = data["model"].strip()
        if isinstance(data.get("provider"), str) and data["provider"].strip():
            self.provider = data["provider"].strip().lower()
        else:
            self.provider = infer_provider_slug(self.model)
        if isinstance(data.get("reasoning_effort"), str) and data["reasoning_effort"].strip():
            self.reasoning_effort = data["reasoning_effort"].strip()
        if isinstance(data.get("keys"), dict):
            for slug, entry in data["keys"].items():
                if isinstance(entry, dict):
                    clean: dict[str, str] = {}
                    if isinstance(entry.get("api_key"), str) and entry["api_key"].strip():
                        clean["api_key"] = entry["api_key"].strip()
                    if isinstance(entry.get("api_base"), str) and entry["api_base"].strip():
                        clean["api_base"] = entry["api_base"].strip()
                    if clean:
                        self._keys[str(slug)] = clean
        if isinstance(data.get("custom_models"), dict):
            for slug, items in data["custom_models"].items():
                if isinstance(items, list):
                    self._custom_models[str(slug)] = [str(m).strip() for m in items if str(m).strip()]

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "provider": self.provider,
            "reasoning_effort": self.reasoning_effort,
            "keys": self._keys,
            "custom_models": self._custom_models,
        }
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.config_path)

    def _find_spec(self, slug: str) -> ProviderSpec | None:
        norm = slug.strip().lower()
        for spec in _BUILTIN_PROVIDERS:
            if spec.slug == norm:
                return spec
        return None

    def _env_key_for(self, spec: ProviderSpec) -> str | None:
        val = os.environ.get(spec.key_env, "").strip()
        if val:
            return val
        # 全局 ORANGECODE_API_KEY / settings.api_key 仅匹配默认供应商或 custom
        if settings.api_key and (spec.slug == infer_provider_slug(settings.default_model) or spec.slug == "custom"):
            return settings.api_key
        return None

    def is_provider_authenticated(self, slug: str) -> bool:
        spec = self._find_spec(slug)
        if not spec:
            return bool(self._keys.get(slug, {}).get("api_key"))
        if self._keys.get(spec.slug, {}).get("api_key"):
            return True
        return bool(self._env_key_for(spec))

    def has_any_credentials(self) -> bool:
        return bool(settings.api_key) or any(
            self.is_provider_authenticated(spec.slug) for spec in _BUILTIN_PROVIDERS
        )

    def resolve_credentials(self, model_name: str | None = None, provider_slug: str | None = None) -> tuple[str | None, str | None]:
        """解析指定或当前模型可用的 (api_key, api_base)。"""
        target_model = (model_name or self.model).strip()
        slug = (provider_slug or self.provider or infer_provider_slug(target_model)).strip().lower()
        stored = self._keys.get(slug, {})
        spec = self._find_spec(slug)

        api_key = stored.get("api_key") or (self._env_key_for(spec) if spec else None) or settings.api_key
        api_base = stored.get("api_base") or settings.api_base
        return api_key, api_base

    def _provider_payload(self, spec: ProviderSpec) -> dict[str, Any]:
        models = list(dict.fromkeys([*spec.models, *self._custom_models.get(spec.slug, [])]))
        if spec.slug == self.provider and self.model and self.model not in models:
            models.insert(0, self.model)
        return {
            "slug": spec.slug,
            "name": spec.name,
            "authenticated": self.is_provider_authenticated(spec.slug),
            "is_current": spec.slug == self.provider,
            "auth_type": spec.auth_type,
            "key_env": spec.key_env,
            "models": models,
            "total_models": len(models),
            "needs_api_base": spec.needs_api_base,
            "warning": "",
        }

    def model_options(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "providers": [self._provider_payload(spec) for spec in _BUILTIN_PROVIDERS],
        }

    def save_key(self, slug: str, api_key: str, api_base: str | None = None) -> dict[str, Any]:
        spec = self._find_spec(slug)
        if not spec:
            raise KeyError(f"Unknown provider '{slug}'")
        cleaned_key = api_key.strip()
        if not cleaned_key:
            raise ValueError("API key is required")
        cleaned_base = (api_base or "").strip()
        if spec.needs_api_base and not cleaned_base:
            raise ValueError("API base URL is required for custom provider")

        entry: dict[str, str] = {"api_key": cleaned_key}
        if cleaned_base:
            entry["api_base"] = cleaned_base
        self._keys[spec.slug] = entry
        self._save()
        return {"provider": self._provider_payload(spec)}

    def add_model(self, slug: str, model: str) -> dict[str, Any]:
        spec = self._find_spec(slug)
        if not spec:
            raise KeyError(f"Unknown provider '{slug}'")
        cleaned = model.strip()
        if not cleaned:
            raise ValueError("Model name is required")
        bucket = self._custom_models.setdefault(spec.slug, [])
        if cleaned not in bucket and cleaned not in spec.models:
            bucket.append(cleaned)
            self._save()
        return {"provider": self._provider_payload(spec)}

    def remove_model(self, slug: str, model: str) -> dict[str, Any]:
        spec = self._find_spec(slug)
        if not spec:
            raise KeyError(f"Unknown provider '{slug}'")
        cleaned = model.strip()
        bucket = self._custom_models.get(spec.slug, [])
        if cleaned in bucket:
            bucket.remove(cleaned)
            self._save()
        return {"provider": self._provider_payload(spec)}

    def disconnect(self, slug: str) -> dict[str, Any]:
        norm = slug.strip().lower()
        removed = norm in self._keys
        self._keys.pop(norm, None)
        if removed:
            self._save()
        return {"disconnected": removed}

    def set_active_model(self, model: str, provider: str | None = None) -> str:
        cleaned = model.strip()
        if not cleaned:
            raise ValueError("Model name cannot be empty")
        prev = self.model
        self.model = cleaned
        self.provider = (provider or infer_provider_slug(cleaned)).strip().lower()
        self._save()
        return prev

    def set_reasoning_effort(self, effort: str | None) -> str | None:
        prev = self.reasoning_effort
        self.reasoning_effort = effort.strip() if effort and effort.strip() else None
        self._save()
        return prev

    def snapshot(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "reasoning_effort": self.reasoning_effort or "",
            "max_tool_iterations": settings.max_tool_iterations,
            "environment": settings.environment,
        }
