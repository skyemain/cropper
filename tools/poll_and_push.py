#!/usr/bin/env python3
"""Poll saved device session in /tmp/gh_device_active.json and push to GitHub."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT_ID = "178c6fc778ccc68e1d6a"
DEVICE_PATH = Path("/tmp/gh_device_active.json")
TOKEN_PATH = Path("/tmp/github_token.txt")
STATUS_PATH = Path("/tmp/push-status.txt")
REPO = "skyemain/cropper"


def main() -> int:
    device = json.loads(DEVICE_PATH.read_text())
    interval = int(device.get("interval", 5))
    token = None
    for attempt in range(72):
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
        if result.get("error") == "authorization_pending":
            continue
        if "access_token" in result:
            token = result["access_token"]
            TOKEN_PATH.write_text(token)
            break
        STATUS_PATH.write_text("PUSH_FAIL")
        return 1

    if not token:
        STATUS_PATH.write_text("PUSH_FAIL")
        return 1

    remote = f"https://x-access-token:{token}@github.com/{REPO}.git"
    proc = subprocess.run(["git", "push", remote, "main"], cwd="/workspace")
    STATUS_PATH.write_text("PUSH_OK" if proc.returncode == 0 else "PUSH_FAIL")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
