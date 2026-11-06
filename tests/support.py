"""TEST ONLY: executes our fixed fixtures locally. This is NOT an isolation backend.

Production never imports this module. Resource/network enforcement needs test-docker.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from client.api import Client
from runtime.common import Fault, Remote, make_server
from runtime.gateway import Gateway
from runtime.harness import Harness
from runtime.llm_proxy import ModelProxy
from runtime.sandbox_manager import SandboxManager


class FixtureProcessEngine:
    def __init__(self):
        self.containers = {}
        self.created = []
        self.lock = threading.RLock()
        self.temp = tempfile.TemporaryDirectory()
        self.bin = Path(self.temp.name)
        (self.bin / "python").symlink_to(sys.executable)

    def ping(self):
        pass

    def create(self, config):
        cid = uuid.uuid4().hex
        with self.lock:
            self.containers[cid] = {"config": config, "process": None}
            self.created.append(config)
        return cid

    def start(self, cid):
        with self.lock:
            item = self.containers[cid]
            config = item["config"]
            folder = config["HostConfig"]["Mounts"][0]["Source"]
            cmd = config["Cmd"]
            if cmd[:2] == ["python", "/opt/file_tool.py"]:
                code = "import json,sys; from runtime.file_tool import execute; execute(sys.argv[1],json.loads(sys.argv[2]),sys.argv[3])"
                cmd = [sys.executable, "-c", code, *cmd[2:], folder]
            elif cmd[:2] == ["/bin/sh", "-lc"]:
                cmd = ["/bin/sh", "-c", cmd[2]]
            item["stdout"], item["stderr"] = tempfile.TemporaryFile(), tempfile.TemporaryFile()
            item["process"] = subprocess.Popen(cmd, cwd=folder, start_new_session=True,
                stdout=item["stdout"], stderr=item["stderr"],
                env={"PATH": f"{self.bin}:/usr/local/bin:/usr/bin:/bin", "HOME": self.temp.name,
                     "LANG": "C.UTF-8", "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                     "PYTHONDONTWRITEBYTECODE": "1"})

    def inspect(self, cid):
        with self.lock:
            if cid not in self.containers:
                raise Fault("sandbox", "Container already removed", 503)
            process = self.containers[cid]["process"]
            code = process.poll()
            return {"Running": code is None, "ExitCode": code, "OOMKilled": False}

    def logs(self, cid):
        item = self.containers[cid]
        result = {"truncated": False}
        for name in ("stdout", "stderr"):
            item[name].seek(0)
            raw = item[name].read(65537)
            result[name] = raw[:65536].decode("utf-8", "replace")
            result["truncated"] |= len(raw) > 65536
        return result

    def remove(self, cid):
        with self.lock:
            item = self.containers.pop(cid, None)
            if item:
                process = item["process"]
                if process:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=3)
                    item["stdout"].close()
                    item["stderr"].close()

    def cleanup(self, _):
        for cid in list(self.containers):
            self.remove(cid)

    def close(self):
        self.cleanup("")
        self.temp.cleanup()


@contextmanager
def server(app, token="internal"):
    http = make_server(app, token, "127.0.0.1", 0)
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(http.server_port)
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)


@contextmanager
def stack():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work = root / "workspaces"
        work.mkdir()
        engine = FixtureProcessEngine()
        manager = SandboxManager(engine, work, work)
        try:
            with server(manager) as sandbox_url, server(ModelProxy()) as model_url:
                harness = Harness(Remote(sandbox_url, "internal"), Remote(model_url, "internal"), root / "traces")
                try:
                    with server(harness) as harness_url:
                        gateway = Gateway(Remote(harness_url, "internal"))
                        with server(gateway, "client-token") as gateway_url:
                            yield {"client": Client(gateway_url, "client-token"), "url": gateway_url,
                                   "root": work, "manager": manager, "harness": harness,
                                   "engine": engine, "traces": root / "traces"}
                finally:
                    harness.close()
        finally:
            manager.close()
            engine.close()
