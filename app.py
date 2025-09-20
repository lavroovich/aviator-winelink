import os
import json
import qrcode
from io import BytesIO
from flask import Flask, render_template, send_from_directory, send_file, request, jsonify, url_for, Response
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
            "price": v.price,
            "image_url": image_url
        })

    return render_template("catalog.html", vines=vines_list, applyed_filters=applyed_filters)

@app.route("/status.json")
def status_json():
    # ENV and DB mode
    env = "vercel" if os.getenv("VERCEL") else "local"
    db_mode = "ro" if os.getenv("VERCEL") else "rw"

    # Try DB connectivity and collect stats safely
    ok = True
    details = {}
    try:
        vines = Vine.query.all()
        details["vines_total"] = len(vines)

        # counts and uniques
        colors = {}
        sparkling_yes = 0
        countries = set()
        regions = set()
        grapes_set = set()
        sugars_set = set()
        for v in vines:
            colors[v.color] = colors.get(v.color, 0) + 1
            if getattr(v, "sparkling", "no") == "yes":
                sparkling_yes += 1
            if v.country:
                countries.add(v.country)
            if v.region:
                regions.add(v.region)
            if v.sugar:
                sugars_set.add(v.sugar)
            # v.grape is JSON array or string
            try:
                gs = json.loads(v.grape) if v.grape else []
                if isinstance(gs, list):
                    for g in gs:
                        grapes_set.add(str(g))
                elif isinstance(gs, str) and gs:
                    grapes_set.add(gs)
            except Exception:
                if v.grape:
                    grapes_set.add(str(v.grape))

        details["colors"] = colors
        details["sparkling_yes"] = sparkling_yes
        details["countries_total"] = len(countries)
        details["regions_total"] = len(regions)
        details["grapes_total"] = len(grapes_set)
        details["sugars_present"] = sorted(list(sugars_set))

        # filesystem checks for PDFs
        try:
            pdfs_dir = os.path.join(app.root_path, "pdfs")
            fs_files = set(os.listdir(pdfs_dir)) if os.path.isdir(pdfs_dir) else set()
            db_files = set(v.pdf_file for v in vines if v.pdf_file)
            missing = sorted(list(db_files - fs_files))
            extra = sorted(list(fs_files - db_files))
            details["pdfs_in_dir"] = len(fs_files)
            details["pdfs_missing"] = missing
            details["pdfs_extra"] = extra
        except Exception:
            # ignore FS errors
            pass
    except Exception:
        ok = False

    payload = {
        "env": env,
        "db_mode": db_mode,
        "db_connected": ok,
        "version": "2.1",
        "details": details,
    }
    return jsonify(payload)


