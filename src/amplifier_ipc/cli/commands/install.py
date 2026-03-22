"""Install command — resolve a name via registry, create a virtualenv, install the service."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

import click
import yaml

from amplifier_ipc.host.definition_registry import Registry


def _run_uv(args: list[str]) -> None:
    """Run a uv command via subprocess.

    Args:
        args: Arguments to pass to uv (e.g. ["venv", "/path/to/env"]).
              The "uv" executable is prepended automatically.

    Raises:
        subprocess.CalledProcessError: If the uv command exits with a non-zero status.
    """
    subprocess.run(["uv", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607


def install_service(
    registry: Any,
    definition_id: str,
    source: str,
    *,
    force: bool = False,
) -> None:
    """Create a virtualenv and install a service package into it.

    Skips installation if the environment already exists unless ``force=True``.

    Args:
        registry: Registry instance used to check and locate environments.
        definition_id: The definition identifier used to locate the environment path.
        source: The pip-installable source (e.g. a package specifier or path).
        force: If True, reinstall even if the environment already exists.
    """
    if not force and registry.is_installed(definition_id):
        return

    env_path: Path = registry.get_environment_path(definition_id)
    python_path = env_path / "bin" / "python"

    venv_args = ["venv", str(env_path)]
    if force:
        venv_args.append("--clear")
    _run_uv(venv_args)
    _run_uv(["pip", "install", "--python", str(python_path), source])


@click.command()
@click.argument("name")
@click.option(
    "--force", is_flag=True, default=False, help="Reinstall even if already installed."
)
@click.option(
    "--home",
    default=None,
    help="Override $AMPLIFIER_HOME path (useful for testing).",
)
def install(name: str, force: bool, home: Optional[str]) -> None:
    """Install the services for a registered agent or behavior NAME.

    Resolves NAME from the registry (agent first, then behavior), reads its
    definition YAML, and installs each declared service into a dedicated
    virtualenv managed by uv.
    """
    home_path = Path(home) if home else None
    registry = Registry(home=home_path)

    # Resolve name: try agent first, fall back to behavior.
    try:
        def_path = registry.resolve_agent(name)
    except FileNotFoundError:
        try:
            def_path = registry.resolve_behavior(name)
        except FileNotFoundError:
            raise click.ClickException(
                f"'{name}' not found in registry as an agent or behavior. "
                "Run amplifier-ipc discover to populate the registry."
            )

    # Parse definition YAML to get the services list.
    # Definitions use a nested format: top-level key is 'agent' or 'behavior',
    # with services and other fields in the inner mapping.
    definition: dict = yaml.safe_load(def_path.read_text()) or {}
    inner: dict = definition.get("agent") or definition.get("behavior") or definition
    services: list[dict] = (inner or {}).get("services") or []

    if not services:
        click.echo(f"No services to install for '{name}'.")
        return

    # Derive the definition_id from the file stem (matches how Registry stores it).
    definition_id = def_path.stem

    for service in services:
        source: Optional[str] = (
            service.get("source") if isinstance(service, dict) else None
        )
        if not source:
            svc_name = (
                service.get("name", "<unknown>")
                if isinstance(service, dict)
                else service
            )
            click.echo(f"Skipping service '{svc_name}': no source specified.")
            continue

        install_service(registry, definition_id, source, force=force)
        svc_name = service.get("name", source) if isinstance(service, dict) else source
        click.echo(f"Installed: {svc_name}")
