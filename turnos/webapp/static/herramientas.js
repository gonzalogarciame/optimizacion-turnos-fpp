"use strict";

// =====================================================================
// Diálogos de la rejilla:
//   · "Plazas de llegada y salida": plazas necesarias y "acepta hasta" de cada turno el primer y el último día.
//   · "WhatsApp": texto con los turnos de un día, listo para pegar en el grupo.
// Se carga después de rejilla.js (usa REJ, esc, rotulo, abrirModal, toast...) y antes de app.js.
// =====================================================================

const nombreDia = (info) => {
  if (!info || !info.fecha) return info ? `día ${info.dia}` : "";
  const f = new Date(`${info.fecha}T12:00:00`);
  const dow = f.toLocaleDateString("es-ES", { weekday: "long" });
  const mes = f.toLocaleDateString("es-ES", { month: "long" });
  return `${dow.charAt(0).toUpperCase()}${dow.slice(1)} ${info.dia} de ${mes}`;
};

// ---------------------------------------------------------------------
// Plazas de llegada y salida
// Solo el primer y el último día tienen plazas propias (los demás usan las normales de cada turno).
// ---------------------------------------------------------------------
const PL = { datos: null, trabajo: {}, orig: {}, dias: [], modal: null };

const numONulo = (v) => (v === "" || v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));

async function abrirPlazas() {
  if (REJ.modo !== "edicion") { toast("Aplica o descarta la propuesta antes de cambiar las plazas.", "info"); return; }
  let datos;
  try { datos = await api("GET", "/api/plazas"); } catch (e) { toast(e.message, "error"); return; }
  const primero = datos.dias[0], ultimo = datos.dias[datos.dias.length - 1];
  const extremos = primero.dia === ultimo.dia ? [primero] : [primero, ultimo];
  PL.datos = datos;
  PL.dias = extremos.map((x) => x.dia);
  PL.trabajo = {};
  PL.orig = {};
  datos.turnos.forEach((t) => {
    PL.trabajo[t.turno] = {};
    PL.orig[t.turno] = {};
    PL.dias.forEach((d) => {
      const v = { plazas: t.plazas[String(d)], max: t.max[String(d)] ?? null };
      PL.trabajo[t.turno][d] = { ...v };
      PL.orig[t.turno][d] = { ...v };
    });
  });

  const rotuloDia = (x) => (x.dia === primero.dia ? "Llegada" : "Salida");
  const cabeceras = extremos.map((x) => `<th colspan="2" class="sep">${rotuloDia(x)}<small>${esc(nombreDia(x))}</small></th>`).join("");
  const subcab = extremos.map(() => `<th class="sep">Necesarias</th><th>Acepta hasta</th>`).join("");
  const m = abrirModal(`
    <h3>Plazas de llegada y salida</h3>
    <p class="pl-ayuda"><b>Necesarias:</b> plazas que hay que cubrir ese día (0 = el turno «no existe»).
    <b>Acepta hasta:</b> máximo de personas que puede tener. Si sobra gente, el optimizador la coloca en los turnos que aceptan más
    en vez de mandar a descansar a los monitores de fin de semana. Los días intermedios usan las plazas normales de cada turno
    (pantalla «Turnos y dependientes»).</p>
    <table class="pl-tabla">
      <thead><tr><th rowspan="2">Turno</th>${cabeceras}</tr><tr>${subcab}</tr></thead>
      <tbody id="pl-cuerpo"></tbody>
    </table>
    <div class="pl-resumenes">${PL.dias.map((d) => `<div class="pl-resumen" id="pl-resumen-${d}"></div>`).join("")}</div>
    <div class="modal-pie">
      <button type="button" class="secundario" id="pl-cancelar">Cancelar</button>
      <button type="button" id="pl-guardar">Guardar plazas</button>
    </div>`, "ancho");
  PL.modal = m;

  const cuerpo = m.querySelector("#pl-cuerpo");
  datos.turnos.forEach((t) => {
    const acento = estiloSeccion({ tipo: "turno", titulo: t.turno })[1];
    const celdas = PL.dias.map((d) => {
      const v = PL.trabajo[t.turno][d];
      return `<td class="sep"><input type="number" min="0" class="pl-plazas" data-dia="${d}" value="${v.plazas}"></td>
              <td><input type="number" min="0" class="pl-max" data-dia="${d}" value="${v.max ?? ""}" placeholder="${v.plazas}"></td>`;
    }).join("");
    const tr = elemento(`<tr style="--acento-fila:${acento}"><td class="pl-turno"><i class="punto"></i>${esc(rotulo(t.turno))} ${insigniaSexo(t.sexo_req)}</td>${celdas}</tr>`);
    PL.dias.forEach((d) => {
      const inpP = tr.querySelector(`.pl-plazas[data-dia="${d}"]`), inpM = tr.querySelector(`.pl-max[data-dia="${d}"]`);
      const sincronizar = () => {
        const p = Math.max(0, numONulo(inpP.value) ?? 0);
        const mx = numONulo(inpM.value);
        PL.trabajo[t.turno][d] = { plazas: p, max: mx !== null && mx > p ? mx : null };
        inpM.placeholder = String(p);
        resumenPlazas(d);
      };
      inpP.addEventListener("input", sincronizar);
      inpM.addEventListener("input", sincronizar);
      [inpP, inpM].forEach((i) => i.addEventListener("focus", () => i.select()));
    });
    cuerpo.appendChild(tr);
  });
  m.querySelector("#pl-cancelar").addEventListener("click", cerrarModal);
  m.querySelector("#pl-guardar").addEventListener("click", guardarPlazas);
  PL.dias.forEach(resumenPlazas);
  const primerInput = m.querySelector(".pl-plazas");
  if (primerInput) primerInput.focus();
}