@app.route("/scan")
def scan_resources():
    try:
        vines = Vine.query.order_by(Vine.name).all()
    except Exception as exc:
        failure_log = [
            "--- Проверка ассоциаций базы данных и ресурсов ---",
            "",
            "Ошибка при обращении к базе данных:",
            str(exc),
        ]
        return Response("\n".join(failure_log), content_type="text/plain; charset=utf-8", status=500)

    pdfs_dir = os.path.join(app.root_path, "pdfs")
    pdf_dir_exists = os.path.isdir(pdfs_dir)
    pdf_fs_files = set()
    if pdf_dir_exists:
        pdf_fs_files = {entry for entry in os.listdir(pdfs_dir) if entry.lower().endswith(".pdf")}

    bottle_lookup, bottles_dir = _build_bottle_lookup()
    bottle_dir_exists = bool(bottles_dir and os.path.isdir(bottles_dir))
    bottle_files = set(bottle_lookup.values()) if bottle_dir_exists else set()

    total_vines = len(vines)
    vines_with_pdf = [v for v in vines if (v.pdf_file or "").strip()]
    pdf_names_in_db = {v.pdf_file.strip() for v in vines_with_pdf}

    missing_pdf_field = []
    missing_pdf_on_disk = []
    missing_bottle_images = []
    used_bottle_files = set()

    for vine in vines:
        pdf_name = (vine.pdf_file or "").strip()
        if not pdf_name:
            missing_pdf_field.append(vine)
            continue

        if pdf_dir_exists and pdf_name not in pdf_fs_files:
            missing_pdf_on_disk.append((vine, pdf_name))

        base_name = os.path.splitext(pdf_name)[0].lower()
        bottle_filename = bottle_lookup.get(base_name)
        if bottle_filename:
            used_bottle_files.add(bottle_filename)
        else:
            missing_bottle_images.append((vine, base_name))

    unused_pdf_files = sorted(pdf_fs_files - pdf_names_in_db) if pdf_dir_exists else []
    unused_bottle_files = sorted(bottle_files - used_bottle_files) if bottle_dir_exists else []

    lines = ["--- Проверка ассоциаций базы данных и ресурсов ---", ""]

    lines.append("===================")
    lines.append(f"Всего вин в базе: {total_vines}")
    lines.append(f"Вин с указанным PDF: {len(vines_with_pdf)}")
    lines.append(f"Уникальных PDF в базе: {len(pdf_names_in_db)}")
    if pdf_dir_exists:
        lines.append(f"PDF файлов в каталоге: {len(pdf_fs_files)}")
    else:
        lines.append("Каталог с PDF не найден")
    if bottle_dir_exists:
        lines.append(f"Изображений бутылок в каталоге: {len(bottle_files)}")
    else:
        lines.append("Каталог с изображениями бутылок не найден")
    lines.append("===================")
    lines.append("")

    lines.append("===================")
    lines.append(f"Вин без указанного PDF: {len(missing_pdf_field)}")
    if missing_pdf_field:
        for vine in missing_pdf_field:
            lines.append(f"- Имя вина: {vine.name} (id={vine.id})")
    else:
        lines.append("- Нет таких записей")
    lines.append("===================")
    lines.append("")

    lines.append("===================")
    lines.append(f"Недостающих PDF на диске: {len(missing_pdf_on_disk)}")
    if missing_pdf_on_disk:
        for vine, pdf_name in missing_pdf_on_disk:
            lines.append(f"- Имя вина: {vine.name} (ожидаемый файл: {pdf_name})")
    elif not pdf_dir_exists:
        lines.append("- Проверка невозможна: каталог отсутствует")
    else:
        lines.append("- Нет таких записей")
    lines.append("===================")
    lines.append("")

    lines.append("===================")
    lines.append(f"Недостающих изображений бутылок: {len(missing_bottle_images)}")
    if missing_bottle_images:
        for vine, base_name in missing_bottle_images:
            lines.append(f"- Имя вина: {vine.name} (ожидаемый файл: {base_name}.png/.jpg)")
    elif not bottle_dir_exists:
        lines.append("- Проверка невозможна: каталог отсутствует")
    else:
        lines.append("- Нет таких записей")
    lines.append("===================")
    lines.append("")

    lines.append("===================")
    lines.append(f"Неиспользуемых PDF файлов: {len(unused_pdf_files)}")
    if unused_pdf_files:
        for filename in unused_pdf_files:
            lines.append(f"- {filename}")
    elif not pdf_dir_exists:
        lines.append("- Проверка невозможна: каталог отсутствует")
    else:
        lines.append("- Нет таких файлов")
    lines.append("===================")
    lines.append("")

    lines.append("===================")
    lines.append(f"Неиспользуемых изображений бутылок: {len(unused_bottle_files)}")
    if unused_bottle_files:
        for filename in unused_bottle_files:
            lines.append(f"- {filename}")
    elif not bottle_dir_exists:
        lines.append("- Проверка невозможна: каталог отсутствует")
    else:
        lines.append("- Нет таких файлов")
    lines.append("===================")

    return Response("\n".join(lines), content_type="text/plain; charset=utf-8")

@app.route("/dev-only/upload-test-vines")
def upload_test_vines():
    wine1 = Vine(
        name="[ТЕСТОВОЕ] Каберне Совиньон",
        color="red",
        country="russia",
        region="Краснодар",
        grape=json.dumps(["Cabernet Sauvignon"]),
        sugar="dry",
        pdf_file="kab_sov.pdf"
    )
    wine2 = Vine(
        name="[ТЕСТОВОЕ] Бордо купаж",
        color="red",
        country="france",
        region="Бордо",
        grape=json.dumps(["Cabernet Sauvignon", "Merlot", "Cabernet Franc"]),
        sugar="dry",
        pdf_file="bordeaux.pdf"
    )
    database.session.add(wine1)
    database.session.add(wine2)
    database.session.commit()
    return "Test vines uploaded successfully!"

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

@app.route("/vinery/pdfs/<filename>")
def pdfs(filename):
    pdfs_dir = os.path.join(app.root_path, "pdfs")
    return send_from_directory(pdfs_dir, filename, mimetype="application/pdf")


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

# ----- Инициализация -----
if not os.getenv("VERCEL"):
    with app.app_context():
        database.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 4400)))
