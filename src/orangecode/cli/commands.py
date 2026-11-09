"""命令行入口（Typer）。"""

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from orangecode import __version__
from orangecode.agent.loop import AgentLoop
from orangecode.agent.tools import BashTool, ReadFileTool, ToolRegistry, WriteFileTool
from orangecode.config import settings
from orangecode.providers import LiteLLMProvider

app = typer.Typer(
    name="orangecode",
    help="Concurrent, multi-turn Agent Harness.",
    add_completion=False,
    no_args_is_help=True,
)
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
    model: Annotated[str | None, typer.Option("--model", "-m", help="指定调用的模型名称")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", "-k", help="模型 API Key")] = None,
    api_base: Annotated[str | None, typer.Option("--api-base", "-b", help="模型 Base URL")] = None,
    max_iterations: Annotated[int, typer.Option("--max-iter", help="最大迭代思考轮次")] = 20,
):
    """启动 Agent Loop 执行单次复杂任务。"""
    chosen_model = model or settings.default_model
    chosen_api_key = api_key or settings.api_key
    chosen_api_base = api_base or settings.api_base

    console.print(Panel(f"[bold]Prompt:[/bold] {prompt}", title="[cyan]OrangeCode Task[/cyan]"))
    console.print(f"[dim]Using model:[/dim] [yellow]{chosen_model}[/yellow]")

    # 初始化 Provider 与 ToolRegistry
    provider = LiteLLMProvider(
        model_name=chosen_model,
        api_key=chosen_api_key,
        api_base=chosen_api_base,
    )
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(BashTool())

    agent = AgentLoop(provider=provider, tool_registry=registry)

    async def _execute():
        with console.status("[bold green]Agent thinking and executing tools..."):
            return await agent.run(prompt=prompt, max_iterations=max_iterations)

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


def run():
    """CLI 执行入口点。"""
    app()


if __name__ == "__main__":
    run()
