"""
Backend del sorteo NOW (Flask + SQLite)

Ejecutar:
    pip install -r requirements.txt
    python app.py

Variables de entorno opcionales:
    ADMIN_TOKEN       clave para ver/descargar los registros (¡cámbiala!)
    ALLOWED_ORIGINS   dominios que pueden enviar el formulario, separados por coma
"""
import csv
import io
import os
import re
import secrets
import sqlite3
from datetime import datetime

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "sorteo.db")

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "cambia-este-token")
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:5500,http://localhost:5500,https://now.com.pe,https://www.now.com.pe",
    ).split(",")
    if o.strip()
]

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
PHONE_RE = re.compile(r"^9\d{8}$")  # Perú: 9 dígitos, empieza con 9


# ---------------------------------------------------------------- base de datos
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS participantes (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo    TEXT UNIQUE,
                nombre    TEXT NOT NULL,
                correo    TEXT NOT NULL UNIQUE,
                telefono  TEXT NOT NULL UNIQUE,
                fecha     TEXT NOT NULL
            )
            """
        )


# ------------------------------------------------------------------------ CORS
@app.after_request
def cors(resp):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


# ------------------------------------------------------------ registro público
@app.route("/api/sorteo", methods=["POST", "OPTIONS"])
def registrar():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    correo = str(data.get("correo", "")).strip().lower()
    telefono = re.sub(r"\D", "", str(data.get("telefono", "")))

    if len(nombre) < 3 or len(nombre) > 100:
        return jsonify(ok=False, campo="nombre", error="Escribe tu nombre completo."), 400
    if not EMAIL_RE.match(correo) or len(correo) > 150:
        return jsonify(ok=False, campo="correo", error="Escribe un correo válido."), 400
    if not PHONE_RE.match(telefono):
        return jsonify(ok=False, campo="telefono", error="Debe tener 9 dígitos y empezar con 9."), 400

    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO participantes (nombre, correo, telefono, fecha) VALUES (?, ?, ?, ?)",
                (nombre, correo, telefono, datetime.now().isoformat(timespec="seconds")),
            )
            codigo = f"NOW-{cur.lastrowid:04d}"
            conn.execute("UPDATE participantes SET codigo = ? WHERE id = ?", (codigo, cur.lastrowid))
    except sqlite3.IntegrityError:
        return jsonify(ok=False, campo="correo", error="Este correo o teléfono ya está registrado."), 409

    return jsonify(ok=True, codigo=codigo), 201


# ------------------------------------------------------------- panel de control
def es_admin():
    token = request.args.get("token") or request.headers.get("X-Admin-Token", "")
    return secrets.compare_digest(token, ADMIN_TOKEN)


@app.route("/admin/participantes")
def listar():
    if not es_admin():
        return jsonify(error="No autorizado"), 401
    with db() as conn:
        filas = [dict(r) for r in conn.execute("SELECT * FROM participantes ORDER BY id")]
    return jsonify(total=len(filas), participantes=filas)


def _celda_segura(valor):
    """Evita que Excel ejecute fórmulas si alguien escribe '=...' como nombre."""
    valor = str(valor)
    return "'" + valor if valor[:1] in ("=", "+", "-", "@") else valor


@app.route("/admin/exportar.csv")
def exportar():
    if not es_admin():
        return jsonify(error="No autorizado"), 401
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["codigo", "nombre", "correo", "telefono", "fecha"])
    with db() as conn:
        for r in conn.execute("SELECT * FROM participantes ORDER BY id"):
            escritor.writerow([r["codigo"], _celda_segura(r["nombre"]), r["correo"], r["telefono"], r["fecha"]])
    return Response(
        "\ufeff" + salida.getvalue(),  # BOM para que Excel respete las tildes
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=participantes-now.csv"},
    )


@app.route("/admin/sortear")
def sortear():
    if not es_admin():
        return jsonify(error="No autorizado"), 401
    with db() as conn:
        filas = conn.execute("SELECT * FROM participantes").fetchall()
    if not filas:
        return jsonify(error="No hay participantes todavía."), 404
    ganador = secrets.choice(filas)  # aleatorio criptográficamente seguro
    return jsonify(ganador=dict(ganador), total_participantes=len(filas))


@app.route("/")
def salud():
    return jsonify(estado="ok")


if __name__ == "__main__":
    init_db()
    if ADMIN_TOKEN == "cambia-este-token":
        print("⚠️  Cambia ADMIN_TOKEN antes de publicar (set ADMIN_TOKEN=tu_clave_larga)")
    app.run(host="127.0.0.1", port=5000, debug=True)