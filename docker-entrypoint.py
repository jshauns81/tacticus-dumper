"""Container entrypoint for permission repair and privilege drop."""

from __future__ import annotations

import grp
import os
import pwd

APP_USER = os.environ.get("APP_USER", "app")
APP_GROUP = os.environ.get("APP_GROUP", APP_USER)
DATA_DIR = os.environ.get("DATA_DIR", "/data")


def _ids() -> tuple[int, int]:
    return pwd.getpwnam(APP_USER).pw_uid, grp.getgrnam(APP_GROUP).gr_gid


def _chown_tree(path: str, uid: int, gid: int) -> None:
    for root, dirs, files in os.walk(path):
        os.chown(root, uid, gid)
        for name in dirs:
            os.chown(os.path.join(root, name), uid, gid)
        for name in files:
            os.chown(os.path.join(root, name), uid, gid)


def _prepare_data_dir(uid: int, gid: int) -> None:
    dumps_dir = os.path.join(DATA_DIR, "dumps")
    os.makedirs(dumps_dir, exist_ok=True)
    _chown_tree(DATA_DIR, uid, gid)


def _drop_privileges(uid: int, gid: int) -> None:
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    os.environ["HOME"] = "/app"


def main() -> None:
    uid, gid = _ids()
    if os.getuid() == 0:
        _prepare_data_dir(uid, gid)
        _drop_privileges(uid, gid)

    workers = os.environ.get("GUNICORN_WORKERS", "2")
    host = os.environ.get("HOST", "0.0.0.0")
    port = os.environ.get("PORT", "5000")
    timeout = os.environ.get("GUNICORN_TIMEOUT", "60")
    os.execlp(
        "gunicorn",
        "gunicorn",
        "-w",
        workers,
        "-b",
        f"{host}:{port}",
        "--timeout",
        timeout,
        "app:app",
    )


if __name__ == "__main__":
    main()
