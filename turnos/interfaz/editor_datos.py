"""Escritura de las hojas "maestras" (MONITORES, DISPONIBILIDAD, FIJACIONES)
desde la interfaz Streamlit.

Esto es distinto de `io_excel.escritor`, que solo escribe la SOLUCIÓN
(`Solucion -> TURNOS`). Aquí se editan los datos de entrada: altas/bajas de
monitores, la matriz D/X/R y las fijaciones manuales. Vive en `interfaz/`
porque solo la usa la interfaz interactiva (la CLI no edita datos, solo
optimiza); mantiene `io_excel.escritor` fiel a su única responsabilidad
("regla de oro" del README: el modelo y la solución no saben de Excel más
que a través de esos dos módulos).
"""
from __future__ import annotations

from typing import Iterable

import openpyxl
import pandas as pd

from ..nombres import normalizar


def _mapa_cabecera(ws):
    return {str(c.value).strip().upper(): idx + 1 for idx, c in enumerate(ws[1]) if c.value is not None}


def leer_monitores_df(ruta: str) -> pd.DataFrame:
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = wb["MONITORES"]
    cab = _mapa_cabecera(ws)
    filas = []
    for fila in range(2, ws.max_row + 1):
        nombre = ws.cell(fila, cab["NOMBRE"]).value
        if not nombre:
            continue
        filas.append({
            "NOMBRE": nombre,
            "SEXO": ws.cell(fila, cab["SEXO"]).value,
            "GRUPO": ws.cell(fila, cab.get("GRUPO", cab["SEXO"])).value if "GRUPO" in cab else "",
            "PERMITE_DESCANSO": int(ws.cell(fila, cab["PERMITE_DESCANSO"]).value or 0),
            "PENALIZAR_DESCANSO": int(ws.cell(fila, cab["PENALIZAR_DESCANSO"]).value or 0),
            "DEPENDIENTE_1": ws.cell(fila, cab.get("DEPENDIENTE_1", 0)).value if "DEPENDIENTE_1" in cab else None,
            "DEPENDIENTE_2": ws.cell(fila, cab.get("DEPENDIENTE_2", 0)).value if "DEPENDIENTE_2" in cab else None,
        })
    return pd.DataFrame(filas)


def guardar_monitores_df(ruta: str, df: pd.DataFrame, dias: Iterable[int]) -> list:
    """Reescribe MONITORES con el contenido de `df` (una fila por monitor).

    Los monitores nuevos (que no existían en la hoja) reciben también una
    fila nueva en DISPONIBILIDAD con 'D' todos los días, tal como pide la
    hoja LEYENDA ("Añade la fila en MONITORES y la fila correspondiente en
    DISPONIBILIDAD"). Los monitores eliminados de la tabla NO se borran de
    DISPONIBILIDAD (para no perder histórico sin querer): se devuelve un
    aviso para que el usuario lo revise a mano si hace falta.
    """
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["MONITORES"]
    cab = _mapa_cabecera(ws)

    existentes = set()
    for fila in range(2, ws.max_row + 1):
        nombre = ws.cell(fila, cab["NOMBRE"]).value
        if nombre:
            existentes.add(str(nombre).strip())

    nuevos_en_df = {str(n).strip() for n in df["NOMBRE"] if str(n).strip()}
    eliminados = existentes - nuevos_en_df
    nuevos = nuevos_en_df - existentes

    # Limpia el bloque actual de datos (sin tocar la cabecera).
    ultima_fila_actual = max(ws.max_row, 1)
    for fila in range(2, ultima_fila_actual + 1):
        for col in range(1, ws.max_column + 1):
            if col not in (cab.get("DIAS_PRESENTE", -1), cab.get("DISPONIBILIDAD_TXT", -1)):
                ws.cell(fila, col).value = None

    for i, fila_datos in enumerate(df.itertuples(index=False)):
        fila = i + 2
        d = fila_datos._asdict()
        ws.cell(fila, cab["NOMBRE"]).value = d.get("NOMBRE")
        ws.cell(fila, cab["SEXO"]).value = d.get("SEXO")
        if "GRUPO" in cab:
            ws.cell(fila, cab["GRUPO"]).value = d.get("GRUPO")
        ws.cell(fila, cab["PERMITE_DESCANSO"]).value = int(d.get("PERMITE_DESCANSO") or 0)
        ws.cell(fila, cab["PENALIZAR_DESCANSO"]).value = int(d.get("PENALIZAR_DESCANSO") or 0)
        if "DEPENDIENTE_1" in cab:
            ws.cell(fila, cab["DEPENDIENTE_1"]).value = d.get("DEPENDIENTE_1") or None
        if "DEPENDIENTE_2" in cab:
            ws.cell(fila, cab["DEPENDIENTE_2"]).value = d.get("DEPENDIENTE_2") or None

    ws_disp = wb["DISPONIBILIDAD"]
    cab_disp = _mapa_cabecera(ws_disp)
    mapa_dias_disp = {}
    for col in range(2, ws_disp.max_column + 1):
        v = ws_disp.cell(1, col).value
        if isinstance(v, (int, float)):
            mapa_dias_disp[int(v)] = col

    if nuevos:
        fila_libre = ws_disp.max_row + 1
        for nombre in sorted(nuevos):
            ws_disp.cell(fila_libre, 1).value = nombre
            for dia, col in mapa_dias_disp.items():
                ws_disp.cell(fila_libre, col).value = "D"
            fila_libre += 1

    wb.save(ruta)

    avisos = []
    if eliminados:
        avisos.append(
            "Se han quitado de MONITORES: " + ", ".join(sorted(eliminados)) +
            ". Sus filas en DISPONIBILIDAD y su histórico en TURNOS NO se han borrado "
            "automáticamente (revísalo a mano si hace falta)."
        )
    if nuevos:
        avisos.append(
            "Monitores nuevos añadidos también a DISPONIBILIDAD con 'D' todos los días: "
            + ", ".join(sorted(nuevos))
        )
    return avisos


