import os
import json
import qrcode
from io import BytesIO
from flask import Flask, render_template, send_from_directory, send_file, request, jsonify
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

# ----- Роуты -----
@app.route("/")
def welcome():
    return render_template("welcome.html")

@app.route("/winery/")
def catalog():
    
    applyed_filters=request.args.get("applyed_filters", "")
    if applyed_filters:
        applyed_filters = json.loads(applyed_filters)
    else:
        applyed_filters = {}
    
    vines = Vine.query.all()
    vines_list = []
    for v in vines:
        try:
            grapes = json.loads(v.grape) if v.grape else []
        except:
            grapes = [v.grape] if v.grape else []

        vines_list.append({
            "id": v.id,
            "name": v.name,
            "color": v.color,
            "country": v.country,
            "region": v.region,
            "grape": grapes,
            "sugar": v.sugar,
            "pdf_file": v.pdf_file,
            "sparkling": v.sparkling
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
        "version": "2.0",
        "details": details,
    }
    return jsonify(payload)

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

# ----- Инициализация -----
if not os.getenv("VERCEL"):
    with app.app_context():
        database.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 4400)))
