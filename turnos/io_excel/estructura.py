"""Cambios de *estructura* en el Excel: plazas por día y tamaño de la rejilla TURNOS.

Cada turno de trabajo ocupa un bloque de filas fijo en la hoja TURNOS
(`FILA_INI..FILA_FIN` de TIPOS_TURNO). Si un día un turno tiene que admitir más
gente que filas tiene su bloque (p. ej. «limpieza acepta hasta 12 personas el
día de llegada»), hay que hacerle sitio: se insertan filas, se desplaza lo que
queda debajo y se actualizan `FILA_INI/FILA_FIN` de los turnos siguientes y
`FILA` de los dependientes. Nunca se borran filas.
"""
from __future__ import annotations

import copy
from copy import copy as _copiar
from typing import Dict, Iterable, List, Optional

import openpyxl
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter

from ..modelo.datos import Datos
from .lector import _mapa_dias_por_columna, _texto

HOJA_MAX = "PLAZAS_MAX_POR_DIA"
NOTA_MAX = (
    "Máximo de personas que acepta cada turno cada día (celda vacía = solo las plazas necesarias). "
    "Sirve para días con pocos turnos (llegada/salida): si sobra gente, el optimizador la coloca aquí "
    "en vez de mandar a descansar a quien prefiere no hacerlo. Cada persona de más cuesta W_EXTRA."
)


class ErrorPlazas(Exception):
    def __init__(self, errores: List[str]):
        self.errores = errores
        super().__init__("; ".join(errores))


# ----------------------------------------------------------------------
# Insertar filas sin romper las celdas fusionadas
# ----------------------------------------------------------------------
def desplazar_filas(ws, fila_inicio: int, cantidad: int) -> None:
    """Empuja hacia abajo `cantidad` filas todo lo que hay desde `fila_inicio`.

    No se usa `ws.insert_rows`: en TURNOS cada bloque de turno está fusionado
    en una sola celda de la columna A (`A13:A16`, etc.) y `insert_rows` no
    reubica esas fusiones, lo que corrompe el contenido de las filas vecinas
    a una fusión (p. ej. hace desaparecer la etiqueta 'DESCANSO'). Aquí se
    copian los valores y el estilo celda a celda -de abajo arriba, para no
    pisar filas que aún no se han movido- y las fusiones se recrean ya
    desplazadas.
    """
    max_row = ws.max_row
    max_col = ws.max_column
    if fila_inicio > max_row:
        return

    fusiones = list(ws.merged_cells.ranges)
    for rango in fusiones:
        ws.unmerge_cells(str(rango))

    for fila in range(max_row, fila_inicio - 1, -1):
        for col in range(1, max_col + 1):
            origen = ws.cell(fila, col)
            destino = ws.cell(fila + cantidad, col)
            destino.value = origen.value
            destino._style = _copiar(origen._style)

    for fila in range(fila_inicio, fila_inicio + cantidad):
        for col in range(1, max_col + 1):
            ws.cell(fila, col).value = None

    for rango in fusiones:
        if rango.min_row >= fila_inicio:
            desde = f"{get_column_letter(rango.min_col)}{rango.min_row + cantidad}"
            hasta = f"{get_column_letter(rango.max_col)}{rango.max_row + cantidad}"
            ws.merge_cells(f"{desde}:{hasta}")
        else:
            ws.merge_cells(str(rango))


def _cabecera(ws) -> Dict[str, int]:
    return {str(c.value).strip().upper(): i + 1 for i, c in enumerate(ws[1]) if c.value is not None}


