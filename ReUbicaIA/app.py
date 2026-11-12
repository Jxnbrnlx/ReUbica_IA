"""ReUbica IA: servidor Flask, base de datos SQLite y motor de recomendación.

Ejecutar con:  python app.py   y abrir  http://127.0.0.1:5000
"""
import os
import re
import sqlite3
import unicodedata

from flask import Flask, g, jsonify, render_template, request
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "reubicai.db")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Catálogos definidos directamente en Python (no necesitan tablas propias)
# ---------------------------------------------------------------------------

ESTADOS_EMPLEADO = ["Activo", "En reubicación", "En capacitación", "Desvinculado"]
CLASIFICACIONES = ["automatizable", "asistida", "humana"]
ESTADOS_REC = ["pendiente", "aceptada", "rechazada"]
ESTADOS_CAP = ["sin_iniciar", "en_curso", "completada"]

CARGOS = [
    {
        "nombre": "Asesor/a de seguimiento",
        "descripcion": "Acompaña a los clientes después de la primera atención y verifica que su solicitud avance.",
        "competencias": ["comunicación", "organización", "atención al cliente", "CRM"],
    },
    {
        "nombre": "Verificador/a de calidad",
        "descripcion": "Revisa respuestas y procesos para confirmar que cumplen los estándares de la empresa.",
        "competencias": ["organización", "redacción", "atención al detalle", "análisis"],
    },
    {
        "nombre": "Gestor/a de casos complejos",
        "descripcion": "Atiende reclamos y situaciones que la automatización no puede resolver.",
        "competencias": ["comunicación", "negociación", "resolución de problemas", "servicio al cliente"],
    },
    {
        "nombre": "Asistente de procesos digitales",
        "descripcion": "Apoya el funcionamiento diario de las herramientas y los flujos de trabajo digitales.",
        "competencias": ["organización", "herramientas digitales", "análisis", "gestión de información"],
    },
    {
        "nombre": "Supervisor/a de procesos automatizados",
        "descripcion": "Vigila los resultados de las herramientas automáticas y corrige los errores que detecta.",
        "competencias": ["supervisión", "herramientas digitales", "análisis", "resolución de problemas"],
    },
]

CURSOS = {
    "crm": "Introducción a herramientas CRM y seguimiento de clientes",
    "negociacion": "Taller de negociación y manejo de objeciones",
    "herramientas digitales": "Herramientas digitales para la oficina: hojas de cálculo y trabajo en la nube",
    "analisis": "Fundamentos de análisis de datos para procesos de servicio",
    "redaccion": "Redacción clara para la atención al cliente",
    "atencion al detalle": "Revisión y control de calidad de procesos",
    "gestion de informacion": "Gestión y organización de la información empresarial",
    "supervision": "Supervisión de procesos automatizados",
    "resolucion de problemas": "Resolución de problemas y manejo de casos complejos",
    "comunicacion": "Comunicación efectiva con clientes",
    "organizacion": "Organización del trabajo y gestión del tiempo",
    "atencion al cliente": "Fundamentos de atención al cliente",
    "servicio al cliente": "Servicio al cliente y experiencia del usuario",
}

