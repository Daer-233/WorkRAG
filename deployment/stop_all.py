"""Stop every WorkRAG service owned by this deployment.

Wraps ``deployment/local.py stop`` and then sweeps whatever it left behind:
stray uvicorn workers, the Pi harness, and the compose project. The sweep only
touches processes whose command line points at *this* checkout, so a sibling
deployment on the same machine is never killed by mistake.

Usage:
    python deployment/stop_all.py           # stop everything
    python deployment/stop_all.py --check    # report only, change nothing
"""
from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deployment"
RUNTIME = ROOT / "data/manuals/runtime/local"
DOCKER = Path("G:/docker/Desktop/resources/bin/docker.exe")
COMPOSE = ["-f", "G:/docker/workrag/compose.yaml"]

SERVICE_NAMES = ("embedding", "rerank", "backend", "workrag-mcp")
MODULE_PORTS = (
    ("embedding_app.main:app", 8031, "embedding"),
    ("rerank_app.main:app", 8032, "rerank"),
    ("app.manual_main:app", 8060, "backend"),
    ("workrag_agent.mcp_server:app", 8061, "workrag-mcp"),
)
PROCESS_NAMES = ("python.exe", "pythonw.exe", "node.exe")


def say(message: str) -> None:
    print(message, flush=True)


def belongs(cmd: str, root: str) -> bool:
    """True when the command line references this checkout, not a sibling one."""
    start = cmd.find(root)
    while start != -1:
        end = start + len(root)
        if end == len(cmd) or cmd[end] in '\\/" \t':
            return True
        start = cmd.find(root, start + 1)
    return False


def candidates() -> list[psutil.Process]:
    """Project processes: uvicorn workers and the Pi harness of this checkout."""
    root = str(ROOT).replace("/", "\\").lower()
    modules = [module for module, _, _ in MODULE_PORTS]
    found: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info["name"] or "").lower() not in PROCESS_NAMES:
                continue
            cmd = " ".join(proc.cmdline()).replace("/", "\\").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not belongs(cmd, root):
            continue
        # Require the real uvicorn invocation: inline `python -c` helpers are ignored.
        is_pi = "server.mjs" in cmd and "pi-harness" in cmd
        is_api = "-m uvicorn" in cmd and any(module in cmd for module in modules)
        if is_pi or is_api:
            found.append(proc)
    return found


def identify(proc: psutil.Process) -> tuple[str, str]:
    """Return (port, service name) for one project process."""
    try:
        cmd = " ".join(proc.cmdline())
    except psutil.Error:
        cmd = ""
    lowered = cmd.lower()
    if "server.mjs" in lowered and "pi-harness" in lowered:
        return "-", "pi-harness"
    for module, port, name in MODULE_PORTS:
        if module in cmd:
            return str(port), name
    return "-", "uvicorn"


def summarise(procs: list[psutil.Process]) -> list[tuple[tuple[str, str], list[int]]]:
    """Fold the venv launcher and its interpreter into one line per service."""
    buckets: dict[tuple[str, str], list[int]] = {}
    for proc in procs:
        buckets.setdefault(identify(proc), []).append(proc.pid)
    return sorted(buckets.items(), key=lambda item: (item[0][0] != "-", item[0][0]))


def describe(procs: list[psutil.Process]) -> list[str]:
    return [
        f"port={port:<5} {kind:<16} pid={','.join(str(pid) for pid in pids)}"
        for (port, kind), pids in summarise(procs)
    ]


def terminate(procs: list[psutil.Process], wait: int = 10) -> list[psutil.Process]:
    targets: list[psutil.Process] = []
    for proc in procs:
        try:
            targets.extend(proc.children(recursive=True))
        except psutil.Error:
            pass
        targets.append(proc)
    for proc in targets:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(targets, timeout=wait)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    _, still = psutil.wait_procs(alive, timeout=5)
    return [proc for proc in still if proc.is_running()]


def clear_records() -> list[str]:
    """Drop pid bookkeeping for services that are gone; tokens stay untouched."""
    removed: list[str] = []
    for name in SERVICE_NAMES + ("pi-harness-process",):
        record = RUNTIME / f"{name}.json"
        if record.exists():
            try:
                record.unlink()
                removed.append(record.name)
            except OSError:
                pass
    return removed


@lru_cache(maxsize=1)
def docker_ready() -> bool:
    if not DOCKER.exists():
        return False
    try:
        probe = subprocess.run(
            [str(DOCKER), "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def compose_state() -> list[str]:
    if not docker_ready():
        return []
    try:
        result = subprocess.run(
            [str(DOCKER), "compose", *COMPOSE, "ps", "--status", "running", "--format", "{{.Service}}"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def compose_stop() -> tuple[bool, str]:
    if not DOCKER.exists():
        return True, "docker.exe not found, skipped"
    try:
        result = subprocess.run(
            [str(DOCKER), "compose", *COMPOSE, "stop"],
            capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"{type(error).__name__}: {error}"
    detail = (result.stdout + result.stderr).strip().splitlines()
    return result.returncode == 0, detail[-1] if detail else "compose stop done"


def managed_stop() -> tuple[bool, str]:
    sys.path.insert(0, str(DEPLOY))
    try:
        import local  # noqa: PLC0415 - deployment module, path added above

        local.stop()
        return True, "deployment/local.py stop completed"
    except Exception as error:  # noqa: BLE001 - report and keep sweeping
        return False, f"{type(error).__name__}: {error}"


def check() -> int:
    procs = candidates()
    containers = compose_state()
    say("[check] read-only, nothing will be stopped")
    if procs:
        say(f"[check] project processes: {len(procs)}")
        for line in describe(procs):
            say(f"        {line}")
    else:
        say("[check] project processes: none")
    say(f"[check] compose running: {', '.join(containers) if containers else 'none'}")
    records = [n for n in SERVICE_NAMES + ("pi-harness-process",) if (RUNTIME / f"{n}.json").exists()]
    say(f"[check] pid records: {', '.join(records) if records else 'none'}")
    return 0


def main() -> int:
    if "--check" in sys.argv or "/check" in sys.argv:
        return check()

    say("[1/4] Stopping managed services (Pi harness, APIs, compose)...")
    ok, detail = managed_stop()
    say(f"      {'[ok]' if ok else '[warn]'} {detail}")

    say("[2/4] Sweeping leftover project processes...")
    leftovers = candidates()
    if leftovers:
        for line in describe(leftovers):
            say(f"      stopping {line}")
        failed = terminate(leftovers)
        if failed:
            for proc in failed:
                say(f"      [warn] could not stop pid={proc.pid} (access denied?)")
    else:
        say("      none")

    say("[3/4] Clearing stale pid records...")
    removed = clear_records()
    say(f"      {', '.join(removed) if removed else 'none'}")

    say("[4/4] Stopping compose project (postgres, qdrant, langbot)...")
    if docker_ready():
        ok, detail = compose_stop()
        say(f"      {'[ok]' if ok else '[warn]'} {detail}")
    else:
        say("      docker engine not running, skipped")

    remaining = candidates()
    containers = compose_state()
    print()
    if remaining or containers:
        say("[result] NOT fully stopped:")
        for line in describe(remaining):
            say(f"         {line}")
        if containers:
            say(f"         containers still running: {', '.join(containers)}")
        say(f"[result] inspect logs under {RUNTIME}")
        return 1
    say("[result] WorkRAG stopped. Ports 8031/8032/8060/8061/8062 released.")
    say("[result] Volumes and instances/ are kept; for a full teardown run:")
    say("         docker compose -f G:/docker/workrag/compose.yaml down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
