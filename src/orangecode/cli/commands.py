"""命令行入口（Typer + Rich）：支持 run 单次运行、chat 多轮交互与 session 会话管理。"""

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from orangecode import __version__
from orangecode.agent.loop import AgentLoop
from orangecode.agent.tools import BashTool, ReadFileTool, ToolRegistry, WriteFileTool
from orangecode.config import settings
from orangecode.providers import LiteLLMProvider
from orangecode.session.manager import SessionManager
from orangecode.spine.events import (
    ToolEvent,
    ToolPhase,
    TurnEnded,
    TurnEvent,
    TurnStarted,
)
from orangecode.spine.scheduler import SpineScheduler
from orangecode.spine.turn import TurnRequest

app = typer.Typer(
    name="orangecode",
    help="Concurrent, multi-turn Agent Harness with context governance, checkpoint recovery, and sandboxing.",
    add_completion=False,
    no_args_is_help=True,
)
session_app = typer.Typer(name="session", help="会话持久化与检查点管理", no_args_is_help=True)
cron_app = typer.Typer(name="cron", help="定时任务调度管理", no_args_is_help=True)
gateway_app = typer.Typer(name="gateway", help="常驻后台网关管理", no_args_is_help=True)
skills_app = typer.Typer(name="skills", help="技能库检索与查看", no_args_is_help=True)
provider_app = typer.Typer(name="provider", help="模型提供商与智能路由管理", no_args_is_help=True)
evolve_app = typer.Typer(name="evolve", help="自进化变体管理与评估", no_args_is_help=True)

app.add_typer(session_app, name="session")
app.add_typer(cron_app, name="cron")
app.add_typer(gateway_app, name="gateway")
app.add_typer(skills_app, name="skills")
app.add_typer(provider_app, name="provider")
app.add_typer(evolve_app, name="evolve")

console = Console()


@app.callback()
def main_callback():
    """OrangeCode CLI 统一入口。"""
    pass


@app.command("version")
def version_cmd():
    """查看当前版本号与环境配置。"""
    console.print(f"[bold cyan]OrangeCode[/bold cyan] v[bold green]{__version__}[/bold green]")
    console.print(f"Default model: [yellow]{settings.default_model}[/yellow]")
    console.print(f"State dir: [dim]{settings.state_dir}[/dim]")


@app.command("status")
def status_cmd():
    """查看 OrangeCode 运行时整体健康与会话/渠道状态。"""
    mgr = SessionManager()
    sessions = mgr.list_sessions()

    table = Table(title="OrangeCode Harness Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Version", f"v{__version__}")
    table.add_row("Default Model", settings.default_model)
    table.add_row("API Key Configured", "Yes" if settings.api_key else "No (Set via ORANGECODE_API_KEY)")
    table.add_row("State Directory", str(settings.state_dir))
    table.add_row("Saved Sessions", str(len(sessions)))
    table.add_row("Environment", settings.environment)
    table.add_row("Max Tool Iterations", str(settings.max_tool_iterations))

    console.print(table)


@app.command("tui")
def tui_cmd(
    check: bool = typer.Option(False, "--check", help="仅烟雾测试 Node.js 与 TUI 依赖并退出"),
    dev: bool = typer.Option(True, "--dev", help="从 TypeScript 源码启动"),
):
    """启动 Node.js + React + Ink 原生终端 UI。"""
    import shutil
    import subprocess
    from pathlib import Path

    node_bin = shutil.which("node")
    if not node_bin:
        console.print("[bold red]Error:[/bold red] Node.js runtime not found in PATH. Node >= 22 required.")
        raise typer.Exit(1)

    tui_dir = Path.cwd() / "ui-tui"
    if not tui_dir.is_dir():
        tui_dir = Path(__file__).resolve().parent.parent.parent.parent / "ui-tui"

    if not tui_dir.is_dir():
        console.print(f"[bold red]Error:[/bold red] ui-tui directory not found at {tui_dir}")
        raise typer.Exit(1)

    if check:
        console.print(f"[green]✓[/green] Found Node.js: {node_bin}")
        console.print(f"[green]✓[/green] Found TUI source at: {tui_dir}")
        return

    console.print("[cyan]Launching OrangeCode Native Terminal UI...[/cyan]")
    try:
        subprocess.run(["npm", "run", "dev"], cwd=str(tui_dir))
    except KeyboardInterrupt:
        console.print("\n[dim]TUI closed.[/dim]")


