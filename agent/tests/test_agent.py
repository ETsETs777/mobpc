"""Тесты агента mobpc. Запуск из папки agent:

    .venv\\Scripts\\python -m unittest discover -s tests -v
"""

import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))

# Отдельная папка данных, чтобы тесты не трогали настоящих привязанных устройств.
_TMP = Path(tempfile.mkdtemp(prefix="mobpc-test-", dir=Path(__file__).resolve().parent))
os.environ["MOBPC_DATA_DIR"] = str(_TMP / "data")
os.environ["MOBPC_LOGS_DIR"] = str(_TMP / "logs")

from auth.pairing import TooManyAttempts, auth_manager, normalize_code  # noqa: E402
from executor.dispatcher import dispatcher  # noqa: E402
from executor.shell_files import exec_shell  # noqa: E402
from server import network  # noqa: E402
from executor.downloads import DownloadManager, download_manager, _filename  # noqa: E402
from executor.input import _resolve_shortcut_key  # noqa: E402
from server.app import _app_url, create_app, is_local_request  # noqa: E402
from server.tunnel import keep_awake, tunnel_manager  # noqa: E402
from server.config import settings  # noqa: E402


def tearDownModule() -> None:
    import logging

    # Windows не даёт удалить открытый файл лога — сначала закрываем обработчики.
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_mobpc", False):
            h.close()
            root.removeHandler(h)
    shutil.rmtree(_TMP, ignore_errors=True)


class PairingTests(unittest.TestCase):
    def setUp(self) -> None:
        auth_manager._fails.clear()

    def test_code_format(self):
        s = auth_manager.create_pairing_code()
        self.assertEqual(len(s.code), 8)
        self.assertNotRegex(s.code, "[01OIL]")
        self.assertEqual(s.display_code, f"{s.code[:4]}-{s.code[4:]}")

    def test_exchange_verify_revoke(self):
        s = auth_manager.create_pairing_code()
        token, device = auth_manager.exchange_pairing_code(s.display_code.lower(), "Тестовый телефон")
        self.assertEqual(auth_manager.verify_token(token).id, device.id)
        self.assertEqual(s.status, "paired")
        self.assertTrue(auth_manager.revoke(device.id))
        self.assertIsNone(auth_manager.verify_token(token))

    def test_code_is_single_use(self):
        s = auth_manager.create_pairing_code()
        self.assertIsNotNone(auth_manager.exchange_pairing_code(s.code, "a"))
        self.assertIsNone(auth_manager.exchange_pairing_code(s.code, "b"))

    def test_expired_code_rejected(self):
        s = auth_manager.create_pairing_code()
        s.expires_at = time.time() - 1
        self.assertIsNone(auth_manager.exchange_pairing_code(s.code, "a"))

    def test_bruteforce_is_limited(self):
        for _ in range(20):
            auth_manager.exchange_pairing_code("AAAA-AAAA", "x")
        with self.assertRaises(TooManyAttempts):
            auth_manager.exchange_pairing_code("BBBB-BBBB", "x")

    def test_garbage_token(self):
        self.assertIsNone(auth_manager.verify_token("not-a-jwt"))
        self.assertIsNone(auth_manager.verify_token(None))

    def test_normalize(self):
        self.assertEqual(normalize_code(" ab cd-ef9h "), "ABCDEF9H")


class LocalRequestTests(unittest.TestCase):
    def test_loopback_is_local(self):
        self.assertTrue(is_local_request("127.0.0.1", {}))
        self.assertTrue(is_local_request("::1", {}))

    def test_lan_is_not_local(self):
        self.assertFalse(is_local_request("192.168.1.20", {}))

    def test_tunnel_is_not_local(self):
        # cloudflared подключается к агенту с 127.0.0.1, но добавляет заголовки
        self.assertFalse(is_local_request("127.0.0.1", {"cf-connecting-ip": "1.2.3.4"}))
        self.assertFalse(is_local_request("127.0.0.1", {"x-forwarded-for": "1.2.3.4"}))


class NetworkTests(unittest.TestCase):
    def test_virtual_mac_detection(self):
        self.assertTrue(network._is_virtual_mac(None))
        self.assertTrue(network._is_virtual_mac("00-00-00-00-00-00"))
        self.assertTrue(network._is_virtual_mac("02-50-76-FA-25-C7"))  # локально назначенный
        self.assertTrue(network._is_virtual_mac("00-15-5D-2E-0A-BA"))  # Hyper-V
        self.assertFalse(network._is_virtual_mac("74-56-3C-98-5E-DA"))

    def test_list_addresses_shape(self):
        for a in network.list_addresses():
            self.assertEqual(set(a), {"ip", "iface", "kind", "wifi", "primary"})
            self.assertFalse(a["ip"].startswith("127."))


