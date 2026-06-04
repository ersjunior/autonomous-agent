"""Valida upload de avatar (rodar no container backend)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

from app.core.config import settings

BASE = "http://127.0.0.1:8000/api/v1"
IMAGE = Path("/tmp/avatar-test.png")


def main() -> int:
    if not IMAGE.is_file():
        print("FAIL: /tmp/avatar-test.png ausente (docker cp antes)")
        return 1

    r = httpx.post(
        f"{BASE}/auth/login",
        json={"email": "admin@admin.com", "password": "admin"},
        timeout=30.0,
    )
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    put = httpx.put(
        f"{BASE}/settings",
        headers=h,
        json={"settings": {"avatar_default_image": "hacker.png"}},
        timeout=30.0,
    )
    detail = put.json().get("detail", "")
    reg_ok = put.status_code == 400 and (
        "read-only" in detail.lower() or "Unknown" in detail
    )
    print(f"PUT regressão: {put.status_code} — {detail}")

    with IMAGE.open("rb") as f:
        up = httpx.post(
            f"{BASE}/settings/avatar-image",
            headers=h,
            files={"file": ("avatar-test.png", f, "image/png")},
            timeout=60.0,
        )
    print(f"POST avatar-image: {up.status_code} — {up.json()}")
    up_ok = up.status_code == 201
    expected_name = up.json().get("filename", "avatar.png") if up_ok else ""

    info = httpx.get(f"{BASE}/settings/avatar-image/info", headers=h).json()
    print(f"GET info: {info}")

    preview = httpx.get(f"{BASE}/settings/avatar-image/preview", headers=h)
    print(f"GET preview: {preview.status_code}, {len(preview.content)} bytes")

    sg = httpx.get(f"{BASE}/settings", headers=h).json()
    field = next(
        (
            f
            for c in sg.get("categories", [])
            for f in c.get("fields", [])
            if f.get("key") == "avatar_default_image"
        ),
        None,
    )
    print(f"read_only={field.get('read_only') if field else None}")
    print(f"runtime={sg.get('runtime', {}).get('avatar_default_image')}")
    print(f"singleton settings.avatar_default_image={settings.avatar_default_image}")

    root = Path(settings.avatars_root)
    listing = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    print(f"ls {root}: {listing}")

    ok = (
        reg_ok
        and up_ok
        and field
        and field.get("read_only") is True
        and settings.avatar_default_image == expected_name
        and (root / expected_name).is_file()
        and preview.status_code == 200
        and info.get("filename") == expected_name
    )
    print("RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
