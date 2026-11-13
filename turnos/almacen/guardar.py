"""`Solucion` -> base de datos (equivale a `io_excel.escritor.escribir_solucion`)."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from ..modelo.datos import NO_PRESENTE, POR_DECIDIR, Datos, Solucion
from .esquema import abrir


def _ordenados(nombres) -> List[str]:
    return sorted(nombres, key=lambda n: n.lower())


def escribir_solucion_db(ruta: str, datos: Datos, solucion: Solucion) -> int:
    """Escribe la solución en la rejilla para los días a generar (>= DIA_REOPTIMIZACION).

    Los días anteriores no se tocan. Todo ocurre en una sola transacción: si algo
    falla, la base de datos queda como estaba. Devuelve cuántas casillas escribe.
    """
    if solucion.estado not in ("optimo",) and not solucion.estado.startswith("factible"):
        raise ValueError(f"No se escribe una solución en estado '{solucion.estado}'")

    dia_reopt = datos.cfg.dia_reoptimizacion
    dias = [d for d in datos.dias if d >= dia_reopt]
    if not dias:
        return 0
    fijado_obliga = {(f.monitor, f.turno, f.dia) for f in datos.fijaciones if f.tipo == "OBLIGA"}

    por_turno: Dict[Tuple[str, int], List[str]] = defaultdict(list)
    for (mo, t, d), v in solucion.x.items():
        if v == 1:
            por_turno[(t, d)].append(mo)
    decidido = {(p, d): mo for (mo, p, d), v in solucion.y.items() if v == 1}
    descansan: Dict[int, List[str]] = defaultdict(list)
    for (mo, d), v in solucion.r.items():
        if v == 1:
            descansan[d].append(mo)

    filas: List[Tuple[str, str, int, int, str, int]] = []
    for turno in datos.turnos:
        for dia in dias:
            for pos, nombre in enumerate(_ordenados(por_turno.get((turno, dia), []))):
                filas.append(("turno", turno, dia, pos, nombre, int((nombre, turno, dia) in fijado_obliga)))
    for acampado in datos.dependientes:
        for dia in dias:
            valor = datos.asig_dependiente.get((acampado, dia), NO_PRESENTE)
            if valor is NO_PRESENTE:
                continue
            if valor == POR_DECIDIR:
                if (acampado, dia) in decidido:
                    filas.append(("dependiente", acampado, dia, 0, decidido[(acampado, dia)], 0))
            else:
                filas.append(("dependiente", acampado, dia, 0, valor, 1))
    for dia in dias:
        for pos, nombre in enumerate(_ordenados(descansan.get(dia, []))):
            filas.append(("descanso", "", dia, pos, nombre, 0))

    con = abrir(ruta)
    try:
        with con:
            con.executemany("DELETE FROM asignaciones WHERE dia = ?", [(d,) for d in dias])
            con.executemany(
                "INSERT INTO asignaciones (tipo, clave, dia, pos, monitor, fijada) VALUES (?, ?, ?, ?, ?, ?)", filas
            )
    finally:
        con.close()
    return len(filas)


def guardar_config_valores(ruta: str, valores: Dict[str, object]) -> None:
    """Cambia valores de CONFIG (p. ej. DIA_REOPTIMIZACION)."""
    con = abrir(ruta)
    try:
        with con:
            for clave, valor in valores.items():
                con.execute(
                    "INSERT INTO config (clave, valor) VALUES (?, ?) "
                    "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                    (clave, str(valor)),
                )
    finally:
        con.close()
