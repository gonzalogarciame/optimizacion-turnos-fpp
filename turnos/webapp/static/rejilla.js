"use strict";

// =====================================================================
// Pantalla "Rejilla": tabla turnos × días, editable casilla a casilla.
//
// - Se lee directamente de la hoja TURNOS (cualquier día, también el pasado).
// - Clic en una casilla -> selector de monitores con buscador.
// - Los cambios son un borrador hasta pulsar "Guardar" (copia de seguridad
//   automática). Ctrl+Z los deshace.
// - "Generar" lanza el optimizador desde el día elegido y enseña una
//   PROPUESTA: no toca el Excel hasta pulsar "Aplicar".
//
// Se carga antes que app.js, que usa renderRejilla() y rejillaTieneCambios().
// Depende de api(), elemento(), banner() de app.js (solo se usan al ejecutar).
// =====================================================================

const REJ = {
  datos: null,            // respuesta de /api/rejilla (o de la propuesta)
  celdas: new Map(),      // clave -> {v, f, u}   estado actual (borrador)
  orig: new Map(),        // clave -> {v, f}      lo que hay en el Excel
  info: new Map(),        // clave -> {sec, fila, idx, dia, tipo, key}
  monitor: new Map(),     // nombre -> {nombre, sexo, grupo, alias}
  diaInfo: new Map(),     // dia -> {dia, semana, finde}
  disp: {},               // monitor -> {dia: 'D'|'X'|'R'}
  colocados: new Map(),   // dia -> Map(monitor -> [claves])
  sinAsignar: new Map(),  // dia -> [monitores disponibles sin puesto]
  conflictos: new Set(),  // claves de casillas con un monitor repetido ese día
  tds: new Map(),         // clave -> <td>
  resumenes: new Map(),   // "seccion|dia" -> <td> del resumen de sección
  chipsSin: new Map(),    // dia -> <button> de "sin puesto"
  desde: null,
  numDias: null,          // cuántos días generar desde `desde` (null = todos hasta el final)
  plegadas: new Set(["descanso"]),
  deshacer: [],
  modo: "edicion",        // "edicion" | "propuesta"
  refBase: null,          // en modo propuesta: lo guardado, para resaltar diferencias
  trabajo: null,          // resumen de la generación mostrada en modo propuesta
  el: {},                 // elementos fijos de la pantalla
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
const claveCelda = (tipo, fila, dia) => `${tipo}|${fila}|${dia}`;
const TITULOS = {
  paseo_piscina_siesta: "Paseo / piscina (siesta)",
  vigilancia_chicos: "Vigilancia nocturna · chicos",
  vigilancia_chicas: "Vigilancia nocturna · chicas",
  vigilancia_D_chicos: "Vigilancia dependientes · chicos",
  vigilancia_D_chicas: "Vigilancia dependientes · chicas",
};
const rotulo = (turno) => {
  if (TITULOS[turno]) return TITULOS[turno];
  const txt = String(turno).replace(/_/g, " ");
  return txt.charAt(0).toUpperCase() + txt.slice(1);
};
// Icono y color de acento de cada bloque de la tabla.
const ESTILOS = {
  lavaplatos: ["🧽", "#0ea5e9"], limpieza: ["🧹", "#10b981"], cocina: ["🍳", "#f97316"],
  comedor: ["🍽️", "#eab308"], paseo_piscina_siesta: ["🏊", "#06b6d4"],
  vigilancia_chicos: ["🌙", "#6366f1"], vigilancia_chicas: ["🌙", "#ec4899"],
  vigilancia_D_chicos: ["🌙", "#4338ca"], vigilancia_D_chicas: ["🌙", "#be185d"],
};
function estiloSeccion(sec) {
  if (sec.tipo === "dependiente") return ["🧒", "#8b5cf6"];
  if (sec.tipo === "descanso") return ["😴", "#94a3b8"];
  return ESTILOS[sec.titulo] || ["📋", "#64748b"];
}
const SEXO_TXT = { M: ["♂", "chico"], F: ["♀", "chica"] };
const insigniaSexo = (s) => SEXO_TXT[s] ? `<em class="sexo ${s}" title="Requiere monitor ${SEXO_TXT[s][1]}">${SEXO_TXT[s][0]}</em>` : "";
// "Alejandra fernandez De Villavicencio" -> nombre en negrita y apellidos debajo.
function nombreHtml(nombre) {
  const [primero, ...resto] = String(nombre).trim().split(/\s+/);
  return `<span class="n1">${esc(primero)}</span>${resto.length ? `<span class="n2">${esc(resto.join(" "))}</span>` : ""}`;
}
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
const hayNombre = (c) => !!c.v && c.v !== "-";

function rejillaTieneCambios() {
  return REJ.modo === "edicion" && !!REJ.datos && cambiosPendientes().length > 0;
}

// ---------------------------------------------------------------------
// Carga e indexado
// ---------------------------------------------------------------------
function indexar(datos) {
  REJ.datos = datos;
  REJ.celdas = new Map();
  REJ.orig = new Map();
  REJ.info = new Map();
  REJ.monitor = new Map(datos.monitores.map((m) => [m.nombre, m]));
  REJ.diaInfo = new Map(datos.dias.map((d) => [d.dia, d]));
  REJ.disp = datos.disponibilidad;
  datos.secciones.forEach((sec) => {
    sec.filas.forEach((fila, idx) => {
      datos.dias.forEach(({ dia }) => {
        const c = fila.celdas[String(dia)] || { v: "", f: false };
        const key = claveCelda(sec.tipo, fila.fila, dia);
        REJ.celdas.set(key, { v: c.v, f: !!c.f, u: !!c.u });
        REJ.orig.set(key, { v: c.v, f: !!c.f });
        REJ.info.set(key, { sec, fila, idx, dia, tipo: sec.tipo, key });
      });
    });
  });
  REJ.deshacer = [];
}

async function cargarRejilla() {
  const datos = await api("GET", "/api/rejilla");
  indexar(datos);
  REJ.desde = datos.desde;
  REJ.modo = "edicion";
  REJ.refBase = null;
  REJ.trabajo = null;
}

function cambiosPendientes() {
  const cambios = [];
  REJ.celdas.forEach((c, key) => {
    const o = REJ.orig.get(key);
    if (!o) return;
    const info = REJ.info.get(key);
    const cambiaPin = info.tipo === "turno" && !!c.f !== !!o.f && hayNombre(c);
    if (c.v !== o.v || cambiaPin) {
      cambios.push({ tipo: info.tipo, fila: info.fila.fila, dia: info.dia, valor: c.v, fijado: !!c.f && hayNombre(c) });
    }
  });
  return cambios;
}

const esEditada = (key) => {
  const c = REJ.celdas.get(key), o = REJ.orig.get(key);
  if (!c || !o) return false;
  const info = REJ.info.get(key);
  return c.v !== o.v || (info.tipo === "turno" && hayNombre(c) && !!c.f !== !!o.f);
};

// ---------------------------------------------------------------------
// Cálculos derivados: quién está dónde, conflictos, huecos
// ---------------------------------------------------------------------
function recalcular() {
  REJ.colocados = new Map(REJ.datos.dias.map(({ dia }) => [dia, new Map()]));
  REJ.celdas.forEach((c, key) => {
    if (!hayNombre(c)) return;
    const mapa = REJ.colocados.get(REJ.info.get(key).dia);
    if (!mapa.has(c.v)) mapa.set(c.v, []);
    mapa.get(c.v).push(key);
  });
  REJ.conflictos = new Set();
  REJ.sinAsignar = new Map();
  REJ.datos.dias.forEach(({ dia }) => {
    const mapa = REJ.colocados.get(dia);
    mapa.forEach((claves) => { if (claves.length > 1) claves.forEach((k) => REJ.conflictos.add(k)); });
    const libres = REJ.datos.monitores
      .filter((m) => ["D", "R"].includes((REJ.disp[m.nombre] || {})[String(dia)]) && !mapa.has(m.nombre))
      .map((m) => m.nombre);
    REJ.sinAsignar.set(dia, libres);
  });
}

function pintarTodo() {
  recalcular();
  REJ.tds.forEach((_, key) => pintarCelda(key));
  pintarResumenes();
  pintarCabeceras();
  actualizarBarra();
}

function cambiaRespectoBase(info, c) {
  const ref = REJ.refBase;
  if (!ref || !hayNombre(c)) return false;
  if (info.tipo === "dependiente") return ref.dep.get(`${info.fila.etiqueta}|${info.dia}`) !== c.v;
  const conj = ref.conj.get(`${info.sec.clave}|${info.dia}`);
  return !(conj && conj.has(c.v));
}

function pintarCelda(key) {
  const td = REJ.tds.get(key);
  if (!td) return;
  const info = REJ.info.get(key), c = REJ.celdas.get(key);
  const { sec, dia, tipo } = info;
  const cls = ["celda"], avisos = [];
  let texto = c.v;

  if (dia < REJ.desde) cls.push("hist");
  if (REJ.diaInfo.get(dia).finde) cls.push("finde");
  if (dia === REJ.desde) cls.push("borde-desde");
  if (!c.v) cls.push("vacia");

  if (tipo === "turno") {
    const plazas = sec.plazas[String(dia)] ?? 0;
    const tope = Math.max(plazas, (sec.tope || {})[String(dia)] ?? 0);
    if (!c.v && info.idx >= tope) cls.push("sinplaza");
    else if (!c.v && info.idx >= plazas) { cls.push("opcional"); avisos.push("Plaza opcional: el turno acepta más gente ese día"); }
    else if (!c.v) { cls.push("falta"); avisos.push("Plaza sin cubrir"); }
    else if (info.idx >= tope) { cls.push("exceso"); avisos.push("Hay más gente de la que el turno acepta ese día (ajusta «Plazas por día»)"); }
    else if (info.idx >= plazas) { cls.push("extra"); avisos.push("Persona de más: el turno acepta más gente ese día"); }
  }
  if (tipo === "dependiente" && c.v === "-") { cls.push("nopresente"); texto = "—"; avisos.push("El acampado no está ese día"); }

  if (hayNombre(c)) {
    const m = REJ.monitor.get(c.v);
    if (c.u || !m) { cls.push("desconocido"); avisos.push("Nombre no reconocido: vacía la casilla o elige otro monitor"); }
    else {
      if (REJ.conflictos.has(key)) { cls.push("conflicto"); avisos.push("Este monitor está en más de un sitio ese día"); }
      const estado = (REJ.disp[c.v] || {})[String(dia)];
      if (estado === "X") { cls.push("aviso-ausente"); avisos.push("Figura como ausente ese día"); }
      else if (estado === "R" && tipo !== "descanso") { cls.push("aviso-ausente"); avisos.push("Tiene descanso impuesto ese día: hay que reasignar este puesto"); }
      if (tipo === "descanso" && m.descansa === false) { cls.push("aviso-finde"); avisos.push("Monitor de fin de semana: prefiere no descansar"); }
      const req = tipo === "dependiente" ? info.fila.sexo_req : sec.sexo_req;
      if (req && req !== "-" && m.sexo !== req) { cls.push("aviso-sexo"); avisos.push(`Este puesto requiere sexo ${req}`); }
    }
    if (tipo === "turno" && c.f && dia >= REJ.desde) { cls.push("fijada"); avisos.push("Fijada: el optimizador la respeta"); }
  }
  if (REJ.modo === "edicion" && esEditada(key)) cls.push("editada");
  if (REJ.modo === "propuesta" && dia >= REJ.desde && cambiaRespectoBase(info, c)) cls.push("cambia");
  if (REJ.modo === "propuesta" || cls.includes("sinplaza")) cls.push("solo-lectura");

  td.className = cls.join(" ");
  td.title = [c.v && c.v !== "-" ? c.v : "", ...avisos].filter(Boolean).join(" · ");
  const pin = cls.includes("fijada") ? `<i class="pin" aria-label="Fijada">📌</i>` : "";
  td.innerHTML = c.v && c.v !== "-" ? `<span class="nom">${nombreHtml(texto)}</span>${pin}` : `<span class="nom"><span class="n1">${esc(texto)}</span></span>`;
}

function pintarResumenes() {
  REJ.datos.secciones.forEach((sec) => {
    REJ.datos.dias.forEach(({ dia }) => {
      const td = REJ.resumenes.get(`${sec.clave}|${dia}`);
      if (!td) return;
      const celdas = sec.filas.map((f) => REJ.celdas.get(claveCelda(sec.tipo, f.fila, dia)));
      let texto = "", clase = "";
      if (sec.tipo === "turno") {
        const plazas = sec.plazas[String(dia)] ?? 0;
        const tope = Math.max(plazas, (sec.tope || {})[String(dia)] ?? 0);
        const n = celdas.filter(hayNombre).length;
        if (plazas || n || tope) {
          texto = `${n}/${plazas}`;
          clase = n < plazas ? "falta" : n > tope ? "exceso" : "ok";
          if (tope > plazas) texto += `<small>hasta ${tope}</small>`;
        }
      } else if (sec.tipo === "dependiente") {
        const presentes = celdas.filter((c) => c.v !== "-").length;
        const n = celdas.filter(hayNombre).length;
        texto = `${n}/${presentes}`;
        clase = n < presentes ? "falta" : "ok";
      } else {
        texto = String(celdas.filter(hayNombre).length);
      }
      const extremo = dia === REJ.datos.dias[0].dia || dia === REJ.datos.dias[REJ.datos.dias.length - 1].dia;
      td.className = `resumen ${clase}` + (dia < REJ.desde ? " hist" : "") + (sec.tipo === "turno" && extremo ? " editable" : "");
      td.innerHTML = texto;
    });
  });
}

function pintarCabeceras() {
  REJ.datos.dias.forEach(({ dia }) => {
    const th = REJ.el.cabeceraDia && REJ.el.cabeceraDia.get(dia);
    if (th) {
      th.classList.toggle("hist", dia < REJ.desde);
      th.classList.toggle("borde-desde", dia === REJ.desde);
      th.classList.toggle("desde-marca", dia === REJ.desde);
    }
    const chip = REJ.chipsSin.get(dia);
    if (chip) {
      const n = REJ.sinAsignar.get(dia).length;
      chip.textContent = n ? String(n) : "✓";
      chip.className = "chip-sin " + (n ? (dia < REJ.desde ? "grave" : "pendiente") : "ok");
      chip.title = n ? `${n} monitor(es) disponible(s) sin puesto ese día` : "Todos los monitores disponibles tienen puesto";
      chip.parentElement.classList.toggle("hist", dia < REJ.desde);
      chip.parentElement.classList.toggle("borde-desde", dia === REJ.desde);
    }
  });
}

// ---------------------------------------------------------------------
// Edición: cambios con deshacer
// ---------------------------------------------------------------------
const pinPorDefecto = (info) => info.tipo === "dependiente" || (info.tipo === "turno" && info.dia >= REJ.desde);

function aplicarOperacion(op) {
  op.cambios.forEach(({ key, despues }) => REJ.celdas.set(key, { ...despues }));
  REJ.deshacer.push(op);
  pintarTodo();
}

function cambio(key, nuevo) {
  return { key, antes: { ...REJ.celdas.get(key) }, despues: { v: nuevo.v, f: !!nuevo.f, u: false } };
}

function deshacer() {
  if (REJ.modo !== "edicion") return;
  const op = REJ.deshacer.pop();
  if (!op) { toast("No hay nada que deshacer", "info"); return; }
  op.cambios.forEach(({ key, antes }) => REJ.celdas.set(key, { ...antes }));
  pintarTodo();
  toast("Deshecho: " + op.texto, "info");
}

function elegirMonitor(key, nombre) {
  const info = REJ.info.get(key), actual = REJ.celdas.get(key);
  const otros = (REJ.colocados.get(info.dia).get(nombre) || []).filter((k) => k !== key);
  const cambios = [cambio(key, { v: nombre, f: pinPorDefecto(info) })];
  let texto = `${nombre} → ${rotulo(info.sec.titulo)}`;
  if (otros.length) {
    // Ya tenía puesto ese día: se intercambian (quien estaba aquí pasa a su sitio).
    const [primero, ...resto] = otros;
    const desplazado = hayNombre(actual) ? actual.v : "";
    cambios.push(cambio(primero, { v: desplazado, f: desplazado ? pinPorDefecto(REJ.info.get(primero)) : false }));
    resto.forEach((k) => cambios.push(cambio(k, { v: "", f: false })));
    const dest = REJ.info.get(primero);
    texto += desplazado ? ` (intercambiado con ${rotulo(dest.sec.titulo)})` : ` (sale de ${rotulo(dest.sec.titulo)})`;
  }
  aplicarOperacion({ texto, cambios });
  if (otros.length) toast(texto, "info");
}

function fijarValor(key, v) {
  const actual = REJ.celdas.get(key);
  if (actual.v === v) return;
  aplicarOperacion({ texto: "casilla", cambios: [cambio(key, { v, f: false })] });
}

function alternarFijada(key) {
  const c = REJ.celdas.get(key);
  aplicarOperacion({ texto: "fijar", cambios: [cambio(key, { v: c.v, f: !c.f })] });
}

// ---------------------------------------------------------------------
// Selector de monitores (ventana emergente con buscador)
// ---------------------------------------------------------------------
let selectorAbierto = null;

function cerrarSelector() {
  if (selectorAbierto) { selectorAbierto.caja.remove(); selectorAbierto = null; }
}

function ubicarFlotante(caja, ancla) {
  const r = ancla.getBoundingClientRect();
  const ancho = caja.offsetWidth, alto = caja.offsetHeight;
  let izq = Math.min(Math.max(8, r.left), window.innerWidth - ancho - 8);
  let arriba = r.bottom + 4;
  if (arriba + alto > window.innerHeight - 8) arriba = Math.max(8, r.top - alto - 4);
  caja.style.left = `${izq}px`;
  caja.style.top = `${arriba}px`;
}

function ubicacionTexto(claves) {
  return claves.map((k) => {
    const i = REJ.info.get(k);
    return i.tipo === "descanso" ? "descanso" : i.tipo === "dependiente" ? i.fila.etiqueta : rotulo(i.sec.titulo);
  }).join(", ");
}

function abrirSelector(key, td, textoInicial = "") {
  if (REJ.modo !== "edicion") return;
  const info = REJ.info.get(key);
  const celda = REJ.celdas.get(key);
  const dia = info.dia, tipo = info.tipo;
  if (td.classList.contains("sinplaza")) return;
  cerrarSelector();

  const reqSexo = tipo === "dependiente" ? info.fila.sexo_req : info.sec.sexo_req;
  const di = REJ.diaInfo.get(dia);
  const titulo = tipo === "dependiente" ? info.fila.etiqueta : tipo === "descanso" ? "Descanso" : rotulo(info.sec.titulo);

  const caja = elemento(`<div class="selector" role="dialog">
    <div class="sel-cab"><b>${esc(titulo)}</b><span>día ${dia} · ${esc(di.semana)}${reqSexo && reqSexo !== "-" ? " · requiere " + reqSexo : ""}</span></div>
    <input class="sel-buscar" type="text" placeholder="Escribe para buscar un monitor…" autocomplete="off" spellcheck="false">
    <div class="sel-lista"></div>
    <div class="sel-pie"></div>
  </div>`);
  document.body.appendChild(caja);
  const entrada = caja.querySelector(".sel-buscar");
  const lista = caja.querySelector(".sel-lista");
  const pie = caja.querySelector(".sel-pie");
  let visibles = [], activo = 0;

  function construirLista() {
    const q = norm(entrada.value);
    const items = [];
    REJ.datos.monitores.forEach((m) => {
      if (q && !(norm(m.nombre).includes(q) || (m.alias || []).some((a) => norm(a).includes(q)))) return;
      const disp = (REJ.disp[m.nombre] || {})[String(dia)];
      const puestos = REJ.colocados.get(dia).get(m.nombre) || [];
      const aqui = puestos.includes(key);
      const otros = puestos.filter((k) => k !== key);
      const sexoOk = !reqSexo || reqSexo === "-" || m.sexo === reqSexo;
      const grupo = aqui ? 0 : disp === "X" ? 3 : otros.length ? 2 : 1;
      items.push({ m, disp, aqui, otros, sexoOk, grupo, rango: grupo * 2 + (sexoOk || grupo === 0 ? 0 : 1) });
    });
    items.sort((a, b) => a.rango - b.rango || a.m.nombre.localeCompare(b.m.nombre, "es"));
    visibles = items;
    activo = Math.min(activo, Math.max(0, items.length - 1));

    lista.innerHTML = "";
    if (!items.length) { lista.innerHTML = `<div class="sel-vacio">Ningún monitor coincide</div>`; return; }
    const titulos = { 0: "En esta casilla", 1: "Sin puesto ese día", 2: "Ya tienen puesto (se intercambian)", 3: "Ausentes ese día" };
    let ultimo = -1;
    items.forEach((it, i) => {
      if (it.grupo !== ultimo) {
        ultimo = it.grupo;
        lista.appendChild(elemento(`<div class="sel-grupo">${titulos[it.grupo]}</div>`));
      }
      const nota = it.grupo === 2 ? ubicacionTexto(it.otros) : it.grupo === 3 ? "ausente" : "";
      const fila = elemento(`<div class="sel-item${i === activo ? " activo" : ""}${it.sexoOk ? "" : " otro-sexo"}" data-i="${i}">
        <span class="sel-nombre">${esc(it.m.nombre)}</span>
        ${it.m.descansa === false ? `<span class="sel-tag" title="Monitor de fin de semana: prefiere no descansar">finde</span>` : ""}
        <span class="sel-meta">${it.sexoOk ? "" : "⚠ sexo · "}${esc(nota)}</span>
        <span class="sel-sexo ${it.m.sexo}">${it.m.sexo}</span>
      </div>`);
      fila.addEventListener("mousedown", (e) => { e.preventDefault(); elegir(it); });
      fila.addEventListener("mousemove", () => { if (activo !== i) { activo = i; marcarActivo(false); } });
      lista.appendChild(fila);
    });
  }

  function marcarActivo(desplazar = true) {
    lista.querySelectorAll(".sel-item").forEach((el) => {
      const on = Number(el.dataset.i) === activo;
      el.classList.toggle("activo", on);
      if (on && desplazar) el.scrollIntoView({ block: "nearest" });
    });
  }

  function elegir(it) {
    cerrarSelector();
    if (!it.aqui) elegirMonitor(key, it.m.nombre);
    td.focus();
  }

  function construirPie() {
    pie.innerHTML = "";
    const actual = REJ.celdas.get(key);
    if (tipo === "turno" && dia >= REJ.desde && hayNombre(actual)) {
      const lbl = elemento(`<label class="sel-fijar"><input type="checkbox" ${actual.f ? "checked" : ""}> Fijar (el optimizador la respeta)</label>`);
      lbl.querySelector("input").addEventListener("change", () => { alternarFijada(key); cerrarSelector(); td.focus(); });
      pie.appendChild(lbl);
    }
    const botones = elemento(`<div class="sel-botones"></div>`);
    if (tipo === "dependiente" && actual.v !== "-") {
      const b = elemento(`<button type="button" class="secundario">No está ese día (—)</button>`);
      b.addEventListener("click", () => { cerrarSelector(); fijarValor(key, "-"); td.focus(); });
      botones.appendChild(b);
    }
    if (actual.v !== "") {
      const etiqueta = tipo === "dependiente" ? "Que lo decida el optimizador" : "Vaciar casilla";
      const b = elemento(`<button type="button" class="secundario">${etiqueta}</button>`);
      b.addEventListener("click", () => { cerrarSelector(); fijarValor(key, ""); td.focus(); });
      botones.appendChild(b);
    }
    pie.appendChild(botones);
  }

  entrada.addEventListener("input", () => { activo = 0; construirLista(); });
  entrada.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); activo = Math.min(visibles.length - 1, activo + 1); marcarActivo(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); activo = Math.max(0, activo - 1); marcarActivo(); }
    else if (e.key === "Enter") { e.preventDefault(); if (visibles[activo]) elegir(visibles[activo]); }
    else if (e.key === "Escape") { e.preventDefault(); cerrarSelector(); td.focus(); }
  });

  entrada.value = textoInicial;
  construirLista();
  construirPie();
  ubicarFlotante(caja, td);
  selectorAbierto = { caja, td };
  entrada.focus();
  const activoEl = lista.querySelector(".sel-item.activo");
  if (activoEl) activoEl.scrollIntoView({ block: "nearest" });
}

