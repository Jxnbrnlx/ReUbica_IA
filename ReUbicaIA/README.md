# ReUbica IA

Plataforma web para identificar tareas automatizables, recomendar nuevos cargos y sugerir capacitaciones
a los empleados. Prototipo académico con datos ficticios.

**Tecnologías:** HTML, CSS, JavaScript y Python (Flask, SQLite, Scikit-learn).

## Cómo ejecutarla

1. Instala Python 3.9 o superior.
2. Abre una terminal en la carpeta `ReUbicaIA` (por ejemplo, desde Visual Studio Code).
3. Crea y activa un entorno virtual:

   ```
   python -m venv venv
   venv\Scripts\activate        (Windows)
   source venv/bin/activate     (macOS o Linux)
   ```
4. Instala las bibliotecas:

   ```
   pip install -r requirements.txt
   ```
5. Inicia el servidor:

   ```
   python app.py
   ```
6. Abre http://127.0.0.1:5000 en el navegador.

La base de datos `reubicai.db` se crea sola la primera vez. Para empezar con datos, pulsa
**Cargar datos de ejemplo** en la sección Inicio (20 empleados y 10 actividades ficticias).
Para reiniciar todo, detén el servidor y borra el archivo `reubicai.db`.

## Estructura

```
ReUbicaIA/
  app.py              Servidor Flask, rutas, SQLite y motor de recomendación
  requirements.txt    Bibliotecas necesarias
  templates/
    index.html        Interfaz (Inicio, Empleados, Tareas, Recomendaciones IA)
  static/
    css/style.css     Diseño visual
    js/app.js         Interactividad y comunicación con fetch()
```

## Cómo funciona la IA

La función `recomendar()` de `app.py` hace lo siguiente:

1. Toma las habilidades, los intereses y el cargo actual del empleado.
2. Toma las competencias de cada cargo del catálogo `CARGOS`.
3. `TfidfVectorizer` (Scikit-learn) convierte esos textos en vectores numéricos.
4. `cosine_similarity` compara el perfil con cada cargo.
5. Ordena los cargos de mayor a menor similitud (se muestran los tres primeros).
6. Compara las habilidades del empleado con las del cargo para hallar las que faltan.
7. Busca en el diccionario `CURSOS` una capacitación para cada habilidad faltante.

El porcentaje es una similitud entre textos, no la probabilidad de éxito en el cargo. El sistema solo sugiere:
el administrador y el empleado revisan cada recomendación y registran la decisión.

Para agregar cargos o cursos, edita `CARGOS` y `CURSOS` en `app.py`.

## Rutas de la API

| Solicitud | Ruta | Función |
|-----------|------|---------|
| GET | /api/empleados | Consultar empleados |
| POST | /api/empleados | Registrar un empleado |
| PUT | /api/empleados/<id> | Modificar un empleado |
| DELETE | /api/empleados/<id> | Eliminar un empleado |
| GET | /api/tareas | Consultar actividades |
| POST | /api/tareas | Registrar una actividad |
| PUT, DELETE | /api/tareas/<id> | Modificar o eliminar una actividad |
| POST | /api/recomendaciones | Ejecutar el motor de IA para un empleado |
| GET | /api/recomendaciones | Consultar las decisiones registradas |
| PUT, DELETE | /api/recomendaciones/<id> | Aceptar, rechazar, registrar capacitación o quitar |
| GET | /api/cargos | Consultar el catálogo de cargos |
| GET | /api/dashboard | Indicadores del Inicio |
| POST | /api/demo | Cargar datos de ejemplo |
