#!/usr/bin/env python3
"""AutoBrain backup agent.

Connects to an AutoBrain instance with its admin API key, downloads a
full-database snapshot, and hands the file to autobrain-backup.

Configuration (env):
    AUTOBRAIN_URL         base URL of the AutoBrain instance (required)
    AUTOBRAIN_API_KEY     admin API key, sent as X-Admin-API-Key (required)
    BACKUP_ENDPOINT       path, default /admin-api/backup
    OUT_DIR               where to keep local copies, default ./backups
    KEEP                  max local copies to retain, default 30
    TARGET_URL            autobrain-backup ingest URL; upload if set (optional)
    TARGET_KEY            API key for TARGET_URL if it needs one (optional)
    TARGET_INSTANCE       instance id to push to (appends ?instance= to TARGET_URL)
    CA_BUNDLE             path to custom CA bundle for TLS (optional)

Run once:  agent.py --once
Run loop (hourly):  agent.py            # sleeps 1h between attempts
"""

import argparse
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_NAME = "autobrain"
KIND_BACKUP = "backup"
HEADER_KEY = "X-Admin-API-Key"


class AgentError(Exception):
    pass


def _headers(api_key, accept="application/json"):
    h = {"Accept": accept, "User-Agent": "autobrain-backup-agent/1.0"}
    if api_key:
        h[HEADER_KEY] = api_key
    return h


def _opener(ca_bundle):
    if ca_bundle:
        ctx = ssl.create_default_context(cafile=ca_bundle)
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener()


def fetch_backup(url, api_key, opener):
    """Download the backup snapshot; returns (bytes, media_type, disposition)."""
    try:
        with opener.open(urllib.request.Request(url, headers=_headers(api_key)), timeout=120) as r:
            body = r.read()
            return body, r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", "")
    except urllib.error.HTTPError as e:
        raise AgentError(f"server returned HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise AgentError(f"cannot reach {url}: {e.reason}") from e


def validate(body):
    """Ensure the payload really is an AutoBrain backup; returns parsed dict."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise AgentError("payload is not valid JSON") from e
    if not isinstance(data, dict):
        raise AgentError("payload is not a JSON object")
    if data.get("app") != APP_NAME:
        raise AgentError(f"not an {APP_NAME} backup: app={data.get('app')!r}")
    if data.get("kind") != KIND_BACKUP:
        raise AgentError(f"not a full backup: kind={data.get('kind')!r}")
    if not isinstance(data.get("data"), dict):
        raise AgentError("backup missing data section")
    return data


def _stamp(created_at):
    if created_at:
        return str(created_at).replace(":", "").replace("-", "")[:15]
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def filename_for(data):
    return f"{APP_NAME}-backup-{_stamp(data.get('created_at'))}.json"


def save(body, out_dir, keep):
    out_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".backup-", suffix=".json", dir=out_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        path = out_dir / filename_for(validate(body))
        shutil.move(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    for old in sorted(out_dir.glob(f"{APP_NAME}-backup-*.json"))[:-keep] if keep else []:
        old.unlink()
    return path


def upload(path, target_url, target_key, opener):
    with path.open("rb") as f:
        data = f.read()
    req = urllib.request.Request(
        target_url,
        data=data,
        headers=_headers(target_key, accept="*/*"),
        method="POST",
    )
    try:
        with opener.open(req, timeout=300) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        raise AgentError(f"target {target_url} returned HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise AgentError(f"cannot reach target {target_url}: {e.reason}") from e


def main(argv=None):
    p = argparse.ArgumentParser(description="AutoBrain backup agent")
    p.add_argument("--once", action="store_true", help="run a single backup and exit")
    p.add_argument("--interval", type=int, default=3600, help="seconds between runs (default 3600)")
    args = p.parse_args(argv)

    url = os.environ.get("AUTOBRAIN_URL", "").rstrip("/")
    api_key = os.environ.get("AUTOBRAIN_API_KEY", "")
    if not url:
        p.error("AUTOBRAIN_URL is required")
    if not api_key:
        p.error("AUTOBRAIN_API_KEY is required")

    endpoint = os.environ.get("BACKUP_ENDPOINT", "/admin-api/backup")
    backup_url = url + endpoint
    out_dir = Path(os.environ.get("OUT_DIR", "backups"))
    keep = int(os.environ.get("KEEP", "30") or "30")
    target_url = os.environ.get("TARGET_URL", "").rstrip("/")
    target_key = os.environ.get("TARGET_KEY", "")
    target_instance = os.environ.get("TARGET_INSTANCE", "").strip()
    if target_instance:
        sep = "&" if "?" in target_url else "?"
        target_url += f"{sep}instance={target_instance}"
    opener = _opener(os.environ.get("CA_BUNDLE", ""))

    while True:
        try:
            body, _, _ = fetch_backup(backup_url, api_key, opener)
            validate(body)
            path = save(body, out_dir, keep)
            status = "saved"
            if target_url:
                code = upload(path, target_url, target_key, opener)
                status = f"saved + uploaded (HTTP {code})"
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} backup OK -> {path} ({status})", flush=True)
        except AgentError as e:
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} FAIL: {e}", flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
