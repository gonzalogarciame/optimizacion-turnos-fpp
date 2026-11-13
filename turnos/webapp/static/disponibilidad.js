"use strict";

// =====================================================================
// Pantalla "Disponibilidad": quién viene cada día.
//
// Una tabla de colores. Se elige un "pincel" (Disponible / No viene / Descanso
// impuesto) y se pinta con clic o arrastrando. Clic en un nombre pinta toda su
// fila; clic en un día pinta toda su columna (solo los monitores visibles).
// Pintar con el pincel sobre una casilla que ya lo tiene la devuelve a «Disponible».
// Los cambios son un borrador hasta pulsar Guardar. Ctrl+Z deshace.
//
// Se carga después de rejilla.js (usa esc, norm, toast, estiloSeccion...) y antes de app.js.
// =====================================================================

const PINCELES = {
  D: { texto: "Disponible", corto: "Viene", icono: "✓", ayuda: "Viene y puede tener turno" },
  X: { texto: "No viene", corto: "No viene", icono: "✕", ayuda: "No participa ese día" },
  R: { texto: "Descanso impuesto", corto: "Descanso", icono: "😴", ayuda: "Está, pero ese día descansa sí o sí" },
};

const DP = {
  dias: [],
  diasInfo: [],
  filas: [],            // [{nombre, meta, vals:{dia: código}}]
  orig: new Map(),      // "i|dia" -> código guardado
  pincel: "X",
  texto: "",
  grupo: "",
  ver: "todos",         // todos | ausencias | cambios
  deshacer: [],
  arrastre: null,       // {valor, op}
  tds: new Map(),       // "i|dia" -> <td>
  trs: [],
  el: {},
};

function disponibilidadTieneCambios() {
  return DP.filas.length > 0 && cambiosDisp().length > 0;
}

const claveDisp = (i, dia) => `${i}|${dia}`;
const valDisp = (i, dia) => DP.filas[i].vals[dia];

function cambiosDisp() {
  const filas = [];
  DP.filas.forEach((f, i) => {
    if (DP.dias.some((d) => f.vals[d] !== DP.orig.get(claveDisp(i, d)))) filas.push(i);
  });
  return filas;
}

function celdasCambiadas() {
  let n = 0;
  DP.filas.forEach((f, i) => DP.dias.forEach((d) => { if (f.vals[d] !== DP.orig.get(claveDisp(i, d))) n += 1; }));
  return n;
}

// ---------------------------------------------------------------------
// Carga y pantalla
// ---------------------------------------------------------------------
async function renderDisponibilidad(cont) {
  const r = await api("GET", "/api/disponibilidad");
  DP.dias = r.dias;
  DP.diasInfo = r.dias_info || r.dias.map((dia) => ({ dia, semana: "", finde: false }));
  DP.orig = new Map();
  DP.deshacer = [];
  DP.filas = r.filas.map((f, i) => {
    const vals = {};
    DP.dias.forEach((d) => {
      const v = String(f[String(d)] ?? "D").trim().toUpperCase();
      vals[d] = PINCELES[v] ? v : "D";
      DP.orig.set(claveDisp(i, d), vals[d]);
    });
    return { nombre: f.NOMBRE, meta: r.monitores[f.NOMBRE] || { sexo: "", grupo: "", descansa: true }, vals };
  });
  const grupos = [...new Set(DP.filas.map((f) => f.meta.grupo).filter(Boolean))].sort();

  cont.classList.add("llena");
  cont.innerHTML = `
    <div class="pagina-cab">
      <h2>Disponibilidad</h2>
      <span class="muted">Elige un pincel y haz clic o arrastra. Clic en un nombre: toda su fila · clic en un día: toda la columna.</span>
    </div>
    <div class="barra" id="disp-barra">
      <div class="barra-grupo">
        <span class="etq-barra">Pincel</span>
        <div class="segmentado" id="disp-pinceles"></div>
      </div>
      <span class="barra-sep"></span>
      <div class="barra-grupo">
        <input type="search" id="disp-buscar" placeholder="Buscar monitor…" autocomplete="off">
        <select id="disp-grupo"><option value="">Todos los grupos</option>${grupos.map((g) => `<option>${esc(g)}</option>`).join("")}</select>
        <select id="disp-ver">
          <option value="todos">Todos</option>
          <option value="ausencias">Con ausencias</option>
          <option value="cambios">Cambiados</option>
        </select>
      </div>
      <div class="barra-grupo derecha">
        <span id="disp-estado" class="estado"></span>
        <button id="disp-deshacer" class="secundario" title="Ctrl+Z">Deshacer</button>
        <button id="disp-descartar" class="secundario">Descartar</button>
        <button id="disp-guardar">Guardar</button>
      </div>
    </div>
    <div id="disp-avisos"></div>
    <div class="tablero-caja" id="disp-caja"></div>
    <div class="leyenda">
      ${Object.entries(PINCELES).map(([c, p]) => `<span><i class="lg d-${c}"></i> ${p.texto}: ${p.ayuda.toLowerCase()}</span>`).join("")}
      <span><i class="lg editada"></i> Cambiada, sin guardar</span>
      <span><i class="lg aviso-finde"></i> Monitor de fin de semana en descanso</span>
    </div>`;
  DP.el = {
    cont, barra: cont.querySelector("#disp-barra"), caja: cont.querySelector("#disp-caja"), avisos: cont.querySelector("#disp-avisos"),
  };
  dibujarPinceles();
  const q = (s) => cont.querySelector(s);
  q("#disp-buscar").value = DP.texto;
  q("#disp-grupo").value = DP.grupo;
  q("#disp-ver").value = DP.ver;
  q("#disp-buscar").addEventListener("input", (e) => { DP.texto = e.target.value; filtrarDisp(); });
  q("#disp-grupo").addEventListener("change", (e) => { DP.grupo = e.target.value; filtrarDisp(); });
  q("#disp-ver").addEventListener("change", (e) => { DP.ver = e.target.value; filtrarDisp(); });
  q("#disp-guardar").addEventListener("click", guardarDisp);
  q("#disp-deshacer").addEventListener("click", deshacerDisp);
  q("#disp-descartar").addEventListener("click", descartarDisp);
  dibujarTablaDisp();
  pintarDispTodo();
}

