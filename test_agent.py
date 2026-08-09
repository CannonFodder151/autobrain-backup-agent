"""Runnable self-check for the backup agent (stdlib only, no framework).

Serves a fake AutoBrain backup over a local HTTP server and asserts the agent
downloads, validates, saves and uploads it. Run:  python3 test_agent.py
"""

import contextlib
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

import agent


@contextlib.contextmanager
def serve(payload, key, upload_target=None):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/admin-api/backup":
                if self.headers.get(agent.HEADER_KEY) != key:
                    self.send_response(401)
                    self.end_headers()
                    return
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/target":
                n = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(n)
                self.send_response(202)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as httpd:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        yield httpd.server_address[1]
        httpd.shutdown()


def main():
    key = "test-key-123"
    payload = {"app": "autobrain", "kind": "backup", "version": 1,
               "created_at": "2026-08-08T10:00:00", "data": {"users": [{"id": "u1"}]}}
    url = {"url": None}

    with serve(payload, key) as port:
        url["url"] = f"http://127.0.0.1:{port}"
        with tempfile.TemporaryDirectory() as d:
            os.environ.update({"AUTOBRAIN_URL": url["url"], "AUTOBRAIN_API_KEY": key,
                               "OUT_DIR": d, "KEEP": "30",
                               "TARGET_URL": url["url"] + "/target", "TARGET_KEY": key})
            assert agent.main(["--once"]) == 0, "agent run should exit 0"

            files = list(Path(d).glob("autobrain-backup-*.json"))
            assert len(files) == 1, f"expected one saved backup, got {len(files)}"
            saved = json.loads(files[0].read_text())
            assert saved["app"] == "autobrain" and saved["kind"] == "backup", "content mismatch"

            assert agent.validate(json.dumps(payload).encode()) is not None
            for bad in (b"not json", b"[]", json.dumps({"app": "autobrain", "kind": "profile", "data": {}}).encode()):
                try:
                    agent.validate(bad)
                    raise AssertionError(f"should reject: {bad}")
                except agent.AgentError:
                    pass

            os.environ["AUTOBRAIN_API_KEY"] = "wrong"
            try:
                agent.fetch_backup(url["url"] + "/admin-api/backup", "wrong", agent._opener(""))
                raise AssertionError("bad key should fail")
            except agent.AgentError as e:
                assert "401" in str(e), str(e)

    print("test_agent.py: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