function resumenPlazas(dia) {
  const d = String(dia);
  let necesarias = 0, sitio = 0;
  PL.datos.turnos.forEach((t) => {
    const v = PL.trabajo[t.turno][dia];
    necesarias += v.plazas;
    sitio += Math.max(v.plazas, v.max ?? 0);
  });
  const dep = PL.datos.dependientes[d], disp = PL.datos.disponibles[d], finde = PL.datos.finde[d];
  const cabe = sitio + dep;
  // Los sitios que ya ocupa gente fijada a mano (amarillo, dependientes escritos) no están libres para nadie más.
  const libres = cabe - PL.datos.fijados[d];
  const pendientes = finde - PL.datos.finde_fijados[d];
  let clase, texto;
  if (libres < pendientes) {
    clase = "mal";
    texto = `Faltan ${pendientes - libres} sitio(s) para los monitores de fin de semana (quedan ${libres} libres y hay ${pendientes} sin puesto). Alguno tendría que descansar: sube «Acepta hasta» en algún turno.`;
  } else if (cabe < disp) {
    clase = "aviso";
    texto = `Los de fin de semana caben (${libres} sitios libres para ${pendientes}). Al menos ${disp - cabe} monitor(es) más descansarán por falta de sitio (normal).`;
  } else {
    clase = "ok";
    texto = `Caben todos: sitio para ${cabe} personas y ${disp} monitores disponibles.`;
  }
  const info = PL.datos.dias.find((x) => x.dia === dia);
  const caja = PL.modal.querySelector(`#pl-resumen-${dia}`);
  caja.className = `pl-resumen ${clase}`;
  caja.innerHTML =
    `<b class="pl-dia">${dia === PL.datos.dias[0].dia ? "Llegada" : "Salida"} · día ${dia} (${esc(info.semana)})</b>
     <div class="pl-cifras"><span><b>${disp}</b> disponibles (<b>${finde}</b> de fin de semana)</span><span><b>${dep}</b> dependientes</span>
     <span><b>${necesarias}</b> necesarias</span><span><b>${sitio}</b> como máximo</span><span><b>${PL.datos.fijados[d]}</b> fijados a mano</span></div>
     <div>${esc(texto)}</div>`;
}

async function guardarPlazas() {
  const cambios = [];
  PL.datos.turnos.forEach((t) => PL.dias.forEach((dia) => {
    const a = PL.trabajo[t.turno][dia], b = PL.orig[t.turno][dia];
    if (a.plazas !== b.plazas || (a.max ?? null) !== (b.max ?? null)) cambios.push({ turno: t.turno, dia, plazas: a.plazas, max: a.max });
  }));
  if (!cambios.length) { cerrarModal(); return; }
  const pendientes = cambiosPendientes().length;
  if (pendientes) {
    if (!confirm(`Hay ${pendientes} cambio(s) de casillas sin guardar. Se guardarán antes (con copia de seguridad) porque la rejilla puede cambiar de forma.\n\n¿Continuar?`)) return;
    if (!(await guardarCambios({ silencioso: true }))) return;
  }
  try {
    const r = await api("POST", "/api/plazas", { cambios });
    cerrarModal();
    await recargarManteniendoVista();
    const añadidas = Object.entries(r.filas_añadidas || {}).map(([t, n]) => `${rotulo(t)} +${n}`).join(", ");
    toast(`Plazas guardadas.${añadidas ? " Filas nuevas en la rejilla: " + añadidas + "." : ""}`, "exito");
  } catch (e) {
    toast(e.message, "error");
  }
}

// ---------------------------------------------------------------------
// WhatsApp
// ---------------------------------------------------------------------
const WA = { dia: null, dependientes: true, descanso: false, soloNombre: false };