function dibujarPinceles() {
  const cont = DP.el.cont.querySelector("#disp-pinceles");
  cont.innerHTML = "";
  Object.entries(PINCELES).forEach(([c, p]) => {
    const b = elemento(`<button type="button" class="pincel d-${c} ${DP.pincel === c ? "on" : ""}" title="${esc(p.ayuda)}"><i></i>${p.corto}</button>`);
    b.addEventListener("click", () => { DP.pincel = c; dibujarPinceles(); });
    cont.appendChild(b);
  });
}

function dibujarTablaDisp() {
  DP.tds = new Map();
  DP.trs = [];
  const tabla = elemento(`<table class="tablero disp"><thead></thead><tbody></tbody></table>`);
  const thead = tabla.querySelector("thead"), tbody = tabla.querySelector("tbody");

  const tr1 = elemento(`<tr></tr>`);
  tr1.appendChild(elemento(`<th class="etq esquina">Monitor <small id="disp-n"></small></th>`));
  DP.diasInfo.forEach(({ dia, semana, finde }) => {
    const th = elemento(`<th class="dia${finde ? " finde" : ""}" title="Clic: pintar este día para los monitores que se ven"><b>${dia}</b><small>${esc(semana)}</small></th>`);
    th.addEventListener("click", () => pintarColumna(dia));
    tr1.appendChild(th);
  });
  thead.appendChild(tr1);

  const tr2 = elemento(`<tr class="fila-sin"></tr>`);
  tr2.appendChild(elemento(`<th class="etq" title="Monitores que vienen ese día (disponibles o en descanso)">Vienen <small>cada día</small></th>`));
  DP.dias.forEach((d) => tr2.appendChild(elemento(`<th class="sin"><span class="cuenta-dia" data-dia="${d}"></span></th>`)));
  thead.appendChild(tr2);

  DP.filas.forEach((f, i) => {
    const tr = document.createElement("tr");
    tr.className = "fila disp-fila";
    const etq = elemento(`<td class="etq sub disp-nombre" title="Clic: pintar toda la fila de ${esc(f.nombre)}">
      <span class="acampado">${esc(f.nombre)}</span>${insigniaSexo(f.meta.sexo)}
      ${f.meta.descansa === false ? `<span class="sel-tag" title="Monitor de fin de semana: prefiere no descansar">finde</span>` : ""}</td>`);
    etq.addEventListener("click", () => pintarFila(i));
    tr.appendChild(etq);
    DP.dias.forEach((d, k) => {
      const td = document.createElement("td");
      td.className = "dcell";
      td.dataset.i = i;
      td.dataset.d = d;
      DP.tds.set(claveDisp(i, d), td);
      tr.appendChild(td);
    });
    DP.trs.push(tr);
    tbody.appendChild(tr);
  });

  DP.el.caja.innerHTML = "";
  DP.el.caja.appendChild(tabla);

  // Pintar con clic y arrastre
  tabla.addEventListener("mousedown", (e) => {
    const td = e.target.closest("td.dcell");
    if (!td || e.button !== 0) return;
    e.preventDefault();
    const i = Number(td.dataset.i), d = Number(td.dataset.d);
    const valor = valDisp(i, d) === DP.pincel ? "D" : DP.pincel;
    DP.arrastre = { valor, op: [] };
    aplicarCelda(i, d, valor);
  });
  tabla.addEventListener("mouseover", (e) => {
    if (!DP.arrastre) return;
    const td = e.target.closest("td.dcell");
    if (td) aplicarCelda(Number(td.dataset.i), Number(td.dataset.d), DP.arrastre.valor);
  });
}

