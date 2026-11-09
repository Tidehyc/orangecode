from pathlib import Path

import pytest

from orangecode.context.assembler import ContextAssembler
from orangecode.context.segments import (
    AssemblyContext,
    BootstrapSegment,
    IdentitySegment,
    MemorySegment,
    SkillsSegment,
    render_segments,
)


@pytest.mark.asyncio
async def test_identity_segment(tmp_path: Path):
    seg_builder = IdentitySegment(workspace=tmp_path, agent_name="OrangeCode")
    ctx = AssemblyContext(
        workspace=tmp_path,
        channel="feishu",
        chat_id="oc_12345",
    )
    seg = await seg_builder.build(ctx)
    assert seg is not None
    assert "# OrangeCode Runtime Context" in seg.text
    assert str(tmp_path.resolve()) in seg.text
    assert "Active Channel: feishu" in seg.text


@pytest.mark.asyncio
async def test_bootstrap_segment(tmp_path: Path):
    instructions = tmp_path / "INSTRUCTIONS.md"
    instructions.write_text("Always answer in python.", encoding="utf-8")

    seg_builder = BootstrapSegment(workspace=tmp_path)
    ctx = AssemblyContext(workspace=tmp_path)
    seg = await seg_builder.build(ctx)

    assert seg is not None
    assert "### Workspace Instruction: INSTRUCTIONS.md" in seg.text
    assert "Always answer in python." in seg.text


@pytest.mark.asyncio
async def test_memory_and_skills_segments(tmp_path: Path):
    mem_builder = MemorySegment(memories=["User prefers dark mode", "Project uses uv"])
    skills_builder = SkillsSegment(
        active_skills=[{"name": "git", "description": "Manage git repository"}]
    )

    ctx = AssemblyContext(workspace=tmp_path)

    mem_seg = await mem_builder.build(ctx)
    assert mem_seg is not None
    assert "User prefers dark mode" in mem_seg.text

    skills_seg = await skills_builder.build(ctx)
    assert skills_seg is not None
    assert "**git**: Manage git repository" in skills_seg.text

    combined = render_segments([mem_seg, skills_seg])
    assert "User prefers dark mode" in combined
    assert "**git**" in combined


@pytest.mark.asyncio
async def test_assembler_async_with_segments(tmp_path: Path):
    instructions = tmp_path / "INSTRUCTIONS.md"
    instructions.write_text("Follow PEP 8 strictly.", encoding="utf-8")

    builders = [
        IdentitySegment(workspace=tmp_path),
        BootstrapSegment(workspace=tmp_path),
        MemorySegment(memories=["Key: Value"]),
    ]

    assembler = ContextAssembler(segment_builders=builders)
    messages, outcome = await assembler.assemble_async(
        workspace=tmp_path,
        system_prompt="Base system prompt.",
        history=[],
        current_prompt="Hello world",
    )

    assert outcome.ok
    assert len(messages) == 2
    system_msg = messages[0]["content"]
    assert "Base system prompt." in system_msg
    assert "Follow PEP 8 strictly." in system_msg
    assert "Key: Value" in system_msg
    assert messages[1]["content"] == "Hello world"
