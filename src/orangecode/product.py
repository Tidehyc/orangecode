"""集中定义 OrangeCode 产品标识与项目隔离状态根路径。"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

PRODUCT_NAME = "OrangeCode"
PRODUCT_LOGO = "🍊"
CLI_NAME = "orangecode"
DISTRIBUTION_NAME = "orangecode"
GLOBAL_STATE_DIRNAME = ".orangecode"
WORKSPACE_STATE_DIRNAME = ".orangecode"
DEFAULT_WORKSPACE_SPEC = "~/.orangecode/workspace"


def get_product_home() -> Path:
    override = os.environ.get("ORANGECODE_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / GLOBAL_STATE_DIRNAME


def get_default_workspace() -> Path:
    return get_product_home() / "workspace"


def get_workspace_state_dir(workspace: Path) -> Path:
    return workspace / WORKSPACE_STATE_DIRNAME


def get_project_state_dir(workspace: Path) -> Path:
    resolved = workspace.expanduser().resolve()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved.name).strip(".-") or "workspace"
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return get_product_home() / "projects" / f"{slug}-{digest}"