document.addEventListener("mouseup", () => {
  if (!DP.arrastre) return;
  const op = DP.arrastre.op;
  DP.arrastre = null;
  if (op.length) { DP.deshacer.push(op); pintarDispTodo(); }
});

// ---------------------------------------------------------------------
// Pintar
// ---------------------------------------------------------------------
function aplicarCelda(i, dia, valor) {
  const antes = valDisp(i, dia);
  if (antes === valor) return;
  DP.filas[i].vals[dia] = valor;
  if (DP.arrastre) DP.arrastre.op.push({ i, dia, antes });
  pintarCeldaDisp(i, dia);
  actualizarCuentas();
}

function aplicarMasivo(celdas, valor, texto) {
  const op = [];
  celdas.forEach(([i, dia]) => {
    const antes = valDisp(i, dia);
    if (antes !== valor) { op.push({ i, dia, antes }); DP.filas[i].vals[dia] = valor; }
  });
  if (!op.length) return;
  DP.deshacer.push(op);
  pintarDispTodo();
  toast(`${texto} · ${op.length} casilla${op.length === 1 ? "" : "s"} (Ctrl+Z deshace)`, "info");
}

function visiblesDisp() {
  return DP.filas.map((_, i) => i).filter((i) => !DP.trs[i].hidden);
}

function pintarFila(i) {
  const todas = DP.dias.every((d) => valDisp(i, d) === DP.pincel);
  const valor = todas ? "D" : DP.pincel;
  aplicarMasivo(DP.dias.map((d) => [i, d]), valor, `${DP.filas[i].nombre}: ${PINCELES[valor].texto.toLowerCase()} todos los días`);
}

function pintarColumna(dia) {
  const filas = visiblesDisp();
  if (!filas.length) return;
  if (filas.length > 12 && !confirm(`Vas a pintar el día ${dia} para ${filas.length} monitores (los que se ven ahora) como «${PINCELES[DP.pincel].texto}». ¿Seguro?`)) return;
  const todas = filas.every((i) => valDisp(i, dia) === DP.pincel);
  const valor = todas ? "D" : DP.pincel;
  aplicarMasivo(filas.map((i) => [i, dia]), valor, `Día ${dia}: ${PINCELES[valor].corto.toLowerCase()} para ${filas.length} monitor(es)`);
}

function pintarCeldaDisp(i, dia) {
  const td = DP.tds.get(claveDisp(i, dia));
  if (!td) return;
  const v = valDisp(i, dia), f = DP.filas[i];
  const cls = ["dcell", `d-${v}`];
  const info = DP.diasInfo.find((x) => x.dia === dia);
  if (info && info.finde) cls.push("finde");
  if (v !== DP.orig.get(claveDisp(i, dia))) cls.push("editada");
  let titulo = `${f.nombre} · día ${dia} · ${PINCELES[v].texto}`;
  if (v === "R" && f.meta.descansa === false) {
    cls.push("aviso-finde");
    titulo += " — ⚠ monitor de fin de semana: el descanso impuesto contradice que prefiera no descansar (el generador lo rechazará)";
  }
  td.className = cls.join(" ");
  td.title = titulo;
  td.textContent = v === "D" ? "" : PINCELES[v].icono;
}

