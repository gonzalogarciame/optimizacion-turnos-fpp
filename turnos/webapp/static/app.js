"use strict";

// ---------------------------------------------------------------------
// Utilidades básicas: llamadas a la API y mensajes
// ---------------------------------------------------------------------
async function api(metodo, url, cuerpo) {
  const opciones = { method: metodo, headers: {} };
  if (cuerpo !== undefined) {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(cuerpo);
  }
  const resp = await fetch(url, opciones);
  let datos = null;
  try { datos = await resp.json(); } catch (e) { /* respuesta vacía o binaria */ }
  if (!resp.ok) {
    const mensaje = (datos && datos.error) ? datos.error : `Error ${resp.status}`;
    throw new Error(mensaje);
  }
  return datos;
}

function elemento(html) {
  const plantilla = document.createElement("template");
  plantilla.innerHTML = html.trim();
  return plantilla.content.firstChild;
}

function banner(tipo, texto) {
  return `<div class="banner ${tipo}">${texto}</div>`;
}

function insertarBanner(contenedor, tipo, texto) {
  const div = elemento(banner(tipo, texto));
  contenedor.prepend(div);
  return div;
}

// ---------------------------------------------------------------------
// MiniGrid: tabla editable genérica (sin dependencias externas)
//
// columnas: [{clave, etiqueta, tipo: 'texto'|'numero'|'select'|'check',
//             opciones?, editable?: bool (default true), fija?: bool}]
// filas: [{clave: valor, ...}]
// ---------------------------------------------------------------------
function crearGrid(columnas, filasIniciales, opciones = {}) {
  const permitirFilas = !!opciones.permitirFilas;
  const filaVacia = opciones.filaVacia || (() => ({}));

  const contenedor = elemento(`<div class="grid-envoltorio"></div>`);
  const tabla = elemento(`<table class="grid"><thead><tr></tr></thead><tbody></tbody></table>`);
  contenedor.appendChild(tabla);
  const filaCabecera = tabla.querySelector("thead tr");
  const cuerpo = tabla.querySelector("tbody");

  columnas.forEach((col, i) => {
    const th = elemento(`<th>${col.etiqueta}</th>`);
    if (col.fija) th.classList.add("fija-col");
    filaCabecera.appendChild(th);
  });
  if (permitirFilas) filaCabecera.appendChild(elemento(`<th></th>`));

  // matriz[filaIdx][colIdx] -> elemento de entrada (input/select), o null si es de solo lectura
  let matriz = [];
  let datos = filasIniciales.map((f) => ({ ...f }));

  function valorInicial(col, fila) {
    const v = fila[col.clave];
    return v === undefined || v === null ? "" : v;
  }

  function crearCelda(col, fila, filaIdx, colIdx) {
    const td = document.createElement("td");
    if (col.fija) td.classList.add("fija-col");
    const editable = col.editable !== false;
    if (!editable) {
      td.classList.add("deshabilitada");
      const span = document.createElement("span");
      span.className = "solo-lectura";
      span.textContent = valorInicial(col, fila);
      td.appendChild(span);
      matriz[filaIdx][colIdx] = null;
      return td;
    }

    let campo;
    if (col.tipo === "select") {
      campo = document.createElement("select");
      (col.opciones || []).forEach((op) => {
        const o = document.createElement("option");
        o.value = op;
        o.textContent = op;
        campo.appendChild(o);
      });
      campo.value = valorInicial(col, fila) || (col.opciones || [])[0] || "";
    } else if (col.tipo === "check") {
      campo = document.createElement("input");
      campo.type = "checkbox";
      campo.checked = !!valorInicial(col, fila);
    } else if (col.tipo === "numero") {
      campo = document.createElement("input");
      campo.type = "number";
      campo.step = col.paso || "any";
      campo.value = valorInicial(col, fila);
    } else {
      campo = document.createElement("input");
      campo.type = "text";
      campo.value = valorInicial(col, fila);
    }

    campo.dataset.fila = filaIdx;
    campo.dataset.col = colIdx;
    matriz[filaIdx][colIdx] = campo;

    campo.addEventListener("keydown", (e) => manejarTeclado(e, filaIdx, colIdx));
    campo.addEventListener("paste", (e) => manejarPegado(e, filaIdx, colIdx, col.tipo));

    td.appendChild(campo);
    return td;
  }

  function dibujarFilaDom(fila, filaIdx) {
    const tr = document.createElement("tr");
    matriz[filaIdx] = [];
    columnas.forEach((col, colIdx) => tr.appendChild(crearCelda(col, fila, filaIdx, colIdx)));
    if (permitirFilas) {
      const tdBoton = document.createElement("td");
      const btn = document.createElement("button");
      btn.className = "peligro";
      btn.type = "button";
      btn.textContent = "✕";
      btn.title = "Quitar fila";
      btn.addEventListener("click", () => quitarFila(filaIdx));
      tdBoton.appendChild(btn);
      tr.appendChild(tdBoton);
    }
    return tr;
  }

  function redibujarTodo() {
    cuerpo.innerHTML = "";
    matriz = [];
    datos.forEach((fila, i) => cuerpo.appendChild(dibujarFilaDom(fila, i)));
  }

  function quitarFila(filaIdx) {
    datos.splice(filaIdx, 1);
    redibujarTodo();
  }

  function agregarFila() {
    datos.push(filaVacia());
    redibujarTodo();
    // enfoca la primera celda editable de la fila nueva
    const nueva = matriz[matriz.length - 1] || [];
    const primerEditable = nueva.find((c) => c);
    if (primerEditable) primerEditable.focus();
  }

  function manejarTeclado(e, r, c) {
    if (e.key === "Enter") {
      e.preventDefault();
      moverFoco(r + 1, c);
    } else if (e.key === "ArrowDown" && e.altKey) {
      e.preventDefault();
      moverFoco(r + 1, c);
    } else if (e.key === "ArrowUp" && e.altKey) {
      e.preventDefault();
      moverFoco(r - 1, c);
    }
  }

  function moverFoco(r, c) {
    if (matriz[r] && matriz[r][c]) matriz[r][c].focus();
  }

  function asignarValorCampo(campo, valor, tipo) {
    if (tipo === "check") {
      campo.checked = ["1", "true", "verdadero", "x", "sí", "si"].includes(String(valor).trim().toLowerCase());
    } else if (campo.tagName === "SELECT") {
      const opciones = Array.from(campo.options).map((o) => o.value);
      const encontrada = opciones.find((o) => o.toLowerCase() === String(valor).trim().toLowerCase());
      campo.value = encontrada !== undefined ? encontrada : valor;
    } else {
      campo.value = valor;
    }
  }

  function manejarPegado(e, r, c, tipo) {
    const texto = (e.clipboardData || window.clipboardData).getData("text");
    if (!texto.includes("\t") && !texto.includes("\n")) return; // pegado normal de una celda
    e.preventDefault();
    const filasPegadas = texto.replace(/\r/g, "").split("\n").filter((l, i, arr) => !(i === arr.length - 1 && l === ""));
    filasPegadas.forEach((linea, dr) => {
      linea.split("\t").forEach((valor, dc) => {
        const campo = matriz[r + dr] && matriz[r + dr][c + dc];
        if (campo) asignarValorCampo(campo, valor, columnas[c + dc] && columnas[c + dc].tipo);
      });
    });
  }

  function leerFilas() {
    return datos.map((filaOriginal, filaIdx) => {
      const resultado = {};
      columnas.forEach((col, colIdx) => {
        const campo = matriz[filaIdx][colIdx];
        if (!campo) {
          resultado[col.clave] = filaOriginal[col.clave];
        } else if (col.tipo === "check") {
          resultado[col.clave] = campo.checked;
        } else if (col.tipo === "numero") {
          resultado[col.clave] = campo.value === "" ? 0 : Number(campo.value);
        } else {
          resultado[col.clave] = campo.value;
        }
      });
      return resultado;
    });
  }

  redibujarTodo();

  if (permitirFilas) {
    const btnAgregar = elemento(`<button type="button" class="secundario" style="margin-top:8px;">+ Añadir fila</button>`);
    btnAgregar.addEventListener("click", agregarFila);
    contenedor.appendChild(btnAgregar);
  }

  return { elemento: contenedor, leerFilas, datosOriginales: datos };
}

