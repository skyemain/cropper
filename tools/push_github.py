#!/usr/bin/env python3
"""Push the current repository to GitHub using the Git Data API.

Used when `git push` cannot authenticate in the cloud agent environment.
Requires GITHUB_TOKEN with repo scope for the target repository.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ.get("GITHUB_REPO", "skyemain/cropper")
BRANCH = os.environ.get("GITHUB_BRANCH", "main")
ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "build", "dist",
    "installer_output", ".pytest_cache", "terminals",
}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def api(method: str, path: str, data: dict | None = None) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set")
    url = f"https://api.github.com{path}"
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "id-photo-auto-cropper-push",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"GitHub API {method} {path} failed ({exc.code}): {detail}") from exc


def collect_files() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.name in SKIP_FILES:
            continue
        files.append((rel.as_posix(), path.read_bytes()))
    return files


def main() -> int:
    print(f"Collecting files from {ROOT} ...")
    files = collect_files()
    print(f"Uploading {len(files)} files to {REPO} ({BRANCH}) ...")

    tree_items = []
    for idx, (name, blob) in enumerate(files, start=1):
        created = api("POST", f"/repos/{REPO}/git/blobs", {
            "content": base64.b64encode(blob).decode(),
            "encoding": "base64",
        })
        tree_items.append({"path": name, "mode": "100644", "type": "blob",
                           "sha": created["sha"]})
        if idx % 25 == 0 or idx == len(files):
            print(f"  blobs {idx}/{len(files)}")

    tree = api("POST", f"/repos/{REPO}/git/trees", {"tree": tree_items})
    head = None
    try:
        ref = api("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
        head = ref["object"]["sha"]
    except SystemExit as exc:
        if "404" not in str(exc):
            raise

    commit = api("POST", f"/repos/{REPO}/git/commits", {
        "message": "Initial import: ID Photo Auto Cropper",
        "tree": tree["sha"],
        **({"parents": [head]} if head else {}),
    })

    if head:
        api("PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}", {"sha": commit["sha"]})
    else:
        api("POST", f"/repos/{REPO}/git/refs", {
            "ref": f"refs/heads/{BRANCH}", "sha": commit["sha"],
        })

    print(f"Done: https://github.com/{REPO}/tree/{BRANCH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