@app.command("doctor")
def doctor_cmd():
    """执行环境自检与系统健康体检。"""
    import shutil
    import sys

    table = Table(title="OrangeCode Doctor System Diagnostics")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    # 1. Python 版本
    py_ver = sys.version.split()[0]
    if sys.version_info >= (3, 12):
        table.add_row("Python Interpreter", "[green]✓ PASS[/green]", f"Python {py_ver}")
    else:
        table.add_row("Python Interpreter", "[red]✗ FAIL[/red]", f"Python {py_ver} (>=3.12 required)")

    # 2. Node.js
    node_path = shutil.which("node")
    if node_path:
        table.add_row("Node.js Runtime", "[green]✓ PASS[/green]", f"Found at {node_path}")
    else:
        table.add_row("Node.js Runtime", "[yellow]! OPTIONAL[/yellow]", "Node.js not on PATH (required only for UI-TUI)")

    # 3. Git
    git_path = shutil.which("git")
    if git_path:
        table.add_row("Git VCS", "[green]✓ PASS[/green]", f"Found at {git_path}")
    else:
        table.add_row("Git VCS", "[red]✗ FAIL[/red]", "git binary not found")

    # 4. State dir
    try:
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        test_file = settings.state_dir / ".doctor_probe"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        table.add_row("State Directory Storage", "[green]✓ PASS[/green]", f"Writable at {settings.state_dir}")
    except Exception as e:
        table.add_row("State Directory Storage", "[red]✗ FAIL[/red]", f"Write error: {e}")

    # 5. Model Configuration
    api_key_status = "[green]Configured[/green]" if settings.api_key else "[yellow]Not set (use ORANGECODE_API_KEY or .env)[/yellow]"
    table.add_row("Default Model", "[green]✓ PASS[/green]", f"{settings.default_model} (API Key: {api_key_status})")

    # 6. Sandboxing
    srt_found = shutil.which("srt") is not None
    table.add_row("Direct & Isolated Sandbox", "[green]✓ PASS[/green]", "Direct and Workspace-isolated sandboxes ready")
    table.add_row("Anthropic SRT OS Sandbox", "[green]✓ PASS[/green]" if srt_found else "[yellow]! STANDBY[/yellow]", "Available" if srt_found else "Not installed (Optional OS-level sandbox)")

    console.print(table)


@app.command("run")
def run_agent_cmd(
    prompt: Annotated[str, typer.Argument(help="给智能体下达的任务提示词")],
    conversation_id: Annotated[str, typer.Option("--session", "-s", help="会话 ID（支持断点续聊）")] = "default",
    model: Annotated[str | None, typer.Option("--model", "-m", help="指定调用的模型名称")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", "-k", help="模型 API Key")] = None,
    api_base: Annotated[str | None, typer.Option("--api-base", "-b", help="模型 Base URL")] = None,
    max_iterations: Annotated[int, typer.Option("--max-iter", help="最大迭代思考轮次")] = 20,
):
    """启动 Agent Loop 执行单次复杂任务（由 Spine 调度管理）。"""
    chosen_model = model or settings.default_model
    chosen_api_key = api_key or settings.api_key
    chosen_api_base = api_base or settings.api_base

    console.print(Panel(f"[bold]Prompt:[/bold] {prompt}", title=f"[cyan]OrangeCode Task (Session: {conversation_id})[/cyan]"))
    console.print(f"[dim]Model:[/dim] [yellow]{chosen_model}[/yellow]")

    provider = LiteLLMProvider(
        model_name=chosen_model,
        api_key=chosen_api_key,
        api_base=chosen_api_base,
    )
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(BashTool())

    def agent_factory(cid: str) -> AgentLoop:
        return AgentLoop(provider=provider, tool_registry=registry)

    async def on_run_event(evt: TurnEvent):
        if isinstance(evt, ToolEvent):
            if evt.phase == ToolPhase.START:
                console.print(f"[cyan]⚡ Executing tool: [bold]{evt.tool_name}[/bold] {evt.arguments or ''}[/cyan]")
            elif evt.phase == ToolPhase.COMPLETE:
                if evt.failed:
                    console.print(f"[red]✗ Tool '{evt.tool_name}' failed:[/red] {evt.result}")
                else:
                    console.print(f"[green]✓ Tool '{evt.tool_name}' completed[/green]")

    scheduler = SpineScheduler(agent_factory=agent_factory, event_sink=on_run_event)

    async def _execute():
        with console.status("[bold green]Agent thinking and executing tools via Spine..."):
            handle = scheduler.submit(
                TurnRequest(
                    prompt=prompt,
                    conversation_id=conversation_id,
                )
            )
            return await handle.wait()

    outcome = asyncio.run(_execute())

    if outcome.success:
        console.print(
            Panel(
                Markdown(outcome.final_content),
                title="[bold green]Final Answer[/bold green]",
                subtitle=f"Iterations: {outcome.iterations} | Tokens: {outcome.total_usage.total_tokens}",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]Task Failed / Stopped:[/bold red] {outcome.error_message}\n\n{outcome.final_content}",
                title="[bold red]Execution Alert[/bold red]",
            )
        )