class DispatcherTests(unittest.TestCase):
    def test_ping(self):
        r = asyncio.run(dispatcher.dispatch("system.ping", {}, "test"))
        self.assertTrue(r["pong"])

    def test_unknown_command(self):
        with self.assertRaises(ValueError):
            asyncio.run(dispatcher.dispatch("rm.everything", {}, "test"))

    def test_stats(self):
        r = asyncio.run(dispatcher.dispatch("system.stats", {}, "test"))
        self.assertIn("cpu", r)
        self.assertGreater(r["ram"]["total"], 0)

    def test_nested_macro_forbidden(self):
        r = asyncio.run(dispatcher.dispatch("macro.run", {"steps": [{"type": "macro.run", "payload": {}}]}, "test"))
        self.assertFalse(r["results"][0]["ok"])

    def test_file_list_drives(self):
        r = asyncio.run(dispatcher.dispatch("file.list", {"path": "::drives"}, "test"))
        self.assertTrue(all(e["drive"] for e in r["entries"]))


class ShellTests(unittest.TestCase):
    def test_cyrillic_output(self):
        r = asyncio.run(exec_shell({"command": "Write-Output 'Привет, жюри'"}))
        self.assertEqual(r["exit_code"], 0)
        self.assertIn("Привет, жюри", r["stdout"])

    def test_cmd_shell(self):
        r = asyncio.run(exec_shell({"command": "echo Тест", "shell": "cmd"}))
        self.assertIn("Тест", r["stdout"])

    def test_timeout_kills_process(self):
        started = time.time()
        r = asyncio.run(exec_shell({"command": "Start-Sleep -Seconds 20", "timeout": 1}))
        self.assertTrue(r["timed_out"])
        self.assertLess(time.time() - started, 10)


class DownloadTests(unittest.TestCase):
    """Скачивание по ссылке: поднимаем локальный HTTP-сервер с тестовым файлом."""

    @classmethod
    def setUpClass(cls):
        import functools
        import http.server

        cls.src = _TMP / "www"
        cls.src.mkdir(parents=True, exist_ok=True)
        (cls.src / "game-patch.bin").write_bytes(os.urandom(700_000))
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(cls.src))
        handler.log_message = lambda *a, **k: None
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/game-patch.bin"
        cls.dest = _TMP / "dl"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _wait(self, item_id, timeout=10):
        for _ in range(timeout * 20):
            d = download_manager.items[item_id]
            if d.status in ("done", "error", "cancelled"):
                return d
            time.sleep(0.05)
        self.fail("download did not finish")

    def test_download_file(self):
        r = download_manager.start({"url": self.url, "dir": str(self.dest)})
        d = self._wait(r["id"])
        self.assertEqual(d.status, "done", d.error)
        self.assertEqual(Path(d.path).read_bytes(), (self.src / "game-patch.bin").read_bytes())

    def test_same_name_gets_suffix(self):
        a = self._wait(download_manager.start({"url": self.url, "dir": str(self.dest)})["id"])
        b = self._wait(download_manager.start({"url": self.url, "dir": str(self.dest)})["id"])
        self.assertNotEqual(a.path, b.path)

    def test_name_known_before_response(self):
        with mock.patch('executor.downloads.threading.Thread.start'):
            result = download_manager.start({'url': self.url, 'dir': str(self.dest)})
        self.assertEqual(result['name'], 'game-patch.bin')
        download_manager.items.pop(result['id'])

    def test_existing_partial_file_is_preserved(self):
        folder = _TMP / 'partial-download'
        folder.mkdir()
        partial = folder / 'game-patch.bin.part'
        partial.write_bytes(b'previous interrupted download')
        result = download_manager.start({'url': self.url, 'dir': str(folder)})
        item = self._wait(result['id'])
        self.assertEqual(item.status, 'done', item.error)
        self.assertNotEqual(Path(item.path).name, 'game-patch.bin')
        self.assertEqual(partial.read_bytes(), b'previous interrupted download')

    def test_short_response_is_not_reported_as_complete(self):
        folder = _TMP / 'truncated-download'
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://example.test/file.bin'
        response.headers = {'Content-Length': '8'}
        response.read.side_effect = [b'abc', b'']
        with mock.patch('executor.downloads.urllib.request.urlopen', return_value=response):
            result = download_manager.start({'url': 'https://example.test/file.bin', 'dir': str(folder)})
            item = self._wait(result['id'])
        self.assertEqual(item.status, 'error')
        self.assertIn('3 из 8', item.error)
        self.assertEqual(list(folder.iterdir()), [])

    def test_windows_device_name_is_saved_as_a_regular_file(self):
        name = _filename('https://example.test/NUL.txt', {})
        path = _TMP / name
        path.write_bytes(b'downloaded content')
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), b'downloaded content')

    def test_concurrent_downloads_keep_separate_contents(self):
        barrier = threading.Barrier(2)
        contents = {'https://example.test/a/file.bin': b'a' * 100,
                    'https://example.test/b/file.bin': b'b' * 100}

        class Response:
            headers = {'Content-Length': '100'}

            def __init__(self, url):
                self.url, self.sent = url, False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def geturl(self):
                return self.url

            def read(self, length):
                if self.sent:
                    return b''
                self.sent = True
                barrier.wait(timeout=5)
                return contents[self.url]

        manager = DownloadManager()
        folder = _TMP / 'concurrent-downloads'
        with mock.patch('executor.downloads.urllib.request.urlopen', side_effect=lambda request, **kw: Response(request.full_url)):
            items = [manager.start({'url': url, 'dir': str(folder)}) for url in contents]
            for item in items:
                for _ in range(100):
                    download = manager.items[item['id']]
                    if download.finished is not None:
                        break
                    time.sleep(.05)
                self.assertEqual(download.status, 'done', download.error)
                self.assertEqual(Path(download.path).read_bytes(), contents[download.url])
        self.assertNotEqual(*(manager.items[item['id']].path for item in items))

    def test_rejects_non_http(self):
        with self.assertRaises(ValueError):
            download_manager.start({"url": "file:///C:/Windows/win.ini"})

    def test_bad_host_reports_error(self):
        r = download_manager.start({"url": "http://127.0.0.1:1/nothing.bin", "dir": str(self.dest)})
        self.assertEqual(self._wait(r["id"]).status, "error")


