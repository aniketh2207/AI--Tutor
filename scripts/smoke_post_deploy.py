#!/usr/bin/env python3
"""Post-deploy ownership smoke test against a live Cloud Run / compose URL.

Usage:
  python scripts/smoke_post_deploy.py --base-url https://SERVICE.run.app

Exits 0 on success, non-zero on failure (CI uses this to trigger rollback).
"""

from __future__ import annotations

import argparse
import io
import sys
import uuid

import httpx


def _pdf_bytes() -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 40), "smoke chapter secret text for ownership check")
    data = doc.tobytes()
    doc.close()
    return data


def run_smoke(base_url: str, timeout: float = 60.0) -> None:
    root = base_url.rstrip("/")
    suffix = uuid.uuid4().hex[:8]
    email_a = f"smoke_a_{suffix}@example.com"
    email_b = f"smoke_b_{suffix}@example.com"
    password = "SmokeTest123!"

    with httpx.Client(base_url=root, timeout=timeout, follow_redirects=True) as client:
        live = client.get("/livez")
        live.raise_for_status()

        reg_a = client.post(
            "/api/auth/register",
            json={"email": email_a, "password": password, "full_name": "Smoke A"},
        )
        assert reg_a.status_code == 201, reg_a.text
        token_a = reg_a.json()["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        login_a = client.post(
            "/api/auth/login",
            json={"email": email_a, "password": password},
        )
        assert login_a.status_code == 200, login_a.text

        upload = client.post(
            "/api/rag/upload",
            headers=headers_a,
            files={"file": ("smoke.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={"title": "Smoke Chapter"},
        )
        assert upload.status_code == 201, upload.text
        chapter_id = upload.json()["chapter"]["id"]

        turn = client.post(
            "/api/tutor/turn",
            headers=headers_a,
            json={
                "track": "RAG",
                "chapter_id": chapter_id,
                "student_input": "What is this chapter about?",
                "chat_mode": True,
            },
        )
        assert turn.status_code == 200, turn.text

        reg_b = client.post(
            "/api/auth/register",
            json={"email": email_b, "password": password, "full_name": "Smoke B"},
        )
        assert reg_b.status_code == 201, reg_b.text
        headers_b = {"Authorization": f"Bearer {reg_b.json()['access_token']}"}

        steal = client.get(
            f"/api/rag/chapters/{chapter_id}/chunks",
            headers=headers_b,
        )
        assert steal.status_code == 404, steal.text

    print("SMOKE_OK ownership and turn path verified")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Deployed service origin")
    args = parser.parse_args()
    try:
        run_smoke(args.base_url)
    except Exception as exc:  # noqa: BLE001 - CI needs any failure → non-zero
        print(f"SMOKE_FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
