"""插件清单 (orangecode-plugin.toml) 规范模型与解析。"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_FACTORY_REF_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


class _ManifestBase(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class ToolContribution(_ManifestBase):
    name: str = Field(min_length=1)
    factory: str = Field(min_length=1)
    description: str = ""

    @field_validator("factory")
    @classmethod
    def _validate_factory(cls, v: str) -> str:
        if not _FACTORY_REF_RE.match(v):
            raise ValueError(f"factory must be 'module.path:callable', got '{v}'")
        return v


class MemoryBackendContribution(_ManifestBase):
    name: str = Field(min_length=1)
    factory: str = Field(min_length=1)

    @field_validator("factory")
    @classmethod
    def _validate_factory(cls, v: str) -> str:
        if not _FACTORY_REF_RE.match(v):
            raise ValueError(f"factory must be 'module.path:callable', got '{v}'")
        return v


class PluginContributions(_ManifestBase):
    tools: list[ToolContribution] = Field(default_factory=list)
    memory_backends: list[MemoryBackendContribution] = Field(default_factory=list)


class PluginMeta(_ManifestBase):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    author: str = ""
    contributes: PluginContributions = Field(default_factory=PluginContributions)


class PluginManifest(_ManifestBase):
    plugin: PluginMeta

    @property
    def id(self) -> str:
        return self.plugin.id

    @property
    def version(self) -> str:
        return self.plugin.version

    @property
    def description(self) -> str:
        return self.plugin.description

    @property
    def contributes(self) -> PluginContributions:
        return self.plugin.contributes


def load_manifest_from_toml(path: Path) -> PluginManifest:
    """从本地 TOML 文件解析并严格校验插件清单。"""
    raw_data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    return PluginManifest.model_validate(raw_data)