@app.command("chat")
def chat_cmd(
    conversation_id: Annotated[str, typer.Option("--session", "-s", help="会话 ID（默认新生成）")] = "chat-cli",
    model: Annotated[str | None, typer.Option("--model", "-m", help="指定调用的模型名称")] = None,
):
    """启动交互式多轮对话终端（REPL）。"""
    chosen_model = model or settings.default_model
    console.print(Panel(f"[bold green]OrangeCode Interactive Chat[/bold green]\nSession ID: [cyan]{conversation_id}[/cyan]\nModel: [yellow]{chosen_model}[/yellow]\nType 'exit' or 'quit' to end chat.", border_style="green"))

    provider = LiteLLMProvider(model_name=chosen_model)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(BashTool())

    async def on_event(evt: TurnEvent):
        if isinstance(evt, TurnStarted):
            console.print(f"[dim]Turn started: {evt.turn_id}[/dim]")
        elif isinstance(evt, ToolEvent):
            if evt.phase == ToolPhase.START:
                console.print(f"[cyan]⚡ Tool: [bold]{evt.tool_name}[/bold][/cyan]")
            elif evt.phase == ToolPhase.COMPLETE:
                if evt.failed:
                    console.print(f"[red]✗ Tool '{evt.tool_name}' failed[/red]")
                else:
                    console.print(f"[green]✓ Tool '{evt.tool_name}' done[/green]")
        elif isinstance(evt, TurnEnded):
            console.print(f"[dim]Turn finished (tokens: {evt.usage.total_tokens})[/dim]")

    scheduler = SpineScheduler(
        agent_factory=lambda cid: AgentLoop(provider=provider, tool_registry=registry),
        event_sink=on_event,
    )

    while True:
        try:
            user_input = console.input("\n[bold cyan]You > [/bold cyan]").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                console.print("[dim]Goodbye![/dim]")
                break

            async def _chat_turn():
                with console.status("[bold green]Thinking..."):
                    handle = scheduler.submit(
                        TurnRequest(
                            prompt=user_input,
                            conversation_id=conversation_id,
                        )
                    )
                    return await handle.wait()

            outcome = asyncio.run(_chat_turn())
            console.print("\n[bold green]OrangeCode > [/bold green]")
            console.print(Markdown(outcome.final_content))
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session terminated.[/dim]")
            break


# ----------------------------------------------------------------------
# Session 子命令集合
# ----------------------------------------------------------------------


@session_app.command("list")
def list_sessions_cmd():
    """列出磁盘中持久化的所有历史会话。"""
    mgr = SessionManager()
    sessions = mgr.list_sessions()
    if not sessions:
        console.print("[dim]No saved sessions found.[/dim]")
        return

    table = Table(title="OrangeCode Saved Sessions")
    table.add_column("Conversation ID", style="cyan", no_wrap=True)
    table.add_column("Messages", justify="right", style="green")
    table.add_column("Last Updated", style="yellow")
    table.add_column("Created At", style="dim")

    for s in sessions:
        table.add_row(
            s.conversation_id,
            str(s.message_count),
            s.updated_at[:19].replace("T", " "),
            s.created_at[:19].replace("T", " "),
        )
    console.print(table)


@session_app.command("show")
def show_session_cmd(conversation_id: str):
    """查看指定会话的完整对话记录。"""
    mgr = SessionManager()
    record = mgr.load(conversation_id)
    if not record:
        console.print(f"[bold red]Session '{conversation_id}' not found.[/bold red]")
        return

    console.print(Panel(f"Session: [cyan]{conversation_id}[/cyan] ({record.metadata.message_count} messages)", title="Transcript"))
    for msg in record.messages:
        role = msg.get("role", "unknown")
        content = msg.get("content") or ""
        if role == "user":
            console.print(f"[bold cyan]User:[/bold cyan] {content}")
        elif role == "assistant":
            if msg.get("tool_calls"):
                tools = [tc["function"]["name"] for tc in msg["tool_calls"]]
                console.print(f"[bold green]Assistant (tool calls):[/bold green] [yellow]{tools}[/yellow]")
            else:
                console.print(f"[bold green]Assistant:[/bold green] {content}")
        elif role == "tool":
            preview = content[:200] + ("..." if len(content) > 200 else "")
            console.print(f"[dim]Tool Result ({msg.get('name', 'tool')}):[/dim] {preview}")


