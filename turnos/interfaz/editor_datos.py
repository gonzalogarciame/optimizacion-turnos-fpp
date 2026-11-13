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

from copy import copy
from typing import Iterable

import openpyxl
import pandas as pd
from openpyxl.utils import get_column_letter

from ..config import leer_pares_clave_valor
from ..io_excel.estructura import desplazar_filas as _desplazar_filas
from ..modelo.datos import TURNO_DESCANSO
from ..nombres import normalizar


def _mapa_cabecera(ws):
    return {str(c.value).strip().upper(): idx + 1 for idx, c in enumerate(ws[1]) if c.value is not None}


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


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


def leer_restricciones_df(ruta: str) -> pd.DataFrame:
    """RESTRICCIONES: ACTIVA es lo único que de verdad enciende/apaga la regla

    (cada r_NN.py la aplica solo si ACTIVA=1). TIPO es documental: lo real
    que hace DURA/BLANDA es el código de cada restricción, no esta celda.
    No se permite dar de alta restricciones nuevas desde aquí: NOMBRE tiene
    que coincidir con un `@restriccion(...)` ya registrado en el código.
    """
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = wb["RESTRICCIONES"]
    cab = _mapa_cabecera(ws)
    col_desc = cab.get("DESCRIPCIÓN") or cab.get("DESCRIPCION")
    filas = []
    for fila in range(2, ws.max_row + 1):
        nombre = _texto(ws.cell(fila, cab["NOMBRE"]).value)
        if not nombre:
            continue
        filas.append({
            "NOMBRE": nombre,
            "ACTIVA": bool(int(ws.cell(fila, cab["ACTIVA"]).value or 0)),
            "TIPO": _texto(ws.cell(fila, cab["TIPO"]).value) or "DURA",
            "DESCRIPCION": _texto(ws.cell(fila, col_desc).value) if col_desc else "",
        })
    return pd.DataFrame(filas)


def guardar_restricciones_df(ruta: str, df: pd.DataFrame) -> None:
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["RESTRICCIONES"]
    cab = _mapa_cabecera(ws)

    filas_por_nombre = {}
    for fila in range(2, ws.max_row + 1):
        nombre = _texto(ws.cell(fila, cab["NOMBRE"]).value)
        if nombre:
            filas_por_nombre[nombre] = fila

    for fila_datos in df.itertuples(index=False):
        d = fila_datos._asdict()
        fila = filas_por_nombre.get(_texto(d.get("NOMBRE")))
        if fila is None:
            continue  # nombre desconocido: no hay código detrás, se ignora
        ws.cell(fila, cab["ACTIVA"]).value = int(bool(d.get("ACTIVA")))
        ws.cell(fila, cab["TIPO"]).value = _texto(d.get("TIPO")).upper() or "DURA"

    wb.save(ruta)


def leer_config_editable(ruta: str) -> dict:
    wb = openpyxl.load_workbook(ruta, data_only=True)
    return leer_pares_clave_valor(wb["CONFIG"])


def guardar_config_valores(ruta: str, cambios: dict) -> None:
    """Sobrescribe SOLO las claves de `cambios` que ya existan en CONFIG.

    No da de alta claves nuevas (no tendrían código detrás que las lea).
    """
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["CONFIG"]
    filas_por_clave = {}
    for fila in range(2, ws.max_row + 1):
        clave = _texto(ws.cell(fila, 1).value).upper()
        if clave:
            filas_por_clave[clave] = fila

    for clave, valor in cambios.items():
        fila = filas_por_clave.get(clave.upper())
        if fila is None:
            continue
        ws.cell(fila, 2).value = valor

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


