"""Solución -> Excel, preservando el formato visual de la rejilla TURNOS.

Solo se escriben las celdas de días `>= DIA_REOPTIMIZACION`. Las columnas
anteriores no se tocan (ni el contenido ni, salvo el propio color gris, el
formato). Antes de sobrescribir el fichero de entrada se guarda siempre una
copia de seguridad con marca de tiempo; con `dry_run=True` (o pasando una
`ruta_salida` distinta) se escribe a un fichero nuevo y el original queda
intacto.
"""
from __future__ import annotations

import copy
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import openpyxl
from openpyxl.styles import PatternFill

from ..modelo.datos import NO_PRESENTE, POR_DECIDIR, Datos, Solucion
from .estructura import asegurar_filas_turnos, filas_necesarias_por_solucion

AMARILLO = PatternFill(start_color="FFFFE599", end_color="FFFFE599", fill_type="solid")
GRIS_CLARO = PatternFill(start_color="FFD9D9D9", end_color="FFD9D9D9", fill_type="solid")
SIN_RELLENO = PatternFill(fill_type=None)
ROJO_SUAVE = PatternFill(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid")


def _mapa_dias_por_columna(ws, fila_cabecera: int, col_ini: int, col_fin: int) -> Dict[int, int]:
    mapa = {}
    for col in range(col_ini, col_fin + 1):
        valor = ws.cell(fila_cabecera, col).value
        if valor is None:
            continue
        if isinstance(valor, (int, float)):
            mapa[int(valor)] = col
            continue
        m = re.search(r"(\d+)", str(valor))
        if m:
            mapa[int(m.group(1))] = col
    return mapa


def hacer_copia_seguridad(ruta: str) -> str:
    ruta_p = Path(ruta)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = ruta_p.with_name(f"{ruta_p.stem}_backup_{marca}{ruta_p.suffix}")
    shutil.copy2(ruta_p, destino)
    return str(destino)


def escribir_solucion(
    ruta_entrada: str,
    datos: Datos,
    solucion: Solucion,
    ruta_salida: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    if solucion.estado not in ("optimo",) and not solucion.estado.startswith("factible"):
        raise ValueError(f"No se escribe una solución en estado '{solucion.estado}'")

    ruta_salida = ruta_salida or ruta_entrada
    misma_ruta = Path(ruta_salida).resolve() == Path(ruta_entrada).resolve()

    if misma_ruta and not dry_run:
        hacer_copia_seguridad(ruta_entrada)

    wb = openpyxl.load_workbook(ruta_entrada, data_only=False)
    ws = wb["TURNOS"]

    # Si algún turno recibe más gente que filas tiene su bloque (turnos que aceptan
    # extras, ver PLAZAS_MAX_POR_DIA) se amplía la rejilla. Eso cambia las filas de
    # `datos`, así que se trabaja sobre una copia: quien llama puede reutilizar el suyo.
    datos = copy.deepcopy(datos)
    asegurar_filas_turnos(wb, datos, filas_necesarias_por_solucion(solucion))

    dia_reopt = datos.cfg.dia_reoptimizacion
    mapa_dias = _mapa_dias_por_columna(ws, 1, 2, ws.max_column)

    fijado_obliga = {(f.monitor, f.turno, f.dia) for f in datos.fijaciones if f.tipo == "OBLIGA"}

    _escribir_bloques_trabajo(ws, datos, solucion, mapa_dias, dia_reopt, fijado_obliga)
    _escribir_dependientes(ws, datos, solucion, mapa_dias, dia_reopt)
    _regenerar_descanso(ws, datos, solucion, mapa_dias, dia_reopt)

    if dry_run and misma_ruta:
        ruta_salida = str(Path(ruta_entrada).with_name(
            Path(ruta_entrada).stem + "_DRYRUN" + Path(ruta_entrada).suffix
        ))

    wb.save(ruta_salida)
    return ruta_salida


def _nombres_ordenados(nombres):
    return sorted(nombres, key=lambda n: n.lower())


def _escribir_bloques_trabajo(ws, datos: Datos, solucion: Solucion, mapa_dias, dia_reopt, fijado_obliga):
    for turno, tt in datos.turnos.items():
        if tt.fila_ini is None:
            continue
        for dia in datos.dias:
            col = mapa_dias[dia]
            if dia < dia_reopt:
                for fila in range(tt.fila_ini, tt.fila_fin + 1):
                    ws.cell(fila, col).fill = GRIS_CLARO
                continue

            asignados = _nombres_ordenados(
                mo for (mo, t, d), v in solucion.x.items() if t == turno and d == dia and v == 1
            )
            filas = list(range(tt.fila_ini, tt.fila_fin + 1))
            for i, fila in enumerate(filas):
                celda = ws.cell(fila, col)
                if i < len(asignados):
                    nombre = asignados[i]
                    celda.value = nombre
                    celda.fill = AMARILLO if (nombre, turno, dia) in fijado_obliga else SIN_RELLENO
                else:
                    celda.value = None
                    celda.fill = SIN_RELLENO
            if len(asignados) > len(filas):
                # Más asignados que plazas físicas en la rejilla: no debería
                # pasar (cobertura tiene igualdad con plazas), pero si el
                # usuario cambió PLAZAS_POR_DIA sin ampliar FILA_FIN, se
                # anota en la última celda para que no se pierda el dato.
                extra = ", ".join(asignados[len(filas):])
                ws.cell(filas[-1], col).value = (ws.cell(filas[-1], col).value or "") + f" (+{extra})"


def _escribir_dependientes(ws, datos: Datos, solucion: Solucion, mapa_dias, dia_reopt):
    # Monitor que el modelo asigna a cada (acampado, día) cuando la celda de
    # ASIG_DEPENDIENTE estaba vacía ("que lo decida el modelo").
    decidido = {(p, d): mo for (mo, p, d), v in solucion.y.items() if v == 1}
    for p, dep in datos.dependientes.items():
        fila = dep.fila
        for dia in datos.dias:
            col = mapa_dias[dia]
            if dia < dia_reopt:
                ws.cell(fila, col).fill = GRIS_CLARO
                continue
            valor = datos.asig_dependiente.get((p, dia), NO_PRESENTE)
            celda = ws.cell(fila, col)
            if valor is NO_PRESENTE:
                celda.value = "-"
                celda.fill = SIN_RELLENO
            elif valor == POR_DECIDIR:
                celda.value = decidido.get((p, dia))
                celda.fill = SIN_RELLENO
            else:
                celda.value = valor
                celda.fill = AMARILLO


def _regenerar_descanso(ws, datos: Datos, solucion: Solucion, mapa_dias, dia_reopt):
    fila_label = None
    for fila in range(2, ws.max_row + 1):
        if str(ws.cell(fila, 1).value or "").strip().upper() == "DESCANSO":
            fila_label = fila
            break
    if fila_label is None:
        raise ValueError("TURNOS: no se encuentra la etiqueta 'DESCANSO'")

    fila_ini = fila_label + 1
    fila_fin = ws.max_row

    for dia in datos.dias:
        if dia < dia_reopt:
            continue
        col = mapa_dias[dia]
        descansan = _nombres_ordenados(mo for (mo, d), v in solucion.r.items() if d == dia and v == 1)
        for i, fila in enumerate(range(fila_ini, fila_fin + 1)):
            celda = ws.cell(fila, col)
            celda.value = descansan[i] if i < len(descansan) else None
            celda.fill = SIN_RELLENO
