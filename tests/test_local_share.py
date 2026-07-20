import base64
import json
import tempfile
import unittest
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from local_share import (
    SESSION_SECRET,
    PASSWORD,
    SHARED_DIRECTORY,
    LocalShareHandler,
    available_name,
    check_auth,
    file_icon,
    hash_password,
    is_image,
    safe_path,
)


class TestHelpers(unittest.TestCase):
    def test_file_icon_images(self):
        self.assertEqual(file_icon("photo.png"), "\U0001f5bc")
        self.assertEqual(file_icon("video.mp4"), "\U0001f3ac")

    def test_file_icon_documents(self):
        self.assertEqual(file_icon("report.pdf"), "\U0001f4c4")
        self.assertEqual(file_icon("data.xlsx"), "\U0001f4ca")

    def test_file_icon_unknown(self):
        self.assertEqual(file_icon("unknown.xyz"), "\U0001f4c1")

    def test_is_image(self):
        self.assertTrue(is_image("photo.png"))
        self.assertTrue(is_image("IMAGE.JPG"))
        self.assertFalse(is_image("document.pdf"))
        self.assertFalse(is_image("archive.zip"))

    def test_hash_password_deterministic(self):
        self.assertEqual(hash_password("test"), hash_password("test"))
        self.assertNotEqual(hash_password("test"), hash_password("other"))

    def test_safe_path_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            shared.mkdir()
            with patch("local_share.SHARED_DIRECTORY", shared):
                result = safe_path("test.txt")
                self.assertIsNotNone(result)
                self.assertEqual(result.name, "test.txt")

    def test_safe_path_strips_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            shared.mkdir()
            with patch("local_share.SHARED_DIRECTORY", shared):
                result = safe_path("../../../etc/passwd")
                self.assertIsNotNone(result)
                self.assertEqual(result.parent, shared.resolve())
                self.assertEqual(result.name, "passwd")

    def test_available_name_no_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            shared.mkdir()
            with patch("local_share.SHARED_DIRECTORY", shared):
                result = available_name("unique.txt")
                self.assertEqual(result.name, "unique.txt")

    def test_available_name_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            shared.mkdir()
            (shared / "file.txt").write_text("exists")
            with patch("local_share.SHARED_DIRECTORY", shared):
                result = available_name("file.txt")
                self.assertEqual(result.name, "file (1).txt")


class TestServer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.shared_path = Path(self.test_dir.name) / "shared"
        self.shared_path.mkdir()

        self.server = HTTPServer(("127.0.0.1", 0), LocalShareHandler)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        import urllib.request
        self.request = urllib.request

    def tearDown(self):
        self.server.shutdown()
        self.test_dir.cleanup()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def test_get_index(self):
        with patch("local_share.SHARED_DIRECTORY", self.shared_path):
            resp = self.request.urlopen(self._url("/"))
            self.assertEqual(resp.status, 200)
            self.assertIn(b"Local Drop", resp.read())

    def test_get_files_empty(self):
        with patch("local_share.SHARED_DIRECTORY", self.shared_path):
            resp = self.request.urlopen(self._url("/api/files"))
            data = json.loads(resp.read())
            self.assertEqual(data, [])

    def test_upload_and_list(self):
        with patch("local_share.SHARED_DIRECTORY", self.shared_path):
            boundary = "----TestBoundary"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="files"; filename="hello.txt"\r\n'
                f"\r\n"
                f"Hello, World!\r\n"
                f"--{boundary}--\r\n"
            ).encode()

            req = self.request.Request(
                self._url("/upload"),
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            resp = self.request.urlopen(req)
            data = json.loads(resp.read())
            self.assertIn("hello.txt", data["saved"])

            resp = self.request.urlopen(self._url("/api/files"))
            files = json.loads(resp.read())
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["name"], "hello.txt")
            self.assertEqual(files[0]["size"], 13)

    def test_download(self):
        with patch("local_share.SHARED_DIRECTORY", self.shared_path):
            (self.shared_path / "test.txt").write_bytes(b"content")

            resp = self.request.urlopen(self._url("/download/test.txt"))
            self.assertEqual(resp.read(), b"content")

    def test_delete(self):
        with patch("local_share.SHARED_DIRECTORY", self.shared_path):
            (self.shared_path / "to_delete.txt").write_bytes(b"bye")

            req = self.request.Request(
                self._url("/api/files/to_delete.txt"),
                method="DELETE",
            )
            resp = self.request.urlopen(req)
            self.assertEqual(resp.status, 204)
            self.assertFalse((self.shared_path / "to_delete.txt").exists())

    def test_404_unknown_route(self):
        with patch("local_share.SHARED_DIRECTORY", self.shared_path):
            with self.assertRaises(Exception):
                self.request.urlopen(self._url("/nonexistent"))


class TestPasswordProtection(unittest.TestCase):
    def test_check_auth_no_password(self):
        with patch("local_share.PASSWORD", ""):
            handler = type("H", (), {"headers": {}})()
            self.assertTrue(check_auth(handler))

    def test_check_auth_valid_basic(self):
        with patch("local_share.PASSWORD", "secret"), patch("local_share.SESSION_SECRET", "testsecret"):
            expected = hash_password("secret")
            auth = base64.b64encode(b"user:secret").decode()
            handler = type("H", (), {"headers": {"Authorization": f"Basic {auth}"}})()
            self.assertTrue(check_auth(handler))

    def test_check_auth_invalid_password(self):
        with patch("local_share.PASSWORD", "secret"), patch("local_share.SESSION_SECRET", "testsecret"):
            auth = base64.b64encode(b"user:wrong").decode()
            handler = type("H", (), {"headers": {"Authorization": f"Basic {auth}"}})()
            self.assertFalse(check_auth(handler))


class TestFileExpiry(unittest.TestCase):
    def test_expired_files_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            shared.mkdir()
            old_file = shared / "old.txt"
            old_file.write_bytes(b"old")
            import os
            os.utime(old_file, (0, 0))

            with patch("local_share.SHARED_DIRECTORY", shared), patch("local_share.FILE_EXPIRY_HOURS", 1):
                from local_share import cleanup_expired_files
                cleanup_expired_files()
                self.assertFalse(old_file.exists())

    def test_recent_files_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            shared.mkdir()
            new_file = shared / "new.txt"
            new_file.write_bytes(b"new")

            with patch("local_share.SHARED_DIRECTORY", shared), patch("local_share.FILE_EXPIRY_HOURS", 1):
                from local_share import cleanup_expired_files
                cleanup_expired_files()
                self.assertTrue(new_file.exists())


if __name__ == "__main__":
    unittest.main()
