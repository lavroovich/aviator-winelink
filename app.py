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
    db_error = None
    try:
        vines = Vine.query.order_by(Vine.name).all()
    except Exception as exc:
        db_error = str(exc)
        vines = []

    pdfs_dir = os.path.join(app.root_path, "pdfs")
    pdf_dir_exists = os.path.isdir(pdfs_dir)
    pdf_fs_files = set()
    pdf_other_files = []
    if pdf_dir_exists:
        for entry in os.listdir(pdfs_dir):
            entry_path = os.path.join(pdfs_dir, entry)
            if not os.path.isfile(entry_path):
                continue
            if entry.lower().endswith(".pdf"):
                pdf_fs_files.add(entry)
            else:
                pdf_other_files.append(entry)

    bottles_dir = os.path.join(app.root_path, "bottles")
    bottle_dir_exists = os.path.isdir(bottles_dir)
    bottle_allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    bottle_lookup, _ = _build_bottle_lookup()
    bottle_files = set(bottle_lookup.values()) if bottle_dir_exists else set()
    bottle_other_files = []
    bottle_base_registry = defaultdict(list)
    if bottle_dir_exists:
        for entry in os.listdir(bottles_dir):
            entry_path = os.path.join(bottles_dir, entry)
            if not os.path.isfile(entry_path):
                continue
            base, ext = os.path.splitext(entry)
            if ext.lower() in bottle_allowed_ext:
                bottle_base_registry[base.lower()].append(entry)
            else:
                bottle_other_files.append(entry)

    total_vines = len(vines)
    vines_with_pdf = [v for v in vines if (v.pdf_file or "").strip()]
    pdf_names_in_db = {v.pdf_file.strip() for v in vines_with_pdf if (v.pdf_file or "").strip()}

    missing_pdf_field = []
    missing_pdf_on_disk = []
    missing_bottle_images = []
    used_bottle_files = set()
    pdf_usage = defaultdict(list)
    color_counter = Counter()
    sugar_counter = Counter()
    sparkling_counter = Counter()
    country_counter = Counter()
    grape_counter = Counter()
    vines_missing_grape = []
    vines_missing_price = []

    for vine in vines:
        pdf_name = (vine.pdf_file or "").strip()
        if not pdf_name:
            missing_pdf_field.append(vine)
        else:
            pdf_usage[pdf_name].append(vine)
            if pdf_dir_exists and pdf_name not in pdf_fs_files:
                missing_pdf_on_disk.append((vine, pdf_name))

            base_name = os.path.splitext(pdf_name)[0].lower()
            bottle_filename = bottle_lookup.get(base_name)
            if bottle_filename:
                used_bottle_files.add(bottle_filename)
            else:
                missing_bottle_images.append((vine, base_name))

        color_counter[vine.color or "не указан"] += 1
        sugar_counter[vine.sugar or "не указано"] += 1
        sparkling_counter[(vine.sparkling or "no").lower()] += 1
        country_counter[vine.country or "не указана"] += 1

        grapes_raw = vine.grape
        grape_values = []
        if grapes_raw:
            try:
                parsed = json.loads(grapes_raw)
                if isinstance(parsed, list):
                    grape_values = [str(g).strip() for g in parsed if str(g).strip()]
                elif isinstance(parsed, str) and parsed.strip():
                    grape_values = [parsed.strip()]
            except Exception:
                grape_values = [str(grapes_raw).strip()]

        if not grape_values:
            vines_missing_grape.append(vine)
        else:
            for grape_name in grape_values:
                grape_counter[grape_name] += 1

        if not (vine.price or "").strip():
            vines_missing_price.append(vine)

    duplicate_pdfs = []
    for pdf_name, linked_vines in pdf_usage.items():
        if len(linked_vines) > 1:
            duplicate_pdfs.append({
                "pdf": pdf_name,
                "vines": sorted(linked_vines, key=lambda v: (v.name or "").lower()),
            })
    duplicate_pdfs.sort(key=lambda item: item["pdf"].lower())

    duplicate_bottle_entries = []
    for base_name, entries in bottle_base_registry.items():
        if len(entries) > 1:
            duplicate_bottle_entries.append({
                "base": base_name,
                "files": sorted(entries),
            })
    duplicate_bottle_entries.sort(key=lambda item: item["base"])

    unused_pdf_files = sorted(pdf_fs_files - pdf_names_in_db) if pdf_dir_exists else []
    unused_bottle_files = sorted(bottle_files - used_bottle_files) if bottle_dir_exists else []

    color_stats = sorted(color_counter.items(), key=lambda item: (-item[1], item[0]))
    sugar_stats = sorted(sugar_counter.items(), key=lambda item: (-item[1], item[0]))
    sparkling_stats = {
        "yes": sparkling_counter.get("yes", 0),
        "no": sparkling_counter.get("no", 0),
        "other": sum(count for state, count in sparkling_counter.items() if state not in {"yes", "no"}),
    }
    country_stats = sorted(country_counter.items(), key=lambda item: (-item[1], item[0]))
    grape_stats = sorted(grape_counter.items(), key=lambda item: (-item[1], item[0]))

    summary = {
        "total_vines": total_vines,
        "with_pdf": len(vines_with_pdf),
        "unique_pdf": len(pdf_names_in_db),
        "pdf_dir_count": len(pdf_fs_files) if pdf_dir_exists else 0,
        "bottle_dir_count": len(bottle_files) if bottle_dir_exists else 0,
        "missing_pdf_field": len(missing_pdf_field),
        "missing_pdf_disk": len(missing_pdf_on_disk),
        "missing_bottles": len(missing_bottle_images),
        "unused_pdf": len(unused_pdf_files),
        "unused_bottles": len(unused_bottle_files),
        "missing_grape": len(vines_missing_grape),
        "missing_price": len(vines_missing_price),
    }

    directories = {
        "pdf": {
            "exists": pdf_dir_exists,
            "path": os.path.relpath(pdfs_dir, base_dir),
            "count": len(pdf_fs_files),
            "other": sorted(pdf_other_files),
        },
        "bottles": {
            "exists": bottle_dir_exists,
            "path": os.path.relpath(bottles_dir, base_dir),
            "count": len(bottle_files),
            "other": sorted(bottle_other_files),
        },
    }

    primary_metrics = [
        {
            "label": "Всего вин",
            "value": summary["total_vines"],
            "caption": "в каталоге",
        },
        {
            "label": "С PDF",
            "value": summary["with_pdf"],
            "caption": "имеют файл",
        },
        {
            "label": "Уникальных PDF",
            "value": summary["unique_pdf"],
            "caption": "имен в базе",
        },
        {
            "label": "PDF в каталоге",
            "value": directories["pdf"]["count"] if directories["pdf"]["exists"] else "—",
            "caption": directories["pdf"]["path"] if directories["pdf"]["exists"] else "нет папки",
        },
        {
            "label": "Изображений бутылок",
            "value": directories["bottles"]["count"] if directories["bottles"]["exists"] else "—",
            "caption": directories["bottles"]["path"] if directories["bottles"]["exists"] else "нет папки",
        },
    ]

    quality_metrics = [
        {
            "label": "Нет PDF в записи",
            "value": summary["missing_pdf_field"],
            "caption": "записей",
        },
        {
            "label": "PDF не найден",
            "value": summary["missing_pdf_disk"],
            "caption": "файлов",
        },
        {
            "label": "Нет изображения",
            "value": summary["missing_bottles"],
            "caption": "бутылок",
        },
        {
            "label": "Неиспользуемые PDF",
            "value": summary["unused_pdf"],
            "caption": "файлов",
        },
        {
            "label": "Неиспользуемые изображения",
            "value": summary["unused_bottles"],
            "caption": "файлов",
        },
        {
            "label": "Без сортов",
            "value": summary["missing_grape"],
            "caption": "вин",
        },
        {
            "label": "Без цены",
            "value": summary["missing_price"],
            "caption": "вин",
        },
    ]

    context = {
        "summary": summary,
        "directories": directories,
        "missing_pdf_field": missing_pdf_field,
        "missing_pdf_on_disk": missing_pdf_on_disk,
        "missing_bottle_images": missing_bottle_images,
        "unused_pdf_files": unused_pdf_files,
        "unused_bottle_files": unused_bottle_files,
        "duplicate_pdfs": duplicate_pdfs,
        "duplicate_bottle_entries": duplicate_bottle_entries,
        "color_stats": color_stats,
        "sugar_stats": sugar_stats,
        "sparkling_stats": sparkling_stats,
        "country_stats": country_stats,
        "grape_stats": grape_stats,
        "vines_missing_grape": vines_missing_grape,
        "vines_missing_price": vines_missing_price,
        "db_error": db_error,
        "primary_metrics": primary_metrics,
        "quality_metrics": quality_metrics,
    }

    return render_template("scan.html", **context)

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
