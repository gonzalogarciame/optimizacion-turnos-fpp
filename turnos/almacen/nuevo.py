"""Crear un campamento nuevo a partir de otro y listar los que hay."""
from __future__ import annotations

import calendar
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, List

from ..config import config_desde_pares, normalizar_clave
from ..modelo.errores import ErrorDatos
from .cargar import leer_datos_db
from .esquema import abrir
from .plantilla import RESTRICCIONES, TURNOS_HABITUALES, pares_config

CARPETA_DATOS = "datos"


def listar_campamentos(raiz: str = None) -> List[Dict]:
    """Bases de datos que hay bajo `raiz` (sin contar las copias de seguridad), la más reciente primero."""
    res = []
    for p in Path(raiz or CARPETA_DATOS).glob("**/*.db"):
        if "copias" in p.parts:
            continue
        try:
            con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
            try:
                cfg = {normalizar_clave(k): v for k, v in con.execute("SELECT clave, valor FROM config")}
            finally:
                con.close()
            res.append({
                "ruta": p.as_posix(),
                "nombre": p.parent.name,
                "quincena": int(cfg["QUINCENA"]), "anio": int(cfg["AÑO"]), "mes": int(cfg["MES"]),
                "dia_inicio": int(cfg["DIA_INICIO"]), "dia_fin": int(cfg["DIA_FIN"]),
                "modificado": p.stat().st_mtime,
            })
        except (sqlite3.Error, KeyError, ValueError):
            continue  # un .db que no es de un campamento
    return sorted(res, key=lambda c: -c["modificado"])


def nombre_carpeta(anio: int, mes: int, quincena: int, dia_inicio: int, dia_fin: int) -> str:
    return f"{anio}-{mes:02d}-quincena{quincena}-{dia_inicio}al{dia_fin}"


