"""Outbound HTTP boundary; keeps external integration code out of services."""
from urllib.request import Request, urlopen
import json


def post_json(url: str, payload: dict, timeout: float = 5.0) -> bytes:
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return response.read()
