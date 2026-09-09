#!/usr/bin/env python3
"""Poll GitHub OAuth device flow until authorized, save token to /tmp/github_token.txt."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT_ID = "178c6fc778ccc68e1d6a"  # GitHub CLI public OAuth app
TOKEN_PATH = Path("/tmp/github_token.txt")
DEVICE_PATH = Path("/tmp/gh_device.json")


def request_device_code() -> dict:
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "scope": "repo,read:org,gist,workflow",
    }).encode()
    req = urllib.request.Request(
        "https://github.com/login/device/code",
        data=data,
        headers={"Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def poll_token(device: dict, max_attempts: int = 72) -> str:
    interval = int(device.get("interval", 5))
    for attempt in range(max_attempts):
        time.sleep(interval)
        poll = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "device_code": device["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }).encode()
        req = urllib.request.Request(
            "https://github.com/login/oauth/access_token",
            data=poll,
            headers={"Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            result = json.loads(exc.read().decode())
        err = result.get("error")
        if err == "authorization_pending":
            print(f"Waiting for authorization... ({attempt + 1}/{max_attempts})", flush=True)
            continue
        if err == "slow_down":
            interval += 5
            continue
        if "access_token" in result:
            return result["access_token"]
        raise SystemExit(f"Unexpected response: {result}")
    raise SystemExit("Timed out waiting for GitHub device authorization")


def main() -> int:
    if TOKEN_PATH.exists() and TOKEN_PATH.read_text().strip():
        print("Token already present")
        return 0
    device = request_device_code()
    DEVICE_PATH.write_text(json.dumps(device))
    print(f"Open: {device.get('verification_uri', 'https://github.com/login/device')}")
    print(f"Enter code: {device['user_code']}")
    token = poll_token(device)
    TOKEN_PATH.write_text(token)
    print("Authorization successful")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
