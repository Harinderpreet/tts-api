"""Exercise the actual local HTTP manager with one then two real requests."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from alignment_service import AlignmentService
from alignment_server import create_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--window", type=int, default=10)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    sample = root / "output/sample-2026-10-14"
    report_path = sample / "optimizations/http-check.json"
    if report_path.exists():
        raise FileExistsError(report_path)
    service = AlignmentService(str(root/".cache/mms-300m-ct2-int8"), workers=2, intra_threads=args.threads,
                               window_length=args.window)
    model_identity = id(service.aligner.model)
    server = create_server(service,0)  # OS-assigned test port; no existing service touched.
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/align"
    payload = {"audio_path":str(sample/"speech.mp3"),
               "transcript":(sample/"transcript.txt").read_text(),"language":"eng"}

    def send(body):
        request = Request(url,data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
        with urlopen(request,timeout=120) as response:
            assert response.status == 200
            return json.load(response)

    try:
        try:
            send({"transcript":"missing fields"})
            raise AssertionError("Invalid request was accepted")
        except HTTPError as error:
            assert error.code == 400
            error.close()
        first = send(payload)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send,payload) for _ in range(2)]
            concurrent = [f.result() for f in futures]
        assert first["srt"] == concurrent[0]["srt"] == concurrent[1]["srt"]
        assert len(first["words"]) == 305
        assert id(service.aligner.model) == model_identity
        reference = sample / "optimizations" / f"stream-{args.window}s-t{args.threads}" / "words.1.1.srt"
        assert first["srt"] == reference.read_text()
        report = {"invalid_request_status":400,"successful_requests":3,
                  "one_then_two_concurrent":True,"all_srts_identical":True,
                  "model_reused":True,"words":305,"window":args.window,"threads":args.threads,
                  "test_server_stopped_after_check":True}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    with report_path.open("x") as file:
        json.dump(report,file,indent=2)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