def _mapa_dias(origen: List[int], destino: List[int]) -> Dict[int, int]:
    """Qué día del campamento de origen sirve de modelo para cada día del nuevo.

    Primer día con primer día (llegada) y último con último (salida); los de en medio, con un día
    «normal» del origen. Si tienen los mismos días, uno a uno.
    """
    m, n = len(origen), len(destino)
    if m == n:
        return dict(zip(destino, origen))
    res = {}
    for i, d in enumerate(destino):
        if i == 0:
            res[d] = origen[0]
        elif i == n - 1:
            res[d] = origen[-1]
        else:
            res[d] = origen[m // 2] if m > 2 else origen[0]
    return res


def _carpeta_nueva(quincena: int, anio: int, mes: int, dia_inicio: int, dia_fin: int, raiz: str = None) -> Path:
    """Valida las fechas y devuelve la carpeta donde irá el campamento (que no debe existir ya)."""
    if not (1 <= mes <= 12):
        raise ValueError("El mes debe estar entre 1 y 12")
    if not (2000 <= anio <= 2100):
        raise ValueError("El año no es válido")
    if quincena < 1:
        raise ValueError("La quincena debe ser 1 o más")
    ultimo = calendar.monthrange(anio, mes)[1]
    if not (1 <= dia_inicio <= dia_fin <= ultimo):
        raise ValueError(f"Los días deben cumplir 1 ≤ llegada ≤ salida ≤ {ultimo} (un campamento no cruza de mes)")
    carpeta = Path(raiz or CARPETA_DATOS) / nombre_carpeta(anio, mes, quincena, dia_inicio, dia_fin)
    if (carpeta / "campamento.db").exists():
        raise ValueError(f"Ya existe ese campamento ({carpeta.name})")
    return carpeta


def crear_en_blanco(quincena: int, anio: int, mes: int, dia_inicio: int, dia_fin: int, raiz: str = None) -> str:
    """Campamento nuevo desde cero: los turnos y reglas habituales, sin monitores ni dependientes
    (se añaden después desde la web). Devuelve la ruta de la nueva base de datos."""
    carpeta = _carpeta_nueva(quincena, anio, mes, dia_inicio, dia_fin, raiz)
    destino = carpeta / "campamento.db"
    dias = range(dia_inicio, dia_fin + 1)
    existia_carpeta = carpeta.exists()
    try:
        con = abrir(str(destino), crear=True)
        try:
            with con:
                con.executemany("INSERT INTO config (clave, valor, descripcion) VALUES (?, ?, ?)",
                                pares_config(quincena, anio, mes, dia_inicio, dia_fin))
                for i, (turno, plazas, sexo, nota) in enumerate(TURNOS_HABITUALES):
                    con.execute("INSERT INTO tipos_turno (orden, turno, plazas, sexo_req, esfuerzo, notas) VALUES (?, ?, ?, ?, 2.0, ?)",
                                (i, turno, plazas, sexo, nota))
                    con.executemany("INSERT INTO plazas_dia (turno, dia, plazas, maximo) VALUES (?, ?, ?, NULL)",
                                    [(turno, d, plazas) for d in dias])
                con.executemany("INSERT INTO restricciones (orden, nombre, activa, tipo, descripcion) VALUES (?, ?, 1, ?, ?)",
                                [(i, n, tipo, desc) for i, (n, tipo, desc) in enumerate(RESTRICCIONES)])
                con.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES ('creado_desde', 'en blanco')")
        finally:
            con.close()
        leer_datos_db(str(destino))  # comprueba que lo creado es coherente
    except BaseException:
        if not existia_carpeta:
            shutil.rmtree(carpeta, ignore_errors=True)
        raise
    return destino.as_posix()


def crear_campamento(ruta_origen: str, quincena: int, anio: int, mes: int, dia_inicio: int, dia_fin: int,
                     copiar_disponibilidad: bool = False, raiz: str = None) -> str:
    """Campamento nuevo y vacío (sin turnos asignados) con los monitores, dependientes, turnos y
    restricciones del de origen. Devuelve la ruta de la nueva base de datos."""
    carpeta = _carpeta_nueva(quincena, anio, mes, dia_inicio, dia_fin, raiz)
    destino = carpeta / "campamento.db"
    dias_nuevos = list(range(dia_inicio, dia_fin + 1))

    src = abrir(ruta_origen)
    try:
        pares = {normalizar_clave(r["clave"]): r["valor"] for r in src.execute("SELECT clave, valor FROM config")}
        cfg_origen = config_desde_pares(pares)
        dias_origen = cfg_origen.dias
        mapa = _mapa_dias(dias_origen, dias_nuevos)
        filas = {t: src.execute(f"SELECT * FROM {t}").fetchall() for t in
                 ("config", "monitores", "alias", "tipos_turno", "dependientes", "restricciones", "disponibilidad", "plazas_dia")}
    finally:
        src.close()

    nuevos = {"QUINCENA": quincena, "AÑO": anio, "MES": mes, "DIA_INICIO": dia_inicio, "DIA_FIN": dia_fin,
              "DIA_REOPTIMIZACION": dia_inicio}
    existia_carpeta = carpeta.exists()
    try:
        dst = abrir(str(destino), crear=True)
        try:
            with dst:
                for r in filas["config"]:
                    clave = normalizar_clave(r["clave"])
                    valor = str(nuevos[clave]) if clave in nuevos else r["valor"]
                    dst.execute("INSERT INTO config (clave, valor, descripcion) VALUES (?, ?, ?)", (r["clave"], valor, r["descripcion"]))
                for tabla in ("monitores", "alias", "tipos_turno", "dependientes", "restricciones"):
                    for r in filas[tabla]:
                        cols = r.keys()
                        dst.execute(f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(r))
                codigos = {(r["monitor"], r["dia"]): r["codigo"] for r in filas["disponibilidad"]}
                dst.executemany(
                    "INSERT INTO disponibilidad (monitor, dia, codigo) VALUES (?, ?, ?)",
                    [(m["nombre"], d, codigos.get((m["nombre"], mapa[d]), "D") if copiar_disponibilidad else "D")
                     for m in filas["monitores"] for d in dias_nuevos],
                )
                plazas = {(r["turno"], r["dia"]): (r["plazas"], r["maximo"]) for r in filas["plazas_dia"]}
                dst.executemany(
                    "INSERT INTO plazas_dia (turno, dia, plazas, maximo) VALUES (?, ?, ?, ?)",
                    [(t["turno"], d, *plazas.get((t["turno"], mapa[d]), (t["plazas"], None)))
                     for t in filas["tipos_turno"] for d in dias_nuevos],
                )
                dst.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES ('creado_desde', ?)", (Path(ruta_origen).parent.name,))
        finally:
            dst.close()
        leer_datos_db(str(destino))  # comprueba que lo creado es coherente
    except BaseException:
        if not existia_carpeta:
            shutil.rmtree(carpeta, ignore_errors=True)
        raise
    return destino.as_posix()
