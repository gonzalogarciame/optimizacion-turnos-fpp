"""Copias de seguridad de la base de datos (sustituyen a los `turnos_backup_*.xlsx`).

Cada copia es un `.db` completo en la carpeta `copias/` junto a la base de
datos. Se conservan las últimas `CONSERVAR`; las más antiguas se borran solas.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path
from typing import List

CONSERVAR = 40


def _carpeta(ruta: str) -> Path:
    return Path(ruta).parent / "copias"


def hacer_copia_seguridad(ruta: str, conservar: int = CONSERVAR) -> str:
    """Copia la base de datos (con marca de tiempo) y devuelve la ruta de la copia."""
    carpeta = _carpeta(ruta)
    carpeta.mkdir(parents=True, exist_ok=True)
    stem = Path(ruta).stem
    ahora = _dt.datetime.now()
    destino = carpeta / f"{stem}_{ahora:%Y%m%d_%H%M%S}.db"
    n = 1
    while destino.exists():  # dos copias en el mismo segundo
        destino = carpeta / f"{stem}_{ahora:%Y%m%d_%H%M%S}_{n}.db"
        n += 1
    origen, copia = sqlite3.connect(ruta), sqlite3.connect(str(destino))
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    for viejo in listar_copias(ruta)[:-conservar] if conservar else []:
        try:
            Path(viejo).unlink()
        except OSError:
            pass
    return str(destino)


def listar_copias(ruta: str) -> List[str]:
    """Copias existentes, de la más antigua a la más reciente."""
    carpeta = _carpeta(ruta)
    if not carpeta.exists():
        return []
    return [str(p) for p in sorted(carpeta.glob(f"{Path(ruta).stem}_*.db"), key=lambda p: (p.stat().st_mtime, p.name))]


def restaurar_copia(ruta: str, copia: str) -> str:
    """Vuelve a una copia anterior. Antes guarda el estado actual como una copia más (por si acaso)."""
    if not Path(copia).exists():
        raise FileNotFoundError(f"No existe la copia '{copia}'")
    previa = hacer_copia_seguridad(ruta)
    origen, destino = sqlite3.connect(copia), sqlite3.connect(ruta)
    try:
        origen.backup(destino)
    finally:
        destino.close()
        origen.close()
    return previa