def asegurar_filas_turnos(wb, datos: Datos, necesarias: Dict[str, int]) -> Dict[str, int]:
    """Amplía en TURNOS los bloques con menos filas que las `necesarias`.

    Modifica el libro `wb` **y** el objeto `datos` (para que quien lo use después
    sepa dónde están ahora las filas). Devuelve {turno: filas añadidas}.
    """
    ws = wb["TURNOS"]
    añadidas: Dict[str, int] = {}
    con_filas = sorted((t for t in datos.turnos.values() if t.fila_ini is not None), key=lambda t: t.fila_ini)
    # De abajo arriba: ampliar un bloque no mueve los que aún quedan por procesar.
    for tt in reversed(con_filas):
        k = int(necesarias.get(tt.turno, 0)) - (tt.fila_fin - tt.fila_ini + 1)
        if k <= 0:
            continue
        fin_viejo = tt.fila_fin
        desplazar_filas(ws, fin_viejo + 1, k)
        for fila in range(fin_viejo + 1, fin_viejo + k + 1):
            for col in range(1, ws.max_column + 1):
                ws.cell(fila, col)._style = _copiar(ws.cell(fin_viejo, col)._style)
        for rango in list(ws.merged_cells.ranges):  # la etiqueta del turno (col. A) abarca todo el bloque
            if rango.min_col == 1 and rango.max_col == 1 and rango.min_row == tt.fila_ini and rango.max_row == fin_viejo:
                ws.unmerge_cells(str(rango))
                ws.merge_cells(start_row=tt.fila_ini, start_column=1, end_row=fin_viejo + k, end_column=1)

        tt.fila_fin += k
        for otro in datos.turnos.values():
            if otro is not tt and otro.fila_ini is not None and otro.fila_ini > fin_viejo:
                otro.fila_ini += k
                otro.fila_fin += k
        for dep in datos.dependientes.values():
            if dep.fila > fin_viejo:
                dep.fila += k
        añadidas[tt.turno] = k

    if añadidas:
        _sincronizar_filas(wb, datos)
    return añadidas


def _sincronizar_filas(wb, datos: Datos) -> None:
    """Vuelca a TIPOS_TURNO y DEPENDIENTES las filas que ahora tiene cada uno en TURNOS."""
    ws = wb["TIPOS_TURNO"]
    cab = _cabecera(ws)
    for fila in range(2, ws.max_row + 1):
        tt = datos.turnos.get(_texto(ws.cell(fila, cab["TURNO"]).value))
        if tt is not None and tt.fila_ini is not None:
            ws.cell(fila, cab["FILA_INI"]).value = tt.fila_ini
            ws.cell(fila, cab["FILA_FIN"]).value = tt.fila_fin
    ws = wb["DEPENDIENTES"]
    cab = _cabecera(ws)
    for fila in range(2, ws.max_row + 1):
        dep = datos.dependientes.get(_texto(ws.cell(fila, cab["ACAMPADO"]).value))
        if dep is not None:
            ws.cell(fila, cab["FILA"]).value = dep.fila


def filas_necesarias_por_solucion(solucion) -> Dict[str, int]:
    """Máximo de personas que la solución pone a la vez en cada turno."""
    cuenta: Dict[tuple, int] = {}
    for (_, turno, dia), v in solucion.x.items():
        if v == 1:
            cuenta[(turno, dia)] = cuenta.get((turno, dia), 0) + 1
    salida: Dict[str, int] = {}
    for (turno, _), n in cuenta.items():
        salida[turno] = max(salida.get(turno, 0), n)
    return salida


# ----------------------------------------------------------------------
# Plazas necesarias / máximas por día
# ----------------------------------------------------------------------
def _asegurar_fila_turno(ws, turno: str, relleno: Optional[Dict[int, int]], mapa) -> int:
    for fila in range(2, ws.max_row + 1):
        if _texto(ws.cell(fila, 1).value) == turno:
            return fila
    fila = ws.max_row + 1
    ws.cell(fila, 1).value = turno
    if relleno:
        for dia, valor in relleno.items():
            if dia in mapa:
                ws.cell(fila, mapa[dia]).value = valor
    return fila


def _hoja_max(wb):
    """PLAZAS_MAX_POR_DIA: la crea (copiando la cabecera de días de PLAZAS_POR_DIA) si no existe."""
    if HOJA_MAX in wb.sheetnames:
        return wb[HOJA_MAX]
    origen = wb["PLAZAS_POR_DIA"]
    ws = wb.create_sheet(HOJA_MAX, index=wb.sheetnames.index("PLAZAS_POR_DIA") + 1)
    for col in range(1, origen.max_column + 1):
        celda = ws.cell(1, col)
        celda.value = origen.cell(1, col).value
        celda._style = _copiar(origen.cell(1, col)._style)
        ancho = origen.column_dimensions[get_column_letter(col)].width
        if ancho:
            ws.column_dimensions[get_column_letter(col)].width = ancho
    ws["A1"].comment = Comment(NOTA_MAX, "turnos")
    return ws