function abrirSinAsignar(dia, ancla) {
  cerrarSelector();
  const libres = REJ.sinAsignar.get(dia) || [];
  const caja = elemento(`<div class="selector sin-asignar" role="dialog">
    <div class="sel-cab"><b>Sin puesto el día ${dia}</b><span>${libres.length} monitor(es)</span></div>
    <div class="sel-lista"></div>
    <div class="sel-pie"><small>Disponibles (D) o en descanso impuesto (R) que no aparecen en ningún turno, dependiente ni descanso.
    Colócalos desde una casilla vacía.</small></div>
  </div>`);
  const lista = caja.querySelector(".sel-lista");
  if (!libres.length) lista.innerHTML = `<div class="sel-vacio">Todos tienen puesto ✓</div>`;
  libres.forEach((n) => {
    const m = REJ.monitor.get(n);
    lista.appendChild(elemento(`<div class="sel-item"><span class="sel-nombre">${esc(n)}</span><span class="sel-meta">${esc(m.grupo || "")}</span><span class="sel-sexo ${m.sexo}">${m.sexo}</span></div>`));
  });
  document.body.appendChild(caja);
  ubicarFlotante(caja, ancla);
  selectorAbierto = { caja, td: ancla };
}

// ---------------------------------------------------------------------
// Avisos flotantes y ventanas modales
// ---------------------------------------------------------------------
function toast(texto, tipo = "info") {
  let pila = document.getElementById("toasts");
  if (!pila) { pila = elemento(`<div id="toasts"></div>`); document.body.appendChild(pila); }
  const t = elemento(`<div class="toast ${tipo}">${esc(texto)}</div>`);
  pila.appendChild(t);
  setTimeout(() => { t.classList.add("saliendo"); setTimeout(() => t.remove(), 300); }, tipo === "error" ? 7000 : 3500);
}

