"""测试 Milestone 3：沙箱工厂配置、SRT 门禁守护、会话 Markdown 导出与 SHA-256 自校验信封。"""

import json

import pytest

from orangecode.sandbox.builder import build_executor
from orangecode.sandbox.config import SandboxConfig
from orangecode.sandbox.srt_executor import SRTExecutor
from orangecode.session.export import export_session_to_file, render_transcript, verify_export
from orangecode.session.manager import SessionMetadata, SessionRecord


def test_sandbox_builder(tmp_path):
    # 1. Direct
    cfg_direct = SandboxConfig(backend="direct")
    exec_direct = build_executor(cfg_direct)
    assert not exec_direct.is_sandboxed

    # 2. Isolated
    cfg_isolated = SandboxConfig(backend="isolated", workspace_dir=tmp_path)
    exec_isolated = build_executor(cfg_isolated)
    assert exec_isolated.is_sandboxed


@pytest.mark.asyncio
async def test_srt_executor_unavailable_guard(tmp_path):
    # 当系统中未安装 srt 二进制文件时，SRTExecutor 必须严厉拒绝执行，不可静默退回宿主机
    srt_exec = SRTExecutor(workspace_dir=tmp_path)
    # 模拟 srt 缺失
    srt_exec._probe_srt_available = lambda: False

    res = await srt_exec.execute("echo 'danger'")
    assert res.exit_code == 127
    assert "Refusing to execute command without mandatory OS sandbox boundary" in res.stderr


def test_session_export_and_verification(tmp_path):
    meta = SessionMetadata(conversation_id="test-export-session", message_count=3)
    messages = [
        {"role": "user", "content": "How do I build a tree?"},
        {
            "role": "assistant",
            "content": "Use nodes and pointers.",
            "tool_calls": [{"function": {"name": "read_file", "arguments": "{\"path\": \"tree.py\"}"}}],
        },
        {"role": "tool", "content": "File contents of tree.py"},
    ]
    record = SessionRecord(metadata=meta, messages=messages)

    # 1. 验证渲染 Markdown 轨迹
    md_text = render_transcript(record)
    assert "## 🧑 User" in md_text
    assert "## 🤖 Assistant" in md_text
    assert "Tool Calls:" in md_text
    assert "tree.py" in md_text

    # 2. 导出为可自校验的 JSON 信封
    json_export_dest = tmp_path / "export.json"
    export_session_to_file(record, json_export_dest)
    assert json_export_dest.exists()

    # 校验合法性
    assert verify_export(json_export_dest)

    # 3. 模拟篡改数据，校验必须失败
    envelope_data = json.loads(json_export_dest.read_text(encoding="utf-8"))
    envelope_data["payload"]["messages"][0]["content"] = "Tampered query"
    tampered_dest = tmp_path / "tampered.json"
    tampered_dest.write_text(json.dumps(envelope_data), encoding="utf-8")

    assert not verify_export(tampered_dest)
