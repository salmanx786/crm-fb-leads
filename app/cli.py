"""Custom Flask CLI commands.

Registered on the app in the factory so they're available via
`flask <command>` (and through manage.py, which builds the same app).
"""
from __future__ import annotations

import click
from flask import Flask

from app.services import user_service
from app.services.user_service import UserAlreadyExistsError


def register_commands(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--name", prompt="Name", help="Administrator's full name.")
    @click.option("--email", prompt="Email", help="Login email address.")
    @click.password_option(
        "--password",
        prompt="Password",
        confirmation_prompt=True,
        help="Login password (hashed before storage).",
    )
    def create_admin(name: str, email: str, password: str) -> None:
        """Create the first administrator account."""
        try:
            user = user_service.create_admin(name=name, email=email, password=password)
        except UserAlreadyExistsError as exc:
            raise click.ClickException(str(exc))

        click.echo(f"Admin created: {user.name} <{user.email}>")
