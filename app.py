import os
import json
import uuid
import qrcode
from io import BytesIO
from flask import Flask, render_template, send_from_directory, send_file, request, url_for, redirect, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

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

ALLOWED_CARD_EXTENSIONS = {".pdf", ".webp"}
ALLOWED_BOTTLE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
COLOR_CHOICES = [("red", "Красное"), ("white", "Белое"), ("pink", "Розовое")]
SUGAR_CHOICES = [
    ("dry", "Сухое"),
    ("semidry", "Полусухое"),
    ("brut", "Брют"),
    ("semisweet", "Полусладкое"),
    ("sweet", "Сладкое"),
]

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


def _slugify_filename(value: str) -> str:
    """Return filesystem-safe slug without extension."""
    safe = secure_filename(value or "").lower()
    if not safe:
        safe = "wine"
    if "." in safe:
        safe = safe.rsplit(".", 1)[0]
    return safe or "wine"


def _new_slug(value: str) -> str:
    """Build a readable slug with a short unique suffix."""
    base = _slugify_filename(value)
    return f"{base}-{uuid.uuid4().hex[:6]}"


def _delete_if_exists(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        return


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


def _parse_grapes(grapes_value: str):
    if not grapes_value:
        return []
    if isinstance(grapes_value, list):
        return grapes_value
    try:
        return [g for g in json.loads(grapes_value) if g]
    except Exception:
        return [g.strip() for g in str(grapes_value).split(",") if g.strip()]


@app.route("/winery/manage", methods=["GET", "POST"])
def manage_wine():
    wine_id_param = request.args.get("wine_id") or request.form.get("wine_id")
    vine = None
    if wine_id_param:
        try:
            vine_id_int = int(wine_id_param)
        except ValueError:
            abort(404)
        vine = Vine.query.get(vine_id_int)
        if vine is None:
            abort(404)

    is_edit = vine is not None
    errors = []
    saved = request.args.get("saved") == "1"
    read_only = bool(os.getenv("VERCEL"))

    grape_list = _parse_grapes(vine.grape) if vine else []
    grape_text = ", ".join(grape_list)
    bottle_lookup, bottles_dir = _build_bottle_lookup()
    current_bottle = None
    if vine and vine.pdf_file:
        base = os.path.splitext(vine.pdf_file)[0].lower()
        current_bottle = bottle_lookup.get(base)

    try:
        country_rows = database.session.query(Vine.country).distinct().all()
        country_choices = sorted({row[0] for row in country_rows if row[0]})
    except Exception:
        country_choices = []
    if not country_choices:
        country_choices = [
            "russia", "france", "italy", "spain", "usa", "germany",
            "georgia", "argentina", "chill", "portugal", "south_africa",
            "australia", "new_zealand"
        ]

    if request.method == "POST" and read_only:
        errors.append("Редактирование отключено: база данных доступна только для чтения.")

    if request.method == "POST" and not read_only:
        name = (request.form.get("name") or "").strip()
        color = (request.form.get("color") or "").strip()
        sparkling = "yes" if request.form.get("sparkling") == "on" else "no"
        bokal = "yes" if request.form.get("bokal") == "on" else "no"
        country_primary = (request.form.get("country") or "").strip()
        country_other = (request.form.get("country_other") or "").strip()
        country = country_other or country_primary
        region = (request.form.get("region") or "").strip() or None
        sugar = (request.form.get("sugar") or "").strip()
        price = (request.form.get("price") or "").strip() or None
        grapes_raw = (request.form.get("grape") or "").strip()
        grape_list = [g.strip() for g in grapes_raw.split(",") if g.strip()]

        card_file = request.files.get("card_file")
        bottle_file = request.files.get("bottle_file")

        if not name:
            errors.append("Укажите название вина.")
        if not color:
            errors.append("Выберите цвет вина.")
        if not sugar:
            errors.append("Укажите уровень сладости.")
        if not country:
            errors.append("Укажите страну.")

        slug_base = os.path.splitext(vine.pdf_file)[0] if vine and vine.pdf_file else _new_slug(name)
        card_filename = vine.pdf_file if vine else None

        if card_file and card_file.filename:
            raw_name = os.path.splitext(card_file.filename)[0]
            ext = os.path.splitext(card_file.filename)[1].lower()
            if ext not in ALLOWED_CARD_EXTENSIONS:
                errors.append("Карточка должна быть в формате PDF или WEBP.")
            else:
                slug_base = _slugify_filename(raw_name) or slug_base
                card_filename = f"{slug_base}{ext}"
                target_dir = os.path.join(app.root_path, _asset_dir_for_extension(ext))
                os.makedirs(target_dir, exist_ok=True)
                new_card_path = os.path.join(target_dir, card_filename)
                _delete_if_exists(new_card_path)
                card_file.save(new_card_path)

                if vine and vine.pdf_file:
                    old_ext = os.path.splitext(vine.pdf_file)[1].lower()
                    old_dir = os.path.join(app.root_path, _asset_dir_for_extension(old_ext))
                    old_path = os.path.join(old_dir, vine.pdf_file)
                    if old_path != new_card_path:
                        _delete_if_exists(old_path)

        if not is_edit and not card_filename:
            errors.append("Загрузите карточку для вивера (PDF или WEBP).")

        bottle_filename = current_bottle
        if bottle_file and bottle_file.filename:
            ext = os.path.splitext(bottle_file.filename)[1].lower()
            if ext not in ALLOWED_BOTTLE_EXTENSIONS:
                errors.append("Бутылка должна быть изображением (PNG, JPG, WEBP, GIF, SVG).")
            else:
                bottle_slug = slug_base
                bottle_filename = f"{bottle_slug}{ext}"
                os.makedirs(bottles_dir, exist_ok=True)
                for entry in os.listdir(bottles_dir):
                    if os.path.splitext(entry)[0].lower() == bottle_slug.lower():
                        _delete_if_exists(os.path.join(bottles_dir, entry))
                bottle_file.save(os.path.join(bottles_dir, bottle_filename))

        if not errors:
            try:
                grape_json = json.dumps(grape_list)
                if is_edit:
                    vine.name = name
                    vine.color = color
                    vine.sparkling = sparkling
                    vine.bokal = bokal
                    vine.country = country
                    vine.region = region
                    vine.grape = grape_json
                    vine.sugar = sugar
                    vine.price = price
                    if card_filename:
                        vine.pdf_file = card_filename
                else:
                    vine = Vine(
                        name=name,
                        color=color,
                        sparkling=sparkling,
                        bokal=bokal,
                        country=country,
                        region=region,
                        grape=grape_json,
                        sugar=sugar,
                        pdf_file=card_filename,
                        price=price
                    )
                    database.session.add(vine)

                database.session.commit()
                return redirect(url_for("manage_wine", wine_id=vine.id, saved=1))
            except Exception as commit_error:
                database.session.rollback()
                errors.append(f"Не удалось сохранить: {commit_error}")

    card_url = url_for("pdf_view", filename=vine.pdf_file) if vine and vine.pdf_file else None
    bottle_url = url_for("bottle_image", filename=current_bottle) if current_bottle else None

    return render_template(
        "manage_wine.html",
        vine=vine,
        grape_text=grape_text,
        errors=errors,
        saved=saved,
        read_only=read_only,
        color_choices=COLOR_CHOICES,
        sugar_choices=SUGAR_CHOICES,
        country_choices=country_choices,
        card_url=card_url,
        bottle_url=bottle_url,
    )

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


# app.py

def init_db():
    with app.app_context():
        database.create_all()

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080)

