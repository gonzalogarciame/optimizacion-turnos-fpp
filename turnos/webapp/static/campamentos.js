"use strict";

// =====================================================================
// Campamentos: abrir uno, crear uno nuevo, importar un Excel, y la
// pantalla «Versiones» (copias de seguridad que se pueden recuperar).
// Se carga después de rejilla.js (usa esc, toast, abrirModal...) y antes de app.js.
// =====================================================================

const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const DIAS_SEMANA_LARGO = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];

const etiquetaCampamento = (c) => `${c.quincena}ª quincena de ${MESES[c.mes - 1]} ${c.anio} (días ${c.dia_inicio}–${c.dia_fin})`;
const refrescarTodo = async () => { await refrescarResumen(); await dibujarPagina(); };

// ---------------------------------------------------------------------
// Menú «Campamento» de la barra superior
// ---------------------------------------------------------------------
function configurarMenuCampamento() {
  const menu = document.getElementById("carga-excel");
  const sel = document.getElementById("sel-campamento");
  const fichero = document.getElementById("fichero-excel");
  menu.addEventListener("toggle", () => { if (menu.open) rellenarCampamentos().catch(() => {}); });
  sel.addEventListener("change", () => abrirCampamento(sel.value));
  document.getElementById("btn-cargar").addEventListener("click", () => abrirCampamento(document.getElementById("input-ruta").value));
  document.getElementById("btn-nuevo-camp").addEventListener("click", () => { menu.open = false; abrirNuevoCampamento(); });
  document.getElementById("btn-importar").addEventListener("click", () => fichero.click());
  fichero.addEventListener("change", () => { menu.open = false; importarExcel(fichero.files[0]); fichero.value = ""; });
}

async function rellenarCampamentos() {
  const sel = document.getElementById("sel-campamento");
  const r = await api("GET", "/api/campamentos");
  const opciones = r.campamentos.map((c) => `<option value="${esc(c.ruta)}">${esc(etiquetaCampamento(c))}</option>`);
  if (!r.campamentos.some((c) => c.ruta === r.actual)) opciones.unshift(`<option value="${esc(r.actual)}">${esc(r.actual)}</option>`);
  sel.innerHTML = opciones.join("");
  sel.value = r.actual;
}

async function abrirCampamento(ruta) {
  const estadoSpan = document.getElementById("estado-carga");
  if (!confirmarSalida()) { rellenarCampamentos().catch(() => {}); return; }
  estadoSpan.textContent = "Cargando…";
  try {
    await api("POST", "/api/cargar", { ruta });
    await refrescarTodo();
    document.getElementById("carga-excel").open = false;
  } catch (e) {
    insertarBanner(document.getElementById("avisos-excel"), "error", e.message);
  } finally {
    estadoSpan.textContent = "";
  }
}

async function importarExcel(archivo) {
  if (!archivo || !confirmarSalida()) return;
  const estadoSpan = document.getElementById("estado-carga");
  estadoSpan.textContent = "Importando el Excel…";
  try {
    const datos = new FormData();
    datos.append("archivo", archivo);
    const resp = await fetch("/api/campamentos/importar", { method: "POST", body: datos });
    const cuerpo = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(cuerpo.error || `Error ${resp.status}`);
    toast("Excel importado. Ya trabajas con la copia en la base de datos; el Excel original no se ha tocado.", "exito");
    await refrescarTodo();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    estadoSpan.textContent = "";
  }
}

