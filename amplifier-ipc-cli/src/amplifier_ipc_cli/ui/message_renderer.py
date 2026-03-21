"""Single source of truth for message rendering.
Provides canonical rendering for user and assistant messages, used
by live chat, history display, and replay mode.
"""

from __future__ import annotations

from rich.console import Console

from amplifier_ipc_cli.console import Markdown


def render_message(
    message: dict, console: Console, *, show_thinking: bool = False
) -> None:
    role = message.get("role")
    if role == "user":
        _render_user_message(message, console)
    elif role == "assistant":
        _render_assistant_message(message, console, show_thinking)


def _render_user_message(message: dict, console: Console) -> None:
    content = _extract_text(message)
    console.print(f"\n[bold green]>[/bold green] {content}")


def _render_assistant_message(
    message: dict, console: Console, show_thinking: bool
) -> None:
    text_blocks, thinking_blocks = _extract_content_blocks(
        message, show_thinking=show_thinking
    )
    if not text_blocks and not thinking_blocks:
        return
    console.print("\n[bold green]Amplifier:[/bold green]")
    if text_blocks:
        console.print(Markdown("\n".join(text_blocks)))
    for thinking in thinking_blocks:
        console.print(Markdown(f"\n**Thinking:**\n{thinking}"), style="dim")


def _extract_content_blocks(
    message: dict, *, show_thinking: bool = False
) -> tuple[list[str], list[str]]:
    content = message.get("content", "")
    text_blocks: list[str] = []
    thinking_blocks: list[str] = []
    if isinstance(content, str):
        text_blocks.append(content)
        return text_blocks, thinking_blocks
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_blocks.append(block.get("text", ""))
                elif block.get("type") == "thinking" and show_thinking:
                    thinking_blocks.append(block.get("thinking", ""))
        return text_blocks, thinking_blocks
    return [str(content)], []


def _extract_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content)
