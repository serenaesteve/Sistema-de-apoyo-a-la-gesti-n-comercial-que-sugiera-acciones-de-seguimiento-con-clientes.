from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import sqlite3
import json
import requests
import hashlib
import secrets
from datetime import datetime, date, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
DB = "crm.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"

# ── HELPERS ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM usuarios WHERE id=?", (session["user_id"],)).fetchone()

# ── DB SETUP ──────────────────────────────────────────────────────────────────

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                rol TEXT DEFAULT 'comercial',
                avatar TEXT DEFAULT '',
                fecha_registro TEXT DEFAULT (date('now'))
            );

            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                empresa TEXT,
                email TEXT,
                telefono TEXT,
                sector TEXT,
                estado TEXT DEFAULT 'prospecto',
                valor_potencial REAL DEFAULT 0,
                notas TEXT,
                usuario_id INTEGER,
                fecha_creacion TEXT DEFAULT (date('now')),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            );

            CREATE TABLE IF NOT EXISTS interacciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                usuario_id INTEGER,
                tipo TEXT NOT NULL,
                descripcion TEXT,
                resultado TEXT,
                fecha TEXT DEFAULT (date('now')),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            );

            CREATE TABLE IF NOT EXISTS seguimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                usuario_id INTEGER,
                accion TEXT NOT NULL,
                prioridad TEXT DEFAULT 'media',
                completado INTEGER DEFAULT 0,
                fecha_sugerida TEXT,
                generado_ia INTEGER DEFAULT 0,
                fecha_creacion TEXT DEFAULT (date('now')),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            );
        """)

def seed_demo(uid):
    db = get_db()
    clientes = [
        ("Laura Martínez", "TechSolutions SL", "laura@techsol.es", "+34 612 345 678", "Tecnología", "activo", 15000, "Interesada en automatización de procesos"),
        ("Carlos Romero", "Distribuciones Norte", "carlos@disnorte.es", "+34 698 234 567", "Distribución", "prospecto", 8000, "Primera reunión pendiente"),
        ("Ana García", "Grupo Retail Plus", "ana@retailplus.es", "+34 655 789 012", "Retail", "activo", 22000, "Cliente recurrente, alto potencial"),
        ("Marcos Vidal", "Consultoría MV", "marcos@consultoriamv.es", "+34 677 456 789", "Consultoría", "inactivo", 5000, "Sin contacto desde hace 3 meses"),
        ("Sara Blanco", "Innovatech", "sara@innovatech.es", "+34 622 987 654", "Tecnología", "prospecto", 30000, "Empresa emergente con gran presupuesto"),
        ("Pedro Sanz", "Logística Express", "pedro@logex.es", "+34 633 111 222", "Logística", "activo", 12000, "Renovación de contrato en julio"),
    ]
    ids = []
    for c in clientes:
        cur = db.execute("INSERT INTO clientes (nombre,empresa,email,telefono,sector,estado,valor_potencial,notas,usuario_id) VALUES (?,?,?,?,?,?,?,?,?)", (*c, uid))
        ids.append(cur.lastrowid)

    interacciones = [
        (ids[0], "llamada", "Llamada inicial de presentación del producto", "positivo", str(date.today() - timedelta(days=5))),
        (ids[0], "email", "Envío de propuesta comercial detallada", "pendiente", str(date.today() - timedelta(days=2))),
        (ids[2], "reunión", "Reunión revisión y renovación de contrato", "positivo", str(date.today() - timedelta(days=10))),
        (ids[2], "llamada", "Seguimiento post-reunión, confirmación de interés", "positivo", str(date.today() - timedelta(days=3))),
        (ids[3], "email", "Email de reactivación enviado sin respuesta", "sin respuesta", str(date.today() - timedelta(days=30))),
        (ids[1], "reunión", "Demo completa del producto", "positivo", str(date.today() - timedelta(days=1))),
        (ids[5], "llamada", "Discusión condiciones renovación", "pendiente", str(date.today() - timedelta(days=7))),
        (ids[4], "email", "Envío de información corporativa y pricing", "positivo", str(date.today() - timedelta(days=4))),
    ]
    for i in interacciones:
        db.execute("INSERT INTO interacciones (cliente_id,tipo,descripcion,resultado,fecha,usuario_id) VALUES (?,?,?,?,?,?)", (*i, uid))

    seguimientos = [
        (ids[0], "Enviar caso de éxito del sector tecnológico", "alta", str(date.today() + timedelta(days=1)), 1),
        (ids[1], "Confirmar fecha de reunión de cierre", "alta", str(date.today()), 1),
        (ids[2], "Proponer renovación con descuento fidelidad 10%", "media", str(date.today() + timedelta(days=7)), 1),
        (ids[3], "Llamada urgente de reactivación", "alta", str(date.today()), 1),
        (ids[4], "Preparar propuesta personalizada con ROI", "media", str(date.today() + timedelta(days=3)), 1),
        (ids[5], "Enviar borrador de contrato de renovación", "media", str(date.today() + timedelta(days=5)), 1),
    ]
    for s in seguimientos:
        db.execute("INSERT INTO seguimientos (cliente_id,accion,prioridad,fecha_sugerida,generado_ia,usuario_id) VALUES (?,?,?,?,?,?)", (*s, uid))

    db.commit()

# ── AUTH ROUTES ───────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
        if user and user["password"] == hash_password(password):
            session["user_id"] = user["id"]
            session["user_nombre"] = user["nombre"]
            return redirect(url_for("index"))
        error = "Email o contraseña incorrectos"
    return render_template("login.html", error=error)

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        demo = request.form.get("demo") == "1"

        if not nombre or not email or not password:
            error = "Todos los campos son obligatorios"
        elif password != password2:
            error = "Las contraseñas no coinciden"
        elif len(password) < 6:
            error = "La contraseña debe tener al menos 6 caracteres"
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
            if existing:
                error = "Ya existe una cuenta con ese email"
            else:
                cur = db.execute("INSERT INTO usuarios (nombre,email,password) VALUES (?,?,?)",
                                 (nombre, email, hash_password(password)))
                uid = cur.lastrowid
                db.commit()
                if demo:
                    seed_demo(uid)
                session["user_id"] = uid
                session["user_nombre"] = nombre
                return redirect(url_for("index"))

    return render_template("registro.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── MAIN ROUTES ───────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    uid = session["user_id"]
    db = get_db()

    stats = {
        "total_clientes": db.execute("SELECT COUNT(*) FROM clientes WHERE usuario_id=?", (uid,)).fetchone()[0],
        "activos": db.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo' AND usuario_id=?", (uid,)).fetchone()[0],
        "prospectos": db.execute("SELECT COUNT(*) FROM clientes WHERE estado='prospecto' AND usuario_id=?", (uid,)).fetchone()[0],
        "inactivos": db.execute("SELECT COUNT(*) FROM clientes WHERE estado='inactivo' AND usuario_id=?", (uid,)).fetchone()[0],
        "valor_pipeline": db.execute("SELECT COALESCE(SUM(valor_potencial),0) FROM clientes WHERE estado IN ('activo','prospecto') AND usuario_id=?", (uid,)).fetchone()[0],
        "seguimientos_pendientes": db.execute("SELECT COUNT(*) FROM seguimientos WHERE completado=0 AND usuario_id=?", (uid,)).fetchone()[0],
        "interacciones_mes": db.execute("SELECT COUNT(*) FROM interacciones WHERE fecha >= date('now','-30 days') AND usuario_id=?", (uid,)).fetchone()[0],
        "tasa_conversion": 0,
    }
    if stats["total_clientes"] > 0:
        stats["tasa_conversion"] = round((stats["activos"] / stats["total_clientes"]) * 100)

    seguimientos_pendientes = db.execute("""
        SELECT s.*, c.nombre, c.empresa, c.estado FROM seguimientos s
        JOIN clientes c ON s.cliente_id = c.id
        WHERE s.completado=0 AND s.usuario_id=?
        ORDER BY CASE s.prioridad WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, s.fecha_sugerida
        LIMIT 10
    """, (uid,)).fetchall()

    actividad_reciente = db.execute("""
        SELECT i.*, c.nombre, c.empresa FROM interacciones i
        JOIN clientes c ON i.cliente_id = c.id
        WHERE i.usuario_id=?
        ORDER BY i.fecha DESC LIMIT 8
    """, (uid,)).fetchall()

    clientes_top = db.execute("""
        SELECT c.*,
            (SELECT COUNT(*) FROM interacciones WHERE cliente_id=c.id) as total_interacciones,
            (SELECT COUNT(*) FROM seguimientos WHERE cliente_id=c.id AND completado=0) as seg_pendientes
        FROM clientes c WHERE c.usuario_id=? ORDER BY valor_potencial DESC LIMIT 5
    """, (uid,)).fetchall()

    sector_data = db.execute("""
        SELECT sector, COUNT(*) as total, COALESCE(SUM(valor_potencial),0) as valor
        FROM clientes WHERE usuario_id=? AND sector IS NOT NULL AND sector != ''
        GROUP BY sector ORDER BY valor DESC
    """, (uid,)).fetchall()

    interacciones_semana = db.execute("""
        SELECT date(fecha) as dia, COUNT(*) as total FROM interacciones
        WHERE usuario_id=? AND fecha >= date('now','-6 days')
        GROUP BY dia ORDER BY dia
    """, (uid,)).fetchall()

    user = current_user()
    return render_template("index.html",
        stats=stats, seguimientos_pendientes=seguimientos_pendientes,
        actividad_reciente=actividad_reciente, clientes_top=clientes_top,
        sector_data=sector_data, interacciones_semana=interacciones_semana,
        user=user, today=str(date.today())
    )

@app.route("/clientes")
@login_required
def clientes():
    uid = session["user_id"]
    db = get_db()
    estado = request.args.get("estado", "")
    sector = request.args.get("sector", "")
    q = request.args.get("q", "")
    orden = request.args.get("orden", "valor")

    order_map = {"valor": "c.valor_potencial DESC", "nombre": "c.nombre ASC", "reciente": "c.fecha_creacion DESC"}
    order_sql = order_map.get(orden, "c.valor_potencial DESC")

    query = f"""SELECT c.*,
        (SELECT COUNT(*) FROM interacciones WHERE cliente_id=c.id) as total_interacciones,
        (SELECT MAX(fecha) FROM interacciones WHERE cliente_id=c.id) as ultima_interaccion,
        (SELECT COUNT(*) FROM seguimientos WHERE cliente_id=c.id AND completado=0) as seg_pendientes
        FROM clientes c WHERE c.usuario_id=?"""
    params = [uid]
    if estado:
        query += " AND c.estado=?"; params.append(estado)
    if sector:
        query += " AND c.sector=?"; params.append(sector)
    if q:
        query += " AND (c.nombre LIKE ? OR c.empresa LIKE ?)"; params += [f"%{q}%", f"%{q}%"]
    query += f" ORDER BY {order_sql}"

    clientes_list = db.execute(query, params).fetchall()
    sectores = db.execute("SELECT DISTINCT sector FROM clientes WHERE usuario_id=? AND sector IS NOT NULL AND sector != '' ORDER BY sector", (uid,)).fetchall()
    user = current_user()
    return render_template("clientes.html", clientes=clientes_list, sectores=sectores,
                           filtro_estado=estado, filtro_sector=sector, q=q, orden=orden, user=user)

@app.route("/cliente/<int:cid>")
@login_required
def cliente_detalle(cid):
    uid = session["user_id"]
    db = get_db()
    cliente = db.execute("SELECT * FROM clientes WHERE id=? AND usuario_id=?", (cid, uid)).fetchone()
    if not cliente:
        return redirect(url_for("clientes"))
    interacciones = db.execute("SELECT * FROM interacciones WHERE cliente_id=? ORDER BY fecha DESC", (cid,)).fetchall()
    seguimientos = db.execute("SELECT * FROM seguimientos WHERE cliente_id=? ORDER BY completado, CASE prioridad WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, fecha_sugerida", (cid,)).fetchall()
    user = current_user()
    return render_template("cliente_detalle.html", cliente=cliente, interacciones=interacciones,
                           seguimientos=seguimientos, user=user, today=str(date.today()))

@app.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    uid = session["user_id"]
    db = get_db()
    user = current_user()
    error = success = None
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "perfil":
            nombre = request.form.get("nombre", "").strip()
            if nombre:
                db.execute("UPDATE usuarios SET nombre=? WHERE id=?", (nombre, uid))
                db.commit()
                session["user_nombre"] = nombre
                success = "Perfil actualizado"
        elif accion == "password":
            actual = request.form.get("actual", "")
            nueva = request.form.get("nueva", "")
            nueva2 = request.form.get("nueva2", "")
            if user["password"] != hash_password(actual):
                error = "Contraseña actual incorrecta"
            elif nueva != nueva2:
                error = "Las contraseñas no coinciden"
            elif len(nueva) < 6:
                error = "Mínimo 6 caracteres"
            else:
                db.execute("UPDATE usuarios SET password=? WHERE id=?", (hash_password(nueva), uid))
                db.commit()
                success = "Contraseña actualizada"
        user = current_user()
    stats = {
        "clientes": db.execute("SELECT COUNT(*) FROM clientes WHERE usuario_id=?", (uid,)).fetchone()[0],
        "interacciones": db.execute("SELECT COUNT(*) FROM interacciones WHERE usuario_id=?", (uid,)).fetchone()[0],
        "seguimientos": db.execute("SELECT COUNT(*) FROM seguimientos WHERE usuario_id=?", (uid,)).fetchone()[0],
        "completados": db.execute("SELECT COUNT(*) FROM seguimientos WHERE usuario_id=? AND completado=1", (uid,)).fetchone()[0],
    }
    return render_template("perfil.html", user=user, stats=stats, error=error, success=success)

# ── API ROUTES ────────────────────────────────────────────────────────────────

@app.route("/api/cliente", methods=["POST"])
@login_required
def crear_cliente():
    uid = session["user_id"]
    data = request.json
    db = get_db()
    db.execute("""INSERT INTO clientes (nombre,empresa,email,telefono,sector,estado,valor_potencial,notas,usuario_id)
                  VALUES (?,?,?,?,?,?,?,?,?)""",
               (data["nombre"], data.get("empresa",""), data.get("email",""),
                data.get("telefono",""), data.get("sector",""), data.get("estado","prospecto"),
                float(data.get("valor_potencial",0)), data.get("notas",""), uid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/cliente/<int:cid>", methods=["PUT"])
@login_required
def editar_cliente(cid):
    uid = session["user_id"]
    data = request.json
    db = get_db()
    db.execute("""UPDATE clientes SET nombre=?,empresa=?,email=?,telefono=?,sector=?,estado=?,valor_potencial=?,notas=?
                  WHERE id=? AND usuario_id=?""",
               (data["nombre"], data.get("empresa",""), data.get("email",""),
                data.get("telefono",""), data.get("sector",""), data.get("estado","prospecto"),
                float(data.get("valor_potencial",0)), data.get("notas",""), cid, uid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/cliente/<int:cid>", methods=["DELETE"])
@login_required
def eliminar_cliente(cid):
    uid = session["user_id"]
    db = get_db()
    db.execute("DELETE FROM interacciones WHERE cliente_id=?", (cid,))
    db.execute("DELETE FROM seguimientos WHERE cliente_id=?", (cid,))
    db.execute("DELETE FROM clientes WHERE id=? AND usuario_id=?", (cid, uid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/interaccion", methods=["POST"])
@login_required
def crear_interaccion():
    uid = session["user_id"]
    data = request.json
    db = get_db()
    db.execute("INSERT INTO interacciones (cliente_id,tipo,descripcion,resultado,fecha,usuario_id) VALUES (?,?,?,?,?,?)",
               (data["cliente_id"], data["tipo"], data.get("descripcion",""), data.get("resultado",""), data.get("fecha", str(date.today())), uid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/seguimiento", methods=["POST"])
@login_required
def crear_seguimiento():
    uid = session["user_id"]
    data = request.json
    db = get_db()
    db.execute("INSERT INTO seguimientos (cliente_id,accion,prioridad,fecha_sugerida,generado_ia,usuario_id) VALUES (?,?,?,?,?,?)",
               (data["cliente_id"], data["accion"], data.get("prioridad","media"),
                data.get("fecha_sugerida", str(date.today() + timedelta(days=3))),
                data.get("generado_ia", 0), uid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/seguimiento/<int:sid>/completar", methods=["POST"])
@login_required
def completar_seguimiento(sid):
    uid = session["user_id"]
    db = get_db()
    db.execute("UPDATE seguimientos SET completado=1 WHERE id=? AND usuario_id=?", (sid, uid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/sugerir/<int:cid>")
@login_required
def sugerir_acciones(cid):
    uid = session["user_id"]
    db = get_db()
    cliente = db.execute("SELECT * FROM clientes WHERE id=? AND usuario_id=?", (cid, uid)).fetchone()
    if not cliente:
        return jsonify({"ok": False, "error": "Cliente no encontrado"})

    interacciones = db.execute("SELECT * FROM interacciones WHERE cliente_id=? ORDER BY fecha DESC LIMIT 5", (cid,)).fetchall()
    seguimientos_prev = db.execute("SELECT * FROM seguimientos WHERE cliente_id=? ORDER BY fecha_creacion DESC LIMIT 3", (cid,)).fetchall()

    historial = "\n".join([f"- {i['fecha']} | {i['tipo']} | {i['descripcion']} | Resultado: {i['resultado']}" for i in interacciones])
    seguim_prev = "\n".join([f"- {s['accion']} (prioridad: {s['prioridad']})" for s in seguimientos_prev])

    prompt = f"""Eres un experto en ventas B2B. Analiza este cliente y responde UNICAMENTE con un JSON valido en una sola linea, sin saltos de linea dentro de strings, sin caracteres especiales.

