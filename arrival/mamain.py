import os
import fitz  # PyMuPDF
from PIL import Image

folder = r"c:\Users\ivanb\Desktop\papka\code\aviator-winelink\arrival"

for file in os.listdir(folder):
    if file.lower().endswith(".pdf"):
        path = os.path.join(folder, file)
        name = os.path.splitext(file)[0]
        doc = fitz.open(path)

        for i, page in enumerate(doc):
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            out = os.path.join(folder, f"{name}.webp")
            img.save(out, "WEBP", quality=90)
            print(f"✔ {out}")