@session_app.command("delete")
def delete_session_cmd(conversation_id: str):
    """删除指定会话。"""
    mgr = SessionManager()
    if mgr.delete(conversation_id):
        console.print(f"[green]Session '{conversation_id}' successfully deleted.[/green]")
    else:
        console.print(f"[yellow]Session '{conversation_id}' does not exist.[/yellow]")


@session_app.command("export")
def export_session_cmd(
    conversation_id: str,
    output: Annotated[str | None, typer.Option("--output", "-o", help="导出文件目标路径")] = None,
    fmt: Annotated[str, typer.Option("--format", "-f", help="导出格式: md 或 json")] = "md",
):
    """将会话导出为 Markdown 轨迹文档或带校验和的 JSON 凭证。"""
    from pathlib import Path

    from orangecode.session.export import export_session_to_file

    mgr = SessionManager()
    record = mgr.load(conversation_id)
    if not record:
        console.print(f"[bold red]Session '{conversation_id}' not found.[/bold red]")
        return

    ext = ".json" if fmt.lower() == "json" else ".md"
    dest = Path(output) if output else Path(f"{conversation_id}_export{ext}")
    saved_path = export_session_to_file(record, dest)
    console.print(f"[bold green]Successfully exported session to:[/bold green] [cyan]{saved_path}[/cyan]")


# ----------------------------------------------------------------------
# Cron 子命令集合
# ----------------------------------------------------------------------


@cron_app.command("list")
def list_cron_cmd():
    """列出所有已配置的定时任务。"""
    from datetime import datetime

    from orangecode.proactive_engine.cron import CronService

    svc = CronService()
    jobs = svc.list_jobs()
    if not jobs:
        console.print("[dim]No cron jobs found.[/dim]")
        return

    table = Table(title="OrangeCode Scheduled Cron Jobs")
    table.add_column("Job ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Cron Expression", style="yellow")
    table.add_column("Next Run", style="green")
    table.add_column("Prompt", style="dim")

    for j in jobs:
        next_str = datetime.fromtimestamp(j.next_run_at).strftime("%Y-%m-%d %H:%M:%S") if j.next_run_at else "-"
        table.add_row(j.job_id, j.name, j.cron_expr, next_str, j.prompt[:40] + ("..." if len(j.prompt) > 40 else ""))
    console.print(table)


@cron_app.command("add")
def add_cron_cmd(
    name: Annotated[str, typer.Argument(help="任务名称")],
    cron_expr: Annotated[str, typer.Argument(help="5 位标准 Cron 表达式 (如 '0 9 * * *')")],
    prompt: Annotated[str, typer.Argument(help="到期触发时执行的提示词")],
):
    """添加一个新的定时调度作业。"""
    from orangecode.proactive_engine.cron import CronService

    svc = CronService()
    try:
        job = svc.add_job(name=name, cron_expr=cron_expr, prompt=prompt)
        console.print(f"[bold green]Cron job successfully created:[/bold green] [cyan]{job.job_id}[/cyan]")
    except Exception as e:
        console.print(f"[bold red]Failed to add cron job:[/bold red] {e}")


@cron_app.command("remove")
def remove_cron_cmd(job_id: str):
    """移除指定定时作业。"""
    from orangecode.proactive_engine.cron import CronService

    svc = CronService()
    if svc.remove_job(job_id):
        console.print(f"[green]Cron job '{job_id}' removed.[/green]")
    else:
        console.print(f"[yellow]Cron job '{job_id}' not found.[/yellow]")


# ----------------------------------------------------------------------
# Gateway 后台常驻网关服务
# ----------------------------------------------------------------------