class RemoteAccessTests(unittest.TestCase):
    def test_app_url_for_tunnel_and_lan(self):
        self.assertEqual(_app_url("https://abc-def.trycloudflare.com", "ABCD2345"), "https://abc-def.trycloudflare.com/app#pair=ABCD2345")
        self.assertEqual(_app_url("192.168.1.5", "ABCD2345"), f"http://192.168.1.5:{settings.port}/app#pair=ABCD2345")

    def test_tunnel_status_shape(self):
        st = tunnel_manager.status()
        self.assertIn(st["state"], ("off", "downloading", "starting", "on", "error"))
        self.assertIn("installed", st)

    def test_keep_awake_toggle(self):
        self.assertTrue(keep_awake.set(True, remember=False))
        r = asyncio.run(dispatcher.dispatch("power.keep_awake", {}, "test"))
        self.assertTrue(r["keep_awake"])
        r = asyncio.run(dispatcher.dispatch("power.keep_awake", {"enabled": False}, "test"))
        self.assertFalse(r["keep_awake"])

    def test_shortcut_keys_ignore_layout(self):
        # Ctrl+C должен нажимать физическую клавишу C (VK 0x43) даже на русской раскладке
        self.assertEqual(_resolve_shortcut_key("c").vk, 0x43)
        self.assertEqual(_resolve_shortcut_key(".").vk, 0xBE)


class ServerIntegrationTests(unittest.TestCase):
    """Поднимает настоящий сервер на свободном порту и общается с ним как телефон."""

    @classmethod
    def setUpClass(cls):
        import uvicorn

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        settings.port = cls.port
        config = uvicorn.Config(create_app(), host="127.0.0.1", port=cls.port, log_level="error")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def _req(self, path, method="GET", body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_pages_served(self):
        for path in ("/", "/app", "/connect", "/assets/app.js", "/manifest.webmanifest"):
            status, _ = self._req(path)
            self.assertEqual(status, 200, path)

    def test_pairing_via_tunnel_forbidden(self):
        status, _ = self._req("/api/pairing", "POST", headers={"CF-Connecting-IP": "8.8.8.8"})
        self.assertEqual(status, 403)
        status, _ = self._req("/api/tunnel/start", "POST", headers={"CF-Connecting-IP": "8.8.8.8"})
        self.assertEqual(status, 403)

    def test_full_flow_over_websocket(self):
        import websockets

        auth_manager._fails.clear()
        status, raw = self._req("/api/pairing?host=127.0.0.1", "POST")
        self.assertEqual(status, 200)
        code = json.loads(raw)["code"]
        status, _ = self._req(f"/api/pairing/{code}/qr.png")
        self.assertEqual(status, 200)
        status, raw = self._req("/api/pairing/exchange", "POST", {"code": code, "device_name": "unittest"})
        self.assertEqual(status, 200)
        token = json.loads(raw)["token"]

        async def talk():
            async with websockets.connect(f"ws://127.0.0.1:{self.port}/ws?token={token}") as ws:
                hello = json.loads(await ws.recv())
                self.assertEqual(hello["type"], "connected")
                await ws.send(json.dumps({"id": "1", "type": "system.ping", "payload": {}}))
                reply = json.loads(await ws.recv())
                self.assertTrue(reply["ok"])
                self.assertTrue(reply["data"]["pong"])
                await ws.send(json.dumps({"id": "2", "type": "nope", "payload": {}}))
                reply = json.loads(await ws.recv())
                self.assertFalse(reply["ok"])

            async with websockets.connect(f"ws://127.0.0.1:{self.port}/ws?token=bad") as ws:
                with self.assertRaises(websockets.ConnectionClosed) as ctx:
                    await ws.recv()
                self.assertEqual(ctx.exception.rcvd.code, 4401)

        asyncio.run(talk())


if __name__ == "__main__":
    unittest.main()
