"use strict";

const API = "";

// ── utilidades ────────────────────────────────────────────────────────────
async function getJSON(url) {
  const r = await fetch(API + url);
  return r.json();
}
async function postJSON(url, body) {
  const r = await fetch(API + url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

const COLOR_GRAVEDAD = { critica: "#f38ba8", importante: "#fab387", menor: "#a6e3a1" };

// ── navegación por pestañas (con hash bookmarkable, p. ej. #hallazgos) ──
function irATab(nombre) {
  const btn = document.querySelector(`.tab[data-tab="${nombre}"]`);
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("activa"));
  document.querySelectorAll(".vista").forEach((v) => v.classList.remove("activa"));
  btn.classList.add("activa");
  document.getElementById("vista-" + nombre).classList.add("activa");
  if (nombre === "hallazgos") cargarHallazgos();
  if (nombre === "ajustes") cargarAjustesFiltro();
  if (nombre === "entregables") actualizarEstado();
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    location.hash = btn.dataset.tab;
  });
});

window.addEventListener("hashchange", () => {
  irATab(location.hash.slice(1) || "revision");
});

if (location.hash) irATab(location.hash.slice(1));

// ── estado local del PDF cargado ────────────────────────────────────────
let pdfActual = null; // { ruta_pdf, nombre, num_paginas }
let hallazgosCache = [];
let filtroGravedad = new Set(["critica", "importante", "menor"]);
let filtroCategoria = new Set();
let categoriasTodas = {};

// ── dropzone / subida de PDF ─────────────────────────────────────────────
const dropzone = document.getElementById("dropzone");
const inputPdf = document.getElementById("input-pdf");

