"""Command-line entry point for slop.measure."""

import typer

_DESCRIPTION = "Measure redundant and structurally eroded source code."

app = typer.Typer(
    name="slop",
    help=f"slop.measure - {_DESCRIPTION}",
    no_args_is_help=True,
)


@app.callback()
def root() -> None:
    """Initialize the root command."""


def main() -> None:
    """Run the command-line application."""
    app()
