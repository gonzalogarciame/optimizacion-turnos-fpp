"""Estado compartido de la app web. Como es una herramienta de escritorio para un único usuario local,
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

import sqlite3
import threading
from typing import Optional

from pathlib import Path

from ..almacen.cargar import leer_datos_db
from ..almacen.esquema import abrir
from ..almacen.importar import importar_excel
from ..almacen.plantilla import completar_campamento
from ..modelo.errores import ErrorDatos
from ..modelo.datos import Datos
from ..nombres import ErrorNombreNoReconocido

RUTA_POR_DEFECTO = "datos/2026-quincena2-18al30jul/turnos.xlsx"  # solo si aún no hay ninguna base de datos


def ruta_inicial() -> str:
    """La base de datos modificada más recientemente bajo datos/ (o el Excel de siempre, que se importa solo)."""
    candidatas = [p for p in Path("datos").glob("**/*.db") if "copias" not in p.parts]
    if candidatas:
        return str(max(candidatas, key=lambda p: p.stat().st_mtime)).replace("\\", "/")
    return RUTA_POR_DEFECTO if Path(RUTA_POR_DEFECTO).exists() else ""  # "" = aún no hay ningún campamento


def resolver_ruta(ruta: str) -> str:
    """Una ruta .xlsx se importa a una base de datos con el mismo nombre (si no existe ya) y se usa esa."""
    p = Path(ruta)
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        destino = p.with_suffix(".db")
        if not destino.exists():
            importar_excel(str(p), str(destino))
        return str(destino).replace("\\", "/")
    return ruta

_estado = {
    "ruta": ruta_inicial(),
    "datos": None,
    "desde": None,
    "modelo": None,
    "solucion": None,
    "error_carga": None,
    "trabajo": None,  # generación en curso o terminada (ver server.py)
}
cerrojo = threading.RLock()


def _cfg_basica(ruta: str) -> dict:
    con = abrir(ruta)
    try:
        return {r["clave"]: r["valor"] for r in con.execute("SELECT clave, valor FROM config")}
    finally:
        con.close()


def cargar(ruta: str, desde: Optional[int] = None) -> bool:
    """Lee el campamento. `desde` (opcional) fija el día de re-optimización."""
    try:
        ruta = resolver_ruta(ruta)
        completar_campamento(ruta)  # reglas y parámetros añadidos después de crear el campamento
        cfg = _cfg_basica(ruta)
        dia_inicio = int(cfg["DIA_INICIO"])
        datos = leer_datos_db(ruta, desde=dia_inicio)
    except (ErrorDatos, ErrorNombreNoReconocido, ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
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
