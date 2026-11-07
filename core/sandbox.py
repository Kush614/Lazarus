"""Runs a target and sends it requests. A timeout or connection failure returns None
(FAILED), which callers must never treat as a match.

DockerTarget is the sandbox the spec requires: 256m memory and an --internal network
with no egress, reached through a socat sidecar because Docker Desktop cannot publish
ports from an internal network. ProcessTarget is unsandboxed, for local dev without Docker.
"""
import json
import os
import socket
import subprocess
import sys
import time
import uuid

import httpx

from core.schemas import Request, Response

REQUEST_TIMEOUT_S = 10.0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def send(base_url: str, req: Request, timeout: float = REQUEST_TIMEOUT_S) -> Response | None:
    content = None
    if req.body is not None:
        content = req.body if isinstance(req.body, str) else json.dumps(req.body)
    try:
        with httpx.Client(follow_redirects=False, timeout=timeout) as c:
            r = c.request(req.method, base_url + req.path, headers=req.headers, content=content)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return None
    try:
        body = json.loads(r.text)
    except ValueError:
        body = r.text
    return Response(status=r.status_code, headers=dict(r.headers), body=body)


class Target:
    base_url: str

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def start(self): ...
    def stop(self): ...

    def send(self, req: Request) -> Response | None:
        return send(self.base_url, req)

    def _wait_ready(self, tries: int = 100):
        for _ in range(tries):
            try:
                httpx.get(self.base_url + "/", timeout=1.0)
                return
            except httpx.HTTPError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError(f"target at {self.base_url} never became ready")


class StaticTarget(Target):
    """An already-running service."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")


class ProcessTarget(Target):
    """Local subprocess. `{port}` in argv is replaced with a free port. No isolation."""

    def __init__(self, argv: list[str], cwd: str | None = None):
        self.port = free_port()
        self.argv = [a.replace("{port}", str(self.port)) for a in argv]
        self.cwd = cwd
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._wait_ready()

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=5)
            self.proc = None


class DockerTarget(Target):
    NETWORK = "lazarus-sandbox"

    def __init__(self, image: str, container_port: int = 8080):
        self.image, self.container_port = image, container_port
        self.name = f"lazarus-{uuid.uuid4().hex[:8]}"
        self.host_port = free_port()
        self.base_url = f"http://127.0.0.1:{self.host_port}"

    def _docker(self, *args, check=True):
        return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)

    def start(self):
        self._docker("network", "create", "--internal", self.NETWORK, check=False)
        self._docker("run", "-d", "--rm", "--name", self.name, "--memory", "256m", "--network", self.NETWORK, self.image)
        self._docker("run", "-d", "--rm", "--name", self.name + "-gw", "--memory", "64m",
                     "-p", f"127.0.0.1:{self.host_port}:9000", "alpine/socat",
                     "TCP-LISTEN:9000,fork,reuseaddr", f"TCP:{self.name}:{self.container_port}")
        # The sidecar sits on both networks; the target only on the internal one.
        self._docker("network", "connect", self.NETWORK, self.name + "-gw")
        self._wait_ready()

    def stop(self):
        self._docker("rm", "-f", self.name, self.name + "-gw", check=False)


def original_target() -> Target:
    """SANDBOX=docker is the real sandbox; SANDBOX=process is unisolated, for dev only."""
    if os.getenv("SANDBOX", "docker") == "docker":
        return DockerTarget(os.environ["RELIC_IMAGE"])
    return ProcessTarget([os.environ["RELIC_BINARY"], "-addr", "127.0.0.1:{port}"])


def port_target(version: int, root: str) -> Target:
    """Runs the port as a black box; callers never import it."""
    if os.getenv("SANDBOX", "docker") == "docker":
        tag = f"lazarus-port:v{version}"
        subprocess.run(["docker", "build", "-q", "-t", tag, "port"], cwd=root, check=True, capture_output=True)
        return DockerTarget(tag)
    return ProcessTarget([sys.executable, "-m", "uvicorn", "port.app:app", "--port", "{port}", "--log-level", "error"], cwd=root)
