import os
import json
import qrcode
from collections import Counter, defaultdict
from io import BytesIO
from flask import Flask, render_template, send_from_directory, send_file, request, jsonify, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# ----- Конфиг базы -----
base_dir = os.path.dirname(os.path.abspath(__file__))
db_file = os.path.join(base_dir, "instance", "vines.db")

if os.getenv("VERCEL"):
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///file:{db_file}?mode=ro&uri=true"
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
database = SQLAlchemy(app)

# ----- Модель -----
class Vine(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    name = database.Column(database.String(100), nullable=False)
    color = database.Column(database.String(50), nullable=False)
    sparkling = database.Column(database.String(50), nullable=False, default="no")
    bokal = database.Column(database.String(50), nullable=False, default="no")
    country = database.Column(database.String(100), nullable=False)
    region = database.Column(database.String(100), nullable=True)
    grape = database.Column(database.String(200), nullable=True)  # JSON
    sugar = database.Column(database.String(50), nullable=False)
    pdf_file = database.Column(database.String(200), nullable=False)
    price = database.Column(database.String(100), nullable=True)

# ----- Роуты -----
@app.route("/")
def welcome():
    return render_template("welcome.html")

def _build_bottle_lookup():
    """Return mapping of pdf base names to bottle image filenames."""
    bottles_dir = os.path.join(app.root_path, "bottles")
    if not os.path.isdir(bottles_dir):
        return {}, bottles_dir

    allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    lookup = {}
    for entry in os.listdir(bottles_dir):
        base, ext = os.path.splitext(entry)
        if ext.lower() not in allowed_ext:
            continue
        lookup[base.lower()] = entry
    return lookup, bottles_dir


def _asset_dir_for_extension(ext: str) -> str:
    """Return subdirectory name that stores files for the provided extension."""
    return "webp" if ext == ".webp" else "pdfs"


def _infer_active_asset_extension(vines) -> str:
    """Guess which extension is currently used for vine description files."""
    for v in vines:
        if v.pdf_file:
            _, ext = os.path.splitext(v.pdf_file)
            if ext:
                return ext.lower()
    # Fallback by checking which directory exists
    webp_dir = os.path.join(app.root_path, "webp")
    return ".webp" if os.path.isdir(webp_dir) else ".pdf"


def _asset_path_info(filename: str):
    """Return (safe_filename, directory_path, extension) for the requested asset."""
    safe_name = os.path.basename(filename)
    _, ext = os.path.splitext(safe_name)
    ext = ext.lower()
    
    # Исправляем неправильное расширение .web на .webp
    if ext == ".web":
        ext = ".webp"
        base_name = os.path.splitext(safe_name)[0]
        safe_name = f"{base_name}.webp"
    
    if ext == "":
        ext = ".webp"
        safe_name = f"{safe_name}.webp"
    directory = os.path.join(app.root_path, _asset_dir_for_extension(ext))
    return safe_name, directory, ext


@app.route("/winery/")
def catalog():
    applyed_filters=request.args.get("applyed_filters", "")
    if applyed_filters:
        applyed_filters = json.loads(applyed_filters)
    else:
        applyed_filters = {}

    bottle_lookup, _ = _build_bottle_lookup()
    vines = Vine.query.all()
    vines_list = []
    for v in vines:
        try:
            grapes = json.loads(v.grape) if v.grape else []
        except:
            grapes = [v.grape] if v.grape else []

        image_url = None
        if v.pdf_file:
            base_name = os.path.splitext(v.pdf_file)[0].lower()
            bottle_filename = bottle_lookup.get(base_name)
            if bottle_filename:
                image_url = url_for("bottle_image", filename=bottle_filename)

        vines_list.append({
            "id": v.id,
            "name": v.name,
            "color": v.color,
            "country": v.country,
            "region": v.region,
            "grape": grapes,
            "sugar": v.sugar,
            "pdf_file": v.pdf_file,
            "sparkling": v.sparkling,
            "bokal": v.bokal,
            "price": v.price,
            "image_url": image_url
        })

    return render_template("catalog.html", vines=vines_list, applyed_filters=applyed_filters)

@app.route("/vinery/qr/<filename>")
def pdf_qr(filename):
    if filename == "catalog-page":
        pdf_url = "https://vinelink.lavroovich.fun/"
    else:
        pdf_url = f"https://vinelink.lavroovich.fun/vinery/{filename}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(pdf_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/vinery/<filename>")
def pdf_view(filename):
    return render_template("viewer.html", filename=filename)

@app.route("/vinery/description/<filename>")
def pdfs(filename):
    safe_name, directory, ext = _asset_path_info(filename)
    if ext == ".webp" and not os.path.isdir(directory):
        # fall back to legacy directory name if present
        legacy = os.path.join(app.root_path, "webps")
        if os.path.isdir(legacy):
            directory = legacy
    if not os.path.isdir(directory):
        return "Not Found", 404
    return send_from_directory(directory, safe_name)


@app.route("/vinery/bottles/<path:filename>")
def bottle_image(filename):
    bottle_lookup, bottles_dir = _build_bottle_lookup()
    valid_files = set(bottle_lookup.values())
    _, ext = os.path.splitext(filename)
    if ext.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
        return "Not Found", 404

    # Ensure requested file exists in lookup to avoid serving arbitrary files
    if filename not in valid_files:
        return "Not Found", 404

    return send_from_directory(bottles_dir, filename, max_age=60 * 60 * 24 * 7)


with app.app_context():
        database.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
