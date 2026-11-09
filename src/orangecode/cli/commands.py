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
from orangecode.spine.events import TurnEnded, TurnEvent, TurnStarted
from orangecode.spine.scheduler import SpineScheduler
from orangecode.spine.turn import TurnRequest

app = typer.Typer(
    name="orangecode",
    help="Concurrent, multi-turn Agent Harness with context governance, checkpoint recovery, and sandboxing.",
    add_completion=False,
    no_args_is_help=True,
)
session_app = typer.Typer(name="session", help="会话持久化与检查点管理", no_args_is_help=True)
app.add_typer(session_app, name="session")

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

    scheduler = SpineScheduler(agent_factory=agent_factory)

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


def run():
    """CLI 执行入口点。"""
    app()


if __name__ == "__main__":
    run()