let modalAbierto = null;
function abrirModal(html, clase = "") {
  cerrarModal();
  const fondo = elemento(`<div class="modal-fondo"><div class="modal ${clase}">${html}</div></div>`);
  document.body.appendChild(fondo);
  modalAbierto = fondo;
  return fondo.querySelector(".modal");
}
function cerrarModal() {
  if (modalAbierto) { modalAbierto.remove(); modalAbierto = null; }
}

// ---------------------------------------------------------------------
// Construcción de la pantalla
// ---------------------------------------------------------------------
async function renderRejilla(cont) {
  cerrarSelector();
  await cargarRejilla();
  dibujarPantalla(cont);
  await revisarTrabajo();
}

function dibujarPantalla(cont) {
  cont.classList.add("llena");  // la tabla ocupa toda la altura que queda en la ventana
  cont.innerHTML = `
    <div class="pagina-cab">
      <h2>Rejilla de turnos</h2>
      <span class="muted">Haz clic en una casilla para elegir quién la hace.</span>
      <button type="button" class="boton-texto" id="btn-ayuda">¿Cómo se usa?</button>
      <div class="ayuda-pop" id="ayuda-pop" hidden>
        <ol>
          <li><b>Rellena o corrige a mano:</b> clic en una casilla y elige monitor (puedes escribir para buscar). <kbd>Supr</kbd> vacía, <kbd>Ctrl</kbd>+<kbd>Z</kbd> deshace.</li>
          <li><b>Guarda</b> para escribir en el Excel (con copia de seguridad).</li>
          <li><b>Generar turnos</b> rellena el resto con el optimizador desde el día que elijas. Verás una propuesta y decides si aplicarla.</li>
          <li>Lo que pones a mano en un día que se va a generar queda <b>fijado</b> y el optimizador lo respeta. Los días anteriores están <b>congelados</b> (en gris), pero puedes corregirlos.</li>
          <li><b>Plazas llegada y salida:</b> cuántas plazas hay que cubrir esos dos días y hasta cuántas personas acepta cada turno.</li>
          <li><b>WhatsApp</b> genera el texto de los turnos de un día para pegar en el grupo.</li>
        </ol>
      </div>
    </div>
    <div id="rej-barra"></div>
    <div id="rej-avisos"></div>
    <div class="tablero-caja" id="rej-caja"></div>
    <div class="leyenda">
      <span><i class="lg fijada"></i> Fijada (el optimizador la respeta)</span>
      <span><i class="lg editada"></i> Cambiada, sin guardar</span>
      <span><i class="lg falta"></i> Plaza sin cubrir</span>
      <span><i class="lg conflicto"></i> Monitor repetido ese día</span>
      <span><i class="lg hist"></i> Día congelado</span>
      <span><i class="lg cambia"></i> Cambio propuesto</span>
    </div>`;
  cont.querySelector("#btn-ayuda").addEventListener("click", () => {
    const pop = cont.querySelector("#ayuda-pop");
    pop.hidden = !pop.hidden;
  });
  REJ.el.cont = cont;
  REJ.el.barra = cont.querySelector("#rej-barra");
  REJ.el.avisos = cont.querySelector("#rej-avisos");
  REJ.el.caja = cont.querySelector("#rej-caja");
  dibujarBarra();
  dibujarTabla();
  pintarTodo();
}