# ---------------------------------------------------------------------
# TIPOS_TURNO / PLAZAS_POR_DIA
#
# Editar un turno existente (plazas, sexo, esfuerzo) es pura edición de
# celdas: no toca la rejilla TURNOS. Añadir un turno nuevo sí la toca,
# porque cada plaza de cada turno tiene su propia fila reservada en TURNOS
# (ver TIPOS_TURNO!FILA_INI/FILA_FIN e `io_excel.escritor`, que escribe ahí
# la solución). Por eso `agregar_tipo_turno` inserta filas de verdad en
# TURNOS -justo antes del primer dependiente- y desplaza el FILA de cada
# fila de DEPENDIENTES lo que haya insertado. TIPOS_TURNO y PLAZAS_POR_DIA
# no dependen del orden de sus filas (se leen por nombre), así que ahí basta
# con añadir la fila nueva al final.
# ---------------------------------------------------------------------
def leer_tipos_turno_df(ruta: str) -> pd.DataFrame:
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = wb["TIPOS_TURNO"]
    cab = _mapa_cabecera(ws)
    filas = []
    for fila in range(2, ws.max_row + 1):
        turno = _texto(ws.cell(fila, cab["TURNO"]).value)
        plazas = ws.cell(fila, cab["PLAZAS"]).value
        if not turno or turno == TURNO_DESCANSO or not isinstance(plazas, (int, float)):
            continue
        filas.append({
            "TURNO": turno,
            "PLAZAS": int(plazas),
            "SEXO_REQ": _texto(ws.cell(fila, cab["SEXO_REQ"]).value).upper() or "-",
            "ESFUERZO": float(ws.cell(fila, cab["ESFUERZO"]).value or 0),
        })
    return pd.DataFrame(filas)


def guardar_tipos_turno_df(ruta: str, df: pd.DataFrame) -> None:
    """Actualiza PLAZAS/SEXO_REQ/ESFUERZO de turnos ya existentes.

    No permite renombrar ni borrar turnos desde aquí: el nombre se usa tal
    cual en FIJACIONES, en la rejilla TURNOS y, para 'comedor', en el código
    de `r08_vigilancia_no_comedor`. Cambiarlo a mano rompería esas
    referencias. PLAZAS aquí es solo el valor por defecto: el reparto
    día a día se edita en PLAZAS_POR_DIA.
    """
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["TIPOS_TURNO"]
    cab = _mapa_cabecera(ws)

    filas_por_turno = {}
    for fila in range(2, ws.max_row + 1):
        turno = _texto(ws.cell(fila, cab["TURNO"]).value)
        if turno:
            filas_por_turno[turno] = fila

    for fila_datos in df.itertuples(index=False):
        d = fila_datos._asdict()
        fila = filas_por_turno.get(_texto(d.get("TURNO")))
        if fila is None:
            continue
        ws.cell(fila, cab["PLAZAS"]).value = int(d.get("PLAZAS") or 0)
        ws.cell(fila, cab["SEXO_REQ"]).value = _texto(d.get("SEXO_REQ")).upper() or "-"
        ws.cell(fila, cab["ESFUERZO"]).value = float(d.get("ESFUERZO") or 0)

    wb.save(ruta)


def leer_plazas_por_dia_df(ruta: str, dias: Iterable[int]) -> pd.DataFrame:
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = wb["PLAZAS_POR_DIA"]
    mapa_dias = {}
    for col in range(2, ws.max_column + 1):
        v = ws.cell(1, col).value
        if isinstance(v, (int, float)):
            mapa_dias[int(v)] = col

    turnos_df = leer_tipos_turno_df(ruta)
    defaults = dict(zip(turnos_df["TURNO"], turnos_df["PLAZAS"]))

    filas_hoja = {}
    for fila in range(2, ws.max_row + 1):
        turno = _texto(ws.cell(fila, 1).value)
        if turno in defaults:
            filas_hoja[turno] = fila

    filas = []
    for turno, plazas_default in defaults.items():
        registro = {"TURNO": turno}
        fila = filas_hoja.get(turno)
        for dia in dias:
            if fila is not None:
                col = mapa_dias.get(dia)
                valor = ws.cell(fila, col).value if col else None
                registro[str(dia)] = int(valor) if valor not in (None, "") else 0
            else:
                registro[str(dia)] = plazas_default
        filas.append(registro)
    return pd.DataFrame(filas)


