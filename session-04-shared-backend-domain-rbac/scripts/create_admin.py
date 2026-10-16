"""Create the first admin (or promote an existing user) from the command line.

Signup always creates members, so the first admin is bootstrapped here:

    make create-admin
    uv run python -m scripts.create_admin --email a@x.io --username admin --name "Admin"
    uv run python -m scripts.create_admin --email existing@x.io --promote

The password is read from ADMIN_PASSWORD when set (for CI), otherwise prompted.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from app.auth.passwords import hash_password
from app.auth.roles import UserRole
from app.db.database import AsyncSessionLocal, engine
from app.repositories.user_repository import UserRepository

MIN_PASSWORD_LENGTH = 8


def _prompt(label: str, value: str | None) -> str:
    while not value:
        value = input(f"{label}: ").strip()
    return value


def _read_password() -> str:
    from_env = os.environ.get("ADMIN_PASSWORD")
    if from_env:
        password = from_env
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            sys.exit("Passwords do not match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


async def _run(args: argparse.Namespace) -> None:
    email = _prompt("Email", args.email)
    async with AsyncSessionLocal() as db:
        existing = await UserRepository.get_by_email(db, email)

        if args.promote:
            if existing is None:
                sys.exit(f"No user with email {email}.")
            existing.role = UserRole.ADMIN
            await db.commit()
            print(f"Promoted {existing.username} <{email}> to admin.")
            return

        if existing is not None:
            sys.exit(f"{email} already exists; rerun with --promote to make it admin.")
        username = _prompt("Username", args.username)
        if await UserRepository.get_by_username(db, username) is not None:
            sys.exit(f"Username {username} is already taken.")
        name = _prompt("Full name", args.name)

        user = await UserRepository.create(
            db,
            name=name,
            username=username,
            email=email,
            password_hash=hash_password(_read_password()),
            role=UserRole.ADMIN,
        )
        print(f"Created admin {user.username} <{user.email}> (id {user.id}).")


async def _main(args: argparse.Namespace) -> None:
    try:
        await _run(args)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote a TaskFlow admin")
    parser.add_argument("--email")
    parser.add_argument("--username")
    parser.add_argument("--name")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Promote the existing user with --email to admin instead of creating one",
    )
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