// ---------------------------------------------------------------------
// Barra superior: carga del campamento + resumen
// ---------------------------------------------------------------------
async function refrescarResumen() {
  const info = await api("GET", "/api/estado");
  const resumen = document.getElementById("resumen-excel");
  const avisos = document.getElementById("avisos-excel");
  document.getElementById("input-ruta").value = info.ruta || "";

  if (!info.cargado) {
    resumen.innerHTML = "";
    avisos.innerHTML = info.error ? banner("error", info.error) : "";
    return info;
  }
  resumen.innerHTML =
    `<span><b>${info.dia_fin - info.dia_inicio + 1}</b> días (${info.dia_inicio}–${info.dia_fin})</span>` +
    `<span><b>${info.n_monitores}</b> monitores</span>` +
    `<span><b>${info.n_dependientes}</b> dependientes</span>`;
  avisos.innerHTML = "";
  return info;
}

function configurarBarraSuperior() {
  configurarMenuCampamento();  // campamentos.js
}

// ---------------------------------------------------------------------
// Navegación
// ---------------------------------------------------------------------
const PAGINAS = {
  rejilla: { titulo: "Rejilla", render: renderRejilla },
  monitores: { titulo: "Monitores", render: renderMonitores },
  disponibilidad: { titulo: "Disponibilidad", render: renderDisponibilidad },
  turnos: { titulo: "Turnos y dependientes", render: renderTurnosDependientes },
  restricciones: { titulo: "Restricciones", render: renderRestricciones },
  informe: { titulo: "Informe", render: renderInforme },
  versiones: { titulo: "Versiones", render: renderVersiones },
};
let paginaActual = "rejilla";

function dibujarNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("activo", btn.dataset.pagina === paginaActual);
  });
}

async function dibujarPagina() {
  const cont = document.getElementById("contenido");
  cont.classList.remove("llena");  // las pantallas con tabla grande se ajustan a la altura de la ventana
  cont.innerHTML = "<p>Cargando…</p>";
  try {
    const est = await api("GET", "/api/estado");
    if (!est.cargado) { renderBienvenida(cont); return; }  // campamentos.js
    await PAGINAS[paginaActual].render(cont);
  } catch (e) {
    cont.innerHTML = banner("error", e.message);
  }
}

function confirmarSalida() {
  const sucio = (paginaActual === "rejilla" && typeof rejillaTieneCambios === "function" && rejillaTieneCambios())
    || (paginaActual === "disponibilidad" && typeof disponibilidadTieneCambios === "function" && disponibilidadTieneCambios());
  return !sucio || confirm("Tienes cambios sin guardar en esta pantalla. ¿Salir sin guardarlos?");
}

function irA(pagina) {
  if (pagina !== paginaActual && !confirmarSalida()) return;
  paginaActual = pagina;
  dibujarNav();
  dibujarPagina();
}

// ---------------------------------------------------------------------
// Página: Monitores
// ---------------------------------------------------------------------
async function renderMonitores(cont) {
  const filas = await api("GET", "/api/monitores");
  cont.innerHTML = `
    <h2>Monitores</h2>
    <p class="subtitulo">Añade una fila para dar de alta a un monitor (se crea también su fila en
    DISPONIBILIDAD con 'D' todos los días). Borrar una fila no borra su disponibilidad
    ni su histórico en TURNOS: revísalo a mano si hace falta.</p>
    <div id="zona-grid"></div>
    <button id="btn-guardar" style="margin-top:12px;">Guardar monitores</button>
    <div id="zona-mensajes"></div>
  `;
  const columnas = [
    { clave: "NOMBRE", etiqueta: "Nombre", tipo: "texto" },
    { clave: "SEXO", etiqueta: "Sexo", tipo: "select", opciones: ["M", "F"] },
    { clave: "GRUPO", etiqueta: "Grupo", tipo: "texto" },
    { clave: "PERMITE_DESCANSO", etiqueta: "Permite descanso", tipo: "check" },
    { clave: "PENALIZAR_DESCANSO", etiqueta: "Penalizar descanso", tipo: "check" },
    { clave: "DEPENDIENTE_1", etiqueta: "Dependiente 1", tipo: "texto" },
    { clave: "DEPENDIENTE_2", etiqueta: "Dependiente 2", tipo: "texto" },
  ];
  const grid = crearGrid(columnas, filas, { permitirFilas: true, filaVacia: () => ({ SEXO: "M" }) });
  cont.querySelector("#zona-grid").appendChild(grid.elemento);

  cont.querySelector("#btn-guardar").addEventListener("click", async () => {
    const zona = cont.querySelector("#zona-mensajes");
    zona.innerHTML = "";
    try {
      const resp = await api("POST", "/api/monitores", { filas: grid.leerFilas() });
      (resp.avisos || []).forEach((a) => insertarBanner(zona, "aviso", a));
      insertarBanner(zona, "exito", "Monitores guardados.");
      await refrescarResumen();
    } catch (e) {
      insertarBanner(zona, "error", e.message);
    }
  });
}