document.addEventListener("mousedown", (e) => {
  const pop = document.getElementById("ayuda-pop");
  if (pop && !pop.hidden && !pop.contains(e.target) && e.target.id !== "btn-ayuda") pop.hidden = true;
});

// Iconos de línea (sin dependencias)
const icono = (trazos, tam = 14) =>
  `<svg width="${tam}" height="${tam}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${trazos}</svg>`;
const ICONO = {
  chat: icono('<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>'),
  ajustes: icono('<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>'),
};

function dibujarBarra() {
  const d = REJ.datos, b = REJ.el.barra;
  if (REJ.modo === "propuesta") {
    const t = REJ.trabajo || {};
    const r = t.resumen || {};
    const faltas = r.total_falta > 1e-6;
    b.className = "barra propuesta";
    b.innerHTML = `
      <div class="prop-info">
        <div class="prop-titulo">Propuesta del optimizador · días ${t.desde}–${t.hasta || d.dia_fin}</div>
        <div class="prop-datos">
          <span class="etiqueta ${faltas ? "mala" : "buena"}">${faltas ? `${r.total_falta.toFixed(0)} plaza(s) sin cubrir` : "Todos los turnos cubiertos"}</span>
          <span class="etiqueta">${esc(r.estado === "optimo" ? "Solución óptima" : r.estado || "")}</span>
          <span class="etiqueta">${r.tiempo_s != null ? r.tiempo_s.toFixed(1) + " s" : ""}</span>
        </div>
        <div class="prop-nota">Lo resaltado en <b class="verde">verde</b> cambia respecto a lo guardado. <b>Aún no se ha escrito nada en el Excel.</b>${t.hasta && t.hasta < d.dia_fin ? ` Los días ${t.hasta + 1}–${d.dia_fin} no se tocan.` : ""}${r.aviso_solver ? " " + esc(r.aviso_solver) : ""}</div>
      </div>
      <div class="barra-grupo derecha">
        <button type="button" id="btn-whatsapp" class="secundario icono">${ICONO.chat} WhatsApp</button>
        <button type="button" id="btn-descartar" class="secundario grande">Descartar</button>
        <button type="button" id="btn-aplicar" class="grande">Aplicar y guardar en el Excel</button>
      </div>`;
    b.querySelector("#btn-aplicar").addEventListener("click", aplicarPropuesta);
    b.querySelector("#btn-descartar").addEventListener("click", descartarPropuesta);
    b.querySelector("#btn-whatsapp").addEventListener("click", () => abrirWhatsApp());
    return;
  }
  b.className = "barra";
  const opcionesDia = d.dias.map(({ dia, semana }) => `<option value="${dia}">${dia} (${semana})</option>`).join("")
    + `<option value="${d.dia_fin + 1}">ninguno (todo congelado)</option>`;
  b.innerHTML = `
    <div class="barra-grupo">
      <label class="campo">Generar desde el día
        <select id="sel-desde">${opcionesDia}</select>
      </label>
      <label class="campo">Días
        <select id="sel-num" title="Cuántos días genera el optimizador a partir del día elegido"></select>
      </label>
      <button type="button" id="btn-generar" title="Lanza el optimizador desde ese día. Antes de tocar el Excel te enseña una propuesta.">Generar turnos</button>
      <details class="opciones">
        <summary title="Más opciones">···</summary>
        <div class="opciones-caja"><label><input type="checkbox" id="chk-dos-fases"> Equilibrar mejor el esfuerzo (más lento)</label></div>
      </details>
    </div>
    <span class="barra-sep"></span>
    <div class="barra-grupo">
      <button type="button" id="btn-plazas" class="secundario icono" title="Plazas necesarias y máximas de cada turno el día de llegada y el de salida">${ICONO.ajustes} Plazas llegada y salida</button>
      <button type="button" id="btn-whatsapp" class="secundario icono" title="Texto con los turnos de un día para pegar en el grupo">${ICONO.chat} WhatsApp</button>
    </div>
    <div class="barra-grupo derecha">
      <span id="rej-estado-cambios" class="estado"></span>
      <button type="button" id="btn-deshacer" class="secundario" title="Ctrl+Z">Deshacer</button>
      <button type="button" id="btn-descartar-cambios" class="secundario">Descartar</button>
      <button type="button" id="btn-guardar-rej">Guardar</button>
      <a class="enlace-boton" href="/api/descargar" title="Descargar el Excel tal como está guardado">Excel</a>
    </div>`;
  const sel = b.querySelector("#sel-desde");
  sel.value = String(REJ.desde);
  sel.addEventListener("change", () => cambiarDesde(Number(sel.value)));
  b.querySelector("#sel-num").addEventListener("change", (e) => { REJ.numDias = e.target.value === "todos" ? null : Number(e.target.value); });
  rellenarNumDias();
  b.querySelector("#btn-generar").addEventListener("click", generar);
  b.querySelector("#btn-plazas").addEventListener("click", () => abrirPlazas());
  b.querySelector("#btn-whatsapp").addEventListener("click", () => abrirWhatsApp());
  b.querySelector("#btn-deshacer").addEventListener("click", deshacer);
  b.querySelector("#btn-descartar-cambios").addEventListener("click", descartarCambios);
  b.querySelector("#btn-guardar-rej").addEventListener("click", () => guardarCambios());
}

