"""Small Docker Engine v1.47 adapter; no shell or Docker CLI on the server."""
import http.client
import json
import socket
import struct
from urllib.parse import quote

from .common import Fault


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=10):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Docker:
    def __init__(self, socket_path="/var/run/docker.sock"):
        self.socket_path = socket_path

    def request(self, method, path, body=None, raw=False):
        conn = UnixConnection(self.socket_path)
        try:
            conn.request(method, "/v1.47" + path,
                         None if body is None else json.dumps(body).encode(),
                         {"Content-Type": "application/json"})
            response = conn.getresponse()
            data = response.read(2_097_152)
            if response.status >= 400:
                raise Fault("sandbox", f"Docker operation failed (HTTP {response.status})", 503)
            return data if raw else (json.loads(data) if data else {})
        except (OSError, http.client.HTTPException, ValueError):
            raise Fault("sandbox", "Docker daemon unavailable", 503) from None
        finally:
            conn.close()

    def ping(self):
        self.request("GET", "/info")

    def create(self, config):
        return self.request("POST", "/containers/create", config)["Id"]

    def start(self, cid):
        self.request("POST", f"/containers/{cid}/start")

    def inspect(self, cid):
        return self.request("GET", f"/containers/{cid}/json")["State"]

    def remove(self, cid):
        try:
            self.request("DELETE", f"/containers/{cid}?force=true&v=true")
        except Fault as exc:
            if "HTTP 404" not in exc.message:
                raise

    def logs(self, cid):
        raw = self.request("GET", f"/containers/{cid}/logs?stdout=true&stderr=true", raw=True)
        streams = {1: bytearray(), 2: bytearray()}
        offset = 0
        truncated = len(raw) >= 2_097_152
        while offset + 8 <= len(raw):
            channel, size = raw[offset], struct.unpack(">I", raw[offset + 4:offset + 8])[0]
            offset += 8
            part = raw[offset:offset + size]
            offset += size
            if channel in streams:
                remaining = max(0, 65536 - len(streams[channel]))
                streams[channel].extend(part[:remaining])
                truncated |= len(part) > remaining
        return {"stdout": streams[1].decode("utf-8", "replace"),
                "stderr": streams[2].decode("utf-8", "replace"), "truncated": truncated}

    def cleanup(self, instance):
        filters = quote(json.dumps({"label": [f"project-a.instance={instance}"]}))
        for item in self.request("GET", "/containers/json?all=true&filters=" + filters):
            self.remove(item["Id"])
