"""A small WebDAV subset for rclone, serving one Linux folder over an SSH tunnel.

All filesystem access is relative to pinned directory descriptors. Symlinks,
hard-linked files, .git and upload staging files are deliberately not exported.
"""
import contextlib
import fcntl
import hmac
import os
import secrets
import stat
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_FILE = 64 * 1024 * 1024
MAX_WORKSPACE_BYTES = 256 * 1024 * 1024
MAX_WORKSPACE_ENTRIES = 4096
HIDDEN = ".agent-upload-"


class QuotaExceeded(OSError):
    pass


def parts_for(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.query or parsed.fragment:
        raise PermissionError("Queries are not workspace paths")
    parts = urllib.parse.unquote(parsed.path, errors="strict").split("/")
    parts = [p for p in parts if p]
    if len(parts) > 64:
        raise PermissionError("Workspace path is too deep")
    if any(p in (".", "..", ".git", ".agent-health") or p.startswith(HIDDEN) or "\x00" in p or "\\" in p for p in parts):
        raise PermissionError("Protected path")
    return parts


class WorkspaceServer:
    def __init__(self, folder, mode="rw", token=None, max_bytes=MAX_WORKSPACE_BYTES,
                 max_entries=MAX_WORKSPACE_ENTRIES):
        if mode not in ("ro", "rw"):
            raise ValueError("Mode must be ro or rw")
        self.folder = Path(folder).resolve(strict=True)
        self.fd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            # No lock file in the user's directory. One exporter per exact folder.
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            raise
        self.mode, self.token = mode, token or secrets.token_urlsafe(32)
        if type(max_bytes) is not int or max_bytes <= 0 or type(max_entries) is not int or max_entries <= 0:
            os.close(self.fd)
            raise ValueError("Workspace quotas must be positive integers")
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.lock = threading.RLock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def log_message(self, *_):
                pass

            def reply(self, status, body=b"", headers=None):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.close_connection = True
                if self.command != "HEAD":
                    self.wfile.write(body)

            def body(self):
                total = 0
                if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                    while True:
                        line = self.rfile.readline(128)
                        size = int(line.split(b";", 1)[0].strip(), 16)
                        if size < 0 or total + size > MAX_FILE:
                            raise OverflowError()
                        if size == 0:
                            # Consume bounded trailers (normally just CRLF).
                            for _ in range(32):
                                if self.rfile.readline(8192) == b"\r\n":
                                    return
                            raise ValueError("Invalid trailers")
                        remaining = size
                        while remaining:
                            chunk = self.rfile.read(min(65536, remaining))
                            if not chunk:
                                raise ConnectionError("Incomplete upload")
                            remaining -= len(chunk)
                            total += len(chunk)
                            yield chunk
                        if self.rfile.read(2) != b"\r\n":
                            raise ValueError("Invalid chunk")
                else:
                    if self.headers.get("Transfer-Encoding"):
                        raise ValueError("Unsupported transfer encoding")
                    remaining = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= remaining <= MAX_FILE:
                        raise OverflowError()
                    while remaining:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            raise ConnectionError("Incomplete upload")
                        remaining -= len(chunk)
                        yield chunk

            def run(self):
                try:
                    if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + owner.token).encode()):
                        self.reply(401)
                        return
                    # Liveness must not wait for a slow upload/read holding the
                    # filesystem lock, or healthy transfers would expire their lease.
                    if self.command in ("GET", "HEAD") and self.path == "/.agent-health":
                        self.reply(200, b"workspace-v1")
                        return
                    with owner.lock:
                        parts = parts_for(self.path)
                        if self.command == "OPTIONS":
                            self.reply(200, headers={"DAV": "1", "Allow": "OPTIONS, PROPFIND, GET, HEAD, PUT, MKCOL, MOVE, DELETE"})
                        elif self.command == "PROPFIND":
                            depth = self.headers.get("Depth", "0")
                            if depth not in ("0", "1"):
                                self.reply(403)
                                return
                            with owner.open(parts) as fd:
                                items = [(parts, os.fstat(fd))]
                                if depth == "1" and stat.S_ISDIR(items[0][1].st_mode):
                                    for name in sorted(os.listdir(fd)):
                                        try:
                                            child = parts_for("/" + "/".join(urllib.parse.quote(p, safe="") for p in [*parts, name]))
                                            with owner.open(child) as entry:
                                                items.append((child, os.fstat(entry)))
                                        except (OSError, ValueError):
                                            continue
                            root = ET.Element("{DAV:}multistatus")
                            for names, info in items:
                                response = ET.SubElement(root, "{DAV:}response")
                                directory = stat.S_ISDIR(info.st_mode)
                                href = "/" + "/".join(urllib.parse.quote(p, safe="") for p in names)
                                ET.SubElement(response, "{DAV:}href").text = href + ("/" if directory and names else "")
                                ps = ET.SubElement(response, "{DAV:}propstat")
                                prop = ET.SubElement(ps, "{DAV:}prop")
                                resource = ET.SubElement(prop, "{DAV:}resourcetype")
                                if directory:
                                    ET.SubElement(resource, "{DAV:}collection")
                                ET.SubElement(prop, "{DAV:}getcontentlength").text = str(info.st_size if not directory else 0)
                                ET.SubElement(prop, "{DAV:}getlastmodified").text = formatdate(info.st_mtime, usegmt=True)
                                ET.SubElement(prop, "{DAV:}getetag").text = f'"{info.st_ino}-{info.st_size}-{info.st_mtime_ns}"'
                                ET.SubElement(ps, "{DAV:}status").text = "HTTP/1.1 200 OK"
                            self.reply(207, ET.tostring(root, encoding="utf-8", xml_declaration=True), {"Content-Type": "application/xml"})
                        elif self.command in ("GET", "HEAD"):
                            with owner.open(parts) as fd:
                                info = os.fstat(fd)
                                if not stat.S_ISREG(info.st_mode):
                                    raise PermissionError()
                                start, end, status = 0, info.st_size - 1, 200
                                headers = {"Accept-Ranges": "bytes"}
                                if self.headers.get("Range"):
                                    import re
                                    match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers["Range"])
                                    if not match:
                                        self.reply(416)
                                        return
                                    start = int(match[1])
                                    end = min(int(match[2]) if match[2] else end, end)
                                    if start > end:
                                        self.reply(416)
                                        return
                                    status = 206
                                    headers["Content-Range"] = f"bytes {start}-{end}/{info.st_size}"
                                self.send_response(status)
                                self.send_header("Content-Length", str(max(0, end - start + 1)))
                                self.send_header("Connection", "close")
                                for k, v in headers.items():
                                    self.send_header(k, v)
                                self.end_headers()
                                self.close_connection = True
                                if self.command != "HEAD":
                                    os.lseek(fd, start, os.SEEK_SET)
                                    remaining = end - start + 1
                                    while remaining > 0:
                                        data = os.read(fd, min(65536, remaining))
                                        if not data:
                                            break
                                        self.wfile.write(data)
                                        remaining -= len(data)
                        elif self.command in ("PUT", "MKCOL", "DELETE", "MOVE"):
                            if owner.mode == "ro" or not parts:
                                raise PermissionError()
                            with owner.open(parts[:-1], directory=True) as parent:
                                name = parts[-1]
                                before = owner.fingerprint(parent, name)
                                if self.command == "PUT":
                                    # Peak allocation includes old file + staged replacement.
                                    # The single exporter lock serializes all remote mutations.
                                    used_bytes, used_entries = owner.usage()
                                    owner.require_quota(used_bytes, used_entries + 1)
                                    temp = HIDDEN + secrets.token_hex(16)
                                    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                                    try:
                                        with os.fdopen(fd, "wb") as target:
                                            staged = 0
                                            for chunk in self.body():
                                                staged += len(chunk)
                                                owner.require_quota(used_bytes + staged, used_entries + 1)
                                                target.write(chunk)
                                            target.flush()
                                            os.fsync(target.fileno())
                                        if owner.fingerprint(parent, name) != before:
                                            self.reply(409)
                                            return
                                        # Account for trusted local edits to other files while
                                        # uploading; our hidden staging file is counted separately.
                                        current_bytes, current_entries = owner.usage()
                                        owner.require_quota(current_bytes + staged, current_entries + 1)
                                        os.chmod(temp, stat.S_IMODE(before[3]) if before else 0o644, dir_fd=parent)
                                        os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
                                        self.reply(204 if before else 201)
                                    finally:
                                        try:
                                            os.unlink(temp, dir_fd=parent)
                                        except FileNotFoundError:
                                            pass
                                elif self.command == "MKCOL":
                                    used_bytes, used_entries = owner.usage()
                                    owner.require_quota(used_bytes, used_entries + 1)
                                    os.mkdir(name, dir_fd=parent)
                                    self.reply(201)
                                elif self.command == "DELETE":
                                    if before is None:
                                        raise FileNotFoundError()
                                    if stat.S_ISDIR(before[3]):
                                        os.rmdir(name, dir_fd=parent)  # Never recursively cross a protected entry.
                                    else:
                                        os.unlink(name, dir_fd=parent)
                                    self.reply(204)
                                else:
                                    if before is None:
                                        raise FileNotFoundError()
                                    if not stat.S_ISREG(before[3]):
                                        raise PermissionError("Directory MOVE is unsupported")
                                    dest = urllib.parse.urlsplit(self.headers.get("Destination", ""))
                                    if dest.netloc and dest.netloc != self.headers.get("Host"):
                                        raise PermissionError()
                                    target_parts = parts_for(self.headers.get("Destination", ""))
                                    if not target_parts:
                                        raise PermissionError()
                                    with owner.open(target_parts[:-1], directory=True) as dest_parent:
                                        existing = owner.fingerprint(dest_parent, target_parts[-1])
                                        if existing and self.headers.get("Overwrite", "T") == "F":
                                            self.reply(412)
                                            return
                                        os.replace(name, target_parts[-1], src_dir_fd=parent, dst_dir_fd=dest_parent)
                                    self.reply(204 if existing else 201)
                        else:
                            self.reply(405)
                except FileNotFoundError:
                    self.reply(404)
                except PermissionError:
                    self.reply(403)
                except QuotaExceeded:
                    self.reply(507)
                except OverflowError:
                    self.reply(413)
                except (ValueError, UnicodeError):
                    self.reply(400)
                except (BrokenPipeError, ConnectionError, TimeoutError):
                    self.close_connection = True
                except OSError:
                    self.reply(409)

            do_OPTIONS = do_PROPFIND = do_GET = do_HEAD = do_PUT = do_MKCOL = do_MOVE = do_DELETE = run

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = False
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def require_quota(self, used_bytes, used_entries):
        if used_bytes > self.max_bytes or used_entries > self.max_entries:
            raise QuotaExceeded("Workspace byte or entry quota exceeded")

    def usage(self):
        """Count exported bytes/entries without following links; bounded by quotas.

        Protected .git and staging entries are not exported. The current upload
        reservation is checked separately, so old+new content cannot bypass quotas.
        Local edits are trusted; this is an agent-write quota, not a host-user quota.
        """
        used_bytes = used_entries = 0

        def visit(fd, depth):
            nonlocal used_bytes, used_entries
            if depth > 64:
                raise QuotaExceeded("Workspace tree is too deep")
            with os.scandir(fd) as entries:
                for entry in entries:
                    if entry.name == ".git" or entry.name.startswith(HIDDEN):
                        continue
                    info = entry.stat(follow_symlinks=False)
                    used_entries += 1
                    if stat.S_ISREG(info.st_mode):
                        used_bytes += info.st_size
                    self.require_quota(used_bytes, used_entries)
                    if stat.S_ISDIR(info.st_mode):
                        child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            visit(child, depth + 1)
                        finally:
                            os.close(child)
        visit(self.fd, 0)
        return used_bytes, used_entries

    @contextlib.contextmanager
    def open(self, parts, directory=False):
        fd = os.dup(self.fd)
        try:
            for i, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if directory or i < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                raise PermissionError("Only directories and single-link regular files are exported")
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def fingerprint(parent, name):
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise PermissionError()
        return (info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)

    @property
    def port(self):
        return self.http.server_port

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        os.close(self.fd)