def _asegurar_peso_extra(wb) -> None:
    ws = wb["CONFIG"]
    for fila in range(2, ws.max_row + 1):
        if _texto(ws.cell(fila, 1).value).upper() == "W_EXTRA":
            return
    fila = ws.max_row + 1
    ws.cell(fila, 1).value = "W_EXTRA"
    ws.cell(fila, 2).value = 40
    ws.cell(fila, 3).value = "Peso: cada persona que un turno acepta por encima de sus plazas (PLAZAS_MAX_POR_DIA)"


def guardar_plazas(ruta: str, datos: Datos, cambios: Iterable[dict], hacer_copia) -> dict:
    """Escribe plazas necesarias y máximas por (turno, día) y hace sitio en TURNOS.

    cambios: [{"turno", "dia", "plazas": int>=0, "max": int|None}]
    `max` vacío (o <= plazas) significa "el turno no acepta más que sus plazas ese día".
    Valida todo antes de tocar el fichero. `hacer_copia(ruta)` hace la copia de seguridad.
    """
    errores: List[str] = []
    limpios: List[dict] = []
    for c in cambios:
        turno, dia = c.get("turno"), c.get("dia")
        try:
            dia = int(dia)
            plazas = int(c.get("plazas"))
            tope = c.get("max")
            tope = None if tope in (None, "") else int(tope)
        except (TypeError, ValueError):
            errores.append(f"Valor no numérico en {turno}, día {c.get('dia')}")
            continue
        if turno not in datos.turnos:
            errores.append(f"El turno '{turno}' no existe")
        elif dia not in datos.dias:
            errores.append(f"Día {dia} fuera del horizonte")
        elif plazas < 0 or (tope is not None and tope < 0):
            errores.append(f"{turno}, día {dia}: las plazas no pueden ser negativas")
        else:
            limpios.append({"turno": turno, "dia": dia, "plazas": plazas,
                            "max": tope if tope is not None and tope > plazas else None})
    if errores:
        raise ErrorPlazas(errores)
    if not limpios:
        return {"cambios": 0, "filas_añadidas": {}, "backup": None}

    datos = copy.deepcopy(datos)  # `asegurar_filas_turnos` lo modifica
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws_p = wb["PLAZAS_POR_DIA"]
    mapa_p = _mapa_dias_por_columna(ws_p, 1, 2, ws_p.max_column)
    ws_m = _hoja_max(wb)
    mapa_m = _mapa_dias_por_columna(ws_m, 1, 2, ws_m.max_column)

    for c in limpios:
        t, dia = c["turno"], c["dia"]
        defecto = {d: datos.plazas.get((t, d), 0) for d in datos.dias}
        fila_p = _asegurar_fila_turno(ws_p, t, defecto, mapa_p)
        fila_m = _asegurar_fila_turno(ws_m, t, None, mapa_m)
        if dia not in mapa_p or dia not in mapa_m:
            raise ErrorPlazas([f"No hay columna para el día {dia} en PLAZAS_POR_DIA / {HOJA_MAX}"])
        ws_p.cell(fila_p, mapa_p[dia]).value = c["plazas"]
        ws_m.cell(fila_m, mapa_m[dia]).value = c["max"]

    # Filas que necesita cada turno: lo máximo que acepte cualquier día (ya con los cambios).
    necesarias: Dict[str, int] = {}
    hay_extras = False
    for fila in range(2, ws_p.max_row + 1):
        turno = _texto(ws_p.cell(fila, 1).value)
        if turno not in datos.turnos:
            continue
        for dia in datos.dias:
            p = ws_p.cell(fila, mapa_p[dia]).value
            necesarias[turno] = max(necesarias.get(turno, 0), int(p) if isinstance(p, (int, float)) else 0)
    for fila in range(2, ws_m.max_row + 1):
        turno = _texto(ws_m.cell(fila, 1).value)
        if turno not in datos.turnos:
            continue
        for dia in datos.dias:
            m = ws_m.cell(fila, mapa_m[dia]).value if dia in mapa_m else None
            if isinstance(m, (int, float)):
                hay_extras = True
                necesarias[turno] = max(necesarias.get(turno, 0), int(m))
    añadidas = asegurar_filas_turnos(wb, datos, necesarias)
    if hay_extras:
        _asegurar_peso_extra(wb)

    backup = hacer_copia(ruta)
    wb.save(ruta)
    return {"cambios": len(limpios), "filas_añadidas": añadidas, "backup": backup}
