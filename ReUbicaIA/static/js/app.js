"use strict";

/* ReUbica IA: interacción con la interfaz y comunicación con Flask (fetch) */

const ESTADOS_EMPLEADO = ["Activo", "En reubicación", "En capacitación", "Desvinculado"];
const CLASES = { automatizable: "Automatizable", asistida: "Asistida por IA", humana: "Humana" };
const ESTADOS_REC = { pendiente: "Pendiente", aceptada: "Aceptada", rechazada: "Rechazada" };
const ESTADOS_CAP = { sin_iniciar: "Sin iniciar", en_curso: "En curso", completada: "Completada" };
const VISTAS = ["inicio", "empleados", "tareas", "recomendaciones"];

const $ = (selector) => document.querySelector(selector);

const esc = (valor) =>
  String(valor ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

let empleados = [];
let tareas = [];
let resultadoActual = [];   // tarjetas de la última recomendación generada
let aviso = null;

/* ---------- Comunicación con el servidor ---------- */

async function api(url, { method = "GET", body } = {}) {
  const opciones = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opciones.body = JSON.stringify(body);
  const respuesta = await fetch(url, opciones);
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(datos.error || "Ocurrió un error inesperado. Intenta de nuevo.");
  return datos;
}

function avisar(mensaje, esError = false) {
  const caja = $("#aviso");
  caja.textContent = mensaje;
  caja.className = "aviso" + (esError ? " error" : "");
  caja.hidden = false;
  clearTimeout(aviso);
  aviso = setTimeout(() => { caja.hidden = true; }, 4500);
}

function mostrarError(idCaja, mensaje) {
  const caja = $(idCaja);
  caja.textContent = mensaje;
  caja.hidden = !mensaje;
}

/* ---------- Navegación ---------- */

function mostrarVista(desdeUsuario = false) {
  let vista = location.hash.slice(1);
  if (!VISTAS.includes(vista)) vista = "inicio";

  document.querySelectorAll(".vista").forEach((s) => { s.hidden = s.id !== "vista-" + vista; });
  document.querySelectorAll(".menu a").forEach((a) => {
    const activo = a.dataset.vista === vista;
    a.classList.toggle("activo", activo);
    if (activo) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  $("#aviso").hidden = true;
  document.title = $("#vista-" + vista + " h1").textContent + " | ReUbica IA";
  if (desdeUsuario) $("#vista-" + vista + " h1").focus({ preventScroll: true });

  cargarVista(vista).catch((e) => avisar(e.message, true));
}

async function cargarVista(vista) {
  if (vista === "inicio") return cargarInicio();
  if (vista === "empleados") return cargarEmpleados();
  if (vista === "tareas") { await cargarEmpleados(); return cargarTareas(); }
  if (vista === "recomendaciones") {
    await cargarEmpleados();
    await Promise.all([cargarHistorial(), cargarCatalogo()]);
  }
}

/* ---------- Inicio ---------- */

function barra(etiqueta, porcentaje, detalle, meta = null) {
  const marcaMeta = meta === null ? "" : `<span class="marca-meta" style="left:${meta}%" title="Meta: ${meta}\u00a0%"></span>`;
  return `
    <div class="barra-fila">
      <div class="barra-texto"><span>${esc(etiqueta)}</span><span>${esc(detalle)}</span></div>
      <div class="pista" role="img" aria-label="${esc(etiqueta)}: ${porcentaje}\u00a0%">
        <div class="relleno" style="width:${porcentaje}%"></div>${marcaMeta}
      </div>
    </div>`;
}

async function cargarInicio() {
  const d = await api("/api/dashboard");
  const vacio = d.empleados === 0 && d.tareas.total === 0;
  $("#inicio-vacio").hidden = !vacio;
  $("#inicio-datos").hidden = vacio;
  if (vacio) return;

  $("#indicadores").innerHTML = `
    <div class="indicador"><span class="valor">${d.empleados}</span><span class="etiqueta">Empleados registrados</span></div>
    <div class="indicador"><span class="valor">${d.tareas.automatizable}</span><span class="etiqueta">Actividades susceptibles de automatización</span></div>
    <div class="indicador"><span class="valor">${d.recomendaciones.total}</span><span class="etiqueta">Recomendaciones de reubicación generadas</span></div>
    <div class="indicador destacado"><span class="valor">${d.conservan}<small> de ${d.empleados}</small></span><span class="etiqueta">Empleados que conservan su vinculación</span></div>`;

  const t = d.tareas;
  const filas = ["automatizable", "asistida", "humana"].map((clave) => {
    const pct = t.total ? Math.round((t[clave] * 100) / t.total) : 0;
    return `
      <div class="barra-fila">
        <div class="barra-texto"><span>${CLASES[clave]}</span><span>${t[clave]} de ${t.total}</span></div>
        <div class="pista" role="img" aria-label="${CLASES[clave]}: ${pct}\u00a0%">
          <div class="relleno t-${clave}" style="width:${pct}%"></div>
        </div>
      </div>`;
  }).join("");
  $("#grafico-tareas").innerHTML = t.total
    ? filas
    : `<p class="aclaracion">Aún no hay actividades clasificadas. Regístralas en la sección Tareas.</p>`;

  const r = d.recomendaciones;
  $("#metas").innerHTML =
    barra("Permanencia laboral", d.tasas.permanencia, `${d.tasas.permanencia}\u00a0% (meta 100\u00a0%)`, 100) +
    barra("Empleados con alternativas de reubicación", d.tasas.alternativas, `${d.con_alternativa} de ${d.empleados} (meta 80\u00a0%)`, 80) +
    barra("Capacitación completada", d.tasas.capacitacion, `${d.capacitados} de ${d.con_aceptacion} (meta 80\u00a0%)`, 80) +
    barra("Recomendaciones aceptadas", d.tasas.aceptacion, `${r.aceptadas} de ${r.total}`);
}

async function cargarDemo() {
  const boton = $("#btn-demo");
  boton.disabled = true;
  try {
    const r = await api("/api/demo", { method: "POST" });
    avisar(`Se cargaron ${r.empleados} empleados y ${r.tareas} actividades de ejemplo.`);
    await cargarInicio();
  } catch (e) {
    avisar(e.message, true);
  } finally {
    boton.disabled = false;
  }
}

/* ---------- Empleados ---------- */

function claseEstado(estado) {
  return { "Activo": "ok", "En reubicación": "aviso", "En capacitación": "", "Desvinculado": "malo" }[estado] ?? "";
}

async function cargarEmpleados() {
  empleados = await api("/api/empleados");
  dibujarEmpleados();
  llenarSelectEmpleados();
}

function dibujarEmpleados() {
  const filtro = $("#buscar-empleado").value.trim().toLowerCase();
  const lista = empleados.filter((e) => (e.nombre + " " + e.cargo).toLowerCase().includes(filtro));
  $("#tabla-empleados").innerHTML = lista.length
    ? lista.map((e) => `
      <tr>
        <td>${esc(e.nombre)}</td>
        <td>${esc(e.cargo)}</td>
        <td>${esc(e.experiencia)}</td>
        <td>${esc(e.habilidades)}</td>
        <td><span class="insignia ${claseEstado(e.estado)}">${esc(e.estado)}</span></td>
        <td><div class="celda-acciones">
          <button type="button" class="boton secundario chico" data-accion="editar-empleado" data-id="${e.id}">Editar</button>
          <button type="button" class="boton peligro chico" data-accion="borrar-empleado" data-id="${e.id}">Eliminar</button>
        </div></td>
      </tr>`).join("")
    : `<tr><td colspan="6" class="vacio-tabla">${empleados.length ? "Ningún empleado coincide con la búsqueda." : "Aún no hay empleados. Usa el formulario para registrar el primero."}</td></tr>`;
}

function llenarSelectEmpleados() {
  const opciones = (primera) =>
    `<option value="">${primera}</option>` +
    empleados.map((e) => `<option value="${e.id}">${esc(e.nombre)}: ${esc(e.cargo)}</option>`).join("");

  const selRec = $("#rec-empleado");
  const previoRec = selRec.value;
  selRec.innerHTML = opciones("Selecciona un empleado");
  selRec.value = previoRec;

  const selTar = $("#tar-empleado");
  const previoTar = selTar.value;
  selTar.innerHTML = opciones("Sin asignar");
  selTar.value = previoTar;
}

function reiniciarFormEmpleado() {
  $("#form-empleado").reset();
  $("#emp-id").value = "";
  $("#emp-estado").value = "Activo";
  $("#titulo-form-empleado").textContent = "Registrar empleado";
  $("#btn-guardar-empleado").textContent = "Guardar empleado";
  $("#btn-cancelar-empleado").hidden = true;
  mostrarError("#error-empleado", "");
}

function editarEmpleado(id) {
  const e = empleados.find((x) => x.id === id);
  if (!e) return;
  $("#emp-id").value = e.id;
  $("#emp-nombre").value = e.nombre;
  $("#emp-cargo").value = e.cargo;
  $("#emp-experiencia").value = e.experiencia;
  $("#emp-habilidades").value = e.habilidades;
  $("#emp-estado").value = e.estado;
  $("#emp-intereses").value = e.intereses;
  $("#titulo-form-empleado").textContent = "Editar empleado";
  $("#btn-guardar-empleado").textContent = "Guardar cambios";
  $("#btn-cancelar-empleado").hidden = false;
  $("#form-empleado").scrollIntoView({ behavior: "smooth", block: "start" });
  $("#emp-nombre").focus({ preventScroll: true });
}

async function guardarEmpleado(evento) {
  evento.preventDefault();
  const id = $("#emp-id").value;
  const cuerpo = {
    nombre: $("#emp-nombre").value,
    cargo: $("#emp-cargo").value,
    experiencia: $("#emp-experiencia").value,
    habilidades: $("#emp-habilidades").value,
    estado: $("#emp-estado").value,
    intereses: $("#emp-intereses").value,
  };
  try {
    await api(id ? `/api/empleados/${id}` : "/api/empleados", { method: id ? "PUT" : "POST", body: cuerpo });
    avisar(id ? "Cambios guardados." : "Empleado registrado.");
    reiniciarFormEmpleado();
    await cargarEmpleados();
  } catch (e) {
    mostrarError("#error-empleado", e.message);
  }
}

async function borrarEmpleado(id) {
  const e = empleados.find((x) => x.id === id);
  if (!e || !confirm(`¿Eliminar a ${e.nombre}? También se borrarán sus recomendaciones.`)) return;
  try {
    await api(`/api/empleados/${id}`, { method: "DELETE" });
    avisar("Empleado eliminado.");
    if ($("#emp-id").value === String(id)) reiniciarFormEmpleado();
    await cargarEmpleados();
  } catch (err) {
    avisar(err.message, true);
  }
}

/* ---------- Tareas ---------- */

async function cargarTareas() {
  tareas = await api("/api/tareas");
  $("#tabla-tareas").innerHTML = tareas.length
    ? tareas.map((t) => `
      <tr>
        <td><strong>${esc(t.nombre)}</strong>${t.descripcion ? `<br><small>${esc(t.descripcion)}</small>` : ""}</td>
        <td><span class="insignia t-${esc(t.clasificacion)}">${esc(CLASES[t.clasificacion])}</span></td>
        <td>${t.empleado_nombre ? esc(t.empleado_nombre) : "<small>Sin asignar</small>"}</td>
        <td><div class="celda-acciones">
          <button type="button" class="boton secundario chico" data-accion="editar-tarea" data-id="${t.id}">Editar</button>
          <button type="button" class="boton peligro chico" data-accion="borrar-tarea" data-id="${t.id}">Eliminar</button>
        </div></td>
      </tr>`).join("")
    : `<tr><td colspan="4" class="vacio-tabla">Aún no hay actividades. Usa el formulario para registrar la primera.</td></tr>`;
}

function reiniciarFormTarea() {
  $("#form-tarea").reset();
  $("#tar-id").value = "";
  $("#titulo-form-tarea").textContent = "Registrar actividad";
  $("#btn-guardar-tarea").textContent = "Guardar actividad";
  $("#btn-cancelar-tarea").hidden = true;
  mostrarError("#error-tarea", "");
}

function editarTarea(id) {
  const t = tareas.find((x) => x.id === id);
  if (!t) return;
  $("#tar-id").value = t.id;
  $("#tar-nombre").value = t.nombre;
  $("#tar-descripcion").value = t.descripcion;
  $("#tar-clasificacion").value = t.clasificacion;
  $("#tar-empleado").value = t.empleado_id ?? "";
  $("#titulo-form-tarea").textContent = "Editar actividad";
  $("#btn-guardar-tarea").textContent = "Guardar cambios";
  $("#btn-cancelar-tarea").hidden = false;
  $("#form-tarea").scrollIntoView({ behavior: "smooth", block: "start" });
  $("#tar-nombre").focus({ preventScroll: true });
}

async function guardarTarea(evento) {
  evento.preventDefault();
  const id = $("#tar-id").value;
  const cuerpo = {
    nombre: $("#tar-nombre").value,
    descripcion: $("#tar-descripcion").value,
    clasificacion: $("#tar-clasificacion").value,
    empleado_id: $("#tar-empleado").value || null,
  };
  try {
    await api(id ? `/api/tareas/${id}` : "/api/tareas", { method: id ? "PUT" : "POST", body: cuerpo });
    avisar(id ? "Cambios guardados." : "Actividad registrada.");
    reiniciarFormTarea();
    await cargarTareas();
  } catch (e) {
    mostrarError("#error-tarea", e.message);
  }
}

async function borrarTarea(id) {
  const t = tareas.find((x) => x.id === id);
  if (!t || !confirm(`¿Eliminar la actividad "${t.nombre}"?`)) return;
  try {
    await api(`/api/tareas/${id}`, { method: "DELETE" });
    avisar("Actividad eliminada.");
    if ($("#tar-id").value === String(id)) reiniciarFormTarea();
    await cargarTareas();
  } catch (err) {
    avisar(err.message, true);
  }
}

/* ---------- Recomendaciones ---------- */

function opciones(mapa, actual) {
  return Object.entries(mapa)
    .map(([valor, texto]) => `<option value="${valor}"${valor === actual ? " selected" : ""}>${texto}</option>`)
    .join("");
}

function tarjetaRecomendacion(r, indice) {
  const fichasTiene = r.coincidentes.length
    ? r.coincidentes.map((h) => `<span class="ficha tiene">${esc(h)}</span>`).join("")
    : `<span class="ficha ninguna">Ninguna coincide todavía.</span>`;
  const fichasFalta = r.faltantes.length
    ? r.faltantes.map((h) => `<span class="ficha falta">${esc(h)}</span>`).join("")
    : `<span class="ficha ninguna">Cubre todas las competencias del cargo.</span>`;
  const cursos = r.capacitaciones.length
    ? `<ul>${r.capacitaciones.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`
    : `<p>${esc(r.capacitacion)}</p>`;
  const pct = Math.max(0, Math.min(100, Number(r.similitud)));
  const aceptada = r.estado === "aceptada";

  return `
    <article class="rec${indice === 0 ? " mejor" : ""}">
      <div class="rec-cab">
        <div class="rec-titulo">
          ${indice === 0 ? `<span class="insignia">Mayor coincidencia</span>` : ""}
          <h3>${esc(r.cargo)}</h3>
          <p>${esc(r.descripcion)}</p>
        </div>
        <div class="similitud">
          <strong>${Math.round(pct)}\u00a0%</strong>
          <span>Similitud entre textos</span>
          <div class="pista" role="img" aria-label="Similitud ${Math.round(pct)}\u00a0%"><div class="relleno" style="width:${pct}%"></div></div>
        </div>
      </div>
      <div class="rec-cuerpo">
        <div><h4>Habilidades que ya tiene</h4><div class="fichas">${fichasTiene}</div></div>
        <div><h4>Habilidades por fortalecer</h4><div class="fichas">${fichasFalta}</div></div>
        <div><h4>Capacitación recomendada</h4>${cursos}</div>
      </div>
      <div class="rec-pie">
        <button type="button" class="boton chico" data-accion="rec-estado" data-id="${r.id}" data-valor="aceptada">Aceptar</button>
        <button type="button" class="boton peligro chico" data-accion="rec-estado" data-id="${r.id}" data-valor="rechazada">Rechazar</button>
        <button type="button" class="boton secundario chico" data-accion="rec-estado" data-id="${r.id}" data-valor="pendiente">Dejar pendiente</button>
        <span class="insignia ${r.estado === "aceptada" ? "ok" : r.estado === "rechazada" ? "malo" : "aviso"}">${ESTADOS_REC[r.estado]}</span>
        <div class="campo">
          <label for="cap-${r.id}">Capacitación</label>
          <select id="cap-${r.id}" data-accion="rec-capacitacion" data-id="${r.id}"${aceptada ? "" : " disabled"}>${opciones(ESTADOS_CAP, r.capacitacion_estado)}</select>
        </div>
      </div>
    </article>`;
}

function dibujarResultado() {
  $("#resultado-tarjetas").innerHTML = resultadoActual.map(tarjetaRecomendacion).join("");
}

async function analizarPerfil(evento) {
  evento.preventDefault();
  mostrarError("#error-analisis", "");
  const id = $("#rec-empleado").value;
  if (!id) return mostrarError("#error-analisis", "Selecciona un empleado para analizar su perfil.");
  const boton = $("#btn-analizar");
  boton.disabled = true;
  try {
    const r = await api("/api/recomendaciones", { method: "POST", body: { empleado_id: Number(id) } });
    resultadoActual = r.recomendaciones;
    $("#resultado-titulo").textContent = "Resultados de ReUbica IA para " + r.empleado.nombre;
    $("#resultado-ia").hidden = false;
    dibujarResultado();
    await cargarHistorial();
  } catch (e) {
    mostrarError("#error-analisis", e.message);
  } finally {
    boton.disabled = false;
  }
}

async function actualizarRecomendacion(id, cambios) {
  try {
    const nueva = await api(`/api/recomendaciones/${id}`, { method: "PUT", body: cambios });
    const i = resultadoActual.findIndex((r) => r.id === id);
    if (i >= 0) {
      resultadoActual[i].estado = nueva.estado;
      resultadoActual[i].capacitacion_estado = nueva.capacitacion_estado;
      dibujarResultado();
    }
    await cargarHistorial();
  } catch (e) {
    avisar(e.message, true);
  }
}

async function cargarHistorial() {
  const filas = await api("/api/recomendaciones");
  $("#tabla-recomendaciones").innerHTML = filas.length
    ? filas.map((r) => `
      <tr>
        <td>${esc(r.empleado_nombre)}</td>
        <td>${esc(r.cargo_sugerido)}</td>
        <td>${Math.round(r.similitud)}\u00a0%</td>
        <td><select aria-label="Revisión de ${esc(r.cargo_sugerido)} para ${esc(r.empleado_nombre)}" data-accion="hist-estado" data-id="${r.id}">${opciones(ESTADOS_REC, r.estado)}</select></td>
        <td><select aria-label="Capacitación de ${esc(r.empleado_nombre)}" data-accion="hist-capacitacion" data-id="${r.id}"${r.estado === "aceptada" ? "" : " disabled"}>${opciones(ESTADOS_CAP, r.capacitacion_estado)}</select></td>
        <td><button type="button" class="boton peligro chico" data-accion="borrar-rec" data-id="${r.id}">Quitar</button></td>
      </tr>`).join("")
    : `<tr><td colspan="6" class="vacio-tabla">Aún no hay decisiones. Analiza un perfil para generar recomendaciones.</td></tr>`;
}

async function borrarRecomendacion(id) {
  if (!confirm("¿Quitar esta recomendación del registro?")) return;
  try {
    await api(`/api/recomendaciones/${id}`, { method: "DELETE" });
    resultadoActual = resultadoActual.filter((r) => r.id !== id);
    dibujarResultado();
    if (!resultadoActual.length) $("#resultado-ia").hidden = true;
    await cargarHistorial();
  } catch (e) {
    avisar(e.message, true);
  }
}

async function cargarCatalogo() {
  const cargos = await api("/api/cargos");
  $("#catalogo-cargos").innerHTML = cargos.map((c) => `
    <div class="cargo-item">
      <h3>${esc(c.nombre)}</h3>
      <p>${esc(c.descripcion)}</p>
      <div class="fichas">${c.competencias.map((x) => `<span class="ficha tiene">${esc(x)}</span>`).join("")}</div>
    </div>`).join("");
}

/* ---------- Eventos ---------- */

document.addEventListener("click", (evento) => {
  const boton = evento.target.closest("[data-accion]");
  if (!boton || boton.tagName === "SELECT") return;
  const id = Number(boton.dataset.id);
  switch (boton.dataset.accion) {
    case "editar-empleado": return editarEmpleado(id);
    case "borrar-empleado": return borrarEmpleado(id);
    case "editar-tarea": return editarTarea(id);
    case "borrar-tarea": return borrarTarea(id);
    case "borrar-rec": return borrarRecomendacion(id);
    case "rec-estado": return actualizarRecomendacion(id, { estado: boton.dataset.valor });
  }
});

document.addEventListener("change", (evento) => {
  const campo = evento.target.closest("select[data-accion]");
  if (!campo) return;
  const id = Number(campo.dataset.id);
  switch (campo.dataset.accion) {
    case "rec-capacitacion":
    case "hist-capacitacion": return actualizarRecomendacion(id, { capacitacion_estado: campo.value });
    case "hist-estado": return actualizarRecomendacion(id, { estado: campo.value });
  }
});

$("#form-empleado").addEventListener("submit", guardarEmpleado);
$("#btn-cancelar-empleado").addEventListener("click", reiniciarFormEmpleado);
$("#form-tarea").addEventListener("submit", guardarTarea);
$("#btn-cancelar-tarea").addEventListener("click", reiniciarFormTarea);
$("#form-analisis").addEventListener("submit", analizarPerfil);
$("#buscar-empleado").addEventListener("input", dibujarEmpleados);
$("#btn-demo").addEventListener("click", cargarDemo);
window.addEventListener("hashchange", () => mostrarVista(true));

$("#emp-estado").innerHTML = ESTADOS_EMPLEADO.map((e) => `<option>${e}</option>`).join("");
mostrarVista(false);
