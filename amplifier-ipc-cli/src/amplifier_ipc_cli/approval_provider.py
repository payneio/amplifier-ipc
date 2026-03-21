"""CLI approval handler for ApprovalRequestEvent prompts."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from amplifier_ipc_host.events import ApprovalRequestEvent

__all__ = ["CLIApprovalHandler"]

# Risk level to color mapping.
_RISK_COLORS: dict[str, str] = {
    "low": "green",
    "medium": "yellow",
    "high": "red",
    "critical": "bold red",
}


class CLIApprovalHandler:
    """Interactive CLI handler for approval request events.

    Displays a Rich Panel summarising the requested action and its risk level,
    then prompts the user for confirmation via :func:`rich.prompt.Confirm.ask`.

    ``Confirm.ask`` is dispatched in a :class:`ThreadPoolExecutor` so that it
    is safe to ``await`` from an async context without blocking the event loop.

    Args:
        console: Rich Console instance used for rendering.
    """

    def __init__(self, console: Console) -> None:
        self._console = console

    async def handle_approval(self, event: ApprovalRequestEvent) -> bool:
        """Display approval panel and prompt the user.

        Extracts ``tool_name``, ``action``, ``risk_level``, and ``details``
        from *event.params*, renders a colour-coded panel, and returns the
        user's yes/no response.

        Args:
            event: The :class:`~amplifier_ipc_host.events.ApprovalRequestEvent`
                   to handle.

        Returns:
            ``True`` if the user approved, ``False`` otherwise.
        """
        params = event.params
        tool_name: str = params.get("tool_name", "unknown")
        action: str = params.get("action", "")
        risk_level: str = params.get("risk_level", "low").lower()
        details: str = params.get("details", "")

        risk_color = _RISK_COLORS.get(risk_level, "white")

        # Build panel content.
        content = Text()
        content.append("Tool:    ", style="bold")
        content.append(f"{tool_name}\n")
        content.append("Action:  ", style="bold")
        content.append(f"{action}\n")
        content.append("Risk:    ", style="bold")
        content.append(risk_level.upper(), style=risk_color)
        if details:
            content.append("\nDetails: ", style="bold")
            content.append(details)

        panel = Panel(
            content,
            title="[bold]Approval Required[/bold]",
            border_style=risk_color,
        )
        self._console.print(panel)

        # Use a thread executor to avoid blocking the event loop.
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            approved: bool = await loop.run_in_executor(
                executor,
                lambda: Confirm.ask("Approve?", console=self._console),
            )
        return approved
