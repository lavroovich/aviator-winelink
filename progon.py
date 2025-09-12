import os
import subprocess

# Папка с PDF
PDF_FOLDER = "pdfs"
# Папка для сжатых PDF
OUTPUT_FOLDER = "pdfs_compressed"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Проходим по всем файлам
for filename in os.listdir(PDF_FOLDER):
    if not filename.lower().endswith(".pdf"):
        continue

    input_path = os.path.join(PDF_FOLDER, filename)
    output_path = os.path.join(OUTPUT_FOLDER, filename)

    # Используем Ghostscript для сжатия
    gs_command = [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dPDFSETTINGS=/screen",  # /screen, /ebook, /printer, /prepress
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={output_path}",
        input_path
    ]

    try:
        subprocess.run(gs_command, check=True)
        print(f"[OK] {filename} → сжат")
    except subprocess.CalledProcessError:
        print(f"[ERROR] Не удалось сжать {filename}")