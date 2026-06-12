"""AssetStream - Claude-powered inventory capture that syncs to HomeBox.

Targets HomeBox v0.25.0 API:
  - auth via POST /v1/users/login (username/password) -> token
  - create  POST /v1/items            {name, description, quantity, locationId}
  - update  PUT  /v1/items/{id}        {id, name, serialNumber, modelNumber, manufacturer, ...}
  - photos  POST /v1/items/{id}/attachments  (multipart: file, name, type, primary)

All secrets live here on the server, never in the browser. The only outbound
internet call is to api.anthropic.com for the vision extraction. HomeBox is
reached over the LAN and never touches the internet.
"""
import base64
import io
import json
import os
import threading
import time

import requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
HOMEBOX_URL = os.environ.get("HOMEBOX_URL", "http://homebox:7745").rstrip("/")
HOMEBOX_USERNAME = os.environ.get("HOMEBOX_USERNAME", "")
HOMEBOX_PASSWORD = os.environ.get("HOMEBOX_PASSWORD", "")
HOMEBOX_LOCATION_ID = os.environ.get("HOMEBOX_LOCATION_ID", "")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

EXTRACTION_PROMPT = (
    "You are an inventory cataloguer. You are given up to two photos of a single physical "
    "item: one front/product view and one close-up of its label or serial plate. "
    "Extract the following and respond with ONLY a JSON object, no markdown, no prose:\n"
    '{"name": str, "manufacturer": str, "model": str, "serial": str, "description": str}\n'
    "Rules: name is a short human label (e.g. 'DeWalt 20V Impact Driver'). manufacturer is the "
    "brand only. model is the model number/name. serial is the serial number exactly as printed "
    "(preserve case and characters). description is one short sentence. If a field is not "
    "determinable from the photos, use an empty string. Do not guess serial numbers."
)

# ---- HomeBox session token cache (login is exchanged for a bearer token) ----
_token = {"value": "", "exp": 0.0}
_token_lock = threading.Lock()


def _login():
    """Log in to HomeBox and cache the token. Returns the token string."""
    r = requests.post(
        f"{HOMEBOX_URL}/api/v1/users/login",
        json={"username": HOMEBOX_USERNAME, "password": HOMEBOX_PASSWORD, "stayLoggedIn": True},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("token", "")
    if not token.startswith("Bearer "):
        token = "Bearer " + token
    with _token_lock:
        _token["value"] = token
        _token["exp"] = time.time() + 6 * 3600  # refresh well before expiry
    return token


def _hb_token():
    with _token_lock:
        if _token["value"] and time.time() < _token["exp"]:
            return _token["value"]
    return _login()


def _hb_headers():
    return {"Authorization": _hb_token()}


def _hb_request(method, path, **kwargs):
    """Call HomeBox, transparently re-logging-in once on a 401."""
    url = f"{HOMEBOX_URL}/api/v1{path}"
    headers = kwargs.pop("headers", {})
    headers.update(_hb_headers())
    resp = requests.request(method, url, headers=headers, **kwargs)
    if resp.status_code == 401:
        _login()
        headers.update(_hb_headers())
        resp = requests.request(method, url, headers=headers, **kwargs)
    return resp


def _anthropic_image_block(data_url):
    header, b64 = data_url.split(",", 1)
    media_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "anthropic_key_set": bool(ANTHROPIC_API_KEY),
        "homebox_creds_set": bool(HOMEBOX_USERNAME and HOMEBOX_PASSWORD),
        "homebox_url": HOMEBOX_URL,
        "model": ANTHROPIC_MODEL,
    })


@app.get("/api/locations")
def locations():
    try:
        r = _hb_request("GET", "/locations", timeout=15)
        r.raise_for_status()
        data = r.json()
        # HomeBox v0.25.0 returns a bare array; some builds wrap it in {"items": [...]}.
        if isinstance(data, dict):
            items = data.get("items", data.get("locations", []))
        else:
            items = data
        out = [{"id": x["id"], "name": x["name"]} for x in items if isinstance(x, dict) and "id" in x]
        return jsonify({"locations": out, "default": HOMEBOX_LOCATION_ID})
    except Exception as e:
        return jsonify({"error": str(e), "locations": []}), 502


