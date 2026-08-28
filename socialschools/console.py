"""How this project talks to a terminal.

One Console and one theme, so PASS is the same green in the evaluator, the
bakeoff and the goal loop. rich drops colour by itself when output is piped,
when NO_COLOR is set or when TERM is dumb — which matters here, because
var/logs/run_report.txt is read back by a model and escape codes would be noise
in its input.

Logs go to stderr and data goes to stdout, so `make eval > table.txt` captures
the table without the chatter.
"""
from rich.console import Console
from rich.table import Table
from rich.theme import Theme
from rich import box

THEME = Theme({
    "ok": "green",
    "bad": "red",
    "alarm": "bold red",
    "warn": "yellow",
    "muted": "dim",
    "head": "bold cyan",
    "money": "bold",
    "logging.level.debug": "dim",
    "logging.level.info": "cyan",
    "logging.level.warning": "yellow",
    "logging.level.error": "bold red",
    "logging.level.critical": "bold white on red",
})

console = Console(theme=THEME)
log_console = Console(theme=THEME, stderr=True)


def new_table(*columns, title=None):
    """A table styled the same way everywhere. Columns are (header, justify) pairs.

    Piped output becomes a Markdown table: readable to a model, and pasteable
    into an issue. Only a real terminal gets box-drawing characters.
    """
    table = Table(title=title,
                  box=box.SIMPLE_HEAD if console.is_terminal else box.MARKDOWN,
                  header_style="head", title_style="head", title_justify="left",
                  pad_edge=False)
    for column in columns:
        header, justify = column if isinstance(column, tuple) else (column, "left")
        table.add_column(header, justify=justify, overflow="fold")
    return table