// ---------------------------------------------------------------------
// Página: Turnos y dependientes
// ---------------------------------------------------------------------
async function renderTurnosDependientes(cont) {
  const info = await api("GET", "/api/estado");
  const [tiposTurno, plazas, dependientes] = await Promise.all([
    api("GET", "/api/tipos_turno"),
    api("GET", "/api/plazas_por_dia"),
    api("GET", "/api/dependientes"),
  ]);

  cont.innerHTML = `
    <h2>Turnos y dependientes</h2>

    <div class="seccion">
      <h3>Turnos existentes</h3>
      <p class="subtitulo">PLAZAS es el valor por defecto; el reparto día a día se ajusta abajo. No se
      puede renombrar ni borrar un turno desde aquí (el nombre se usa tal cual en FIJACIONES y en la
      rejilla).</p>
      <div id="grid-tipos-turno"></div>
      <button id="btn-guardar-tipos" style="margin-top:8px;">Guardar turnos</button>
      <div id="msg-tipos"></div>
    </div>

    <div class="seccion">
      <h3>Plazas por día</h3>
      <p class="subtitulo">Solo se pueden cambiar los días de llegada y salida (también desde la Rejilla, con «Plazas llegada y salida»).
      Los demás días usan las plazas normales de cada turno.</p>
      <div id="grid-plazas"></div>
      <button id="btn-guardar-plazas" style="margin-top:8px;">Guardar plazas por día</button>
      <div id="msg-plazas"></div>
    </div>

    <div class="seccion">
      <h3>Añadir turno nuevo</h3>
      <p class="subtitulo">Reserva plazas nuevas en la rejilla de TURNOS. Los días anteriores al de
      re-optimización se dejan con 0 plazas (el turno no existía entonces).</p>
      <div class="form-inline">
        <label>Nombre <input type="text" id="nt-nombre"></label>
        <label>Plazas <input type="number" id="nt-plazas" value="1" min="1"></label>
        <label>Sexo requerido
          <select id="nt-sexo"><option value="-">-</option><option value="M">M</option><option value="F">F</option></select>
        </label>
        <label>Esfuerzo <input type="number" id="nt-esfuerzo" value="2" step="0.5"></label>
        <button id="btn-nuevo-turno">Añadir turno</button>
      </div>
      <div id="msg-nuevo-turno"></div>
    </div>

    <div class="seccion">
      <h3>Dependientes existentes</h3>
      <p class="subtitulo">ESFUERZO debe ser mayor que el de cualquier turno normal. No se puede
      renombrar ni borrar un dependiente desde aquí.</p>
      <div id="grid-dependientes"></div>
      <button id="btn-guardar-dep" style="margin-top:8px;">Guardar dependientes</button>
      <div id="msg-dep"></div>
    </div>

    <div class="seccion">
      <h3>Añadir dependiente nuevo</h3>
      <p class="subtitulo">Los días anteriores al de re-optimización quedan marcados '-' (no
      presente): si en realidad ya estaba, rellena esas celdas a mano en ASIG_DEPENDIENTE. Los días
      futuros los decide el modelo.</p>
      <div class="form-inline">
        <label>Nombre del acampado <input type="text" id="nd-nombre"></label>
        <label>Sexo del monitor requerido
          <select id="nd-sexo"><option value="-">-</option><option value="M">M</option><option value="F">F</option></select>
        </label>
        <label>Esfuerzo <input type="number" id="nd-esfuerzo" value="4" step="0.5"></label>
        <button id="btn-nuevo-dep">Añadir dependiente</button>
      </div>
      <div id="msg-nuevo-dep"></div>
    </div>
  `;

  const gridTipos = crearGrid(
    [
      { clave: "TURNO", etiqueta: "Turno", tipo: "texto", editable: false },
      { clave: "PLAZAS", etiqueta: "Plazas (por defecto)", tipo: "numero" },
      { clave: "SEXO_REQ", etiqueta: "Sexo requerido", tipo: "select", opciones: ["-", "M", "F"] },
      { clave: "ESFUERZO", etiqueta: "Esfuerzo", tipo: "numero" },
    ],
    tiposTurno
  );
  cont.querySelector("#grid-tipos-turno").appendChild(gridTipos.elemento);
  cont.querySelector("#btn-guardar-tipos").addEventListener("click", async () => {
    const zona = cont.querySelector("#msg-tipos");
    zona.innerHTML = "";
    try {
      await api("POST", "/api/tipos_turno", { filas: gridTipos.leerFilas() });
      insertarBanner(zona, "exito", "Turnos guardados.");
    } catch (e) { insertarBanner(zona, "error", e.message); }
  });

  const gridPlazas = crearGrid(
    [
      { clave: "TURNO", etiqueta: "Turno", tipo: "texto", editable: false, fija: true },
      // Solo la llegada y la salida se editan (los días intermedios usan las plazas normales de cada turno).
      ...info.dias.map((d, i) => ({
        clave: String(d),
        etiqueta: i === 0 ? `${d} (llegada)` : i === info.dias.length - 1 ? `${d} (salida)` : String(d),
        tipo: "numero",
        editable: i === 0 || i === info.dias.length - 1,
      })),
    ],
    plazas.filas
  );
  cont.querySelector("#grid-plazas").appendChild(gridPlazas.elemento);
  cont.querySelector("#btn-guardar-plazas").addEventListener("click", async () => {
    const zona = cont.querySelector("#msg-plazas");
    zona.innerHTML = "";
    try {
      await api("POST", "/api/plazas_por_dia", { filas: gridPlazas.leerFilas() });
      insertarBanner(zona, "exito", "Plazas por día guardadas.");
    } catch (e) { insertarBanner(zona, "error", e.message); }
  });

  cont.querySelector("#btn-nuevo-turno").addEventListener("click", async () => {
    const zona = cont.querySelector("#msg-nuevo-turno");
    zona.innerHTML = "";
    try {
      await api("POST", "/api/tipos_turno/nuevo", {
        nombre: cont.querySelector("#nt-nombre").value,
        plazas: cont.querySelector("#nt-plazas").value,
        sexo_req: cont.querySelector("#nt-sexo").value,
        esfuerzo: cont.querySelector("#nt-esfuerzo").value,
      });
      insertarBanner(zona, "exito", "Turno añadido.");
      await refrescarResumen();
      await renderTurnosDependientes(cont);
    } catch (e) { insertarBanner(zona, "error", e.message); }
  });

  const gridDep = crearGrid(
    [
      { clave: "ACAMPADO", etiqueta: "Acampado", tipo: "texto", editable: false },
      { clave: "SEXO_MONITOR_REQ", etiqueta: "Sexo monitor requerido", tipo: "select", opciones: ["-", "M", "F"] },
      { clave: "ESFUERZO", etiqueta: "Esfuerzo", tipo: "numero" },
    ],
    dependientes
  );
  cont.querySelector("#grid-dependientes").appendChild(gridDep.elemento);
  cont.querySelector("#btn-guardar-dep").addEventListener("click", async () => {
    const zona = cont.querySelector("#msg-dep");
    zona.innerHTML = "";
    try {
      await api("POST", "/api/dependientes", { filas: gridDep.leerFilas() });
      insertarBanner(zona, "exito", "Dependientes guardados.");
    } catch (e) { insertarBanner(zona, "error", e.message); }
  });

  cont.querySelector("#btn-nuevo-dep").addEventListener("click", async () => {
    const zona = cont.querySelector("#msg-nuevo-dep");
    zona.innerHTML = "";
    try {
      await api("POST", "/api/dependientes/nuevo", {
        acampado: cont.querySelector("#nd-nombre").value,
        sexo_req: cont.querySelector("#nd-sexo").value,
        esfuerzo: cont.querySelector("#nd-esfuerzo").value,
      });
      insertarBanner(zona, "exito", "Dependiente añadido.");
      await refrescarResumen();
      await renderTurnosDependientes(cont);
    } catch (e) { insertarBanner(zona, "error", e.message); }
  });
}