def guardar_plazas_por_dia_df(ruta: str, df: pd.DataFrame, dias: Iterable[int]) -> None:
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["PLAZAS_POR_DIA"]
    mapa_dias = {}
    for col in range(2, ws.max_column + 1):
        v = ws.cell(1, col).value
        if isinstance(v, (int, float)):
            mapa_dias[int(v)] = col

    filas_hoja = {}
    for fila in range(2, ws.max_row + 1):
        turno = _texto(ws.cell(fila, 1).value)
        if turno:
            filas_hoja[turno] = fila

    for fila_datos in df.itertuples(index=False):
        d = fila_datos._asdict()
        turno = _texto(d.get("TURNO"))
        fila = filas_hoja.get(turno)
        if fila is None:
            # El turno no tenía fila propia en PLAZAS_POR_DIA (usaba el
            # valor por defecto de TIPOS_TURNO): se crea ahora, al final.
            fila = ws.max_row + 1
            ws.cell(fila, 1).value = turno
            filas_hoja[turno] = fila
        for dia in dias:
            col = mapa_dias.get(dia)
            if col is None:
                continue
            ws.cell(fila, col).value = int(d.get(str(dia)) or 0)

    wb.save(ruta)


def _fila_descanso_en_turnos(ws_turnos) -> int:
    for fila in range(2, ws_turnos.max_row + 1):
        if _texto(ws_turnos.cell(fila, 1).value).upper() == "DESCANSO":
            return fila
    raise ValueError("TURNOS: no se encuentra la etiqueta 'DESCANSO'")