function textoWhatsApp(dia) {
  const info = REJ.diaInfo.get(dia);
  // Con "solo nombre de pila", si dos personas del día se llaman igual se añade la inicial del apellido.
  const cuenta = {};
  const vistos = new Set();
  REJ.celdas.forEach((c, key) => {
    if (!hayNombre(c) || REJ.info.get(key).dia !== dia || vistos.has(c.v)) return;
    vistos.add(c.v);
    const f = c.v.trim().split(/\s+/)[0];
    cuenta[f] = (cuenta[f] || 0) + 1;
  });
  const nombre = (n) => {
    if (!WA.soloNombre) return n;
    const [f, segundo] = String(n).trim().split(/\s+/);
    return cuenta[f] > 1 && segundo ? `${f} ${segundo.charAt(0)}.` : f;
  };
  const lineas = [`📅 *${nombreDia(info)}*`, ""];
  REJ.datos.secciones.forEach((sec) => {
    const celdas = sec.filas.map((f) => REJ.celdas.get(claveCelda(sec.tipo, f.fila, dia)));
    if (sec.tipo === "turno") {
      const nombres = celdas.filter(hayNombre).map((c) => nombre(c.v));
      if (!nombres.length) return;
      lineas.push(`${estiloSeccion(sec)[0]} *${rotulo(sec.titulo)}:* ${nombres.join(", ")}`);
    } else if (sec.tipo === "dependiente" && WA.dependientes) {
      const filas = sec.filas
        .map((f, i) => ({ acampado: f.etiqueta, c: celdas[i] }))
        .filter(({ c }) => c.v !== "-");
      if (!filas.length) return;
      lineas.push("", `🧒 *Dependientes*`);
      filas.forEach(({ acampado, c }) => lineas.push(`• ${acampado}: ${hayNombre(c) ? nombre(c.v) : "(sin asignar)"}`));
    } else if (sec.tipo === "descanso" && WA.descanso) {
      const nombres = celdas.filter(hayNombre).map((c) => nombre(c.v));
      if (nombres.length) lineas.push("", `😴 *Descanso:* ${nombres.join(", ")}`);
    }
  });
  return lineas.join("\n");
}

function abrirWhatsApp(dia) {
  if (!REJ.datos) return;
  const dias = REJ.datos.dias.map((x) => x.dia);
  WA.dia = dias.includes(dia) ? dia : (dias.includes(REJ.desde) ? REJ.desde : dias[0]);
  const m = abrirModal(`
    <h3>📲 Turnos para WhatsApp</h3>
    <p class="pl-ayuda">Texto con los turnos del día, tal como están ahora en la tabla${REJ.modo === "propuesta" ? " (propuesta del optimizador)" : ""}. Cópialo y pégalo en el grupo.</p>
    <div class="pl-cab">
      <button type="button" class="secundario mini-nav" id="wa-prev" title="Día anterior">‹</button>
      <select id="wa-dia">${REJ.datos.dias.map((x) => `<option value="${x.dia}">${esc(nombreDia(x))}</option>`).join("")}</select>
      <button type="button" class="secundario mini-nav" id="wa-sig" title="Día siguiente">›</button>
    </div>
    <div class="wa-opciones">
      <label><input type="checkbox" id="wa-dep" ${WA.dependientes ? "checked" : ""}> Incluir dependientes</label>
      <label><input type="checkbox" id="wa-desc" ${WA.descanso ? "checked" : ""}> Incluir descanso</label>
      <label><input type="checkbox" id="wa-nombre" ${WA.soloNombre ? "checked" : ""}> Solo nombre de pila</label>
    </div>
    <textarea id="wa-texto" class="wa-texto" rows="16" spellcheck="false"></textarea>
    <div class="modal-pie">
      <button type="button" class="secundario" id="wa-cerrar">Cerrar</button>
      <a class="enlace-boton" id="wa-abrir" target="_blank" rel="noopener" style="margin-left:8px;">Abrir WhatsApp</a>
      <button type="button" id="wa-copiar" style="margin-left:8px;">📋 Copiar texto</button>
    </div>`, "ancho");
  const q = (s) => m.querySelector(s);
  const pintar = () => {
    q("#wa-dia").value = String(WA.dia);
    const texto = textoWhatsApp(WA.dia);
    q("#wa-texto").value = texto;
    q("#wa-abrir").href = `https://wa.me/?text=${encodeURIComponent(texto)}`;
  };
  q("#wa-dia").addEventListener("change", () => { WA.dia = Number(q("#wa-dia").value); pintar(); });
  q("#wa-prev").addEventListener("click", () => { const i = dias.indexOf(WA.dia); if (i > 0) { WA.dia = dias[i - 1]; pintar(); } });
  q("#wa-sig").addEventListener("click", () => { const i = dias.indexOf(WA.dia); if (i < dias.length - 1) { WA.dia = dias[i + 1]; pintar(); } });
  q("#wa-dep").addEventListener("change", (e) => { WA.dependientes = e.target.checked; pintar(); });
  q("#wa-desc").addEventListener("change", (e) => { WA.descanso = e.target.checked; pintar(); });
  q("#wa-nombre").addEventListener("change", (e) => { WA.soloNombre = e.target.checked; pintar(); });
  q("#wa-cerrar").addEventListener("click", cerrarModal);
  q("#wa-texto").addEventListener("input", () => { q("#wa-abrir").href = `https://wa.me/?text=${encodeURIComponent(q("#wa-texto").value)}`; });
  q("#wa-copiar").addEventListener("click", async () => {
    const area = q("#wa-texto");
    try { await navigator.clipboard.writeText(area.value); }
    catch (e) { area.select(); document.execCommand("copy"); }
    toast("Texto copiado. Ya puedes pegarlo en WhatsApp.", "exito");
  });
  pintar();
}
