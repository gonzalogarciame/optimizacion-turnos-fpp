"""La rejilla de turnos leída y editada celda a celda desde la base de datos.

Devuelve y acepta lo mismo que `io_excel.rejilla` (así la pantalla no cambia):
una celda se identifica por (tipo, fila, día). Aquí `fila` es un número estable
que se calcula a partir del lugar de la casilla, sin que dependa de cuántas
filas tengan los demás bloques:

    turno        1000 * (orden del turno + 1) + posición
    dependiente  100000 + orden del dependiente
    descanso     200000 + posición
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from ..io_excel.rejilla import NO_PRESENTE_TXT, ErrorEdicionRejilla, info_dias  # noqa: F401  (se reexportan)
from ..modelo.datos import Datos
from ..nombres import ErrorNombreNoReconocido, ResolverNombres
from .copias import hacer_copia_seguridad
from .esquema import abrir

PASO = 1000
BASE_DEPENDIENTES = 100_000
BASE_DESCANSO = 200_000
FILAS_LIBRES_DESCANSO = 3


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def leer_rejilla_db(ruta: str, datos: Datos) -> dict:
    """La rejilla completa lista para serializar a JSON (misma forma que `io_excel.rejilla.leer_rejilla`)."""
    con = abrir(ruta)
    try:
        ordenes = {r["turno"]: r["orden"] for r in con.execute("SELECT turno, orden FROM tipos_turno")}
        asign = con.execute("SELECT tipo, clave, dia, pos, monitor, fijada FROM asignaciones").fetchall()
        ausentes = {(r["acampado"], r["dia"]) for r in con.execute("SELECT acampado, dia FROM dependiente_ausente")}
        pares_alias = [(r["variante"], r["canonico"]) for r in con.execute("SELECT variante, canonico FROM alias")]
    finally:
        con.close()

    alias: Dict[str, List[str]] = defaultdict(list)
    for variante, canonico in pares_alias:
        if canonico in datos.monitores:
            alias[canonico].append(variante)

    por_turno: Dict[str, dict] = defaultdict(dict)    # turno -> {(dia, pos): (monitor, fijada)}
    por_dep: Dict[str, dict] = defaultdict(dict)      # acampado -> {dia: (monitor, fijada)}
    descanso: Dict[int, List[tuple]] = defaultdict(list)  # dia -> [(pos, monitor)]
    for r in asign:
        if r["tipo"] == "turno":
            por_turno[r["clave"]][(r["dia"], r["pos"])] = (r["monitor"], bool(r["fijada"]))
        elif r["tipo"] == "dependiente":
            por_dep[r["clave"]][r["dia"]] = (r["monitor"], bool(r["fijada"]))
        else:
            descanso[r["dia"]].append((r["pos"], r["monitor"]))

    secciones: List[dict] = []

    for tt in datos.turnos.values():
        ocupadas = por_turno.get(tt.turno, {})
        n_filas = max(
            [1] + [datos.tope(tt.turno, d) for d in datos.dias] + [pos + 1 for (_, pos) in ocupadas]
        )
        filas = []
        for pos in range(n_filas):
            celdas = {}
            for d in datos.dias:
                monitor, fijada = ocupadas.get((d, pos), ("", False))
                celdas[str(d)] = {"v": monitor, "f": fijada}
            filas.append({
                "fila": PASO * (ordenes.get(tt.turno, 0) + 1) + pos,
                "etiqueta": f"{tt.turno} {pos + 1}",
                "sexo_req": tt.sexo_req,
                "celdas": celdas,
            })
        secciones.append({
            "clave": f"turno:{tt.turno}",
            "tipo": "turno",
            "titulo": tt.turno,
            "sexo_req": tt.sexo_req,
            "plazas": {str(d): int(datos.plazas.get((tt.turno, d), 0)) for d in datos.dias},
            "max": {str(d): datos.plazas_max.get((tt.turno, d)) for d in datos.dias},
            "tope": {str(d): int(datos.tope(tt.turno, d)) for d in datos.dias},
            "filas": filas,
        })

    filas_dep = []
    for dep in sorted(datos.dependientes.values(), key=lambda p: p.fila):
        celdas = {}
        for d in datos.dias:
            if (dep.acampado, d) in ausentes:
                celdas[str(d)] = {"v": NO_PRESENTE_TXT, "f": False}
            elif d in por_dep.get(dep.acampado, {}):
                monitor, fijada = por_dep[dep.acampado][d]
                celdas[str(d)] = {"v": monitor, "f": fijada}
            else:
                celdas[str(d)] = {"v": "", "f": False}
        filas_dep.append({
            "fila": BASE_DEPENDIENTES + dep.fila,
            "etiqueta": dep.acampado,
            "sexo_req": dep.sexo_monitor_req,
            "celdas": celdas,
        })
    secciones.append({
        "clave": "dependientes", "tipo": "dependiente", "titulo": "Dependientes",
        "sexo_req": "-", "plazas": {}, "filas": filas_dep,
    })

    n_desc = max([0] + [len(v) for v in descanso.values()]) + FILAS_LIBRES_DESCANSO
    n_desc = max(n_desc, max([0] + [pos + 1 for v in descanso.values() for pos, _ in v]))
    filas_desc = []
    for pos in range(n_desc):
        celdas = {}
        for d in datos.dias:
            nombre = next((m for p, m in descanso.get(d, []) if p == pos), "")
            celdas[str(d)] = {"v": nombre, "f": False}
        filas_desc.append({"fila": BASE_DESCANSO + pos, "etiqueta": f"descanso {pos + 1}", "sexo_req": "-", "celdas": celdas})
    secciones.append({
        "clave": "descanso", "tipo": "descanso", "titulo": "Descanso",
        "sexo_req": "-", "plazas": {}, "filas": filas_desc,
    })
    return {"secciones": secciones, "alias": dict(alias)}


# ----------------------------------------------------------------------
# Quién descansa y quién trabaja (para la pantalla de disponibilidad)
# ----------------------------------------------------------------------
def descansos_asignados_db(ruta: str) -> Dict[str, List[int]]:
    con = abrir(ruta)
    try:
        res: Dict[str, set] = defaultdict(set)
        for r in con.execute("SELECT monitor, dia FROM asignaciones WHERE tipo = 'descanso'"):
            res[r["monitor"]].add(r["dia"])
    finally:
        con.close()
    return {m: sorted(ds) for m, ds in res.items()}


def asignaciones_trabajo_db(ruta: str) -> Dict[str, Dict[str, str]]:
    """{monitor: {día: "turno" | "dependiente X"}} de los turnos y dependientes escritos."""
    con = abrir(ruta)
    try:
        res: Dict[str, Dict[str, str]] = defaultdict(dict)
        for r in con.execute("SELECT tipo, clave, dia, monitor FROM asignaciones WHERE tipo IN ('turno', 'dependiente')"):
            res[r["monitor"]][str(r["dia"])] = r["clave"] if r["tipo"] == "turno" else f"dependiente {r['clave']}"
    finally:
        con.close()
    return dict(res)


# ----------------------------------------------------------------------
# Edición
# ----------------------------------------------------------------------
def _destino_de_fila(fila: int, turno_por_orden: Dict[int, str], dep_por_orden: Dict[int, str]):
    """(tipo, clave, pos) al que apunta el número de fila, o None si no existe."""
    if fila >= BASE_DESCANSO:
        return "descanso", "", fila - BASE_DESCANSO
    if fila >= BASE_DEPENDIENTES:
        acampado = dep_por_orden.get(fila - BASE_DEPENDIENTES)
        return ("dependiente", acampado, 0) if acampado else None
    turno = turno_por_orden.get(fila // PASO - 1)
    return ("turno", turno, fila % PASO) if turno else None


def guardar_cambios_rejilla_db(ruta: str, datos: Datos, cambios: List[dict]) -> dict:
    """Escribe solo las casillas cambiadas. Valida todo antes de tocar nada y hace antes una copia.

    cambios: [{"tipo", "fila", "dia", "valor", "fijado"}]. Devuelve {"escritas": n, "backup": ruta}.
    """
    con = abrir(ruta)
    try:
        turno_por_orden = {r["orden"]: r["turno"] for r in con.execute("SELECT orden, turno FROM tipos_turno")}
        dep_por_orden = {r["orden"]: r["acampado"] for r in con.execute("SELECT orden, acampado FROM dependientes")}
        pares_alias = [(r["variante"], r["canonico"]) for r in con.execute("SELECT variante, canonico FROM alias")]
    finally:
        con.close()
    resolver = ResolverNombres.construir(datos.monitores.keys(), pares_alias)

    errores: List[str] = []
    limpios: List[dict] = []
    for c in cambios:
        tipo = c.get("tipo")
        try:
            fila, dia = int(c.get("fila")), int(c.get("dia"))
        except (TypeError, ValueError):
            errores.append(f"Cambio mal formado: {c}")
            continue
        destino = _destino_de_fila(fila, turno_por_orden, dep_por_orden) if tipo in ("turno", "dependiente", "descanso") else None
        if destino is None or destino[0] != tipo:
            errores.append(f"Fila {fila} no es una fila de '{tipo}'")
            continue
        if dia not in datos.dias:
            errores.append(f"Día {dia} fuera del horizonte {datos.dias[0]}–{datos.dias[-1]}")
            continue
        valor = _texto(c.get("valor"))
        if valor == NO_PRESENTE_TXT:
            if tipo != "dependiente":
                errores.append(f"Día {dia}, fila {fila}: '-' solo vale para dependientes")
                continue
        elif valor:
            try:
                valor = resolver.resolver(valor)
            except ErrorNombreNoReconocido:
                errores.append(f"Día {dia}: '{valor}' no es un monitor conocido")
                continue
            if valor not in datos.monitores:
                errores.append(f"Día {dia}: '{valor}' no está en MONITORES")
                continue
        limpios.append({
            "tipo": tipo, "clave": destino[1], "pos": destino[2], "dia": dia, "valor": valor,
            "fijado": bool(c.get("fijado")) and valor not in ("", NO_PRESENTE_TXT),
        })
    if errores:
        raise ErrorEdicionRejilla(errores)
    if not limpios:
        return {"escritas": 0, "backup": None}

    backup = hacer_copia_seguridad(ruta)
    con = abrir(ruta)
    try:
        with con:
            for c in limpios:
                tipo, clave, pos, dia, valor = c["tipo"], c["clave"], c["pos"], c["dia"], c["valor"]
                con.execute("DELETE FROM asignaciones WHERE tipo = ? AND clave = ? AND dia = ? AND pos = ?", (tipo, clave, dia, pos))
                if tipo == "dependiente":
                    con.execute("DELETE FROM dependiente_ausente WHERE acampado = ? AND dia = ?", (clave, dia))
                    if valor == NO_PRESENTE_TXT:
                        con.execute("INSERT INTO dependiente_ausente (acampado, dia) VALUES (?, ?)", (clave, dia))
                        continue
                    fijado = 1  # lo que se escribe a mano para un dependiente queda fijado
                else:
                    fijado = int(c["fijado"] and tipo == "turno")
                if valor:
                    con.execute(
                        "INSERT INTO asignaciones (tipo, clave, dia, pos, monitor, fijada) VALUES (?, ?, ?, ?, ?, ?)",
                        (tipo, clave, dia, pos, valor, fijado),
                    )
    finally:
        con.close()
    return {"escritas": len(limpios), "backup": backup}