// ---------------------------------------------------------------------
// Página: Restricciones
// ---------------------------------------------------------------------
async function renderRestricciones(cont) {
  const filas = await api("GET", "/api/restricciones");
  const cfg = await api("GET", "/api/config");
  cont.innerHTML = `
    <h2>Restricciones y parámetros</h2>
    <p class="subtitulo">ACTIVA enciende o apaga la regla de verdad. TIPO (DURA/BLANDA) es solo
    informativo. No se pueden dar de alta restricciones nuevas desde aquí: necesitan código detrás.</p>
    <div id="grid-restr"></div>
    <button id="btn-guardar-restr" style="margin-top:8px;">Guardar restricciones</button>
    <div id="msg-restr"></div>

    <h3 style="margin-top:28px;">Parámetros y pesos del objetivo</h3>
    <div class="form-grid" id="form-config">
      <label>SOLVER
        <select id="cfg-solver">
          <option value="appsi_highs">appsi_highs (local, gratis, sin licencia)</option>
          <option value="gurobi">gurobi</option>
        </select>
      </label>
      <label>TIME_LIMIT_S <input type="number" id="cfg-time" step="1" value="${cfg.TIME_LIMIT_S}"></label>
      <label>MIP_GAP <input type="number" id="cfg-gap" step="0.001" value="${cfg.MIP_GAP}"></label>
      <label>DIAS_DESCANSO_MINIMO <input type="number" id="cfg-desc-min" step="1" value="${cfg.DIAS_DESCANSO_MINIMO}"></label>
      <label>DIAS_VENTANA_DESCANSO <input type="number" id="cfg-ventana" step="1" value="${cfg.DIAS_VENTANA_DESCANSO}"></label>
      <label>MAX_DIAS_POR_DEP <input type="number" id="cfg-max-dep" step="1" value="${cfg.MAX_DIAS_POR_DEP}"></label>
      <label>W_FALTA <input type="number" id="cfg-w-falta" step="1" value="${cfg.W_FALTA}"></label>
      <label>W_EQUIDAD <input type="number" id="cfg-w-equidad" step="1" value="${cfg.W_EQUIDAD}"></label>
      <label>W_DESCANSO_LIM <input type="number" id="cfg-w-desc" step="1" value="${cfg.W_DESCANSO_LIM}"></label>
      <label>W_VARIEDAD <input type="number" id="cfg-w-var" step="1" value="${cfg.W_VARIEDAD}"></label>
      <label>W_REPETICION <input type="number" id="cfg-w-rep" step="1" value="${cfg.W_REPETICION}"></label>
      <label>W_FALTA_DESC <input type="number" id="cfg-w-falta-desc" step="1" value="${cfg.W_FALTA_DESC}"></label>
    </div>
    <button id="btn-guardar-config">Guardar parámetros</button>
    <div id="msg-config"></div>
  `;
  cont.querySelector("#cfg-solver").value = cfg.SOLVER;

  const grid = crearGrid(
    [
      { clave: "NOMBRE", etiqueta: "Nombre", tipo: "texto", editable: false },
      { clave: "ACTIVA", etiqueta: "Activa", tipo: "check" },
      { clave: "TIPO", etiqueta: "Tipo", tipo: "select", opciones: ["DURA", "BLANDA"] },
      { clave: "DESCRIPCION", etiqueta: "Descripción", tipo: "texto", editable: false },
    ],
    filas
  );
  cont.querySelector("#grid-restr").appendChild(grid.elemento);
  cont.querySelector("#btn-guardar-restr").addEventListener("click", async () => {
    const zona = cont.querySelector("#msg-restr");
    zona.innerHTML = "";
    try {
      await api("POST", "/api/restricciones", { filas: grid.leerFilas() });
      insertarBanner(zona, "exito", "Restricciones guardadas.");
    } catch (e) { insertarBanner(zona, "error", e.message); }
  });

  cont.querySelector("#btn-guardar-config").addEventListener("click", async () => {
    const zona = cont.querySelector("#msg-config");
    zona.innerHTML = "";
    try {
      await api("POST", "/api/config", {
        SOLVER: cont.querySelector("#cfg-solver").value,
        TIME_LIMIT_S: Number(cont.querySelector("#cfg-time").value),
        MIP_GAP: Number(cont.querySelector("#cfg-gap").value),
        DIAS_DESCANSO_MINIMO: Number(cont.querySelector("#cfg-desc-min").value),
        DIAS_VENTANA_DESCANSO: Number(cont.querySelector("#cfg-ventana").value),
        MAX_DIAS_POR_DEP: Number(cont.querySelector("#cfg-max-dep").value),
        W_FALTA: Number(cont.querySelector("#cfg-w-falta").value),
        W_EQUIDAD: Number(cont.querySelector("#cfg-w-equidad").value),
        W_DESCANSO_LIM: Number(cont.querySelector("#cfg-w-desc").value),
        W_VARIEDAD: Number(cont.querySelector("#cfg-w-var").value),
        W_REPETICION: Number(cont.querySelector("#cfg-w-rep").value),
        W_FALTA_DESC: Number(cont.querySelector("#cfg-w-falta-desc").value),
      });
      insertarBanner(zona, "exito", "Parámetros guardados.");
      await refrescarResumen();
    } catch (e) { insertarBanner(zona, "error", e.message); }
  });
}

