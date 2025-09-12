import os
import json
import qrcode
from io import BytesIO
from flask import Flask, render_template, send_from_directory, send_file
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
def catalog():
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

    return render_template("catalog.html", vines=vines_list)

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
