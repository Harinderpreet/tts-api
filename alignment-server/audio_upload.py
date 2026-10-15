"""Stream a multipart audio upload to disk with bounded text/header buffers."""

from pathlib import Path

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header


class UploadTooLarge(ValueError):
    pass


def read_audio_upload(stream, content_type, length, directory, max_bytes):
    """Return private audio path, transcript and language; caller owns directory cleanup."""
    if length <= 0:
        raise ValueError("The upload body is empty")
    if length > max_bytes:
        raise UploadTooLarge("Upload exceeds the configured request size limit")
    media_type, options = parse_options_header(content_type)
    boundary = options.get(b"boundary")
    if media_type.lower() != b"multipart/form-data" or not boundary or len(boundary) > 200:
        raise ValueError("Send multipart/form-data with a valid boundary")

    path = Path(directory) / "audio.upload"
    fields, seen, headers = {}, set(), {}
    header_name, header_value = bytearray(), bytearray()
    part_name = None
    part_count = header_bytes = audio_bytes = 0
    complete = False

    def part_begin():
        nonlocal part_count, header_bytes, part_name
        part_count += 1
        if part_count > 3:
            raise ValueError("Only audio, transcript and language fields are accepted")
        headers.clear()
        header_name.clear()
        header_value.clear()
        header_bytes, part_name = 0, None

    def collect_header(target, data, start, end):
        nonlocal header_bytes
        header_bytes += end - start
        if header_bytes > 16384:
            raise ValueError("Multipart headers are too large")
        target.extend(data[start:end])

    def header_end():
        name = bytes(header_name).lower()
        if not name or name in headers:
            raise ValueError("Invalid or duplicate multipart header")
        headers[name] = bytes(header_value)
        header_name.clear()
        header_value.clear()

    def headers_finished():
        nonlocal part_name
        disposition, parameters = parse_options_header(headers.get(b"content-disposition", b""))
        part_name = parameters.get(b"name")
        if disposition != b"form-data" or part_name not in {b"audio", b"transcript", b"language"}:
            raise ValueError("Expected an audio file and transcript text, with optional language")
        if part_name in seen:
            raise ValueError("Duplicate form field")
        seen.add(part_name)
        if part_name == b"audio":
            if b"filename" not in parameters:
                raise ValueError("audio must be an uploaded file")
        else:
            # Transcript may also arrive as a UTF-8 text-file part; its filename is ignored.
            fields[part_name] = bytearray()
        if headers.get(b"content-transfer-encoding", b"binary").lower() not in {b"binary", b"8bit"}:
            raise ValueError("Upload raw file bytes without transfer encoding")

    def part_data(data, start, end):
        nonlocal audio_bytes
        if part_name == b"audio":
            audio_bytes += end - start
            audio.write(data[start:end])
        elif part_name in fields:
            limit = 2 * 1024 * 1024 if part_name == b"transcript" else 32
            if len(fields[part_name]) + end - start > limit:
                raise UploadTooLarge("Transcript or language field is too large")
            fields[part_name].extend(data[start:end])
        else:
            raise ValueError("Multipart data arrived before its headers")

    def body_end():
        nonlocal complete
        complete = True

    callbacks = {
        "on_part_begin": part_begin,
        "on_header_field": lambda data, start, end: collect_header(header_name, data, start, end),
        "on_header_value": lambda data, start, end: collect_header(header_value, data, start, end),
        "on_header_end": header_end,
        "on_headers_finished": headers_finished,
        "on_part_data": part_data,
        "on_end": body_end,
    }
    parser = MultipartParser(boundary, callbacks)
    try:
        with path.open("xb") as audio:
            remaining = length
            read = getattr(stream, "read1", stream.read)
            while remaining:
                chunk = read(min(remaining, 64 * 1024))
                if not chunk:
                    raise ValueError("Upload ended before Content-Length bytes were received")
                remaining -= len(chunk)
                parser.write(chunk)
            parser.finalize()
    except MultipartParseError as error:
        raise ValueError("Malformed multipart upload") from error
    finally:
        parser.close()

    if not complete or not {b"audio", b"transcript"}.issubset(seen):
        raise ValueError("Upload must include a complete audio file and transcript")
    if not audio_bytes:
        raise ValueError("The audio file is empty")
    transcript = fields[b"transcript"].decode("utf-8-sig").strip()
    language = fields.get(b"language", b"eng").decode("utf-8").strip().lower()
    if not transcript:
        raise ValueError("The transcript must not be empty")
    return str(path), transcript, language
