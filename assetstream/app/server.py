"""AssetStream — Claude-powered inventory capture that syncs to HomeBox.

Flow:
  1. Browser captures two photos (front + serial) via native camera file input.
  2. POST /api/analyze  -> backend calls Claude vision, returns {name, manufacturer, model, serial, description}.
  3. User confirms/edits on screen.
  4. POST /api/save     -> backend creates a HomeBox entity, sets model/serial/manufacturer,
                          and uploads both photos as attachments.

All secrets (Anthropic key, HomeBox token) live here on the server, never in the browser.
The only outbound internet call is to api.anthropic.com for the vision step.
HomeBox is reached over the LAN and never touches the internet.
"""
import base64
import io
import json
import os

import requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

# ---- Configuration (injected by the HA add-on as env vars) ----
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
HOMEBOX_URL = os.environ.get("HOMEBOX_URL", "http://homebox:7745").rstrip("/")
HOMEBOX_TOKEN = os.environ.get("HOMEBOX_TOKEN", "")
HOMEBOX_LOCATION_ID = os.environ.get("HOMEBOX_LOCATION_ID", "")  # optional default location

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


def _anthropic_image_block(data_url: str):
    """Turn a data: URL from the browser into an Anthropic image content block."""
    header, b64 = data_url.split(",", 1)
    media_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": b64},
    }


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "anthropic_key_set": bool(ANTHROPIC_API_KEY),
            "homebox_token_set": bool(HOMEBOX_TOKEN),
            "homebox_url": HOMEBOX_URL,
            "model": ANTHROPIC_MODEL,
        }
    )


@app.get("/api/locations")
def locations():
    """List HomeBox locations so the UI can offer a destination dropdown."""
    try:
        r = requests.get(
            f"{HOMEBOX_URL}/api/v1/locations",
            headers={"Authorization": HOMEBOX_TOKEN},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        out = [{"id": x["id"], "name": x["name"]} for x in items]
        return jsonify({"locations": out, "default": HOMEBOX_LOCATION_ID})
    except Exception as e:
        return jsonify({"error": str(e), "locations": []}), 502


@app.post("/api/analyze")
def analyze():
    """Send the two photos to Claude and return structured fields."""
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured"}), 500

    body = request.get_json(force=True)
    images = [img for img in (body.get("front"), body.get("serial")) if img]
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
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        ).strip()
        # Strip accidental code fences, then parse.
        text = text.replace("```json", "").replace("```", "").strip()
        fields = json.loads(text)
    except json.JSONDecodeError:
        return jsonify({"error": "Claude did not return valid JSON", "raw": text}), 502
    except requests.HTTPError as e:
        return jsonify({"error": f"Anthropic API error: {e.response.status_code}", "detail": e.response.text}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    # Normalise keys we expect.
    clean = {k: str(fields.get(k, "")) for k in ("name", "manufacturer", "model", "serial", "description")}
    return jsonify(clean)


def _hb_headers():
    return {"Authorization": HOMEBOX_TOKEN}


@app.post("/api/save")
def save():
    """Create the HomeBox item, set serial/model/manufacturer, attach both photos."""
    if not HOMEBOX_TOKEN:
        return jsonify({"error": "HOMEBOX_TOKEN is not configured"}), 500

    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    location_id = body.get("locationId") or HOMEBOX_LOCATION_ID

    # 1) Create the entity (item).
    create_payload = {
        "name": name,
        "description": body.get("description", ""),
        "quantity": 1,
    }
    if location_id:
        # HomeBox treats a location as a parent entity.
        create_payload["parentId"] = location_id

    try:
        r = requests.post(
            f"{HOMEBOX_URL}/api/v1/entities",
            headers=_hb_headers(),
            json=create_payload,
            timeout=20,
        )
        r.raise_for_status()
        entity = r.json()
        entity_id = entity["id"]
    except Exception as e:
        detail = getattr(e, "response", None)
        return jsonify({"error": f"create failed: {e}", "detail": detail.text if detail else ""}), 502

    # 2) Patch the structured fields (serial / model / manufacturer) via update.
    try:
        update_payload = {
            "id": entity_id,
            "name": name,
            "description": body.get("description", ""),
            "quantity": 1,
            "serialNumber": body.get("serial", ""),
            "modelNumber": body.get("model", ""),
            "manufacturer": body.get("manufacturer", ""),
            "insured": False,
        }
        if location_id:
            update_payload["parentId"] = location_id
        ru = requests.put(
            f"{HOMEBOX_URL}/api/v1/entities/{entity_id}",
            headers=_hb_headers(),
            json=update_payload,
            timeout=20,
        )
        ru.raise_for_status()
    except Exception as e:
        # Item exists but fields didn't fully set — report, don't crash.
        return jsonify({"warning": f"item created but fields update failed: {e}", "id": entity_id}), 207

    # 3) Upload photos as attachments.
    uploaded = 0
    for key, primary in (("front", "true"), ("serial", "false")):
        data_url = body.get(key)
        if not data_url:
            continue
        try:
            header, b64 = data_url.split(",", 1)
            media_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
            ext = "jpg" if "jpeg" in media_type or "jpg" in media_type else media_type.split("/")[-1]
            raw = base64.b64decode(b64)
            filename = f"{key}.{ext}"
            files = {"file": (filename, io.BytesIO(raw), media_type)}
            form = {"type": "photo", "name": filename, "primary": primary}
            ra = requests.post(
                f"{HOMEBOX_URL}/api/v1/entities/{entity_id}/attachments",
                headers=_hb_headers(),
                files=files,
                data=form,
                timeout=30,
            )
            ra.raise_for_status()
            uploaded += 1
        except Exception:
            pass  # one failed photo shouldn't sink the whole save

    return jsonify({"id": entity_id, "name": name, "photos_uploaded": uploaded})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8099")))
