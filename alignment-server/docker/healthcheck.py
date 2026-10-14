"""Check readiness without running inference or reserving a queue slot."""

import json
import os
from urllib.request import urlopen


port = int(os.environ.get("ALIGNMENT_PORT", "8000"))
with urlopen(f"http://127.0.0.1:{port}/health", timeout=4) as response:
    if response.status != 200 or json.load(response).get("status") != "ready":
        raise SystemExit(1)
