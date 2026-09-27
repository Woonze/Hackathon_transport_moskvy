"""Create a private Compose .env without putting the login password in shell history."""

from __future__ import annotations

import argparse
import getpass
import secrets
from pathlib import Path

from backend.app.services.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", action="store_true", help="Set secure cookies for production")
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit(f"Файл {args.output} уже существует; удалите его вручную, если хотите пересоздать")
    username = input("Логин [fotur]: ").strip() or "fotur"
    password = getpass.getpass("Пароль: ")
    confirmation = getpass.getpass("Повторите пароль: ")
    if len(password) < 12 or password != confirmation:
        raise SystemExit("Пароли не совпадают или короче 12 символов")

    encoded_hash = hash_password(password)
    content = "\n".join(
        (
            "POSTGRES_DB=moskvy_tram",
            "POSTGRES_USER=tram_service",
            f"POSTGRES_PASSWORD={secrets.token_urlsafe(36)}",
            f"AUTH_USERNAME={username}",
            f"AUTH_PASSWORD_HASH={encoded_hash}",
            f"AUTH_COOKIE_SECURE={'true' if args.server else 'false'}",
            "AUTH_COOKIE_PATH=/",
            "",
        )
    )
    args.output.write_text(content, encoding="utf-8")
    try:
        args.output.chmod(0o600)
    except OSError:
        pass
    print(f"Настройки сохранены в {args.output}; пароль в файле хранится только в виде хеша.")


if __name__ == "__main__":
    main()