Cliente: {cliente['nombre']}, empresa {cliente['empresa']}, sector {cliente['sector']}, estado {cliente['estado']}, valor {cliente['valor_potencial']}€. Notas: {(cliente['notas'] or '')[:100]}
Interacciones recientes: {historial[:300] if historial else 'ninguna'}

Responde SOLO con este JSON exacto (una sola linea, sin markdown):
{{"sugerencias":[{{"accion":"texto accion 1","prioridad":"alta","razon":"razon breve","dias":3}},{{"accion":"texto accion 2","prioridad":"media","razon":"razon breve","dias":7}},{{"accion":"texto accion 3","prioridad":"baja","razon":"razon breve","dias":14}}]}}"""

    try:
        resp = requests.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}, timeout=90)
        resp.raise_for_status()
        raw = resp.json()["response"].strip()

        # Extraer el bloque JSON más externo
        start = raw.find("{")
        end = raw.rfind("}") + 1
        json_str = raw[start:end]

        # Limpiar caracteres problemáticos: saltos de línea dentro de strings, etc.
        import re
        # Reemplazar saltos de línea dentro de valores string (entre comillas)
        json_str = re.sub(r'[\r\n]+', ' ', json_str)
        # Eliminar comas trailing antes de } o ]
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Fallback: intentar extraer sugerencias con regex si el JSON está roto
            acciones = re.findall(r'"accion"\s*:\s*"([^"]+)"', raw)
            prioridades = re.findall(r'"prioridad"\s*:\s*"([^"]+)"', raw)
            razones = re.findall(r'"razon"\s*:\s*"([^"]+)"', raw)
            dias_list = re.findall(r'"dias"\s*:\s*(\d+)', raw)

            if not acciones:
                return jsonify({"ok": False, "error": "No se pudo parsear la respuesta del modelo. Intenta de nuevo."})

            sugerencias = []
            for i, accion in enumerate(acciones[:3]):
                sugerencias.append({
                    "accion": accion,
                    "prioridad": prioridades[i] if i < len(prioridades) else "media",
                    "razon": razones[i] if i < len(razones) else "Acción recomendada por el análisis del historial",
                    "dias": int(dias_list[i]) if i < len(dias_list) else (i + 1) * 5
                })
            data = {"sugerencias": sugerencias}

        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
