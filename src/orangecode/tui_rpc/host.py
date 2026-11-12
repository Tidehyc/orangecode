"""TUI 宿主启动器：在后台线程托管 TuiRpcServer 并拉起 Node/Ink 前端进程。"""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import threading
from pathlib import Path

from loguru import logger

from orangecode.config import settings
from orangecode.tui_rpc.server import TuiRpcServer


def resolve_tui_dir() -> Path | None:
    """定位仓库下的 ui-tui 前端根目录。"""
    candidates = [
        Path.cwd() / "ui-tui",
        Path(__file__).resolve().parent.parent.parent.parent / "ui-tui",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return None


def _ensure_ink_dist(tui_dir: Path) -> None:
    """若工作区内置的 @hermes/ink 尚未构建 dist，则先构建一次。"""
    dist_entry = tui_dir / "packages" / "hermes-ink" / "dist" / "entry-exports.js"
    if dist_entry.is_file():
        return
    npm_bin = shutil.which("npm")
    if not npm_bin:
        raise RuntimeError("npm not found while trying to build @hermes/ink.")
    subprocess.run(
        [npm_bin, "run", "build", "--prefix", "packages/hermes-ink"],
        cwd=str(tui_dir),
        check=True,
    )


def _configure_file_logging() -> None:
    """将服务端 loguru 日志重定向到文件，避免污染 AltScreen 终端画面。"""
    log_dir = settings.state_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        str(log_dir / "tui_server.log"),
        rotation="5 MB",
        retention=2,
        level=settings.log_level,
        encoding="utf-8",
    )


def _is_bundle_fresh(tui_dir: Path, dist_entry: Path) -> bool:
    """检查 dist/entry.js 是否存在且不晚于最新 TS/TSX 源码，避免运行过时打包产物。"""
    if not dist_entry.is_file():
        return False
    bundle_mtime = dist_entry.stat().st_mtime
    for src_root in (tui_dir / "src", tui_dir / "packages" / "hermes-ink" / "src"):
        if not src_root.is_dir():
            continue
        for file in src_root.rglob("*.ts*"):
            if file.stat().st_mtime > bundle_mtime:
                return False
    return True


def _ensure_bundle(tui_dir: Path, dist_entry: Path) -> bool:
    """若 dist/entry.js 不存在或已过期则尝试构建一次；返回是否可用。"""
    if _is_bundle_fresh(tui_dir, dist_entry):
        return True
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return False
    try:
        subprocess.run(
            [npm_bin, "run", "build"],
            cwd=str(tui_dir),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return dist_entry.is_file()
    return dist_entry.is_file()


def launch_tui(tui_dir: Path, *, dev: bool = False) -> int:
    """启动本地回环 TuiRpcServer 并在前台运行 ui-tui 子进程，返回前端退出码。"""
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("Node.js runtime not found in PATH (Node >= 22 required).")

    tsx_bin = tui_dir / "node_modules" / ".bin" / "tsx"
    dist_entry = tui_dir / "dist" / "entry.js"
    if not dev and _ensure_bundle(tui_dir, dist_entry):
        cmd = [node_bin, str(dist_entry)]
    elif tsx_bin.is_file():
        _ensure_ink_dist(tui_dir)
        cmd = [str(tsx_bin), "src/entry.tsx"]
    else:
        raise RuntimeError(
            f"Missing ui-tui dependencies at {tui_dir / 'node_modules'}. Run 'npm ci' inside ui-tui first."
        )

    _configure_file_logging()

    token = secrets.token_hex(32)
    cwd = Path.cwd()
    ready_evt = threading.Event()
    state: dict[str, object] = {}

    def _server_thread_main() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server = TuiRpcServer(enable_agent_runtime=True, auth_token=token, cwd=cwd)
        state["loop"] = loop
        state["server"] = server
        try:
            host, port = loop.run_until_complete(server.start_tcp("127.0.0.1", 0))
            state["target"] = f"{host}:{port}"
        except BaseException as exc:
            state["error"] = exc
        finally:
            ready_evt.set()

        if "error" not in state:
            try:
                loop.run_forever()
            finally:
                try:
                    loop.run_until_complete(server.aclose())
                except Exception:
                    pass
                loop.close()
        else:
            loop.close()

    thread = threading.Thread(target=_server_thread_main, name="orangecode-tui-rpc", daemon=True)
    thread.start()
    ready_evt.wait(timeout=10.0)

    if "error" in state:
        raise RuntimeError(f"Failed to start TuiRpcServer: {state['error']}")
    if "target" not in state:
        raise RuntimeError("Timed out waiting for TuiRpcServer to bind.")

    child_env = os.environ.copy()
    child_env["ORANGECODE_RPC_SOCKET"] = str(state["target"])
    child_env["ORANGECODE_RPC_TOKEN"] = token
    child_env["ORANGECODE_CWD"] = str(cwd)

    try:
        proc = subprocess.run(cmd, cwd=str(tui_dir), env=child_env)
        return int(proc.returncode)
    except KeyboardInterrupt:
        return 0
    finally:
        loop = state.get("loop")
        server = state.get("server")
        if isinstance(server, TuiRpcServer):
            server.close()
        if isinstance(loop, asyncio.AbstractEventLoop) and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=3.0)
