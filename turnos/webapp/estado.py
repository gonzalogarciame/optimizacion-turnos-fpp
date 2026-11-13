"""Estado compartido de la app web: igual que `interfaz.estado`, pero sin
Streamlit. Como es una herramienta de escritorio para un único usuario local,
basta con un diccionario a nivel de módulo (no hay sesiones ni usuarios
concurrentes que aislar).

Dos ideas que conviene tener claras:

- `datos` se lee siempre con "nada es histórico" (re-optimización desde el
  primer día). Así la rejilla se puede mostrar y editar aunque un día
  pasado esté a medias; la comprobación de que el histórico está completo
  solo se hace al generar (`leer_datos(ruta, desde=N)` en `server.py`).
- `desde` es el día a partir del cual se regenera. Vive en memoria; solo
  se vuelca a CONFIG!DIA_REOPTIMIZACION al aplicar una solución.
"""
from __future__ import annotations

import threading
from typing import Optional

import openpyxl

from ..config import leer_pares_clave_valor
from ..io_excel.lector import ErrorLecturaExcel, leer_datos
from ..modelo.datos import Datos
from ..nombres import ErrorNombreNoReconocido

RUTA_POR_DEFECTO = "datos/2026-quincena2-18al30jul/turnos.xlsx"

_estado = {
    "ruta": RUTA_POR_DEFECTO,
    "datos": None,
    "desde": None,
    "modelo": None,
    "solucion": None,
    "error_carga": None,
    "trabajo": None,  # generación en curso o terminada (ver server.py)
}
cerrojo = threading.RLock()


def _cfg_basica(ruta: str) -> dict:
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    try:
        return leer_pares_clave_valor(wb["CONFIG"])
    finally:
        wb.close()


def cargar(ruta: str, desde: Optional[int] = None) -> bool:
    """Lee el Excel. `desde` (opcional) fija el día de re-optimización."""
    try:
        cfg = _cfg_basica(ruta)
        dia_inicio = int(cfg["DIA_INICIO"])
        datos = leer_datos(ruta, desde=dia_inicio)
    except (ErrorLecturaExcel, ErrorNombreNoReconocido, ValueError, KeyError, TypeError, OSError) as exc:
        # OSError incluye PermissionError: el Excel puede estar abierto en
        # Excel en ese mismo instante (bloqueado para lectura en Windows).
        _estado["error_carga"] = str(exc)
        _estado["datos"] = None
        return False

    with cerrojo:
        misma_ruta = _estado["ruta"] == ruta and _estado["desde"] is not None
        if desde is None:
            desde = _estado["desde"] if misma_ruta else None
        if desde is None:
            desde = int(cfg.get("DIA_REOPTIMIZACION") or dia_inicio)
        desde = max(datos.cfg.dia_inicio, min(int(desde), datos.cfg.dia_fin + 1))

        _estado["ruta"] = ruta
        _estado["datos"] = datos
        _estado["desde"] = desde
        _estado["modelo"] = None
        _estado["solucion"] = None
        _estado["trabajo"] = None
        _estado["error_carga"] = None
    return True


def datos_actuales() -> Optional[Datos]:
    return _estado["datos"]


def ruta_actual() -> str:
    return _estado["ruta"]


def desde() -> Optional[int]:
    return _estado["desde"]


def fijar_desde(dia: int) -> None:
    datos = _estado["datos"]
    if datos is not None:
        dia = max(datos.cfg.dia_inicio, min(int(dia), datos.cfg.dia_fin + 1))
    _estado["desde"] = dia


def error_carga() -> Optional[str]:
    return _estado["error_carga"]


def get(clave, defecto=None):
    return _estado.get(clave, defecto)


def set(clave, valor) -> None:
    _estado[clave] = valor
