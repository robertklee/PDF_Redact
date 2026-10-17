#!/usr/bin/env python3
"""Set up and start PDF Redact with one command:

    python3 run.py [--port PORT] [--no-browser]

The first run creates a Python environment in backend/.venv, installs the server into it and
builds the UI (which needs Node.js); later runs redo only the steps whose inputs have changed.

    python3 run.py --wheel

builds a wheel with the UI included in dist/ instead. It installs with pip or pipx on machines
without Node.js.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
UI_BUILD = FRONTEND / "dist"
VENV = BACKEND / ".venv"
BIN = VENV / ("Scripts" if os.name == "nt" else "bin")
EXE = ".exe" if os.name == "nt" else ""
PYTHON = BIN / ("python" + EXE)
INSTALLED = VENV / ".pdf-redact-installed"

# What the UI build is made from; a change to any of these makes the build stale.
UI_SOURCES = [
    "src",
    "public",
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
]


class SetupError(Exception):
    pass


def step(message):
    print(f"==> {message}", flush=True)


def run(*command, cwd=None):
    try:
        subprocess.run([str(c) for c in command], cwd=cwd, check=True)
    except FileNotFoundError as e:
        raise SetupError(f"{command[0]} not found") from e
    except subprocess.CalledProcessError as e:
        raise SetupError(
            f"`{' '.join(map(str, command))}` failed (exit code {e.returncode})"
        ) from e


def newest_mtime(paths):
    newest = 0.0
    for path in paths:
        if path.is_dir():
            files = (p for p in path.rglob("*") if p.is_file())
            newest = max([newest, *(p.stat().st_mtime for p in files)])
        elif path.exists():
            newest = max(newest, path.stat().st_mtime)
    return newest


def ensure_server():
    """Create the environment and (re)install the server when its dependencies change."""
    if not PYTHON.exists():
        step("Creating the Python environment in backend/.venv")
        run(sys.executable, "-m", "venv", VENV)
    wanted = hashlib.sha256((BACKEND / "pyproject.toml").read_bytes()).hexdigest()
    if INSTALLED.exists() and INSTALLED.read_text().strip() == wanted:
        return
    step("Installing the server and its dependencies")
    run(PYTHON, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-e", BACKEND)
    INSTALLED.write_text(wanted + "\n")


def ensure_ui():
    """Build the UI when it is missing or older than its sources."""
    index = UI_BUILD / "index.html"
    built = index.stat().st_mtime if index.exists() else None
    if built is not None and built >= newest_mtime(FRONTEND / name for name in UI_SOURCES):
        return
    npm = shutil.which("npm")
    if npm is None:
        if built is not None:
            print("Warning: the UI build is older than its sources, and Node.js is not installed.")
            return
        raise SetupError(
            "Node.js 20 or later is needed to build the UI: https://nodejs.org/\n"
            "(Or install a wheel built with `python3 run.py --wheel`, which needs no Node.js.)"
        )
    lock = FRONTEND / "package-lock.json"
    installed = FRONTEND / "node_modules" / ".package-lock.json"
    if not installed.exists() or installed.stat().st_mtime < lock.stat().st_mtime:
        step("Installing the UI's dependencies")
        run(npm, "ci", "--no-audit", "--no-fund", cwd=FRONTEND)
    step("Building the UI")
    run(npm, "run", "build", cwd=FRONTEND)


def build_wheel():
    """Build a wheel of the server with the UI inside it, in dist/."""
    static = BACKEND / "pdf_redact" / "static"
    leftovers = [static, BACKEND / "build"]
    for path in leftovers:
        shutil.rmtree(path, ignore_errors=True)
    step("Building the wheel")
    try:
        shutil.copytree(UI_BUILD, static)
        run(
            PYTHON, "-m", "pip", "wheel", "--quiet", "--disable-pip-version-check", "--no-deps",
            "--wheel-dir", ROOT / "dist", BACKEND,
        )  # fmt: skip
    finally:
        # Left in place, the copy would shadow later UI builds when running from the repository.
        for path in leftovers:
            shutil.rmtree(path, ignore_errors=True)
    wheels = sorted((ROOT / "dist").glob("pdf_redact-*.whl"), key=lambda p: p.stat().st_mtime)
    print(f"\nBuilt {wheels[-1].relative_to(ROOT)}. Install it with")
    print(f"  pipx install {wheels[-1].name}    (or: python3 -m pip install {wheels[-1].name})")
    print("and start it with `pdf-redact`.")


def main():
    # Kept to syntax that older Pythons can parse, so that they get this message.
    if sys.version_info < (3, 11):  # noqa: UP036
        sys.exit(f"PDF Redact needs Python 3.11 or later; this is {sys.version.split()[0]}.")
    parser = argparse.ArgumentParser(
        description="Set up and start PDF Redact. Other options (--port, --no-browser) are "
        "passed on to the server.",
    )
    parser.add_argument("--wheel", action="store_true", help="build an installable wheel instead")
    args, server_args = parser.parse_known_args()
    try:
        ensure_server()
        ensure_ui()
        if args.wheel:
            build_wheel()
            return
    except SetupError as e:
        sys.exit(f"Error: {e}")
    env = dict(os.environ, PDF_REDACT_STATIC=str(UI_BUILD))
    server = [str(BIN / ("pdf-redact" + EXE)), *server_args]
    if os.name != "nt":
        os.execve(server[0], server, env)
    # The server gets Ctrl+C too; let it shut down (and delete its temporary files) on its own.
    process = subprocess.Popen(server, env=env)
    while True:
        try:
            sys.exit(process.wait())
        except KeyboardInterrupt:
            continue


if __name__ == "__main__":
    main()
