"""Flask-based web interface for managing users and enrolling new cards."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request

from app.services.auth_service import AuthenticationService, Identifier, User
from app.services.emv_service import EMVCardService
from app.services.reader_control import ReaderControl

_DEFAULT_DB_PATH = os.getenv("USBUTLER_USERS_DB", "users.json")


def _is_web_reader_enabled() -> bool:
    value = os.getenv("USBUTLER_WEB_ENABLE_READER", "").strip().lower()
    return value in {"1", "true", "yes", "on"}

# Shared service instances reused across requests
_auth_service = AuthenticationService(_DEFAULT_DB_PATH)
_emv_service = EMVCardService() if _is_web_reader_enabled() else None
_scan_lock = threading.Lock()
_last_scan: Dict[str, Any] | None = None
_reader_control: ReaderControl | None = None
_ALLOWED_METADATA_KEYS = {
    "issuer",
    "expiry",
    "card_type",
    "tag_type",
    "atr_hex",
    "atr_hex_compact",
    "atr_summary",
}


def _filter_metadata(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    filtered: Dict[str, Any] = {}
    for key in _ALLOWED_METADATA_KEYS:
        if key in value:
            item = value[key]
            if item is None:
                continue
            if key == "atr_summary" and isinstance(item, list):
                filtered[key] = [str(entry) for entry in item[:10]]
            else:
                if isinstance(item, (str, int, float, bool)):
                    filtered[key] = item
                elif isinstance(item, (bytes, bytearray)):
                    filtered[key] = item.hex()
                else:
                    continue
    return filtered


def _format_expiry(expiry: Any) -> str | None:
    if expiry is None:
        return None
    digits = "".join(ch for ch in str(expiry) if ch.isdigit())
    if len(digits) == 4:
        year = digits[:2]
        month = digits[2:4]
        return f"{month}/{year}"
    return str(expiry)


def _present_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    if not metadata:
        return {}
    view = {key: value for key, value in metadata.items()}
    expiry = view.get("expiry")
    formatted = _format_expiry(expiry)
    if expiry and formatted and formatted != expiry:
        view.setdefault("expiry_formatted", formatted)
    return view


def _build_scan_metadata(scan: Any) -> Dict[str, Any]:
    metadata = {
        "issuer": getattr(scan, "issuer", None),
        "expiry": getattr(scan, "expiry", None),
        "card_type": getattr(scan, "card_type", None),
        "tag_type": getattr(scan, "tag_type", None),
        "atr_hex": getattr(scan, "atr_hex", None),
        "atr_hex_compact": getattr(scan, "atr_hex_compact", None),
        "atr_summary": getattr(scan, "atr_summary", None),
    }
    return _filter_metadata(metadata)


def _serialize_identifier(identifier: Identifier) -> Dict[str, Any]:
    metadata = _present_metadata(identifier.metadata)
    return {
        "value": identifier.value,
        "type": identifier.type,
        "primary": identifier.primary,
        "masked": identifier.mask(),
        "metadata": metadata,
    }


def _serialize_user(user: User) -> Dict[str, Any]:
    identifiers = [_serialize_identifier(identifier) for identifier in user.identifiers]
    primary = user.primary_identifier()
    return {
        "user_id": user.user_id,
        "name": user.name,
        "access_level": user.access_level,
        "active": user.active,
        "identifiers": identifiers,
        "primary_identifier": _serialize_identifier(primary) if primary else None,
    }


def _build_stats(users: List[User]) -> Dict[str, Any]:
    total = len(users)
    active = sum(1 for user in users if user.active)
    return {"total": total, "active": active, "inactive": total - active}


def _get_reader_control() -> ReaderControl:
    global _reader_control
    if _reader_control is None:
        _reader_control = ReaderControl()
    return _reader_control


def set_reader_control(control: ReaderControl | None) -> None:
    global _reader_control
    _reader_control = control


def reset_services(user_db_path: str | None = None) -> None:
    """Reset service instances (intended for tests)."""

    global _auth_service, _emv_service, _last_scan, _reader_control
    db_path = user_db_path or os.getenv("USBUTLER_USERS_DB", "users.json")
    _auth_service = AuthenticationService(db_path)
    _emv_service = EMVCardService() if _is_web_reader_enabled() else None
    _last_scan = None
    _reader_control = None


def _serialize_reader_state() -> Dict[str, Any]:
    state = _get_reader_control().get_state()
    owner = state.get("owner") or "door"
    updated_at = state.get("updated_at")
    return {
        "owner": owner,
        "owned_by_web": owner == "web",
        "owned_by_door": owner == "door",
        "updated_at": updated_at,
    }


def create_app(reader_control: ReaderControl | None = None) -> Flask:
    if reader_control is not None:
        set_reader_control(reader_control)
    app = Flask(__name__, template_folder="templates", static_folder="static")

    @app.route("/")
    def index() -> str:
        users = list(_auth_service.list_users().values())
        serialized = [_serialize_user(user) for user in users]
        serialized.sort(key=lambda item: item["name"].lower())
        stats = _build_stats(users)
        return render_template(
            "index.html",
            users=serialized,
            stats=stats,
            last_scan=_last_scan,
            reader_enabled=_is_web_reader_enabled(),
            reader_state=_serialize_reader_state(),
        )

    @app.get("/api/users")
    def api_list_users():
        users = list(_auth_service.list_users().values())
        serialized = [_serialize_user(user) for user in users]
        serialized.sort(key=lambda item: item["name"].lower())
        return jsonify(
            {
                "success": True,
                "users": serialized,
                "stats": _build_stats(users),
                "last_scan": _last_scan,
                "reader_enabled": _is_web_reader_enabled(),
                "reader_state": _serialize_reader_state(),
            }
        )

    @app.post("/api/scan-card")
    def api_scan_card():
        payload = request.get_json(silent=True) or {}
        timeout = payload.get("timeout", 15)

        if not _is_web_reader_enabled() or _emv_service is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "reader_disabled",
                        "message": "Card reader access is disabled for this server.",
                    }
                ),
                503,
            )
        try:
            timeout_value = float(timeout)
            if timeout_value <= 0:
                timeout_value = 15.0
        except (TypeError, ValueError):
            timeout_value = 15.0

        reader_control = _get_reader_control()
        if reader_control.get_owner() != "web":
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "reader_locked",
                        "message": "Reader is currently reserved by another service.",
                    }
                ),
                423,
            )

        if not _scan_lock.acquire(blocking=False):
            return (
                jsonify({"success": False, "error": "reader_busy", "message": "Reader is busy with another scan."}),
                409,
            )

        try:
            if not _emv_service.wait_for_card(timeout=int(timeout_value)):
                return jsonify({"success": False, "error": "timeout", "message": "No card detected."}), 200

            try:
                scan = _emv_service.read_card_data()
            finally:
                _emv_service.disconnect()

            identifier = scan.primary_identifier()
            if not identifier:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "no_identifier",
                            "message": "Could not read a stable identifier from the card.",
                            "tag_type": scan.tag_type,
                            "card_type": scan.card_type,
                            "uid": scan.uid,
                            "tokenized": scan.tokenized,
                        }
                    ),
                    200,
                )

            response = {
                "success": True,
                "identifier": identifier,
                "identifier_type": scan.primary_identifier_type(),
                "tag_type": scan.tag_type,
                "card_type": scan.card_type,
                "uid": scan.uid,
                "pan": scan.pan,
                "tokenized": scan.tokenized,
                "masked_identifier": identifier if len(identifier) <= 4 else f"****{identifier[-4:]}",
                "timestamp": time.time(),
            }
            metadata = _build_scan_metadata(scan)
            response["metadata"] = _present_metadata(metadata)
            response["issuer"] = metadata.get("issuer")
            response["expiry"] = metadata.get("expiry")
            response["expiry_formatted"] = response["metadata"].get("expiry_formatted")
            existing_user = _auth_service.find_user_by_identifier(identifier)
            if existing_user:
                response["already_registered"] = True
                response["existing_user"] = _serialize_user(existing_user)
            else:
                response["already_registered"] = False

            global _last_scan
            _last_scan = {
                "identifier": identifier,
                "masked_identifier": response["masked_identifier"],
                "identifier_type": response["identifier_type"],
                "timestamp": response["timestamp"],
                "already_registered": response["already_registered"],
                "existing_user_name": existing_user.name if existing_user else None,
                "existing_user_id": existing_user.user_id if existing_user else None,
                "metadata": response["metadata"],
            }
            return jsonify(response), 200
        except Exception as exc:  # pragma: no cover - defensive fallback
            return (
                jsonify({"success": False, "error": "internal_error", "message": str(exc)}),
                500,
            )
        finally:
            if _scan_lock.locked():
                _scan_lock.release()

    @app.get("/api/reader")
    def api_get_reader_state():
        return jsonify({"success": True, "state": _serialize_reader_state(), "reader_enabled": _is_web_reader_enabled()})

    @app.post("/api/reader/claim")
    def api_claim_reader():
        control = _get_reader_control()
        state = control.get_state()
        owner = state.get("owner")
        if owner == "web":
            return jsonify({"success": True, "state": _serialize_reader_state(), "already_owned": True}), 200
        new_state = control.set_owner("web", {"previous_owner": owner})
        return jsonify({"success": True, "state": _serialize_reader_state(), "reader_enabled": _is_web_reader_enabled(), "updated": new_state}), 200

    @app.post("/api/reader/release")
    def api_release_reader():
        control = _get_reader_control()
        state = control.get_state()
        owner = state.get("owner")
        if owner == "door":
            return jsonify({"success": True, "state": _serialize_reader_state(), "already_released": True}), 200
        new_state = control.reset_to_default()
        return jsonify({"success": True, "state": _serialize_reader_state(), "reader_enabled": _is_web_reader_enabled(), "updated": new_state}), 200

    @app.post("/api/users")
    def api_add_user():
        payload = request.get_json(force=True)
        identifier = (payload.get("identifier") or "").strip()
        identifier_type = (payload.get("identifier_type") or "UID").strip() or "UID"
        access_level = (payload.get("access_level") or "user").strip().lower()
        user_id = (payload.get("user_id") or "").strip() or None
        make_primary = bool(payload.get("make_primary", False))
        name = (payload.get("name") or "").strip()
        metadata = _filter_metadata(payload.get("metadata"))

        if not identifier:
            return jsonify({"success": False, "error": "missing_identifier"}), 400

        if _auth_service.identifier_exists(identifier):
            existing_user = _auth_service.find_user_by_identifier(identifier)
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "user_exists",
                        "existing_user": _serialize_user(existing_user) if existing_user else None,
                    }
                ),
                409,
            )

        if user_id:
            user = _auth_service.get_user(user_id)
            if not user:
                return jsonify({"success": False, "error": "not_found"}), 404
            if not _auth_service.add_identifier_to_user(
                user_id,
                identifier,
                identifier_type,
                make_primary,
                metadata if metadata else None,
            ):
                return jsonify({"success": False, "error": "user_exists"}), 409
            refreshed = _auth_service.get_user(user_id)
            return jsonify({"success": True, "user": _serialize_user(refreshed)}), 200

        if not name:
            return jsonify({"success": False, "error": "missing_name"}), 400
        if access_level not in {"user", "admin"}:
            return jsonify({"success": False, "error": "invalid_access_level"}), 400

        new_user = _auth_service.create_user(
            identifier_value=identifier,
            name=name,
            access_level=access_level,
            identifier_type=identifier_type,
            metadata=metadata if metadata else None,
        )
        return jsonify({"success": True, "user": _serialize_user(new_user)}), 201

    @app.post("/api/users/<user_id>/toggle")
    def api_toggle_user(user_id: str):
        user = _auth_service.get_user(user_id)
        if not user:
            return jsonify({"success": False, "error": "not_found"}), 404
        _auth_service.set_user_active(user_id, not user.active)
        refreshed = _auth_service.get_user(user_id)
        return jsonify({"success": True, "user": _serialize_user(refreshed)})

    @app.post("/api/users/<user_id>/pause")
    def api_pause_user(user_id: str):
        user = _auth_service.get_user(user_id)
        if not user:
            return jsonify({"success": False, "error": "not_found"}), 404
        if user.active:
            _auth_service.set_user_active(user_id, False)
        refreshed = _auth_service.get_user(user_id)
        return jsonify({"success": True, "user": _serialize_user(refreshed)})

    @app.post("/api/users/<user_id>/resume")
    def api_resume_user(user_id: str):
        user = _auth_service.get_user(user_id)
        if not user:
            return jsonify({"success": False, "error": "not_found"}), 404
        if not user.active:
            _auth_service.set_user_active(user_id, True)
        refreshed = _auth_service.get_user(user_id)
        return jsonify({"success": True, "user": _serialize_user(refreshed)})

    @app.delete("/api/users/<user_id>")
    def api_delete_user(user_id: str):
        if not _auth_service.delete_user(user_id):
            return jsonify({"success": False, "error": "not_found"}), 404
        return jsonify({"success": True})

    @app.get("/api/users/by-identifier/<path:identifier_value>")
    def api_get_user_by_identifier(identifier_value: str):
        value = identifier_value.strip()
        if not value:
            return jsonify({"success": False, "error": "missing_identifier"}), 400
        user = _auth_service.find_user_by_identifier(value)
        if not user:
            return jsonify({"success": False, "error": "not_found"}), 404
        return jsonify({"success": True, "user": _serialize_user(user)})

    @app.delete("/api/users/<user_id>/identifiers/<identifier_value>")
    def api_remove_identifier(user_id: str, identifier_value: str):
        if not _auth_service.remove_identifier_from_user(user_id, identifier_value):
            return jsonify({"success": False, "error": "not_found"}), 404
        user = _auth_service.get_user(user_id)
        if not user:
            return jsonify({"success": True, "user_removed": True})
        return jsonify({"success": True, "user": _serialize_user(user)})

    @app.post("/api/users/<user_id>/identifiers/<identifier_value>/primary")
    def api_set_primary(user_id: str, identifier_value: str):
        if not _auth_service.set_primary_identifier(user_id, identifier_value):
            return jsonify({"success": False, "error": "not_found"}), 404
        user = _auth_service.get_user(user_id)
        return jsonify({"success": True, "user": _serialize_user(user)})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
