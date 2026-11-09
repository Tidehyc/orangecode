"""命令行入口（Typer）。"""

import typer
from rich.console import Console

from orangecode import __version__
from orangecode.config import settings

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


def run():
    """CLI 执行入口点。"""
    app()


if __name__ == "__main__":
    run()
