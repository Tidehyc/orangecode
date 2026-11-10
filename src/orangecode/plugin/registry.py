"""插件注册中心与动态装载器。"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from loguru import logger

from orangecode.agent.tools.base import Tool, ToolRegistry
from orangecode.plugin.manifest import PluginManifest, load_manifest_from_toml


class PluginRegistry:
    """管理插件扫描、清单解析与贡献点实例化分发。"""

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self.tool_registry = tool_registry
        self._plugins: dict[str, PluginManifest] = {}

    def register_manifest(self, manifest: PluginManifest) -> None:
        """注册插件清单并实例化其声明的 Tools 挂入 ToolRegistry。"""
        plugin_id = manifest.id
        if plugin_id in self._plugins:
            logger.warning(f"Overwriting already registered plugin: {plugin_id}")
        self._plugins[plugin_id] = manifest

        # 尝试动态加载 Tool 贡献
        if self.tool_registry is not None:
            for tool_contrib in manifest.contributes.tools:
                try:
                    tool_instance = self._resolve_tool(tool_contrib.factory)
                    if isinstance(tool_instance, Tool):
                        self.tool_registry.register(tool_instance)
                        logger.info(f"Loaded tool '{tool_instance.name}' from plugin '{plugin_id}'")
                except Exception as e:
                    logger.error(f"Failed to load tool '{tool_contrib.name}' from '{tool_contrib.factory}': {e}")

    def discover_directory(self, plugins_dir: Path) -> list[PluginManifest]:
        """递归扫描目录下所有包含 orangecode-plugin.toml 的插件子目录。"""
        discovered: list[PluginManifest] = []
        if not plugins_dir.is_dir():
            return discovered

        for toml_path in plugins_dir.glob("**/orangecode-plugin.toml"):
            try:
                manifest = load_manifest_from_toml(toml_path)
                self.register_manifest(manifest)
                discovered.append(manifest)
            except Exception as e:
                logger.error(f"Error parsing plugin manifest at {toml_path}: {e}")

        return discovered

    def get_plugin(self, plugin_id: str) -> PluginManifest | None:
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> list[PluginManifest]:
        return list(self._plugins.values())

    @staticmethod
    def _resolve_tool(factory_ref: str) -> Any:
        module_path, callable_name = factory_ref.split(":")
        mod = importlib.import_module(module_path)
        factory_fn = getattr(mod, callable_name)
        return factory_fn()