def agregar_tipo_turno(
    ruta: str, nombre: str, plazas: int, sexo_req: str, esfuerzo: float,
    dias: Iterable[int], dia_reoptimizacion: int,
) -> None:
    """Da de alta un turno nuevo: reserva sus filas en TURNOS y actualiza
    TIPOS_TURNO, PLAZAS_POR_DIA y el FILA de cada dependiente existente.

    En PLAZAS_POR_DIA se ponen 0 plazas en los días anteriores a
    DIA_REOPTIMIZACION (el turno no existía entonces, así que no le toca
    holgura/falta penalizada por esos días) y `plazas` en los días futuros.
    """
    nombre = _texto(nombre)
    if not nombre:
        raise ValueError("El turno necesita un nombre")
    if nombre == TURNO_DESCANSO:
        raise ValueError("'descanso' es un nombre reservado")
    if plazas < 1:
        raise ValueError("El nuevo turno necesita al menos 1 plaza")

    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws_tipos = wb["TIPOS_TURNO"]
    cab_tipos = _mapa_cabecera(ws_tipos)

    maximo_fila_fin = 1
    for fila in range(2, ws_tipos.max_row + 1):
        turno = _texto(ws_tipos.cell(fila, cab_tipos["TURNO"]).value)
        plazas_val = ws_tipos.cell(fila, cab_tipos["PLAZAS"]).value
        if not turno or not isinstance(plazas_val, (int, float)):
            continue
        if turno == nombre:
            raise ValueError(f"Ya existe un turno llamado '{nombre}'")
        if turno == TURNO_DESCANSO:
            continue
        fila_fin = ws_tipos.cell(fila, cab_tipos["FILA_FIN"]).value
        if isinstance(fila_fin, (int, float)):
            maximo_fila_fin = max(maximo_fila_fin, int(fila_fin))

    fila_ini_nuevo = maximo_fila_fin + 1
    fila_fin_nuevo = fila_ini_nuevo + plazas - 1

    # 1. Reservar filas en la rejilla TURNOS, justo antes del primer
    #    dependiente (o de DESCANSO si no hay ninguno todavía).
    ws_turnos = wb["TURNOS"]
    _desplazar_filas(ws_turnos, fila_ini_nuevo, plazas)
    ws_turnos.cell(fila_ini_nuevo, 1).value = nombre

    # 2. Añadir la fila del turno en TIPOS_TURNO (el orden no importa: se
    #    lee por nombre, no por posición).
    fila_tipos_nueva = ws_tipos.max_row + 1
    ws_tipos.cell(fila_tipos_nueva, cab_tipos["TURNO"]).value = nombre
    ws_tipos.cell(fila_tipos_nueva, cab_tipos["PLAZAS"]).value = plazas
    ws_tipos.cell(fila_tipos_nueva, cab_tipos["SEXO_REQ"]).value = sexo_req
    ws_tipos.cell(fila_tipos_nueva, cab_tipos["ESFUERZO"]).value = esfuerzo
    ws_tipos.cell(fila_tipos_nueva, cab_tipos["FILA_INI"]).value = fila_ini_nuevo
    ws_tipos.cell(fila_tipos_nueva, cab_tipos["FILA_FIN"]).value = fila_fin_nuevo

    # 3. Desplazar el FILA de cada dependiente lo que hayamos insertado:
    #    todos están por debajo del último turno, así que a todos les toca.
    ws_dep = wb["DEPENDIENTES"]
    cab_dep = _mapa_cabecera(ws_dep)
    for fila in range(2, ws_dep.max_row + 1):
        valor_fila = ws_dep.cell(fila, cab_dep["FILA"]).value
        if isinstance(valor_fila, (int, float)):
            ws_dep.cell(fila, cab_dep["FILA"]).value = int(valor_fila) + plazas

    # 4. Añadir la fila en PLAZAS_POR_DIA con el mismo nº de plazas cada día
    #    (se puede afinar día a día después, desde la pantalla de plazas).
    ws_plazas = wb["PLAZAS_POR_DIA"]
    mapa_dias = {}
    for col in range(2, ws_plazas.max_column + 1):
        v = ws_plazas.cell(1, col).value
        if isinstance(v, (int, float)):
            mapa_dias[int(v)] = col
    fila_plazas_nueva = ws_plazas.max_row + 1
    ws_plazas.cell(fila_plazas_nueva, 1).value = nombre
    for dia in dias:
        col = mapa_dias.get(dia)
        if col:
            ws_plazas.cell(fila_plazas_nueva, col).value = 0 if dia < dia_reoptimizacion else plazas

    wb.save(ruta)


# ---------------------------------------------------------------------
# DEPENDIENTES / ASIG_DEPENDIENTE
# ---------------------------------------------------------------------
def leer_dependientes_df(ruta: str) -> pd.DataFrame:
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = wb["DEPENDIENTES"]
    cab = _mapa_cabecera(ws)
    filas = []
    for fila in range(2, ws.max_row + 1):
        acampado = _texto(ws.cell(fila, cab["ACAMPADO"]).value)
        fila_grid = ws.cell(fila, cab["FILA"]).value
        if not acampado or fila_grid in (None, ""):
            continue
        filas.append({
            "ACAMPADO": acampado,
            "SEXO_MONITOR_REQ": _texto(ws.cell(fila, cab["SEXO_MONITOR_REQ"]).value).upper() or "-",
            "ESFUERZO": float(ws.cell(fila, cab["ESFUERZO"]).value or 0),
        })
    return pd.DataFrame(filas)


