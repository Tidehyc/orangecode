"""测试命令执行沙箱与受限环境。"""

import pytest

from orangecode.sandbox.direct_executor import DirectExecutor
from orangecode.sandbox.interfaces import ExecResult
from orangecode.sandbox.isolated_executor import IsolatedWorkspaceExecutor


@pytest.mark.asyncio
async def test_direct_executor():
    executor = DirectExecutor()
    res = await executor.execute("echo 'OrangeCode Sandbox'")
    assert res.exit_code == 0
    assert "OrangeCode Sandbox" in res.stdout


@pytest.mark.asyncio
async def test_direct_executor_timeout():
    executor = DirectExecutor()
    res = await executor.execute("sleep 2", timeout=0.1)
    assert res.exit_code == 124
    assert "timed out" in res.stderr


@pytest.mark.asyncio
async def test_isolated_workspace_executor(tmp_path):
    sandbox_dir = tmp_path / "sandbox"
    executor = IsolatedWorkspaceExecutor(sandbox_root=sandbox_dir)
    assert executor.is_sandboxed

    # 验证环境变量隔离与命令执行
    res = await executor.execute("echo $ORANGECODE_SANDBOX && pwd")
    assert res.exit_code == 0
    assert "1" in res.stdout
    assert str(sandbox_dir) in res.stdout


def test_exec_result_truncation():
    long_stdout = "line " * 2000
    res = ExecResult(stdout=long_stdout, stderr="", exit_code=0)
    text = res.as_text(max_chars=200)
    assert len(text) < 400
    assert "truncated" in text
