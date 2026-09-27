"""Tiny local web server for the generated site (localhost only by default).

Besides static files it offers one write endpoint, `POST /api/notes/<world id>`, used by the
site to save a note. It only changes annotation files (never worlds), and it refuses requests
that a web page from another site could send: a custom header is required (which browsers only
send cross-site after a CORS preflight that this server never approves) and the Host header must
name this server (against DNS rebinding).
"""

import json
from collections.abc import Callable, Mapping
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final, cast, override
from urllib.parse import unquote

type NoteHandler = Callable[[str, Mapping[str, object]], Mapping[str, object]]
"""(world id, JSON body) -> JSON response. Raise KeyError (unknown world) or ValueError."""

API_HEADER: Final = "X-Mcatlas"
MAX_BODY: Final = 256 * 1024
NOTES_PREFIX: Final = "/api/notes/"


class SiteServer(ThreadingHTTPServer):
    on_note: NoteHandler | None = None
    allowed_hosts: frozenset[str] = frozenset()
    extra: Mapping[str, Path] = {}
    """More folders to serve read-only, by first path segment (e.g. "3d" -> BlueMap webroot)."""


class _Handler(SimpleHTTPRequestHandler):
    @override
    def log_message(self, format: str, *args: object) -> None:
        return

    def _site(self) -> SiteServer:
        return cast("SiteServer", self.server)

    def _json(self, status: HTTPStatus, body: Mapping[str, object]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _trusted(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in self._site().allowed_hosts and self.headers.get(API_HEADER) == "1"

    @override
    def translate_path(self, path: str) -> str:
        first, _, rest = path.lstrip("/").partition("/")
        root = self._site().extra.get(first.split("?", 1)[0].split("#", 1)[0])
        if root is None:
            return super().translate_path(path)
        own = self.directory
        self.directory = str(root)
        try:
            return super().translate_path("/" + rest)
        finally:
            self.directory = own

    @override
    def end_headers(self) -> None:
        # The notes file changes while serving; never let the browser keep a stale copy.
        if self.path.split("?", 1)[0].endswith("annotations.js"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    @override
    def do_GET(self) -> None:
        if self.path == "/api/status":
            if not self._trusted():
                self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
                return
            self._json(HTTPStatus.OK, {"notes": self._site().on_note is not None})
            return
        super().do_GET()

    def do_POST(self) -> None:
        handler = self._site().on_note
        if not self.path.startswith(NOTES_PREFIX) or handler is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._trusted():
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        content_type = self.headers.get("Content-Type") or ""
        if not content_type.startswith("application/json") or not 0 < length <= MAX_BODY:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "expected a JSON body"})
            return
        try:
            body = cast("object", json.loads(self.rfile.read(length)))
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "expected a JSON object"})
            return
        try:
            world = unquote(self.path.removeprefix(NOTES_PREFIX))
            result = handler(world, cast("dict[str, object]", body))
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown world"})
        except ValueError as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        else:
            self._json(HTTPStatus.OK, result)


def serve(
    directory: Path,
    host: str,
    port: int,
    *,
    on_note: NoteHandler | None = None,
    extra: Mapping[str, Path] | None = None,
) -> SiteServer:
    handler = partial(_Handler, directory=str(directory))
    server = SiteServer((host, port), handler)
    server.on_note = on_note
    server.extra = dict(extra or {})
    names = {host, "localhost", "127.0.0.1"} if host in {"127.0.0.1", "localhost"} else {host}
    server.allowed_hosts = frozenset(f"{n}:{server.server_address[1]}" for n in names)
    return server