def leer_disponibilidad_df(ruta: str, dias: Iterable[int]) -> pd.DataFrame:
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = wb["DISPONIBILIDAD"]
    mapa_dias = {}
    for col in range(2, ws.max_column + 1):
        v = ws.cell(1, col).value
        if isinstance(v, (int, float)):
            mapa_dias[int(v)] = col

    filas = []
    for fila in range(2, ws.max_row + 1):
        nombre = ws.cell(fila, 1).value
        if not nombre:
            continue
        registro = {"NOMBRE": nombre}
        for dia in dias:
            col = mapa_dias.get(dia)
            registro[str(dia)] = ws.cell(fila, col).value if col else "D"
        filas.append(registro)
    return pd.DataFrame(filas)


def guardar_disponibilidad_df(ruta: str, df: pd.DataFrame, dias: Iterable[int]) -> None:
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["DISPONIBILIDAD"]
    mapa_dias = {}
    for col in range(2, ws.max_column + 1):
        v = ws.cell(1, col).value
        if isinstance(v, (int, float)):
            mapa_dias[int(v)] = col

    filas_por_nombre = {}
    for fila in range(2, ws.max_row + 1):
        nombre = ws.cell(fila, 1).value
        if nombre:
            filas_por_nombre[normalizar(nombre)] = fila

    for fila_datos in df.itertuples(index=False):
        d = fila_datos._asdict()
        nombre = d["NOMBRE"]
        fila = filas_por_nombre.get(normalizar(nombre))
        if fila is None:
            continue
        for dia in dias:
            col = mapa_dias.get(dia)
            if col is None:
                continue
            valor = str(d.get(str(dia), "D")).strip().upper()
            ws.cell(fila, col).value = valor

    wb.save(ruta)


def agregar_fijacion(ruta: str, dia: int, turno: str, nombre: str, tipo: str = "OBLIGA") -> None:
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["FIJACIONES"]
    cab = _mapa_cabecera(ws)
    fila_libre = 2
    while ws.cell(fila_libre, cab["DIA"]).value not in (None, ""):
        fila_libre += 1
    ws.cell(fila_libre, cab["DIA"]).value = dia
    ws.cell(fila_libre, cab["TURNO"]).value = turno
    ws.cell(fila_libre, cab["NOMBRE"]).value = nombre
    ws.cell(fila_libre, cab["TIPO"]).value = tipo
    if "ORIGEN" in cab:
        ws.cell(fila_libre, cab["ORIGEN"]).value = "añadida desde la interfaz"
    wb.save(ruta)