function actualizarCuentas() {
  DP.dias.forEach((d) => {
    const el = DP.el.cont.querySelector(`.cuenta-dia[data-dia="${d}"]`);
    if (!el) return;
    const n = DP.filas.filter((_, i) => valDisp(i, d) !== "X").length;
    el.textContent = n;
    el.className = "cuenta-dia" + (n < DP.filas.length ? " menos" : "");
    el.title = `${n} de ${DP.filas.length} monitores vienen el día ${d}`;
  });
  const n = celdasCambiadas();
  const est = DP.el.cont.querySelector("#disp-estado");
  if (est) {
    est.textContent = n ? `● ${n} casilla${n === 1 ? "" : "s"} cambiada${n === 1 ? "" : "s"} sin guardar` : "✓ Todo guardado";
    est.classList.toggle("pendiente", n > 0);
    DP.el.cont.querySelector("#disp-guardar").disabled = n === 0;
    DP.el.cont.querySelector("#disp-descartar").disabled = n === 0;
    DP.el.cont.querySelector("#disp-deshacer").disabled = DP.deshacer.length === 0;
  }
  // Aviso: descanso impuesto a monitores de fin de semana (el generador lo rechaza)
  const malos = [];
  DP.filas.forEach((f, i) => { if (f.meta.descansa === false && DP.dias.some((d) => valDisp(i, d) === "R")) malos.push(f.nombre); });
  DP.el.avisos.innerHTML = "";
  if (malos.length) {
    DP.el.avisos.appendChild(alerta(
      `${malos.length} monitor(es) de fin de semana tienen «Descanso impuesto» (${malos.slice(0, 4).join(", ")}${malos.length > 4 ? "…" : ""}). ` +
      `Prefieren no descansar y el generador lo marcará como contradictorio: usa «No viene» o quita el descanso.`));
  }
}

function pintarDispTodo() {
  DP.filas.forEach((_, i) => DP.dias.forEach((d) => pintarCeldaDisp(i, d)));
  filtrarDisp();
  actualizarCuentas();
}

function filtrarDisp() {
  const q = norm(DP.texto);
  const cambiadas = new Set(cambiosDisp());
  let visibles = 0;
  DP.filas.forEach((f, i) => {
    let ok = !q || norm(f.nombre).includes(q);
    if (ok && DP.grupo) ok = f.meta.grupo === DP.grupo;
    if (ok && DP.ver === "ausencias") ok = DP.dias.some((d) => valDisp(i, d) !== "D");
    if (ok && DP.ver === "cambios") ok = cambiadas.has(i);
    DP.trs[i].hidden = !ok;
    if (ok) visibles += 1;
  });
  const n = DP.el.cont.querySelector("#disp-n");
  if (n) n.textContent = visibles === DP.filas.length ? `(${visibles})` : `(${visibles} de ${DP.filas.length})`;
}

// ---------------------------------------------------------------------
// Deshacer, descartar, guardar
// ---------------------------------------------------------------------
function deshacerDisp() {
  const op = DP.deshacer.pop();
  if (!op) return;
  op.slice().reverse().forEach(({ i, dia, antes }) => { DP.filas[i].vals[dia] = antes; });
  pintarDispTodo();
}

function descartarDisp() {
  if (!celdasCambiadas()) return;
  if (!confirm("¿Descartar todos los cambios sin guardar?")) return;
  DP.filas.forEach((f, i) => DP.dias.forEach((d) => { f.vals[d] = DP.orig.get(claveDisp(i, d)); }));
  DP.deshacer = [];
  pintarDispTodo();
}

async function guardarDisp() {
  const filas = cambiosDisp().map((i) => {
    const fila = { NOMBRE: DP.filas[i].nombre };
    DP.dias.forEach((d) => { fila[String(d)] = DP.filas[i].vals[d]; });
    return fila;
  });
  if (!filas.length) return;
  const n = celdasCambiadas();
  try {
    await api("POST", "/api/disponibilidad", { filas });
    await refrescarResumen();
    await renderDisponibilidad(DP.el.cont);
    toast(`Disponibilidad guardada: ${n} casilla${n === 1 ? "" : "s"} (con copia de seguridad).`, "exito");
  } catch (e) {
    toast(e.message, "error");
  }
}

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && typeof paginaActual !== "undefined" && paginaActual === "disponibilidad") {
    if (e.target.matches && e.target.matches("input[type=text], input[type=search], textarea")) return;
    e.preventDefault();
    deshacerDisp();
  }
});
window.addEventListener("beforeunload", (e) => {
  if (typeof paginaActual !== "undefined" && paginaActual === "disponibilidad" && disponibilidadTieneCambios()) { e.preventDefault(); e.returnValue = ""; }
});