// ---------------------------------------------------------------------
// Página: Informe
// ---------------------------------------------------------------------
function dibujarSerie(contenedor, titulo, serie, sufijo = "") {
  if (!serie.length) return;
  const max = Math.max(...serie.map((s) => s.valor), 1);
  const bloque = elemento(`<div class="seccion"><h3>${titulo}</h3></div>`);
  serie.forEach((s) => {
    const pct = (s.valor / max) * 100;
    bloque.appendChild(elemento(`
      <div class="barra-fila">
        <span class="barra-etiqueta" title="${s.label}">${s.label}</span>
        <div class="barra-pista"><div class="barra-relleno" style="width:${pct}%"></div></div>
        <span class="barra-valor">${s.valor}${sufijo}</span>
      </div>
    `));
  });
  contenedor.appendChild(bloque);
}

async function renderInforme(cont) {
  cont.innerHTML = `<h2>Informe</h2><div id="zona-informe"></div>`;
  const zona = cont.querySelector("#zona-informe");
  try {
    const r = await api("GET", "/api/informe");
    if (r.vacio) {
      zona.innerHTML = banner("info", "Todavía no hay turnos escritos en la rejilla. Cuando generes o escribas algunos, aquí verás el informe.");
      return;
    }
    zona.appendChild(elemento(`<p class="muted">Días con turnos: ${r.dias[0]}–${r.dias[r.dias.length - 1]}. Refleja lo que hay en la rejilla ahora mismo.</p>`));
    if (r.excluidos_finde.length) {
      zona.appendChild(elemento(`<p class="muted nota-informe" title="${esc(r.excluidos_finde.join(", "))}">Las comparaciones entre monitores no incluyen a los ${r.excluidos_finde.length} monitores de fin de semana, porque no están los mismos días que el resto.</p>`));
    }
    dibujarSerie(zona, "Esfuerzo normalizado por monitor", r.esfuerzo);
    dibujarSerie(zona, "Descansos por monitor", r.descansos);
    dibujarSerie(zona, "Días de dependiente por monitor", r.dias_dependiente_monitor);
    if (r.falta.length) dibujarSerie(zona, "Turnos sin cubrir", r.falta);
    else zona.appendChild(elemento(banner("exito", "No hay turnos sin cubrir.")));
  } catch (e) {
    zona.innerHTML = banner("error", e.message);
  }
}

// ---------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  configurarBarraSuperior();
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => irA(btn.dataset.pagina));
  });
  dibujarNav();
  await refrescarResumen();
  await dibujarPagina();
});