def guardar_dependientes_df(ruta: str, df: pd.DataFrame) -> None:
    """Actualiza SEXO_MONITOR_REQ/ESFUERZO de dependientes ya existentes.

    No permite renombrar ni borrar desde aquí (el nombre se usa tal cual en
    ASIG_DEPENDIENTE y en la rejilla TURNOS).
    """
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["DEPENDIENTES"]
    cab = _mapa_cabecera(ws)

    filas_por_acampado = {}
    for fila in range(2, ws.max_row + 1):
        acampado = _texto(ws.cell(fila, cab["ACAMPADO"]).value)
        if acampado:
            filas_por_acampado[acampado] = fila

    for fila_datos in df.itertuples(index=False):
        d = fila_datos._asdict()
        fila = filas_por_acampado.get(_texto(d.get("ACAMPADO")))
        if fila is None:
            continue
        ws.cell(fila, cab["SEXO_MONITOR_REQ"]).value = _texto(d.get("SEXO_MONITOR_REQ")).upper() or "-"
        ws.cell(fila, cab["ESFUERZO"]).value = float(d.get("ESFUERZO") or 0)

    wb.save(ruta)


def agregar_dependiente(
    ruta: str, acampado: str, sexo_req: str, esfuerzo: float,
    dias: Iterable[int], dia_reoptimizacion: int,
) -> None:
    """Da de alta un dependiente nuevo: reserva su fila en TURNOS (justo
    antes de DESCANSO) y añade su fila en DEPENDIENTES y en ASIG_DEPENDIENTE.

    Los días anteriores a DIA_REOPTIMIZACION ya pasaron y están fijados
    (§ historico_inmutable), así que se marcan '-' (no presente) para que el
    modelo no intente inventar retroactivamente quién lo cuidó: si en
    realidad ya estaba presente, esas celdas hay que rellenarlas a mano con
    el monitor real. Los días futuros quedan vacíos (el modelo decide).
    """
    acampado = _texto(acampado)
    if not acampado:
        raise ValueError("El dependiente necesita un nombre")

    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws_dep = wb["DEPENDIENTES"]
    cab_dep = _mapa_cabecera(ws_dep)

    existentes = set()
    for fila in range(2, ws_dep.max_row + 1):
        nombre = _texto(ws_dep.cell(fila, cab_dep["ACAMPADO"]).value)
        if nombre:
            existentes.add(normalizar(nombre))
    if normalizar(acampado) in existentes:
        raise ValueError(f"Ya existe un dependiente llamado '{acampado}'")

    # 1. Reservar su fila en la rejilla TURNOS, justo antes de DESCANSO.
    ws_turnos = wb["TURNOS"]
    fila_descanso = _fila_descanso_en_turnos(ws_turnos)
    _desplazar_filas(ws_turnos, fila_descanso, 1)
    ws_turnos.cell(fila_descanso, 1).value = acampado
    fila_nueva = fila_descanso

    # 2. Añadir la fila en DEPENDIENTES.
    fila_dep_nueva = ws_dep.max_row + 1
    ws_dep.cell(fila_dep_nueva, cab_dep["ACAMPADO"]).value = acampado
    ws_dep.cell(fila_dep_nueva, cab_dep["SEXO_MONITOR_REQ"]).value = sexo_req
    ws_dep.cell(fila_dep_nueva, cab_dep["ESFUERZO"]).value = esfuerzo
    ws_dep.cell(fila_dep_nueva, cab_dep["FILA"]).value = fila_nueva

    # 3. Añadir su fila en ASIG_DEPENDIENTE: '-' en días pasados (ver
    #    docstring), vacía (por decidir) en días futuros.
    ws_asig = wb["ASIG_DEPENDIENTE"]
    mapa_dias_asig = {}
    for col in range(2, ws_asig.max_column + 1):
        v = ws_asig.cell(1, col).value
        if isinstance(v, (int, float)):
            mapa_dias_asig[int(v)] = col
    fila_asig_nueva = ws_asig.max_row + 1
    ws_asig.cell(fila_asig_nueva, 1).value = acampado
    for dia in dias:
        col = mapa_dias_asig.get(dia)
        if col and dia < dia_reoptimizacion:
            ws_asig.cell(fila_asig_nueva, col).value = "-"

    wb.save(ruta)
