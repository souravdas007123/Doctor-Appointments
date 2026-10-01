import base64
import json
import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from .gateway import RazorpayError, RazorpayGateway


class _Handler(BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        _Handler.calls.append({"path": self.path, "auth": self.headers.get("Authorization"),
                               "idem": self.headers.get("X-Refund-Idempotency"), "body": body})
        if self.path.endswith("/orders") and body.get("amount") == 1:
            status, resp = 400, {"error": {"description": "Amount too small"}}
        elif self.path.endswith("/refund"):
            status, resp = 200, {"id": "rfnd_test1", "status": "processed"}
        else:
            status, resp = 200, {"id": "order_test1"}
        data = json.dumps(resp).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class GatewayClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1"
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.gw = RazorpayGateway("rzp_test_id", "secret", base_url=f"http://127.0.0.1:{cls.server.server_port}/v1")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.calls.clear()

    def test_create_order_request_shape(self):
        order = self.gw.create_order(80000, receipt="APT10001", notes={"appointment_id": "1"})
        self.assertEqual(order["id"], "order_test1")
        call = _Handler.calls[0]
        self.assertEqual(call["path"], "/v1/orders")
        self.assertEqual(call["auth"], "Basic " + base64.b64encode(b"rzp_test_id:secret").decode())
        self.assertEqual(call["body"], {"amount": 80000, "currency": "INR", "receipt": "APT10001", "notes": {"appointment_id": "1"}})

    def test_refund_request_shape_and_idempotency_header(self):
        data = self.gw.refund("pay_abc", 80000, notes={"refund_id": "7"}, idempotency_key="careslot-refund-7")
        self.assertEqual(data["status"], "processed")
        call = _Handler.calls[0]
        self.assertEqual(call["path"], "/v1/payments/pay_abc/refund")
        self.assertEqual(call["idem"], "careslot-refund-7")
        self.assertEqual((call["body"]["amount"], call["body"]["speed"]), (80000, "normal"))

    def test_gateway_error_message_is_surfaced(self):
        with self.assertRaisesRegex(RazorpayError, "Amount too small"):
            self.gw.create_order(1, receipt="x")

    def test_connection_failure_becomes_razorpay_error(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()   # closed port
        gw = RazorpayGateway("a", "b", base_url=f"http://127.0.0.1:{port}/v1", timeout=2)
        with self.assertRaises(RazorpayError):
            gw.create_order(100, receipt="x")
