"""Exercise the actual HTTP handler without binding sockets or using the network."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentic_research_assistant.web import ResearchHandler


class FakeSocket:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = io.BytesIO()

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.write(data)

    def settimeout(self, timeout):
        pass


class WebHTTPTests(unittest.TestCase):
    def request(self, path="/", method="GET", body=None, headers=None, lock=None, profiles=None):
        body = b"" if body is None else body
        headers = {"Host": "127.0.0.1:8765", **(headers or {})}
        if method == "POST":
            headers.setdefault("Content-Type", "application/json")
            headers.setdefault("Content-Length", str(len(body)))
        raw = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n"
        sock = FakeSocket(raw.encode() + body)
        with tempfile.TemporaryDirectory() as directory:
            server = SimpleNamespace(server_address=("127.0.0.1", 8765), storage_root=Path(directory),
                                     research_lock=lock or threading.Lock(), model_profiles=profiles or {})
            ResearchHandler(sock, ("127.0.0.1", 12345), server)
        head, data = sock.output.getvalue().split(b"\r\n\r\n", 1)
        return int(head.split(b" ")[1]), head, data

    def test_static_files_security_headers_and_unknown_routes(self):
        for route in ("/", "/style.css", "/app.js", "/demo.json"):
            status, headers, body = self.request(route)
            self.assertEqual(status, 200)
            self.assertIn(b"Content-Security-Policy", headers)
            self.assertTrue(body)
        self.assertEqual(self.request("/../../README.md")[0], 404)

    def test_config_never_exposes_api_keys(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret-openai", "TAVILY_API_KEY": "secret-tavily"}):
            status, _, body = self.request("/api/config")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["openai"])
        self.assertNotIn(b"secret", body)

    def test_catalog_exposes_only_model_selection_fields(self):
        profiles = {'custom': {'provider':'openai_compatible', 'model':'my-model',
                              'api_key_env':'PRIVATE_API_KEY', 'base_url_env':'PRIVATE_BASE_URL'}}
        status, _, body = self.request('/api/config', profiles=profiles)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['models'], {'custom': {'provider':'openai_compatible', 'model':'my-model'}})
        self.assertNotIn(b'PRIVATE', body)

    def test_rejects_cross_origin_and_rebound_hosts(self):
        for headers in ({"Origin": "https://attacker.example"}, {"Host": "attacker.example"}):
            self.assertEqual(self.request(headers=headers)[0], 403)
            self.assertEqual(self.request("/api/research", "POST", b"{}", headers)[0], 403)

    def test_post_validates_media_type_size_json_and_input(self):
        for body, headers, expected in ((b"{}", {"Content-Type": "text/plain"}, 415),
                                        (b"{}", {"Content-Length": "2000001"}, 413),
                                        (b"{}", {"Content-Length": "bad"}, 400),
                                        (b"{invalid", {}, 400), (b"[]", {}, 400)):
            with self.subTest(body=body, headers=headers):
                self.assertEqual(self.request("/api/research", "POST", body, headers)[0], expected)

    def test_post_produces_research_report(self):
        body = json.dumps({"topic": "Research", "provider": "local", "persist": False,
                           "documents": [{"title": "Evidence", "content": "Research needs source citations."}]}).encode()
        status, _, data = self.request("/api/research", "POST", body)
        self.assertEqual(status, 200)
        report = json.loads(data)
        self.assertTrue(report["findings"][0]["citations"])
        self.assertIsNone(report["stored_session"])

    def test_busy_server_does_not_start_more_research(self):
        lock = threading.Lock()
        lock.acquire()
        self.assertEqual(self.request("/api/research", "POST", b"{}", lock=lock)[0], 409)