STOPWORDS = ["de", "del", "la", "el", "los", "las", "y", "e", "o", "u", "en", "con",
             "para", "por", "un", "una", "al", "a", "que", "se"]


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def cerrar_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS empleados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cargo TEXT NOT NULL,
            experiencia TEXT NOT NULL DEFAULT '',
            habilidades TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'Activo',
            intereses TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            descripcion TEXT NOT NULL DEFAULT '',
            clasificacion TEXT NOT NULL,
            empleado_id INTEGER REFERENCES empleados(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS recomendaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
            cargo_sugerido TEXT NOT NULL,
            similitud REAL NOT NULL,
            faltantes TEXT NOT NULL DEFAULT '',
            capacitacion TEXT NOT NULL DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'pendiente',
            capacitacion_estado TEXT NOT NULL DEFAULT 'sin_iniciar',
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def normalizar(texto):
    """Minúsculas, sin tildes ni signos, con espacios simples."""
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return " ".join(texto.split())


def limpiar(valor, maximo):
    return str(valor if valor is not None else "").strip()[:maximo]


def separar_habilidades(texto):
    """Convierte 'a, b y c' en ['a', 'b', 'c'] sin repetidos."""
    partes = re.split(r"[,;\n]|\s+y\s+", texto or "", flags=re.IGNORECASE)
    vistas, resultado = set(), []
    for parte in partes:
        parte = parte.strip()
        clave = normalizar(parte)
        if clave and clave not in vistas:
            vistas.add(clave)
            resultado.append(parte)
    return resultado


def error(mensaje, codigo=400):
    return jsonify(error=mensaje), codigo


# ---------------------------------------------------------------------------
# Motor de recomendación (TF-IDF + similitud del coseno con Scikit-learn)
# ---------------------------------------------------------------------------

def habilidad_cubierta(competencia, habilidades_norm):
    """Indica si alguna habilidad del empleado cubre la competencia del cargo."""
    comp = normalizar(competencia)
    palabras_comp = set(comp.split()) - set(STOPWORDS)
    for hab in habilidades_norm:
        if len(hab) < 3:
            continue
        if comp == hab or comp in hab or hab in comp:
            return True
        palabras_hab = set(hab.split()) - set(STOPWORDS)
        if palabras_comp and len(palabras_comp & palabras_hab) / len(palabras_comp) >= 0.67:
            return True
    return False


def recomendar(empleado, limite=3):
    """Ordena los cargos disponibles según su similitud con el perfil del empleado."""
    cargo_actual = normalizar(empleado["cargo"])
    cargos = [c for c in CARGOS if normalizar(c["nombre"]) != cargo_actual]
    if not cargos:
        return []

    habilidades = separar_habilidades(empleado["habilidades"])
    habilidades_norm = [normalizar(h) for h in habilidades]

    # 1. Un texto por cargo (sus competencias) y un texto para el empleado.
    textos_cargos = [", ".join(c["competencias"]) for c in cargos]
    perfil = " ".join([empleado["habilidades"], empleado.get("intereses") or "", empleado["cargo"]])

    # 2. TF-IDF convierte los textos en vectores numéricos.
    vectorizador = TfidfVectorizer(preprocessor=normalizar, stop_words=STOPWORDS, ngram_range=(1, 2))
    matriz = vectorizador.fit_transform(textos_cargos + [perfil])

    # 3. La similitud del coseno compara el perfil (última fila) con cada cargo.
    similitudes = cosine_similarity(matriz[-1], matriz[:-1]).flatten()

    # 4. Se ordena del más compatible al menos compatible.
    orden = sorted(range(len(cargos)), key=lambda i: similitudes[i], reverse=True)[:limite]

    resultados = []
    for i in orden:
        cargo = cargos[i]
        coincidentes = [c for c in cargo["competencias"] if habilidad_cubierta(c, habilidades_norm)]
        faltantes = [c for c in cargo["competencias"] if c not in coincidentes]
        capacitaciones = [
            CURSOS.get(normalizar(f), "Curso introductorio de " + f) for f in faltantes
        ]
        resultados.append({
            "cargo": cargo["nombre"],
            "descripcion": cargo["descripcion"],
            "similitud": round(float(similitudes[i]) * 100, 1),
            "coincidentes": coincidentes,
            "faltantes": faltantes,
            "capacitaciones": capacitaciones,
            "capacitacion": "; ".join(capacitaciones)
            or "No necesita capacitación adicional para las competencias de este cargo.",
        })
    return resultados


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

@app.get("/")
def inicio():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Empleados
# ---------------------------------------------------------------------------

def leer_empleado(datos):
    nombre = limpiar(datos.get("nombre"), 120)
    cargo = limpiar(datos.get("cargo"), 120)
    experiencia = limpiar(datos.get("experiencia"), 60)
    habilidades = ", ".join(separar_habilidades(limpiar(datos.get("habilidades"), 600)))
    estado = limpiar(datos.get("estado") or "Activo", 30)
    intereses = limpiar(datos.get("intereses"), 300)
    if not nombre or not cargo or not habilidades:
        return None, "El nombre, el cargo actual y las habilidades son obligatorios."
    if estado not in ESTADOS_EMPLEADO:
        return None, "El estado laboral no es válido."
    return (nombre, cargo, experiencia, habilidades, estado, intereses), None


@app.get("/api/empleados")
def listar_empleados():
    filas = get_db().execute("SELECT * FROM empleados ORDER BY nombre COLLATE NOCASE").fetchall()
    return jsonify([dict(f) for f in filas])


@app.post("/api/empleados")
def crear_empleado():
    valores, problema = leer_empleado(request.get_json(silent=True) or {})
    if problema:
        return error(problema)
    db = get_db()
    cur = db.execute(
        "INSERT INTO empleados (nombre, cargo, experiencia, habilidades, estado, intereses) "
        "VALUES (?, ?, ?, ?, ?, ?)", valores)
    db.commit()
    fila = db.execute("SELECT * FROM empleados WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(fila)), 201


@app.put("/api/empleados/<int:emp_id>")
def modificar_empleado(emp_id):
    valores, problema = leer_empleado(request.get_json(silent=True) or {})
    if problema:
        return error(problema)
    db = get_db()
    cur = db.execute(
        "UPDATE empleados SET nombre=?, cargo=?, experiencia=?, habilidades=?, estado=?, intereses=? "
        "WHERE id=?", valores + (emp_id,))
    db.commit()
    if cur.rowcount == 0:
        return error("El empleado no existe.", 404)
    fila = db.execute("SELECT * FROM empleados WHERE id = ?", (emp_id,)).fetchone()
    return jsonify(dict(fila))


@app.delete("/api/empleados/<int:emp_id>")
def eliminar_empleado(emp_id):
    db = get_db()
    cur = db.execute("DELETE FROM empleados WHERE id = ?", (emp_id,))
    db.commit()
    if cur.rowcount == 0:
        return error("El empleado no existe.", 404)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Tareas
# ---------------------------------------------------------------------------

def leer_tarea(datos, db):
    nombre = limpiar(datos.get("nombre"), 160)
    descripcion = limpiar(datos.get("descripcion"), 400)
    clasificacion = limpiar(datos.get("clasificacion"), 20)
    if not nombre:
        return None, "El nombre de la actividad es obligatorio."
    if clasificacion not in CLASIFICACIONES:
        return None, "Elige una clasificación: automatizable, asistida por IA o humana."
    empleado_id = datos.get("empleado_id")
    if empleado_id in (None, "", 0, "0"):
        empleado_id = None
    else:
        try:
            empleado_id = int(empleado_id)
        except (TypeError, ValueError):
            return None, "El empleado seleccionado no es válido."
        if not db.execute("SELECT 1 FROM empleados WHERE id = ?", (empleado_id,)).fetchone():
            return None, "El empleado seleccionado no existe."
    return (nombre, descripcion, clasificacion, empleado_id), None


CONSULTA_TAREAS = (
    "SELECT t.*, e.nombre AS empleado_nombre FROM tareas t "
    "LEFT JOIN empleados e ON e.id = t.empleado_id"
)


@app.get("/api/tareas")
def listar_tareas():
    filas = get_db().execute(CONSULTA_TAREAS + " ORDER BY t.id DESC").fetchall()
    return jsonify([dict(f) for f in filas])


@app.post("/api/tareas")
def crear_tarea():
    db = get_db()
    valores, problema = leer_tarea(request.get_json(silent=True) or {}, db)
    if problema:
        return error(problema)
    cur = db.execute(
        "INSERT INTO tareas (nombre, descripcion, clasificacion, empleado_id) VALUES (?, ?, ?, ?)", valores)
    db.commit()
    fila = db.execute(CONSULTA_TAREAS + " WHERE t.id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(fila)), 201


@app.put("/api/tareas/<int:tarea_id>")
def modificar_tarea(tarea_id):
    db = get_db()
    valores, problema = leer_tarea(request.get_json(silent=True) or {}, db)
    if problema:
        return error(problema)
    cur = db.execute(
        "UPDATE tareas SET nombre=?, descripcion=?, clasificacion=?, empleado_id=? WHERE id=?",
        valores + (tarea_id,))
    db.commit()
    if cur.rowcount == 0:
        return error("La actividad no existe.", 404)
    fila = db.execute(CONSULTA_TAREAS + " WHERE t.id = ?", (tarea_id,)).fetchone()
    return jsonify(dict(fila))


@app.delete("/api/tareas/<int:tarea_id>")
def eliminar_tarea(tarea_id):
    db = get_db()
    cur = db.execute("DELETE FROM tareas WHERE id = ?", (tarea_id,))
    db.commit()
    if cur.rowcount == 0:
        return error("La actividad no existe.", 404)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Recomendaciones
# ---------------------------------------------------------------------------

@app.get("/api/cargos")
def listar_cargos():
    return jsonify(CARGOS)


@app.post("/api/recomendaciones")
def generar_recomendaciones():
    datos = request.get_json(silent=True) or {}
    try:
        emp_id = int(datos.get("empleado_id"))
    except (TypeError, ValueError):
        return error("Selecciona un empleado.")
    db = get_db()
    empleado = db.execute("SELECT * FROM empleados WHERE id = ?", (emp_id,)).fetchone()
    if not empleado:
        return error("El empleado no existe.", 404)

    resultados = recomendar(dict(empleado))

    # Se reemplazan las sugerencias que aún no fueron revisadas; las ya
    # revisadas o con capacitación en marcha se conservan.
    db.execute(
        "DELETE FROM recomendaciones WHERE empleado_id = ? "
        "AND estado = 'pendiente' AND capacitacion_estado = 'sin_iniciar'", (emp_id,))
    existentes = {f["cargo_sugerido"]: f for f in db.execute(
        "SELECT * FROM recomendaciones WHERE empleado_id = ?", (emp_id,))}

    for r in resultados:
        previa = existentes.get(r["cargo"])
        if previa:
            r.update(id=previa["id"], estado=previa["estado"],
                     capacitacion_estado=previa["capacitacion_estado"])
        else:
            cur = db.execute(
                "INSERT INTO recomendaciones (empleado_id, cargo_sugerido, similitud, faltantes, capacitacion) "
                "VALUES (?, ?, ?, ?, ?)",
                (emp_id, r["cargo"], r["similitud"], ", ".join(r["faltantes"]), r["capacitacion"]))
            r.update(id=cur.lastrowid, estado="pendiente", capacitacion_estado="sin_iniciar")
    db.commit()
    return jsonify(empleado=dict(empleado), recomendaciones=resultados)


CONSULTA_RECS = (
    "SELECT r.*, e.nombre AS empleado_nombre FROM recomendaciones r "
    "JOIN empleados e ON e.id = r.empleado_id"
)


@app.get("/api/recomendaciones")
def listar_recomendaciones():
    filas = get_db().execute(CONSULTA_RECS + " ORDER BY r.id DESC").fetchall()
    return jsonify([dict(f) for f in filas])


@app.put("/api/recomendaciones/<int:rec_id>")
def revisar_recomendacion(rec_id):
    datos = request.get_json(silent=True) or {}
    db = get_db()
    rec = db.execute("SELECT * FROM recomendaciones WHERE id = ?", (rec_id,)).fetchone()
    if not rec:
        return error("La recomendación no existe.", 404)
    estado = datos.get("estado", rec["estado"])
    cap = datos.get("capacitacion_estado", rec["capacitacion_estado"])
    if estado not in ESTADOS_REC:
        return error("El estado de revisión no es válido.")
    if cap not in ESTADOS_CAP:
        return error("El estado de la capacitación no es válido.")
    if estado != "aceptada":
        cap = "sin_iniciar"  # solo se capacita a quien aceptó la recomendación
    db.execute("UPDATE recomendaciones SET estado = ?, capacitacion_estado = ? WHERE id = ?",
               (estado, cap, rec_id))
    db.commit()
    fila = db.execute(CONSULTA_RECS + " WHERE r.id = ?", (rec_id,)).fetchone()
    return jsonify(dict(fila))


@app.delete("/api/recomendaciones/<int:rec_id>")
def eliminar_recomendacion(rec_id):
    db = get_db()
    cur = db.execute("DELETE FROM recomendaciones WHERE id = ?", (rec_id,))
    db.commit()
    if cur.rowcount == 0:
        return error("La recomendación no existe.", 404)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Indicadores del dashboard
# ---------------------------------------------------------------------------

def porcentaje(parte, total):
    return round(parte * 100 / total) if total else 0


@app.get("/api/dashboard")
def dashboard():
    db = get_db()

    def uno(sql):
        return db.execute(sql).fetchone()[0]

    total = uno("SELECT COUNT(*) FROM empleados")
    desvinculados = uno("SELECT COUNT(*) FROM empleados WHERE estado = 'Desvinculado'")
    conservan = total - desvinculados

    tareas = {c: 0 for c in CLASIFICACIONES}
    for fila in db.execute("SELECT clasificacion, COUNT(*) AS n FROM tareas GROUP BY clasificacion"):
        tareas[fila["clasificacion"]] = fila["n"]
    tareas["total"] = sum(tareas.values())

    recs = {
        "total": uno("SELECT COUNT(*) FROM recomendaciones"),
        "pendientes": uno("SELECT COUNT(*) FROM recomendaciones WHERE estado = 'pendiente'"),
        "aceptadas": uno("SELECT COUNT(*) FROM recomendaciones WHERE estado = 'aceptada'"),
        "rechazadas": uno("SELECT COUNT(*) FROM recomendaciones WHERE estado = 'rechazada'"),
    }
    con_alternativa = uno("SELECT COUNT(DISTINCT empleado_id) FROM recomendaciones")
    con_aceptacion = uno("SELECT COUNT(DISTINCT empleado_id) FROM recomendaciones WHERE estado = 'aceptada'")
    capacitados = uno(
        "SELECT COUNT(DISTINCT empleado_id) FROM recomendaciones "
        "WHERE estado = 'aceptada' AND capacitacion_estado = 'completada'")

    return jsonify(
        empleados=total,
        conservan=conservan,
        desvinculados=desvinculados,
        tareas=tareas,
        recomendaciones=recs,
        con_alternativa=con_alternativa,
        con_aceptacion=con_aceptacion,
        capacitados=capacitados,
        tasas={
            "permanencia": porcentaje(conservan, total),
            "alternativas": porcentaje(con_alternativa, total),
            "capacitacion": porcentaje(capacitados, con_aceptacion),
            "aceptacion": porcentaje(recs["aceptadas"], recs["total"]),
        },
    )


# ---------------------------------------------------------------------------
# Datos de ejemplo: empresa ficticia de atención al cliente con 20 trabajadores
# ---------------------------------------------------------------------------

DEMO_EMPLEADOS = [
    ("Ana Martínez", "Auxiliar de atención al cliente", "2 años", "Comunicación, organización, resolución de problemas, atención al cliente", "Atención especializada y seguimiento"),
    ("Carlos Ramírez", "Clasificador de solicitudes", "3 años", "Organización, atención al detalle, redacción, registro de datos", "Control de calidad"),
    ("Laura Gómez", "Digitadora de datos", "1 año", "Digitación, organización, herramientas digitales, gestión de información", "Procesos digitales"),
    ("Andrés Torres", "Auxiliar de atención al cliente", "4 años", "Comunicación, negociación, servicio al cliente, resolución de problemas", "Casos complejos"),
    ("Camila Rojas", "Auxiliar administrativa", "2 años", "Organización, redacción, herramientas digitales, atención al detalle", "Calidad y documentación"),
    ("Julián Herrera", "Clasificador de solicitudes", "1 año", "Organización, comunicación, registro de datos", "Seguimiento de clientes"),
    ("Valentina Cruz", "Auxiliar de atención al cliente", "5 años", "Comunicación, atención al cliente, CRM, organización", "Seguimiento de clientes"),
    ("Sebastián Ortiz", "Digitador de datos", "3 años", "Digitación, análisis, gestión de información, herramientas digitales", "Supervisión de procesos automatizados"),
    ("Daniela Vargas", "Asistente de correspondencia", "2 años", "Redacción, organización, atención al detalle, comunicación", "Control de calidad"),
    ("Mateo Castro", "Auxiliar de atención al cliente", "1 año", "Comunicación, servicio al cliente, organización", "Atención especializada"),
    ("Natalia Moreno", "Clasificadora de solicitudes", "4 años", "Organización, análisis, atención al detalle, resolución de problemas", "Procesos digitales"),
    ("Felipe Díaz", "Auxiliar administrativo", "3 años", "Organización, herramientas digitales, gestión de información, análisis", "Procesos digitales"),
    ("Isabela Peña", "Auxiliar de atención al cliente", "3 años", "Comunicación, negociación, atención al cliente, resolución de problemas", "Casos complejos"),
    ("Santiago Ruiz", "Digitador de datos", "2 años", "Digitación, organización, atención al detalle", "Control de calidad"),
    ("Mariana Silva", "Asistente de soporte", "6 años", "Comunicación, resolución de problemas, servicio al cliente, liderazgo", "Supervisión de procesos automatizados"),
    ("David Ríos", "Clasificador de solicitudes", "2 años", "Organización, comunicación, herramientas digitales", "Seguimiento de clientes"),
    ("Paula Mendoza", "Auxiliar de atención al cliente", "2 años", "Comunicación, organización, atención al cliente, redacción", "Seguimiento de clientes"),
    ("Nicolás Parra", "Auxiliar administrativo", "1 año", "Organización, registro de datos, comunicación", "Atención especializada"),
    ("Sofía Cárdenas", "Digitadora de datos", "4 años", "Digitación, gestión de información, análisis, redacción", "Calidad y documentación"),
    ("Tomás Aguirre", "Asistente de soporte", "3 años", "Comunicación, negociación, servicio al cliente, organización", "Casos complejos"),
]

DEMO_TAREAS = [
    ("Clasificación inicial de solicitudes", "Leer cada solicitud y asignarle una categoría.", "automatizable", "Carlos Ramírez"),
    ("Registro de datos de clientes", "Pasar los datos de formularios al sistema.", "automatizable", "Laura Gómez"),
    ("Respuesta a preguntas frecuentes", "Responder consultas repetidas por correo y chat.", "automatizable", "Mateo Castro"),
    ("Organización de correos y archivos", "Ordenar la información recibida cada día.", "automatizable", "Camila Rojas"),
    ("Redacción de respuestas iniciales", "Preparar un primer borrador de respuesta.", "asistida", "Ana Martínez"),
    ("Preparación de informes semanales", "Reunir cifras y resumir los casos atendidos.", "asistida", "Sebastián Ortiz"),
    ("Búsqueda de información de pedidos", "Consultar el estado de un pedido en varios sistemas.", "asistida", "Paula Mendoza"),
    ("Atención de casos complejos", "Resolver reclamos que requieren criterio propio.", "humana", "Andrés Torres"),
    ("Negociación con clientes en reclamo", "Acordar soluciones con clientes inconformes.", "humana", "Isabela Peña"),
    ("Resolución de conflictos", "Mediar cuando un caso escala o se bloquea.", "humana", "Mariana Silva"),
]


@app.post("/api/demo")
def cargar_demo():
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM empleados").fetchone()[0] > 0:
        return error("Ya hay empleados registrados. Elimínalos antes de cargar el ejemplo.", 409)
    ids = {}
    for nombre, cargo, exp, habs, intereses in DEMO_EMPLEADOS:
        cur = db.execute(
            "INSERT INTO empleados (nombre, cargo, experiencia, habilidades, estado, intereses) "
            "VALUES (?, ?, ?, ?, 'Activo', ?)", (nombre, cargo, exp, habs, intereses))
        ids[nombre] = cur.lastrowid
    for nombre, desc, clase, responsable in DEMO_TAREAS:
        db.execute(
            "INSERT INTO tareas (nombre, descripcion, clasificacion, empleado_id) VALUES (?, ?, ?, ?)",
            (nombre, desc, clase, ids.get(responsable)))
    db.commit()
    return jsonify(empleados=len(DEMO_EMPLEADOS), tareas=len(DEMO_TAREAS)), 201


init_db()

if __name__ == "__main__":
    app.run(debug=True)
