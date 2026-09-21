"""Small standard-library HTTP adapter compatible with the original demo."""
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from app.config import Settings
from app.service.turn_service import TurnService, empty_response

LOGGER = logging.getLogger(__name__)


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service: TurnService):
        self.service = service
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(4.0)

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            LOGGER.warning("response_connection_closed")

    def do_GET(self) -> None:
        if self.path in ("/health", "/healthz"):
            self.send_json(200, {"status": "ok", "protocol": "futurewar-v1.0"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("chunked request bodies are not supported")
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("nonempty body and Content-Length required")
            if length > self.server.service.settings.max_body_bytes:
                self.send_json(413, empty_response())
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete request body")
            def reject_constant(value):
                raise ValueError(f"invalid JSON constant: {value}")
            payload = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
            if not isinstance(payload, dict):
                raise ValueError("request must be a JSON object")
            response = self.server.service.decide(payload)
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            LOGGER.warning("protocol_error %s", exc)
            self.send_json(400, empty_response())
            return
        except TimeoutError:
            LOGGER.warning("request_read_timeout")
            self.send_json(408, empty_response())
            return
        except Exception:
            # A server-side defect is logged, not reported as a successful decision.
            LOGGER.exception("decision_failed; returning safe empty actions")
            self.send_json(200, empty_response())
            return
        self.send_json(200, response)

    def log_message(self, format, *args) -> None:
        return


def serve(port: int, settings: Settings | None = None) -> None:
    settings = settings or Settings.load()
    if settings.allow_base_surroundings:
        LOGGER.info("construction_mode=base_surroundings; user-authorized fallback enabled")
    elif not any(layout.get("verified") for layout in settings.layouts.values()):
        LOGGER.warning("D01: no verified construction coordinates; automatic construction is disabled")
    with AgentServer(("0.0.0.0", port), TurnService(settings)) as server:
        LOGGER.info("listening on 0.0.0.0:%d", port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("server stopping")