// ---------------------------------------------------------------------
// Nuevo campamento
// ---------------------------------------------------------------------
async function abrirNuevoCampamento() {
  if (!confirmarSalida()) return;
  let actual = null;
  try {
    const r = await api("GET", "/api/campamentos");
    actual = r.campamentos.find((c) => c.ruta === r.actual) || null;
  } catch (e) { /* se usan valores por defecto */ }

  // Propuesta: el mes siguiente, con los mismos días y una quincena más
  const hoy = new Date();
  let anio = actual ? actual.anio : hoy.getFullYear(), mes = actual ? actual.mes : hoy.getMonth() + 1;
  mes += 1;
  if (mes > 12) { mes = 1; anio += 1; }
  const quincena = actual ? actual.quincena + 1 : 1;
  const inicio = actual ? actual.dia_inicio : 1;
  const fin = actual ? actual.dia_fin : 13;

  const modal = abrirModal(`
    <h3>Nuevo campamento</h3>
    <p class="muted">Se crea vacío (sin turnos asignados) con los monitores, dependientes, turnos y reglas del campamento que tienes abierto.
    El actual no se modifica.</p>
    <div class="form-rejilla">
      <label>Quincena <input type="number" id="nc-quincena" min="1" value="${quincena}"></label>
      <label>Año <input type="number" id="nc-anio" min="2000" max="2100" value="${anio}"></label>
      <label>Mes <select id="nc-mes">${MESES.map((m, i) => `<option value="${i + 1}">${m}</option>`).join("")}</select></label>
      <label>Día de llegada <input type="number" id="nc-inicio" min="1" max="31" value="${inicio}"></label>
      <label>Día de salida <input type="number" id="nc-fin" min="1" max="31" value="${fin}"></label>
    </div>
    <div id="nc-resumen" class="resumen-fechas"></div>
    <label class="check"><input type="checkbox" id="nc-disp"> Copiar quién viene y quién no del campamento actual (día a día, por posición)</label>
    <div id="nc-error" class="linea-error" hidden></div>
    <div class="modal-pie">
      <button type="button" class="secundario" id="nc-cancelar">Cancelar</button>
      <button type="button" id="nc-crear">Crear campamento</button>
    </div>`);
  const q = (s) => modal.querySelector(s);
  q("#nc-mes").value = String(mes);

  const valores = () => ({
    quincena: Number(q("#nc-quincena").value), anio: Number(q("#nc-anio").value), mes: Number(q("#nc-mes").value),
    dia_inicio: Number(q("#nc-inicio").value), dia_fin: Number(q("#nc-fin").value),
  });
  const texto = (v, d) => {
    const f = new Date(v.anio, v.mes - 1, d);
    return `${DIAS_SEMANA_LARGO[f.getDay()]} ${d} de ${MESES[v.mes - 1]}`;
  };
  const actualizarResumen = () => {
    const v = valores();
    const ultimo = new Date(v.anio, v.mes, 0).getDate();
    const bien = v.dia_inicio >= 1 && v.dia_inicio <= v.dia_fin && v.dia_fin <= ultimo;
    q("#nc-resumen").textContent = bien
      ? `${v.dia_fin - v.dia_inicio + 1} días: de ${texto(v, v.dia_inicio)} (llegada) a ${texto(v, v.dia_fin)} (salida).`
      : `Los días deben estar entre 1 y ${ultimo || 31}, y la salida no puede ser antes que la llegada.`;
    q("#nc-resumen").classList.toggle("mal", !bien);
  };
  modal.querySelectorAll("input, select").forEach((el) => el.addEventListener("input", actualizarResumen));
  actualizarResumen();

  q("#nc-cancelar").addEventListener("click", cerrarModal);
  q("#nc-crear").addEventListener("click", async () => {
    q("#nc-error").hidden = true;
    q("#nc-crear").disabled = true;
    try {
      await api("POST", "/api/campamentos/nuevo", { ...valores(), copiar_disponibilidad: q("#nc-disp").checked });
      cerrarModal();
      toast("Campamento creado. Ya estás trabajando en él.", "exito");
      await refrescarTodo();
    } catch (e) {
      q("#nc-error").textContent = e.message;
      q("#nc-error").hidden = false;
      q("#nc-crear").disabled = false;
    }
  });
}

// ---------------------------------------------------------------------
// Versiones
// ---------------------------------------------------------------------
async function renderVersiones(cont) {
  const lista = await api("GET", "/api/copias");
  const fecha = (iso) => new Date(iso).toLocaleString("es-ES", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  cont.innerHTML = `
    <div class="pagina-cab">
      <h2>Versiones</h2>
      <span class="muted">Cada vez que guardas, generas o cambias plazas se hace una copia automática (se conservan las últimas 40). Puedes volver a cualquiera.</span>
    </div>
    <div class="barra"><div class="barra-grupo">
      <button type="button" id="ver-crear">Guardar una versión ahora</button>
    </div></div>
    ${lista.length ? `
    <table class="tabla-versiones">
      <thead><tr><th>Cuándo</th><th>Contenido</th><th></th></tr></thead>
      <tbody>${lista.map((v, i) => `
        <tr>
          <td><b>${esc(fecha(v.fecha))}</b>${i === 0 ? ` <span class="etiqueta">la más reciente</span>` : ""}</td>
          <td>${v.asignaciones == null ? "—" : `${v.asignaciones} casillas ocupadas`}${v.dia_reoptimizacion > 1 ? ` · días anteriores al ${v.dia_reoptimizacion} cerrados` : ""}</td>
          <td class="derecha"><button type="button" class="secundario" data-nombre="${esc(v.nombre)}" data-fecha="${esc(fecha(v.fecha))}">Volver a esta versión</button></td>
        </tr>`).join("")}</tbody>
    </table>` : `<p class="muted" style="margin-top:16px">Todavía no hay versiones: aparecerán en cuanto guardes algo.</p>`}`;

  cont.querySelector("#ver-crear").addEventListener("click", async () => {
    try {
      await api("POST", "/api/copias/crear", {});
      toast("Versión guardada.", "exito");
      await renderVersiones(cont);
    } catch (e) { toast(e.message, "error"); }
  });
  cont.querySelectorAll("button[data-nombre]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`¿Volver a la versión del ${b.dataset.fecha}?\n\nLo que hay ahora se guarda antes como otra versión, así que se puede deshacer.`)) return;
    try {
      await api("POST", "/api/copias/restaurar", { nombre: b.dataset.nombre });
      toast("Versión recuperada.", "exito");
      await refrescarTodo();
    } catch (e) { toast(e.message, "error"); }
  }));
}
