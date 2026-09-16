from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request, Response
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

import config as cfg

RP_ID = os.getenv("MOBILE_WEBAUTHN_RP_ID", "ibkr001.tailfc0933.ts.net")
ORIGIN = os.getenv("MOBILE_WEBAUTHN_ORIGIN", f"https://{RP_ID}")
RP_NAME = "TradingBotR1000 Mobile Console"
COOKIE_NAME = "tb_mobile_session"
IDLE_SECONDS = int(os.getenv("MOBILE_SESSION_IDLE_SECONDS", "900"))
ABSOLUTE_SECONDS = int(os.getenv("MOBILE_SESSION_ABSOLUTE_SECONDS", "14400"))
RECENT_AUTH_SECONDS = int(os.getenv("MOBILE_RECENT_AUTH_SECONDS", "300"))
STATE_FILE = Path(cfg.BASE_DIR) / "state" / "mobile_webauthn.json"
LOCK = threading.RLock()
SESSIONS: dict[str, dict] = {}
CHALLENGES: dict[str, dict] = {}


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _load() -> dict:
    if not STATE_FILE.exists():
        return {"user_id": _b64e(secrets.token_bytes(32)), "credentials": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data.get("credentials"), list) or not data.get("user_id"):
            raise ValueError("invalid WebAuthn state")
        return data
    except Exception as exc:
        raise RuntimeError("WebAuthn credential store unavailable; failing closed") from exc


def _save(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE_FILE)


def _state() -> dict:
    data = _load()
    if not STATE_FILE.exists():
        _save(data)
    return data


def _credential_descriptors(data: dict) -> list[PublicKeyCredentialDescriptor]:
    return [PublicKeyCredentialDescriptor(id=_b64d(c["credential_id"])) for c in data["credentials"]]


def credential_count() -> int:
    with LOCK:
        return len(_state()["credentials"])


def _challenge(kind: str, challenge: bytes) -> str:
    token = secrets.token_urlsafe(32)
    CHALLENGES[token] = {"kind": kind, "challenge": challenge, "created": time.time()}
    return token


def _consume(token: str, kind: str) -> bytes:
    item = CHALLENGES.pop(token, None)
    if not item or item["kind"] != kind or time.time() - item["created"] > 180:
        raise HTTPException(status_code=401, detail="Authentication challenge expired or invalid")
    return item["challenge"]


def registration_options() -> dict:
    with LOCK:
        data = _state()
        # Bootstrap is permitted only while no passkey exists. Additional enrollment
        # will later require an authenticated session.
        if data["credentials"]:
            raise HTTPException(status_code=403, detail="Passkey already enrolled")
        opts = generate_registration_options(
            rp_id=RP_ID,
            rp_name=RP_NAME,
            user_name="gio",
            user_display_name="TradingBotR1000 Operator",
            user_id=_b64d(data["user_id"]),
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=_credential_descriptors(data),
        )
        return {"challenge_id": _challenge("register", opts.challenge), "options": json.loads(options_to_json(opts))}


def finish_registration(challenge_id: str, credential: dict) -> None:
    challenge = _consume(challenge_id, "register")
    with LOCK:
        data = _state()
        if data["credentials"]:
            raise HTTPException(status_code=403, detail="Passkey already enrolled")
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=RP_ID,
                expected_origin=ORIGIN,
                require_user_verification=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Passkey registration verification failed") from exc
        data["credentials"].append({
            "credential_id": _b64e(verified.credential_id),
            "public_key": _b64e(verified.credential_public_key),
            "sign_count": verified.sign_count,
            "created_at": int(time.time()),
        })
        _save(data)


def authentication_options(purpose: str = "login") -> dict:
    with LOCK:
        data = _state()
        if not data["credentials"]:
            raise HTTPException(status_code=428, detail="No passkey enrolled")
        opts = generate_authentication_options(
            rp_id=RP_ID,
            allow_credentials=_credential_descriptors(data),
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return {"challenge_id": _challenge(f"auth:{purpose}", opts.challenge), "options": json.loads(options_to_json(opts))}


def finish_authentication(challenge_id: str, credential: dict, purpose: str = "login") -> str:
    challenge = _consume(challenge_id, f"auth:{purpose}")
    with LOCK:
        data = _state()
        raw_id = credential.get("rawId") or credential.get("id")
        match = next((c for c in data["credentials"] if c["credential_id"] == raw_id), None)
        if match is None:
            raise HTTPException(status_code=401, detail="Unknown passkey")
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=RP_ID,
                expected_origin=ORIGIN,
                credential_public_key=_b64d(match["public_key"]),
                credential_current_sign_count=int(match["sign_count"]),
                require_user_verification=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Passkey authentication failed") from exc
        match["sign_count"] = verified.new_sign_count
        _save(data)
        return raw_id


def new_session(response: Response) -> str:
    sid = secrets.token_urlsafe(48)
    now = time.time()
    with LOCK:
        SESSIONS[sid] = {"created": now, "last_activity": now, "recent_auth": now}
    response.set_cookie(COOKIE_NAME, sid, secure=True, httponly=True, samesite="strict", path="/")
    return sid


def _session(request: Request) -> tuple[str, dict]:
    sid = request.cookies.get(COOKIE_NAME)
    now = time.time()
    with LOCK:
        session = SESSIONS.get(sid or "")
        if not session or now - session["created"] > ABSOLUTE_SECONDS or now - session["last_activity"] > IDLE_SECONDS:
            if sid:
                SESSIONS.pop(sid, None)
            raise HTTPException(status_code=401, detail="Authentication required")
        return sid, session


def require_session(request: Request) -> dict:
    return _session(request)[1]


def record_physical_activity(request: Request) -> None:
    sid, session = _session(request)
    with LOCK:
        session["last_activity"] = time.time()
        SESSIONS[sid] = session


def mark_recent_auth(request: Request) -> None:
    sid, session = _session(request)
    with LOCK:
        session["recent_auth"] = time.time()
        SESSIONS[sid] = session


def require_recent_auth(request: Request) -> None:
    session = require_session(request)
    if time.time() - session["recent_auth"] > RECENT_AUTH_SECONDS:
        raise HTTPException(status_code=401, detail="Recent passkey authentication required")


def logout(request: Request, response: Response) -> None:
    sid = request.cookies.get(COOKIE_NAME)
    with LOCK:
        if sid:
            SESSIONS.pop(sid, None)
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