@app.post("/api/analyze")
def analyze():
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured"}), 500
    body = request.get_json(force=True)
    images = [img for img in (body.get("frontPhoto"), body.get("serialPhoto")) if img]
    if not images:
        return jsonify({"error": "at least one photo is required"}), 400

    content = [_anthropic_image_block(img) for img in images]
    content.append({"type": "text", "text": EXTRACTION_PROMPT})
    try:
        r = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": ANTHROPIC_MODEL, "max_tokens": 512,
                  "messages": [{"role": "user", "content": content}]},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        fields = json.loads(text)
    except json.JSONDecodeError:
        return jsonify({"error": "Claude did not return valid JSON", "raw": text}), 502
    except requests.HTTPError as e:
        return jsonify({"error": f"Anthropic API error: {e.response.status_code}", "detail": e.response.text}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    clean = {k: str(fields.get(k, "")) for k in ("name", "manufacturer", "model", "serial", "description")}
    return jsonify(clean)


@app.post("/api/save")
def save():
    if not (HOMEBOX_USERNAME and HOMEBOX_PASSWORD):
        return jsonify({"error": "HomeBox username/password not configured"}), 500
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    location_id = body.get("locationId") or HOMEBOX_LOCATION_ID

    # 1) Create the item (name + description + location).
    create_payload = {"name": name, "description": body.get("description", ""), "quantity": 1}
    if location_id:
        create_payload["locationId"] = location_id
    try:
        r = _hb_request("POST", "/items", json=create_payload, timeout=20)
        r.raise_for_status()
        item_id = r.json()["id"]
    except Exception as e:
        detail = getattr(e, "response", None)
        return jsonify({"error": f"create failed: {e}", "detail": detail.text if detail else ""}), 502

    # 2) Update serial / model / manufacturer using read-modify-write.
    # HomeBox's update overwrites EVERY field (including assetId) from the payload,
    # so we must fetch the freshly-created item, overlay our 3 fields, and PUT it
    # back whole. Sending a partial payload would zero out assetId and trip a 500.
    field_error = None
    try:
        cur = _hb_request("GET", f"/items/{item_id}", timeout=15)
        cur.raise_for_status()
        item = cur.json()

        loc = item.get("location") or {}
        location_id = body.get("locationId") or HOMEBOX_LOCATION_ID or loc.get("id", "")

        # Start from the item's own current values, then overlay our extracted fields.
        update_payload = dict(item)
        update_payload["id"] = item_id
        update_payload["serialNumber"] = body.get("serial", "")
        update_payload["modelNumber"] = body.get("model", "")
        update_payload["manufacturer"] = body.get("manufacturer", "")
        if location_id:
            update_payload["locationId"] = location_id
        # Strip read-only / nested objects HomeBox doesn't accept on update.
        for k in ("location", "parent", "attachments", "fields", "imageId",
                  "thumbnailId", "createdAt", "updatedAt"):
            update_payload.pop(k, None)

        ru = _hb_request("PUT", f"/items/{item_id}", json=update_payload, timeout=20)
        if ru.status_code >= 400:
            field_error = f"HTTP {ru.status_code}: {ru.text[:300]}"
        ru.raise_for_status()
    except Exception as e:
        if not field_error:
            field_error = str(e)

    # 3) Upload photos regardless of whether the field update succeeded.
    uploaded = 0
    for key, primary in (("frontPhoto", "true"), ("serialPhoto", "false")):
        data_url = body.get(key)
        if not data_url:
            continue
        try:
            header, b64 = data_url.split(",", 1)
            media_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
            ext = "jpg" if "jpeg" in media_type or "jpg" in media_type else media_type.split("/")[-1]
            raw = base64.b64decode(b64)
            filename = f"{key.replace('Photo','')}.{ext}"
            files = {"file": (filename, io.BytesIO(raw), media_type)}
            form = {"type": "photo", "name": filename, "primary": primary}
            ra = _hb_request("POST", f"/items/{item_id}/attachments", files=files, data=form, timeout=30)
            ra.raise_for_status()
            uploaded += 1
        except Exception:
            pass

    result = {"id": item_id, "name": name, "photos_uploaded": uploaded}
    if field_error:
        result["warning"] = f"serial/model/brand may not have saved: {field_error}"
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8099")))
