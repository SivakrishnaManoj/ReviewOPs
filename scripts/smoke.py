import argparse
import json
import urllib.request


def smoke(base_url: str, expected_sha: str | None = None) -> None:
    with urllib.request.urlopen(base_url.rstrip("/") + "/healthz", timeout=10) as response:
        data = json.load(response)
    if data.get("status") != "ok":
        raise RuntimeError("Liveness check failed")
    if expected_sha and data.get("build_sha") != expected_sha:
        raise RuntimeError("Endpoint is not serving the expected commit")
    with urllib.request.urlopen(base_url.rstrip("/") + "/openapi.json", timeout=10) as response:
        schema = json.load(response)
    if "/api/v1/investigations" not in schema.get("paths", {}):
        raise RuntimeError("API contract missing")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--sha")
    args = parser.parse_args()
    smoke(args.url, args.sha)
    print("Smoke checks passed")
