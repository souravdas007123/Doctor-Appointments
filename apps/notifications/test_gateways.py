import base64
import json
import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from .gateways import ConsoleSMSGateway, SMSError, TwilioSMSGateway


class _Handler(BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        from urllib.parse import parse_qs
        form = {k: v[0] for k, v in parse_qs(body).items()}
        _Handler.calls.append({"path": self.path, "auth": self.headers.get("Authorization"),
                               "content_type": self.headers.get("Content-Type"), "form": form})
        if form.get("To") == "+10000000000":
            status, resp = 400, {"message": "Invalid To number"}
        else:
            status, resp = 201, {"sid": "SM_test1", "status": "queued"}
        data = json.dumps(resp).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TwilioGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1"
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.gw = TwilioSMSGateway("AC_test_sid", "auth_tok", "+15005550006",
                                   base_url=f"http://127.0.0.1:{cls.server.server_port}/2010-04-01")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.calls.clear()

    def test_send_request_shape(self):
        result = self.gw.send("+919876543210", "Your appointment is confirmed")
        self.assertEqual(result["sid"], "SM_test1")
        call = _Handler.calls[0]
        self.assertEqual(call["path"], "/2010-04-01/Accounts/AC_test_sid/Messages.json")
        self.assertEqual(call["content_type"], "application/x-www-form-urlencoded")
        self.assertEqual(call["auth"], "Basic " + base64.b64encode(b"AC_test_sid:auth_tok").decode())
        self.assertEqual(call["form"], {"To": "+919876543210", "From": "+15005550006", "Body": "Your appointment is confirmed"})

    def test_gateway_error_message_surfaced(self):
        with self.assertRaisesRegex(SMSError, "Invalid To number"):
            self.gw.send("+10000000000", "test")

    def test_connection_failure_becomes_sms_error(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        gw = TwilioSMSGateway("a", "b", "+1", base_url=f"http://127.0.0.1:{port}", timeout=2)
        with self.assertRaises(SMSError):
            gw.send("+919876543210", "x")


class ConsoleGatewayTests(unittest.TestCase):
    def test_console_gateway_returns_queued_without_network(self):
        result = ConsoleSMSGateway().send("+919876543210", "hello")
        self.assertEqual(result["status"], "queued")
