import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app_lifecycle import BrowserLifecycle, InstanceLock


class BrowserLifecycleTests(unittest.TestCase):
    def test_last_tab_closes_server(self):
        stopped = threading.Event()
        lifecycle = BrowserLifecycle(stopped.set, grace_seconds=0.1)
        lifecycle.opened()
        lifecycle.opened()
        lifecycle.closed()
        self.assertFalse(stopped.wait(0.15))
        lifecycle.closed()
        self.assertTrue(stopped.wait(1.0))

    def test_refresh_cancels_pending_exit(self):
        stopped = threading.Event()
        lifecycle = BrowserLifecycle(stopped.set, grace_seconds=0.15)
        lifecycle.opened()
        lifecycle.closed()
        lifecycle.opened()
        self.assertFalse(stopped.wait(0.25))
        lifecycle.closed()
        self.assertTrue(stopped.wait(1.0))

    def test_exit_button_stops_with_open_tabs(self):
        stopped = threading.Event()
        lifecycle = BrowserLifecycle(stopped.set, grace_seconds=5.0)
        lifecycle.opened()
        lifecycle.request_exit()
        self.assertTrue(stopped.wait(1.5))


class InstanceLockTests(unittest.TestCase):
    def test_only_one_instance_owns_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            first = InstanceLock(Path(directory))
            second = InstanceLock(Path(directory))
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
            finally:
                second.release()
                first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_existing_instance_url_is_verified(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"title": "AI 本地图像生成工具"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            instance = InstanceLock(Path(directory))
            try:
                self.assertTrue(instance.acquire())
                url = f"http://127.0.0.1:{server.server_port}"
                instance.publish(url)
                self.assertEqual(instance.wait_for_url(timeout_seconds=1), url)
            finally:
                instance.release()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