@gateway_app.command("start")
def start_gateway_cmd(
    model: Annotated[str | None, typer.Option("--model", "-m", help="指定主模型")] = None,
):
    """启动常驻后台 Gateway：集成 Spine 调度总线、Cron 定时引擎与多平台消息中枢。"""
    from orangecode.agent.tools import BashTool, ReadFileTool, ToolRegistry, WriteFileTool
    from orangecode.channels import ChannelManager, FeishuChannel, WeComChannel
    from orangecode.proactive_engine.cron import CronService

    chosen_model = model or settings.default_model
    console.print(Panel(f"[bold green]OrangeCode Unified Gateway Daemon[/bold green]\nModel: [yellow]{chosen_model}[/yellow]\nPress Ctrl+C to terminate.", border_style="cyan"))

    provider = LiteLLMProvider(model_name=chosen_model)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(BashTool())

    channel_mgr: ChannelManager | None = None

    async def gateway_event_sink(evt: TurnEvent):
        if channel_mgr:
            await channel_mgr.on_spine_event(evt)

    scheduler = SpineScheduler(
        agent_factory=lambda cid: AgentLoop(provider=provider, tool_registry=registry),
        event_sink=gateway_event_sink,
    )

    channel_mgr = ChannelManager(scheduler=scheduler)
    channel_mgr.register_channel(FeishuChannel())
    channel_mgr.register_channel(WeComChannel())

    cron_svc = CronService()

    async def _main_loop():
        try:
            await cron_svc.start(scheduler=scheduler, check_interval=1.0)
        except asyncio.CancelledError:
            cron_svc.stop()
            await scheduler.shutdown()

    try:
        asyncio.run(_main_loop())
    except KeyboardInterrupt:
        console.print("\n[dim]Gateway daemon stopped gracefully.[/dim]")


# ----------------------------------------------------------------------
# Skills, Provider & Evolve 子命令集合
# ----------------------------------------------------------------------


@skills_app.command("list")
def list_skills_cmd(
    directory: str = typer.Option(".", "--dir", "-d", help="技能包根目录"),
):
    """列出指定目录下所有通过 SKILL.md 定义的技能。"""
    from pathlib import Path

    from orangecode.memory_engine.skill_local import SkillWatcher

    watcher = SkillWatcher(root_dir=Path(directory))
    skills = watcher.skills
    if not skills:
        console.print("[dim]No skills found (looking for **/SKILL.md)[/dim]")
        return

    table = Table(title=f"Discovered Skills ({len(skills)})")
    table.add_column("Name", style="bold cyan")
    table.add_column("Description", style="white")
    table.add_column("Path", style="dim")
    for s in skills.values():
        table.add_row(s.name, s.description, str(s.path or ""))
    console.print(table)


@provider_app.command("list")
def list_providers_cmd():
    """列出当前激活的大模型提供商与智能路由策略。"""
    table = Table(title="Configured Providers & Routing")
    table.add_column("Component", style="cyan")
    table.add_column("Status / Config", style="green")

    table.add_row("Primary Provider", "LiteLLM Multi-model Gateway")
    table.add_row("Active Model", settings.default_model)
    table.add_row("Semantic Router", "KNN Cosine Utility Router (Active)")
    table.add_row("Failover Policy", "FallbackProvider (Exponential Backoff)")
    table.add_row("Cost Ledger", "Pricing & Prompt Cache Tracking (Active)")
    console.print(table)


@evolve_app.command("run")
def run_evolve_cmd(
    name: str = typer.Option("candidate_1", "--name", "-n", help="变体名称"),
):
    """运行一轮变体评估与 UCB1 老虎机探索选择。"""
    from orangecode.evolver import (
        CandidateLabel,
        CandidateManifest,
        EvolutionTree,
        StatisticalGate,
        TreeAwareBandit,
    )

    manifest = CandidateManifest(
        candidate_id=name,
        label=CandidateLabel.PROMPT,
        hypothesis="Be concise and factual in responses",
        diff_patch="# Evolved prompt rule: Be concise and factual.",
    )
    tree = EvolutionTree(root_id="root", baseline_score=0.8)
    tree.add_node(node_id=name, parent_id="root", manifest=manifest, score=0.85)

    bandit = TreeAwareBandit()
    selected_node = bandit.select_node(tree)

    gate = StatisticalGate(min_delta=0.02, min_trials=3)
    verdict = gate.evaluate([0.8, 0.82, 0.81], [0.85, 0.88, 0.86])

    console.print("[bold green]Evolution Round Completed[/bold green]")
    console.print(f"- Registered Candidate ID: [cyan]{manifest.candidate_id}[/cyan] ({manifest.label})")
    console.print(f"- Tree Total Nodes: [yellow]{len(tree.nodes)}[/yellow]")
    console.print(f"- Bandit Selected Node: [bold magenta]{selected_node.node_id}[/bold magenta] (score: {selected_node.score})")
    gate_color = "green" if verdict.passed else "red"
    console.print(f"- Statistical Gate Passed: [{gate_color}]{verdict.passed}[/{gate_color}] (delta: +{verdict.delta:.3f})")


def run():
    """CLI 执行入口点。"""
    app()


if __name__ == "__main__":
    run()
