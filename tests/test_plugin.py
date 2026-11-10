from pathlib import Path

from orangecode.plugin.manifest import load_manifest_from_toml
from orangecode.plugin.registry import PluginRegistry


def test_plugin_manifest_loading(tmp_path: Path):
    manifest_content = """
    [plugin]
    id = "calculator-plugin"
    version = "1.0.0"
    description = "A math plugin for OrangeCode"
    author = "OrangeCode Team"

    [[plugin.contributes.tools]]
    name = "calc"
    factory = "math:calc"
    description = "Perform calculations"
    """
    toml_file = tmp_path / "orangecode-plugin.toml"
    toml_file.write_text(manifest_content.strip(), encoding="utf-8")

    manifest = load_manifest_from_toml(toml_file)
    assert manifest.id == "calculator-plugin"
    assert manifest.version == "1.0.0"
    assert len(manifest.contributes.tools) == 1
    assert manifest.contributes.tools[0].name == "calc"
    assert manifest.contributes.tools[0].factory == "math:calc"


def test_plugin_registry_discovery(tmp_path: Path):
    plugin_dir = tmp_path / "my_plugin"
    plugin_dir.mkdir()
    manifest_content = """
    [plugin]
    id = "demo-plugin"
    version = "0.1.0"
    """
    (plugin_dir / "orangecode-plugin.toml").write_text(manifest_content.strip(), encoding="utf-8")

    registry = PluginRegistry()
    discovered = registry.discover_directory(tmp_path)
    assert len(discovered) == 1
    assert discovered[0].id == "demo-plugin"
    assert registry.get_plugin("demo-plugin") is not None