function dibujarTabla() {
  const d = REJ.datos;
  REJ.tds = new Map();
  REJ.resumenes = new Map();
  REJ.chipsSin = new Map();
  REJ.el.cabeceraDia = new Map();

  const tabla = elemento(`<table class="tablero"><thead></thead><tbody></tbody></table>`);
  const thead = tabla.querySelector("thead"), tbody = tabla.querySelector("tbody");

  // Cabecera 1: días (el primero es la llegada y el último la salida: solo esos dos tienen plazas propias)
  const primero = d.dias[0].dia, ultimo = d.dias[d.dias.length - 1].dia;
  const esExtremo = (dia) => dia === primero || dia === ultimo;
  const trDias = elemento(`<tr></tr>`);
  trDias.appendChild(elemento(`<th class="etq esquina">Turnos</th>`));
  d.dias.forEach(({ dia, semana, finde }) => {
    const tag = d.dias.length > 1 ? (dia === primero ? "llegada" : dia === ultimo ? "salida" : "") : "";
    const th = elemento(`<th class="dia${finde ? " finde" : ""}" title="Clic: generar desde este día"><b>${dia}</b><small>${esc(semana)}</small>${tag ? `<i class="tag-dia">${tag}</i>` : ""}
      <span class="dia-acciones"><button type="button" class="mini" data-acc="wa" title="Turnos de este día para WhatsApp">${ICONO.chat}</button>${esExtremo(dia) ? `<button type="button" class="mini" data-acc="plazas" title="Plazas de llegada y salida">${ICONO.ajustes}</button>` : ""}</span></th>`);
    th.addEventListener("click", (e) => {
      const acc = e.target.closest && e.target.closest("button.mini");
      if (acc) { e.stopPropagation(); acc.dataset.acc === "wa" ? abrirWhatsApp(dia) : abrirPlazas(dia); return; }
      cambiarDesde(dia);
    });
    REJ.el.cabeceraDia.set(dia, th);
    trDias.appendChild(th);
  });
  thead.appendChild(trDias);

  // Cabecera 2: monitores sin puesto
  const trSin = elemento(`<tr class="fila-sin"></tr>`);
  trSin.appendChild(elemento(`<th class="etq" title="Monitores disponibles ese día que no aparecen en ningún turno, dependiente ni descanso">Sin puesto <small>sin asignar</small></th>`));
  d.dias.forEach(({ dia }) => {
    const th = elemento(`<th class="sin"><button type="button" class="chip-sin"></button></th>`);
    const chip = th.querySelector("button");
    chip.addEventListener("click", (e) => { e.stopPropagation(); abrirSinAsignar(dia, chip); });
    REJ.chipsSin.set(dia, chip);
    trSin.appendChild(th);
  });
  thead.appendChild(trSin);

  // Cuerpo
  d.secciones.forEach((sec) => {
    const plegada = REJ.plegadas.has(sec.clave);
    const acento = estiloSeccion(sec)[1];
    const trSec = elemento(`<tr class="sec ${sec.tipo}" style="--acento-fila:${acento}"></tr>`);
    const etq = elemento(`<td class="etq"><button type="button" class="plegar" aria-expanded="${!plegada}" title="${plegada ? "Desplegar" : "Plegar"}">${plegada ? "▸" : "▾"}</button>
      <i class="punto"></i><span class="sec-titulo">${esc(sec.tipo === "turno" ? rotulo(sec.titulo) : sec.titulo)}</span>
      ${insigniaSexo(sec.sexo_req)}
      ${sec.tipo === "descanso" ? `<small class="nota-sec" title="En los días que se regeneran, esta lista la recalcula el optimizador">la recalcula el optimizador</small>` : ""}</td>`);
    etq.addEventListener("click", () => {
      if (REJ.plegadas.has(sec.clave)) REJ.plegadas.delete(sec.clave); else REJ.plegadas.add(sec.clave);
      cerrarSelector();
      dibujarTabla();
      pintarTodo();
    });
    trSec.appendChild(etq);
    d.dias.forEach(({ dia }) => {
      const td = document.createElement("td");
      if (sec.tipo === "turno" && esExtremo(dia)) {
        td.title = "Clic para cambiar las plazas de este día";
        td.addEventListener("click", () => abrirPlazas());
      }
      REJ.resumenes.set(`${sec.clave}|${dia}`, td);
      trSec.appendChild(td);
    });
    tbody.appendChild(trSec);
    if (plegada) return;

    sec.filas.forEach((fila, idx) => {
      const tr = elemento(`<tr class="fila ${sec.tipo}" style="--acento-fila:${acento}"></tr>`);
      const etiqueta = sec.tipo === "dependiente"
        ? `<span class="acampado">${esc(fila.etiqueta)}</span>${insigniaSexo(fila.sexo_req)}`
        : `<span class="num">${sec.tipo === "turno" ? "Plaza " : ""}${idx + 1}</span>`;
      tr.appendChild(elemento(`<td class="etq sub">${etiqueta}</td>`));
      d.dias.forEach(({ dia }) => {
        const key = claveCelda(sec.tipo, fila.fila, dia);
        const td = document.createElement("td");
        td.dataset.key = key;
        td.tabIndex = 0;
        REJ.tds.set(key, td);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  });

  REJ.el.caja.innerHTML = "";
  REJ.el.caja.appendChild(tabla);
  REJ.el.tabla = tabla;

  tabla.addEventListener("click", (e) => {
    const td = e.target.closest("td.celda");
    if (td) abrirSelector(td.dataset.key, td);
  });
  tabla.addEventListener("keydown", teclasTabla);
  REJ.el.caja.addEventListener("scroll", reubicarSelector, { passive: true });
}

// El navegador desplaza la tabla al enfocar una casilla medio oculta: en vez de
// cerrar el selector, se recoloca junto a su casilla (y se cierra solo si ésta sale de la vista).
function reubicarSelector() {
  if (!selectorAbierto || !REJ.el.caja) return;
  const caja = REJ.el.caja.getBoundingClientRect();
  const r = selectorAbierto.td.getBoundingClientRect();
  if (r.bottom < caja.top || r.top > caja.bottom || r.right < caja.left || r.left > caja.right) { cerrarSelector(); return; }
  ubicarFlotante(selectorAbierto.caja, selectorAbierto.td);
}
window.addEventListener("scroll", reubicarSelector, { passive: true });
window.addEventListener("resize", reubicarSelector);

// ---------------------------------------------------------------------
// Teclado: moverse por la tabla, escribir para buscar, Supr para vaciar
// ---------------------------------------------------------------------
function celdaVecina(td, dx, dy) {
  if (dx) {
    let s = dx > 0 ? td.nextElementSibling : td.previousElementSibling;
    while (s && !s.classList.contains("celda")) s = dx > 0 ? s.nextElementSibling : s.previousElementSibling;
    return s;
  }
  const col = td.cellIndex;
  let tr = td.parentElement;
  for (;;) {
    tr = dy > 0 ? tr.nextElementSibling : tr.previousElementSibling;
    if (!tr) return null;
    const c = tr.cells[col];
    if (c && c.classList.contains("celda")) return c;
  }
}

function teclasTabla(e) {
  const td = e.target.closest && e.target.closest("td.celda");
  if (!td || e.ctrlKey || e.metaKey || e.altKey) return;
  const mover = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[e.key];
  if (mover) {
    e.preventDefault();
    const destino = celdaVecina(td, mover[0], mover[1]);
    if (destino) destino.focus();
  } else if (REJ.modo === "edicion" && (e.key === "Enter" || e.key === "F2")) {
    e.preventDefault();
    abrirSelector(td.dataset.key, td);
  } else if (REJ.modo === "edicion" && (e.key === "Delete" || e.key === "Backspace")) {
    e.preventDefault();
    if (!td.classList.contains("sinplaza")) fijarValor(td.dataset.key, "");
  } else if (REJ.modo === "edicion" && e.key.length === 1) {
    e.preventDefault();
    abrirSelector(td.dataset.key, td, e.key);
  }
}

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && typeof paginaActual !== "undefined" && paginaActual === "rejilla") {
    if (e.target.matches && e.target.matches("input[type=text], textarea")) return;
    e.preventDefault();
    deshacer();
  }
});
document.addEventListener("mousedown", (e) => {
  if (selectorAbierto && !selectorAbierto.caja.contains(e.target)) cerrarSelector();
});
window.addEventListener("beforeunload", (e) => {
  if (rejillaTieneCambios()) { e.preventDefault(); e.returnValue = ""; }
});

// ---------------------------------------------------------------------
// Barra de estado: cambios pendientes y avisos sobre días congelados
// ---------------------------------------------------------------------
function actualizarBarra() {
  if (!REJ.el.barra) return;
  const n = cambiosPendientes().length;
  const estadoEl = REJ.el.barra.querySelector("#rej-estado-cambios");
  if (estadoEl) {
    estadoEl.textContent = n ? `● ${n} cambio${n === 1 ? "" : "s"} sin guardar` : "✓ Todo guardado";
    estadoEl.classList.toggle("pendiente", n > 0);
    REJ.el.barra.querySelector("#btn-guardar-rej").disabled = n === 0;
    REJ.el.barra.querySelector("#btn-descartar-cambios").disabled = n === 0;
    REJ.el.barra.querySelector("#btn-deshacer").disabled = REJ.deshacer.length === 0;
  }

  const av = REJ.el.avisos;
  av.innerHTML = "";
  avisarFindeEnDescanso(av);
  if (REJ.modo !== "edicion") return;
  const incompletos = REJ.datos.dias
    .filter(({ dia }) => dia < REJ.desde && ((REJ.sinAsignar.get(dia) || []).length || [...REJ.conflictos].some((k) => REJ.info.get(k).dia === dia)))
    .map(({ dia }) => dia);
  if (incompletos.length) {
    const uno = incompletos.length === 1;
    av.appendChild(alerta(
      `Antes de generar desde el día ${REJ.desde}, completa ${uno ? "el día congelado" : "los días congelados"} ${incompletos.join(", ")}: ` +
      `${uno ? "tiene" : "tienen"} monitores sin puesto o repetidos (fila «Sin puesto» y casillas en rojo).`));
  }
  const nConf = REJ.conflictos.size;
  if (nConf) av.appendChild(alerta(`${nConf} casilla(s) con un monitor repetido el mismo día (en rojo).`, "error"));
}

// Una línea de aviso sobre la tabla; el texto completo queda en el tooltip.
function alerta(texto, tipo = "", boton = null) {
  const el = elemento(`<div class="alerta ${tipo}"><span title="${esc(texto)}">${texto}</span></div>`);
  if (boton) {
    const b = elemento(`<button type="button" class="secundario">${esc(boton.texto)}</button>`);
    b.addEventListener("click", boton.accion);
    el.appendChild(b);
  }
  return el;
}

// Los monitores de fin de semana prefieren no descansar: si hay alguno en descanso se avisa y, si el día
// es el de llegada o el de salida, se ofrece hacer sitio (que algún turno acepte más gente).
function avisarFindeEnDescanso(av) {
  const porDia = new Map();
  REJ.celdas.forEach((c, key) => {
    const info = REJ.info.get(key);
    if (info.tipo !== "descanso" || !hayNombre(c)) return;
    const m = REJ.monitor.get(c.v);
    if (m && m.descansa === false) {
      if (!porDia.has(info.dia)) porDia.set(info.dia, []);
      porDia.get(info.dia).push(c.v);
    }
  });
  const dias = REJ.datos.dias.map((x) => x.dia);
  porDia.forEach((nombres, dia) => {
    const extremo = dia === dias[0] || dia === dias[dias.length - 1];
    const texto = `<b>${nombres.length} monitor(es) de fin de semana en descanso el día ${dia}</b> (prefieren no descansar): ${esc(nombres.join(", "))}`;
    const boton = extremo && REJ.modo === "edicion" ? { texto: "Plazas llegada y salida", accion: () => abrirPlazas() } : null;
    av.appendChild(alerta(texto, "", boton));
  });
}

// Opciones del selector «Días»: de 1 al número de días que quedan desde el elegido ("todos" = hasta el final).
function rellenarNumDias() {
  const sel = REJ.el.barra && REJ.el.barra.querySelector("#sel-num");
  if (!sel || !REJ.datos) return;
  const fin = REJ.datos.dia_fin, max = fin - REJ.desde + 1;
  sel.disabled = max < 1;
  if (REJ.numDias != null && REJ.numDias >= max) REJ.numDias = null;
  let html = "";
  for (let n = 1; n < max; n++) html += `<option value="${n}">${n} día${n === 1 ? "" : "s"} (hasta el ${REJ.desde + n - 1})</option>`;
  if (max >= 1) html += `<option value="todos">Todos (hasta el ${fin})</option>`;
  sel.innerHTML = html;
  sel.value = REJ.numDias == null ? "todos" : String(REJ.numDias);
}

// Último día que se va a generar según el selector.
function hastaElegido() {
  const fin = REJ.datos.dia_fin;
  return REJ.numDias == null ? fin : Math.min(fin, REJ.desde + REJ.numDias - 1);
}

async function cambiarDesde(dia) {
  if (REJ.modo !== "edicion") return;
  REJ.desde = dia;
  const sel = REJ.el.barra.querySelector("#sel-desde");
  if (sel) sel.value = String(dia);
  rellenarNumDias();
  pintarTodo();
  try { await api("POST", "/api/desde", { dia }); } catch (e) { /* solo informativo */ }
}

// ---------------------------------------------------------------------
// Guardar / descartar
// ---------------------------------------------------------------------
async function guardarCambios({ silencioso = false } = {}) {
  const cambios = cambiosPendientes();
  if (!cambios.length) return true;
  try {
    const r = await api("POST", "/api/rejilla/guardar", { cambios });
    const copia = r.backup ? String(r.backup).split(/[\\/]/).pop() : "";
    await recargarManteniendoVista();
    if (!silencioso) toast(`Guardado: ${r.escritas} casilla(s). Copia de seguridad: ${copia}`, "exito");
    return true;
  } catch (e) {
    toast(e.message, "error");
    return false;
  }
}

async function recargarManteniendoVista() {
  const desde = REJ.desde;
  await cargarRejilla();
  if (desde != null && desde !== REJ.desde) { REJ.desde = desde; }
  dibujarPantalla(REJ.el.cont);
  await refrescarResumen();
}

function descartarCambios() {
  if (!cambiosPendientes().length) return;
  if (!confirm("¿Descartar todos los cambios sin guardar?")) return;
  REJ.celdas.forEach((c, key) => { const o = REJ.orig.get(key); REJ.celdas.set(key, { v: o.v, f: o.f, u: false }); });
  REJ.deshacer = [];
  pintarTodo();
}

// ---------------------------------------------------------------------
// Generar con el optimizador
// ---------------------------------------------------------------------
async function generar() {
  if (REJ.modo !== "edicion") return;
  if (REJ.desde > REJ.datos.dia_fin) { toast("Elige un día de inicio dentro del horizonte para generar.", "error"); return; }
  const pendientes = cambiosPendientes().length;
  if (pendientes) {
    if (!confirm(`Hay ${pendientes} cambio(s) sin guardar. Se guardarán en el Excel (con copia de seguridad) antes de generar.\n\n¿Continuar?`)) return;
    if (!(await guardarCambios({ silencioso: true }))) return;
  }
  const dosFases = REJ.el.barra.querySelector("#chk-dos-fases").checked;
  const hasta = hastaElegido();
  mostrarProgreso(hasta === REJ.desde ? `Generando el día ${REJ.desde}…` : `Generando los días ${REJ.desde}–${hasta}…`);
  try {
    await api("POST", "/api/generar", { desde: REJ.desde, hasta, dos_fases: dosFases });
  } catch (e) {
    cerrarModal();
    toast(e.message, "error");
    return;
  }
  await sondearTrabajo();
}

function mostrarProgreso(texto) {
  const m = abrirModal(`<div class="progreso"><div class="spinner"></div><div><b id="prog-titulo">${esc(texto)}</b><div id="prog-detalle" class="prog-detalle">Preparando…</div></div></div>`);
  return m;
}

async function sondearTrabajo() {
  for (;;) {
    let t;
    try { t = await api("GET", "/api/generar/estado"); }
    catch (e) { cerrarModal(); toast(e.message, "error"); return; }
    if (t.estado !== "corriendo") return finTrabajo(t);
    const det = document.getElementById("prog-detalle");
    if (!det) return;  // el usuario cerró la ventana o cambió de pantalla
    det.textContent = `${t.fase || ""} ${Math.round(t.segundos)} s`;
    await esperar(500);
  }
}

async function revisarTrabajo() {
  let t;
  try { t = await api("GET", "/api/generar/estado"); } catch (e) { return; }
  if (t.estado === "ninguno") return;
  if (t.estado === "corriendo") { REJ.desde = t.desde; mostrarProgreso(`Generando los días ${t.desde}–${t.hasta || REJ.datos.dia_fin}…`); await sondearTrabajo(); }
  else await finTrabajo(t);
}

async function finTrabajo(t) {
  cerrarModal();
  if (t.estado === "listo") {
    try {
      const prop = await api("GET", "/api/generar/propuesta");
      entrarPropuesta(prop, t);
    } catch (e) { toast(e.message, "error"); }
    return;
  }
  const avisos = (t.avisos || []).length ? `<details><summary>${t.avisos.length} aviso(s)</summary><ul>${t.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>` : "";
  let cuerpo;
  if (t.estado === "error_validacion") {
    cuerpo = `<h3>No se puede generar todavía</h3><p>La comprobación previa ha encontrado problemas:</p>
      <ul class="lista-err">${t.errores.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>${avisos}`;
  } else if (t.estado === "infactible") {
    cuerpo = `<h3>El optimizador no encuentra ninguna solución</h3>
      <p>Con las reglas activas y lo que has fijado no hay forma de cubrir todos los turnos. Suele deberse a casillas fijadas (amarillo) que se contradicen
      con la disponibilidad o con los dependientes. Prueba a quitar alguna fijación, o desactiva una regla en «Restricciones».</p>
      <ul class="lista-err">${(t.diagnostico || []).map((e) => `<li>${esc(e)}</li>`).join("")}</ul>${avisos}`;
  } else {
    cuerpo = `<h3>No se ha podido generar</h3><p class="msg-err">${esc(t.mensaje || "Error desconocido")}</p>`;
  }
  const m = abrirModal(`${cuerpo}<div class="modal-pie"><button id="modal-cerrar">Entendido</button></div>`);
  m.querySelector("#modal-cerrar").addEventListener("click", async () => {
    cerrarModal();
    try { await api("POST", "/api/generar/descartar", {}); } catch (e) { /* nada */ }
  });
}

function entrarPropuesta(prop, trabajo) {
  // Foto de lo guardado, para resaltar en verde lo que la propuesta cambia.
  const conj = new Map(), dep = new Map();
  REJ.celdas.forEach((c, key) => {
    const info = REJ.info.get(key);
    if (info.tipo === "dependiente") { dep.set(`${info.fila.etiqueta}|${info.dia}`, c.v); return; }
    if (!hayNombre(c)) return;
    const k = `${info.sec.clave}|${info.dia}`;
    if (!conj.has(k)) conj.set(k, new Set());
    conj.get(k).add(c.v);
  });
  REJ.refBase = { conj, dep };
  REJ.trabajo = trabajo;
  indexar(prop);
  REJ.desde = trabajo.desde;
  REJ.modo = "propuesta";
  cerrarSelector();
  dibujarPantalla(REJ.el.cont);
}

async function aplicarPropuesta() {
  const btn = document.getElementById("btn-aplicar");
  if (btn) btn.disabled = true;
  try {
    await api("POST", "/api/generar/aplicar", {});
    await cargarRejilla();
    dibujarPantalla(REJ.el.cont);
    await refrescarResumen();
    toast("Propuesta aplicada y guardada en el Excel (con copia de seguridad).", "exito");
  } catch (e) {
    toast(e.message, "error");
    if (btn) btn.disabled = false;
  }
}

async function descartarPropuesta() {
  try { await api("POST", "/api/generar/descartar", {}); } catch (e) { /* nada */ }
  await cargarRejilla();
  dibujarPantalla(REJ.el.cont);
  toast("Propuesta descartada. El Excel no se ha modificado.", "info");
}