dropzone.addEventListener("click", () => inputPdf.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("sobre"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("sobre"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("sobre");
  if (e.dataTransfer.files.length) subirPdf(e.dataTransfer.files[0]);
});
inputPdf.addEventListener("change", () => {
  if (inputPdf.files.length) subirPdf(inputPdf.files[0]);
});

async function subirPdf(file) {
  document.getElementById("dropzone-sub").textContent = "Subiendo…";
  const buf = await file.arrayBuffer();
  const r = await fetch("/api/subir_pdf", {
    method: "POST",
    headers: { "X-Filename": encodeURIComponent(file.name) },
    body: buf,
  });
  const datos = await r.json();
  if (datos.error) {
    document.getElementById("dropzone-sub").textContent = "Error: " + datos.error;
    return;
  }
  pdfActual = datos;
  document.getElementById("dropzone-texto").textContent = datos.nombre;
  document.getElementById("dropzone-sub").textContent = `${datos.num_paginas} páginas`;
}

// ── proveedores / modelos ────────────────────────────────────────────────
let CATALOGO = null;
async function cargarProveedores() {
  CATALOGO = await getJSON("/api/proveedores");
  document.getElementById("cfg-autor").value = CATALOGO.autor || "";
  actualizarModelos();
  renderKeysConfig();
}

function actualizarModelos() {
  const prov = document.getElementById("sel-proveedor").value;
  const sel = document.getElementById("sel-modelo");
  sel.innerHTML = "";
  let opciones = [];
  if (prov === "ollama") opciones = CATALOGO.modelos_ollama_sugeridos;
  else opciones = CATALOGO.modelos_disponibles[prov] || [];
  opciones.forEach((m) => {
    const op = document.createElement("option");
    op.value = m;
    op.textContent = m;
    sel.appendChild(op);
  });
  const actual = CATALOGO.modelo_actual[prov];
  if (actual) sel.value = actual;
}
document.getElementById("sel-proveedor").addEventListener("change", actualizarModelos);

function renderKeysConfig() {
  const cont = document.getElementById("cfg-keys");
  cont.innerHTML = "";
  const etiquetas = { openai: "OpenAI", gemini: "Google Gemini", claude: "Anthropic Claude", perplexity: "Perplexity" };
  Object.entries(etiquetas).forEach(([id, nombre]) => {
    const fila = document.createElement("div");
    fila.className = "fila";
    fila.style.marginBottom = "10px";
    const configurada = CATALOGO.keys_configuradas[id];
    fila.innerHTML = `
      <label>${nombre} API key ${configurada ? "✓" : ""}
        <input type="password" id="cfg-key-${id}" placeholder="${configurada ? "•••••••• (ya configurada)" : "pega tu key aquí"}" />
      </label>
      <label>Modelo
        <select id="cfg-modelo-${id}"></select>
      </label>`;
    cont.appendChild(fila);
    const sel = fila.querySelector(`#cfg-modelo-${id}`);
    (CATALOGO.modelos_disponibles[id] || []).forEach((m) => {
      const op = document.createElement("option");
      op.value = m; op.textContent = m;
      if (m === CATALOGO.modelo_actual[id]) op.selected = true;
      sel.appendChild(op);
    });
  });
}

document.getElementById("btn-guardar-config").addEventListener("click", async () => {
  const body = { autor: document.getElementById("cfg-autor").value };
  ["openai", "gemini", "claude", "perplexity"].forEach((id) => {
    const k = document.getElementById(`cfg-key-${id}`).value;
    if (k) body[`key_${id}`] = k;
    body[`modelo_${id}`] = document.getElementById(`cfg-modelo-${id}`).value;
  });
  await postJSON("/api/config", body);
  await cargarProveedores();
  alert("Configuración guardada.");
});

// ── costo estimado + iniciar revisión ────────────────────────────────────
const modalFondo = document.getElementById("modal-costo-fondo");

document.getElementById("btn-iniciar").addEventListener("click", async () => {
  if (!pdfActual) { alert("Selecciona un PDF primero."); return; }
  const proveedor = document.getElementById("sel-proveedor").value;
  const est = await postJSON("/api/estimar_costo", { ruta_pdf: pdfActual.ruta_pdf, proveedor });
  if (est.error) { alert("Error al estimar costo: " + est.error); return; }
  document.getElementById("modal-costo-texto").textContent = est.resumen;
  modalFondo.classList.add("activo");
});

document.getElementById("modal-costo-cancelar").addEventListener("click", () => {
  modalFondo.classList.remove("activo");
});

document.getElementById("modal-costo-confirmar").addEventListener("click", async () => {
  modalFondo.classList.remove("activo");
  const proveedor = document.getElementById("sel-proveedor").value;
  const modelo = document.getElementById("sel-modelo").value;
  await postJSON("/api/config", { [`modelo_${proveedor}`]: modelo });
  const r = await postJSON("/api/iniciar_revision", { ruta_pdf: pdfActual.ruta_pdf, proveedor });
  if (r.error) { alert(r.error); return; }
  document.getElementById("btn-iniciar").disabled = true;
  document.getElementById("btn-detener").disabled = false;
  iniciarPolling();
});

document.getElementById("btn-detener").addEventListener("click", async () => {
  await postJSON("/api/detener", {});
});

// ── polling de estado (progreso + log) ───────────────────────────────────
let pollHandle = null;
function iniciarPolling() {
  if (pollHandle) return;
  pollHandle = setInterval(actualizarEstado, 700);
}

async function actualizarEstado() {
  const e = await getJSON("/api/estado");

  const pct = e.progreso.total > 0 ? Math.round((e.progreso.actual / e.progreso.total) * 100) : 0;
  document.getElementById("barra-progreso").style.width = pct + "%";
  document.getElementById("progreso-texto").textContent = e.progreso.mensaje;

  const logEl = document.getElementById("log");
  logEl.innerHTML = e.log
    .map((l) => `<div class="l-${l.nivel}">[${l.ts}] ${escapeHtml(l.msg)}</div>`)
    .join("");
  logEl.scrollTop = logEl.scrollHeight;

  const dictEl = document.getElementById("dictamen");
  dictEl.textContent = e.dictamen || "";
  dictEl.className = "dictamen" + (e.dictamen.includes("Aprobable") ? " ok" : "");

  const badge = document.getElementById("perfil-badge");
  badge.textContent = e.perfil.cargado ? "◆ " + e.perfil.resumen : "◸ Sin perfil de estilo";
  badge.classList.toggle("activo", e.perfil.cargado);

  if (!e.en_proceso) {
    document.getElementById("btn-iniciar").disabled = false;
    document.getElementById("btn-detener").disabled = true;
    if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
    if (e.entregables_listos) renderEntregables(e);
  }
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// ── entregables ───────────────────────────────────────────────────────────
function renderEntregables(estado) {
  const cont = document.getElementById("tarjeta-entregables");
  const items = [
    ["pdf", "PDF anotado"],
    ["xfdf", "XFDF para Acrobat Pro"],
    ["informe", "Informe Markdown"],
    ["csv", "CSV de hallazgos"],
  ];
  cont.innerHTML = items
    .map(
      ([tipo, nombre]) => `
      <div class="entregable-fila">
        <div>
          <div class="entregable-nombre">${nombre}</div>
          <div class="entregable-sub">${estado.dictamen || ""}</div>
        </div>
        <a class="btn btn-accent" href="/api/entregables/descargar?tipo=${tipo}">Descargar</a>
      </div>`
    )
    .join("");
}

// ── hallazgos: chips + mapa de densidad + tabla ──────────────────────────
async function cargarHallazgos() {
  const cats = await getJSON("/api/categorias");
  categoriasTodas = { ...cats.categorias };
  const r = await getJSON("/api/hallazgos");
  hallazgosCache = r.items;
  // Defensa contra deriva del prompt: si el LLM devuelve una categoría que
  // no está en el catálogo (como pasó con "diagramacion" antes de arreglar
  // ASUNTOS), igual se muestra un chip para ella en vez de ocultar esos
  // hallazgos en silencio sin ninguna forma de volver a activarlos.
  hallazgosCache.forEach((h) => {
    if (h.categoria && !(h.categoria in categoriasTodas)) {
      categoriasTodas[h.categoria] = h.categoria;
    }
  });
  Object.keys(categoriasTodas).forEach((id) => filtroCategoria.add(id));
  renderChips();
  renderHallazgos();
}

function renderChips() {
  const conteoGravedad = { critica: 0, importante: 0, menor: 0 };
  const conteoCategoria = {};
  hallazgosCache.forEach((h) => {
    conteoGravedad[h.gravedad] = (conteoGravedad[h.gravedad] || 0) + 1;
    conteoCategoria[h.categoria] = (conteoCategoria[h.categoria] || 0) + 1;
  });

  const contG = document.getElementById("chips-gravedad");
  contG.innerHTML = "";
  Object.entries(conteoGravedad).forEach(([g, n]) => {
    const chip = document.createElement("span");
    chip.className = "chip" + (filtroGravedad.has(g) ? " activo" : "");
    if (filtroGravedad.has(g)) chip.style.background = COLOR_GRAVEDAD[g];
    chip.textContent = `${g} ${n}`;
    chip.addEventListener("click", () => {
      filtroGravedad.has(g) ? filtroGravedad.delete(g) : filtroGravedad.add(g);
      renderChips();
      renderHallazgos();
    });
    contG.appendChild(chip);
  });

  const contC = document.getElementById("chips-categoria");
  contC.innerHTML = "";
  Object.entries(categoriasTodas).forEach(([id, etiqueta]) => {
    const n = conteoCategoria[id] || 0;
    const chip = document.createElement("span");
    chip.className = "chip" + (filtroCategoria.has(id) ? " activo" : "");
    if (filtroCategoria.has(id)) chip.style.background = "#89b4fa";
    chip.textContent = `${etiqueta} ${n}`;
    chip.addEventListener("click", () => {
      filtroCategoria.has(id) ? filtroCategoria.delete(id) : filtroCategoria.add(id);
      renderChips();
      renderHallazgos();
    });
    contC.appendChild(chip);
  });
}

function hallazgosFiltrados() {
  return hallazgosCache.filter(
    (h) => filtroGravedad.has(h.gravedad) && filtroCategoria.has(h.categoria)
  );
}

function renderHallazgos() {
  const items = hallazgosFiltrados();
  const body = document.getElementById("tabla-hallazgos-body");
  body.innerHTML = items
    .map(
      (h, i) => `
      <tr data-idx="${i}">
        <td>${h.pagina}</td>
        <td><span class="badge-gravedad badge-${h.gravedad}">${h.gravedad}</span></td>
        <td>${(categoriasTodas[h.categoria] || h.categoria || "").toString()}</td>
        <td>${escapeHtml(h.descripcion || "")}</td>
        <td>${escapeHtml((h.fragmento || "").slice(0, 45))}</td>
        <td>${escapeHtml((h.correccion || "").slice(0, 60))}</td>
      </tr>`
    )
    .join("");
  document.getElementById("conteo-hallazgos").textContent = `${items.length} de ${hallazgosCache.length} hallazgo(s)`;

  renderMapaHallazgos(items);
}

function renderMapaHallazgos(items) {
  const mapa = document.getElementById("mapa-hallazgos");
  mapa.innerHTML = "";
  const alto = mapa.clientHeight || 400;
  const nMax = Math.max(items.length, 1);
  const altoPunto = Math.max(2, Math.min(6, alto / nMax - 2));
  items.forEach((h, i) => {
    const punto = document.createElement("div");
    punto.className = "mapa-punto";
    punto.style.height = altoPunto + "px";
    punto.style.background = COLOR_GRAVEDAD[h.gravedad] || "#6c7086";
    punto.title = `Pág. ${h.pagina} — ${h.descripcion || ""}`;
    punto.addEventListener("click", () => {
      const fila = document.querySelector(`tr[data-idx="${i}"]`);
      if (fila) {
        fila.scrollIntoView({ block: "center", behavior: "smooth" });
        document.querySelectorAll(".tabla-hallazgos tr.resaltada").forEach((f) => f.classList.remove("resaltada"));
        fila.classList.add("resaltada");
      }
    });
    mapa.appendChild(punto);
  });
}

// ── ajustes de filtrado ───────────────────────────────────────────────────
async function cargarAjustesFiltro() {
  const r = await getJSON("/api/reglas_filtro");
  const cont = document.getElementById("grupos-filtro");
  cont.innerHTML = "";
  Object.entries(r.grupos).forEach(([grupo, reglas]) => {
    const div = document.createElement("div");
    div.className = "grupo-filtro";
    div.innerHTML = `<h3>${grupo}</h3>`;
    reglas.forEach((regla) => {
      const fila = document.createElement("div");
      fila.className = "regla-fila";
      fila.innerHTML = `
        <label class="toggle">
          <input type="checkbox" ${regla.activa ? "checked" : ""} data-id="${regla.id}" />
          <span class="toggle-slider"></span>
        </label>
        <div class="regla-texto">
          <div class="regla-etiqueta">${escapeHtml(regla.etiqueta)}</div>
          <div class="regla-descripcion">${escapeHtml(regla.descripcion)}</div>
        </div>`;
      const input = fila.querySelector("input");
      input.addEventListener("change", async () => {
        await postJSON("/api/reglas_filtro", { [regla.id]: input.checked });
      });
      div.appendChild(fila);
    });
    cont.appendChild(div);
  });
}

document.getElementById("btn-reaplicar").addEventListener("click", async () => {
  const r = await postJSON("/api/reaplicar_filtro", {});
  if (!r.ok) { alert(r.mensaje || "No se pudo reaplicar."); return; }
  alert(`Filtro reaplicado: ${r.despues}/${r.antes} hallazgos conservados.`);
  cargarHallazgos();
});

document.getElementById("btn-restablecer").addEventListener("click", async () => {
  await postJSON("/api/reglas_filtro/restablecer", {});
  cargarAjustesFiltro();
});

// ── arranque ──────────────────────────────────────────────────────────────
cargarProveedores();
actualizarEstado();
