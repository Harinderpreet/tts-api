"""Multipart parsing and temporary-file cleanup checks; no real model is loaded."""

from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from alignment_queue import AlignmentQueue
from alignment_server import create_server
from audio_upload import read_audio_upload, UploadTooLarge


CONTENT_TYPE = "multipart/form-data; boundary=upload-boundary"


def multipart(parts):
    body = bytearray()
    for name, value, filename in parts:
        body.extend(b"--upload-boundary\r\n")
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        body.extend((disposition + "\r\n\r\n").encode())
        body.extend(value)
        body.extend(b"\r\n")
    body.extend(b"--upload-boundary--\r\n")
    return bytes(body)


class SmallChunks(BytesIO):
    def read1(self, size):
        return super().read(min(size, 7))


class UploadTests(unittest.TestCase):
    def test_binary_upload_split_across_boundaries_and_utf8_text(self):
        audio = bytes(range(256)) * 3
        body = multipart([
            ("transcript", "Hello café.".encode(), "transcript.txt"),
            ("audio", audio, "../../outside.mp3"),
        ])
        with TemporaryDirectory() as directory:
            path, transcript, language = read_audio_upload(
                SmallChunks(body), CONTENT_TYPE, len(body), directory, 10000,
            )
            self.assertEqual(Path(path), Path(directory) / "audio.upload")
            self.assertEqual(Path(path).read_bytes(), audio)
            self.assertEqual(transcript, "Hello café.")
            self.assertEqual(language, "eng")

    def test_explicit_language_and_text_fields(self):
        body = multipart([("audio", b"audio", "voice.wav"),
                          ("transcript", b"Hello", None), ("language", b" ENG ", None)])
        with TemporaryDirectory() as directory:
            result = read_audio_upload(BytesIO(body), CONTENT_TYPE, len(body), directory, 10000)
            self.assertEqual(result[1:], ("Hello", "eng"))

    def test_invalid_forms(self):
        audio = ("audio", b"audio", "voice.mp3")
        transcript = ("transcript", b"Hello", None)
        cases = [
            [audio], [transcript], [audio, transcript, transcript],
            [("audio", b"", "voice.mp3"), transcript],
            [("audio", b"audio", None), transcript],
            [audio, ("transcript", b"  ", None)],
            [audio, transcript, ("audio_path", b"/some/file", None)],
        ]
        for parts in cases:
            with self.subTest(parts=parts), TemporaryDirectory() as directory:
                body = multipart(parts)
                with self.assertRaises(ValueError):
                    read_audio_upload(BytesIO(body), CONTENT_TYPE, len(body), directory, 10000)

    def test_limits_and_truncation(self):
        body = multipart([("audio", b"audio", "voice.mp3"), ("transcript", b"Hello", None)])
        with TemporaryDirectory() as directory:
            with self.assertRaises(UploadTooLarge):
                read_audio_upload(BytesIO(body), CONTENT_TYPE, len(body), directory, len(body)-1)
        for truncated, declared_length in ((body[:-30], len(body)), (body[:-30], len(body)-30)):
            with TemporaryDirectory() as directory, self.assertRaises(ValueError):
                read_audio_upload(BytesIO(truncated), CONTENT_TYPE, declared_length, directory, 10000)
        large = multipart([("audio", b"audio", "voice.mp3"),
                           ("transcript", b"x" * (2*1024*1024+1), None)])
        with TemporaryDirectory() as directory, self.assertRaises(UploadTooLarge):
            read_audio_upload(BytesIO(large), CONTENT_TYPE, len(large), directory, len(large))


class FakeService:
    def __init__(self):
        self.queue = AlignmentQueue(1, 1, 5)
        self.paths = []
        self.fail = False

    def align(self, path, transcript, language):
        self.paths.append(Path(path))
        if Path(path).read_bytes() != b"sample audio":
            raise AssertionError("Uploaded bytes changed")
        if self.fail:
            raise RuntimeError("Simulated alignment failure")
        return {"words": [{"text": transcript, "start": 0, "end": .2}], "srt": "sample SRT"}


class UploadHTTPTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()
        self.server = create_server(self.service, 0, max_upload_bytes=10000)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def send(self, body, content_type=CONTENT_TYPE):
        request = Request(self.url + "/align", data=body, headers={"Content-Type": content_type})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_upload_result_cleanup_and_error_cleanup(self):
        body = multipart([("audio", b"sample audio", "voice.mp3"), ("transcript", b"Hello", None)])
        self.assertEqual(self.send(body)["srt"], "sample SRT")
        self.assertFalse(self.service.paths[-1].parent.exists())
        self.service.fail = True
        with self.assertRaises(HTTPError) as raised:
            self.send(body)
        self.assertEqual(raised.exception.code, 500)
        raised.exception.close()
        self.assertFalse(self.service.paths[-1].parent.exists())
        self.service.fail = False
        self.assertEqual(self.send(body)["srt"], "sample SRT")

    def test_rejects_path_json_and_oversize_and_reports_upload_support(self):
        with self.assertRaises(HTTPError) as raised:
            self.send(b'{"audio_path":"/server/file"}', "application/json")
        self.assertEqual(raised.exception.code, 415)
        raised.exception.close()
        body = multipart([("audio", b"x"*10000, "voice.mp3"), ("transcript", b"Hello", None)])
        with self.assertRaises(HTTPError) as raised:
            self.send(body)
        self.assertEqual(raised.exception.code, 413)
        raised.exception.close()
        with urlopen(self.url + "/health", timeout=5) as response:
            self.assertTrue(json.load(response)["audio_upload"])


if __name__ == "__main__":
    unittest.main()
