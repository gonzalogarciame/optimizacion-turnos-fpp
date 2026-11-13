"""Lectura y edición de los datos maestros desde la base de datos.

Equivale a `io_excel.editor_datos` + `io_excel.estructura.guardar_plazas`, con
las mismas funciones y los mismos DataFrames (columnas NOMBRE, SEXO, ...), así
que las pantallas no cambian. Ya no hay filas que reservar en ninguna rejilla:
añadir un turno o un dependiente es insertar una fila.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

import pandas as pd

from ..io_excel.estructura import ErrorPlazas
from ..modelo.datos import TURNO_DESCANSO, Datos
from ..nombres import normalizar
from .copias import hacer_copia_seguridad
from .esquema import abrir
from .rejilla import FILAS_LIBRES_DESCANSO  # noqa: F401


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _por_nombre_normalizado(nombres: Iterable[str]) -> Dict[str, str]:
    return {normalizar(n): n for n in nombres}


# ----------------------------------------------------------------------
# Monitores
# ----------------------------------------------------------------------
def leer_monitores_df(ruta: str) -> pd.DataFrame:
    con = abrir(ruta)
    try:
        filas = [{
            "NOMBRE": r["nombre"], "SEXO": r["sexo"], "GRUPO": r["grupo"],
            "PERMITE_DESCANSO": r["permite_descanso"], "PENALIZAR_DESCANSO": r["penalizar_descanso"],
            "DEPENDIENTE_1": r["dependiente_1"], "DEPENDIENTE_2": r["dependiente_2"],
        } for r in con.execute("SELECT * FROM monitores ORDER BY orden")]
    finally:
        con.close()
    return pd.DataFrame(filas)


def guardar_monitores_df(ruta: str, df: pd.DataFrame, dias: Iterable[int]) -> List[str]:
    """Reemplaza la lista de monitores por la de `df` (una fila por monitor).

    Los nuevos reciben disponibilidad 'D' todos los días. Uno que ya no está en la
    tabla se borra solo si no tiene nada asignado; si lo tiene se conserva y se avisa.
    """
    filas = []
    for d in df.to_dict(orient="records"):
        nombre = _texto(d.get("NOMBRE"))
        if not nombre:
            continue
        sexo = _texto(d.get("SEXO")).upper()
        if sexo not in ("M", "F"):
            raise ValueError(f"Monitor '{nombre}': el sexo debe ser M o F")
        filas.append((nombre, sexo, _texto(d.get("GRUPO")), int(bool(int(d.get("PERMITE_DESCANSO") or 0))),
                      int(bool(int(d.get("PENALIZAR_DESCANSO") or 0))),
                      _texto(d.get("DEPENDIENTE_1")) or None, _texto(d.get("DEPENDIENTE_2")) or None))
    nombres = [f[0] for f in filas]
    if len(set(nombres)) != len(nombres):
        raise ValueError("Hay monitores con el mismo nombre")

    dias = list(dias)
    avisos: List[str] = []
    con = abrir(ruta)
    try:
        existentes = {r["nombre"] for r in con.execute("SELECT nombre FROM monitores")}
        nuevos = [n for n in nombres if n not in existentes]
        sin_borrar = []
        with con:
            for i, (nombre, sexo, grupo, permite, penaliza, dep1, dep2) in enumerate(filas):
                if nombre in existentes:
                    con.execute(
                        "UPDATE monitores SET orden=?, sexo=?, grupo=?, permite_descanso=?, penalizar_descanso=?, "
                        "dependiente_1=?, dependiente_2=? WHERE nombre=?", (i, sexo, grupo, permite, penaliza, dep1, dep2, nombre))
                else:
                    con.execute(
                        "INSERT INTO monitores (orden, nombre, sexo, grupo, permite_descanso, penalizar_descanso, dependiente_1, dependiente_2) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (i, nombre, sexo, grupo, permite, penaliza, dep1, dep2))
                    con.executemany("INSERT INTO disponibilidad (monitor, dia, codigo) VALUES (?, ?, 'D')", [(nombre, d) for d in dias])
            for quitado in sorted(existentes - set(nombres)):
                tiene = con.execute(
                    "SELECT (SELECT COUNT(*) FROM asignaciones WHERE monitor = ?) + (SELECT COUNT(*) FROM fijaciones WHERE monitor = ?)",
                    (quitado, quitado)).fetchone()[0]
                if tiene:
                    sin_borrar.append(quitado)
                else:
                    con.execute("DELETE FROM alias WHERE canonico = ?", (quitado,))
                    con.execute("DELETE FROM monitores WHERE nombre = ?", (quitado,))
    finally:
        con.close()
    if sin_borrar:
        avisos.append(
            "No se han podido quitar porque tienen turnos o fijaciones asignados: " + ", ".join(sin_borrar) +
            ". Libera esas casillas en la Rejilla y vuelve a intentarlo."
        )
    if nuevos:
        avisos.append("Monitores nuevos, disponibles todos los días: " + ", ".join(sorted(nuevos)))
    return avisos


# ----------------------------------------------------------------------
# Disponibilidad
# ----------------------------------------------------------------------
def leer_disponibilidad_df(ruta: str, dias: Iterable[int]) -> pd.DataFrame:
    dias = list(dias)
    con = abrir(ruta)
    try:
        nombres = [r["nombre"] for r in con.execute("SELECT nombre FROM monitores ORDER BY orden")]
        codigos = {(r["monitor"], r["dia"]): r["codigo"] for r in con.execute("SELECT monitor, dia, codigo FROM disponibilidad")}
    finally:
        con.close()
    return pd.DataFrame([
        {"NOMBRE": n, **{str(d): codigos.get((n, d), "D") for d in dias}} for n in nombres
    ])


def guardar_disponibilidad_df(ruta: str, df: pd.DataFrame, dias: Iterable[int]) -> None:
    dias = list(dias)
    con = abrir(ruta)
    try:
        por_norm = _por_nombre_normalizado(r["nombre"] for r in con.execute("SELECT nombre FROM monitores"))
        with con:
            for d in df.to_dict(orient="records"):  # no itertuples(): renombra columnas como "18" a "_1"
                nombre = por_norm.get(normalizar(d["NOMBRE"]))
                if nombre is None:
                    continue
                for dia in dias:
                    codigo = str(d.get(str(dia), "D")).strip().upper()
                    con.execute(
                        "INSERT INTO disponibilidad (monitor, dia, codigo) VALUES (?, ?, ?) "
                        "ON CONFLICT(monitor, dia) DO UPDATE SET codigo = excluded.codigo", (nombre, dia, codigo))
    finally:
        con.close()


# ----------------------------------------------------------------------
# Restricciones y parámetros
# ----------------------------------------------------------------------
def leer_restricciones_df(ruta: str) -> pd.DataFrame:
    con = abrir(ruta)
    try:
        filas = [{"NOMBRE": r["nombre"], "ACTIVA": bool(r["activa"]), "TIPO": r["tipo"] or "DURA", "DESCRIPCION": r["descripcion"]}
                 for r in con.execute("SELECT * FROM restricciones ORDER BY orden")]
    finally:
        con.close()
    return pd.DataFrame(filas)


def guardar_restricciones_df(ruta: str, df: pd.DataFrame) -> None:
    """Solo se enciende/apaga lo que ya existe: cada regla tiene su código detrás."""
    con = abrir(ruta)
    try:
        with con:
            for d in df.to_dict(orient="records"):
                con.execute("UPDATE restricciones SET activa = ?, tipo = ? WHERE nombre = ?",
                            (int(bool(d.get("ACTIVA"))), _texto(d.get("TIPO")).upper() or "DURA", _texto(d.get("NOMBRE"))))
    finally:
        con.close()


def leer_config_editable(ruta: str) -> dict:
    con = abrir(ruta)
    try:
        return {r["clave"]: r["valor"] for r in con.execute("SELECT clave, valor FROM config")}
    finally:
        con.close()


def guardar_config_valores(ruta: str, cambios: dict) -> None:
    """Cambia solo las claves de CONFIG que ya existen (una clave nueva no tendría código que la lea)."""
    con = abrir(ruta)
    try:
        with con:
            for clave, valor in cambios.items():
                con.execute("UPDATE config SET valor = ? WHERE clave = ?", (str(valor), clave.upper()))
    finally:
        con.close()


# ----------------------------------------------------------------------
# Turnos y plazas
# ----------------------------------------------------------------------
def leer_tipos_turno_df(ruta: str) -> pd.DataFrame:
    con = abrir(ruta)
    try:
        filas = [{"TURNO": r["turno"], "PLAZAS": int(r["plazas"]), "SEXO_REQ": r["sexo_req"], "ESFUERZO": float(r["esfuerzo"])}
                 for r in con.execute("SELECT * FROM tipos_turno ORDER BY orden")]
    finally:
        con.close()
    return pd.DataFrame(filas)


def guardar_tipos_turno_df(ruta: str, df: pd.DataFrame) -> None:
    """Actualiza plazas por defecto, sexo y esfuerzo de turnos que ya existen (no se renombran ni se borran)."""
    con = abrir(ruta)
    try:
        with con:
            for d in df.to_dict(orient="records"):
                con.execute("UPDATE tipos_turno SET plazas = ?, sexo_req = ?, esfuerzo = ? WHERE turno = ?",
                            (int(d.get("PLAZAS") or 0), _texto(d.get("SEXO_REQ")).upper() or "-", float(d.get("ESFUERZO") or 0), _texto(d.get("TURNO"))))
    finally:
        con.close()


def leer_plazas_por_dia_df(ruta: str, dias: Iterable[int]) -> pd.DataFrame:
    dias = list(dias)
    con = abrir(ruta)
    try:
        turnos = [(r["turno"], int(r["plazas"])) for r in con.execute("SELECT turno, plazas FROM tipos_turno ORDER BY orden")]
        plazas = {(r["turno"], r["dia"]): int(r["plazas"]) for r in con.execute("SELECT turno, dia, plazas FROM plazas_dia")}
    finally:
        con.close()
    return pd.DataFrame([
        {"TURNO": t, **{str(d): plazas.get((t, d), defecto) for d in dias}} for t, defecto in turnos
    ])


def guardar_plazas_por_dia_df(ruta: str, df: pd.DataFrame, dias: Iterable[int]) -> None:
    dias = list(dias)
    con = abrir(ruta)
    try:
        with con:
            for d in df.to_dict(orient="records"):
                turno = _texto(d.get("TURNO"))
                if not con.execute("SELECT 1 FROM tipos_turno WHERE turno = ?", (turno,)).fetchone():
                    continue
                for dia in dias:
                    con.execute(
                        "INSERT INTO plazas_dia (turno, dia, plazas) VALUES (?, ?, ?) "
                        "ON CONFLICT(turno, dia) DO UPDATE SET plazas = excluded.plazas", (turno, dia, int(d.get(str(dia)) or 0)))
    finally:
        con.close()


def agregar_tipo_turno(ruta: str, nombre: str, plazas: int, sexo_req: str, esfuerzo: float,
                       dias: Iterable[int], dia_reoptimizacion: int) -> None:
    """Turno nuevo. Sus plazas son 0 en los días ya pasados (el turno no existía) y `plazas` en los demás."""
    nombre = _texto(nombre)
    if not nombre:
        raise ValueError("El turno necesita un nombre")
    if nombre == TURNO_DESCANSO:
        raise ValueError("'descanso' es un nombre reservado")
    if plazas < 1:
        raise ValueError("El nuevo turno necesita al menos 1 plaza")
    if sexo_req not in ("M", "F", "-"):
        raise ValueError("El sexo requerido debe ser M, F o -")
    con = abrir(ruta)
    try:
        if con.execute("SELECT 1 FROM tipos_turno WHERE turno = ?", (nombre,)).fetchone():
            raise ValueError(f"Ya existe un turno llamado '{nombre}'")
        with con:
            orden = con.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM tipos_turno").fetchone()[0]
            con.execute("INSERT INTO tipos_turno (orden, turno, plazas, sexo_req, esfuerzo) VALUES (?, ?, ?, ?, ?)",
                        (orden, nombre, plazas, sexo_req, esfuerzo))
            con.executemany("INSERT INTO plazas_dia (turno, dia, plazas) VALUES (?, ?, ?)",
                            [(nombre, d, 0 if d < dia_reoptimizacion else plazas) for d in dias])
    finally:
        con.close()


# ----------------------------------------------------------------------
# Dependientes
# ----------------------------------------------------------------------
def leer_dependientes_df(ruta: str) -> pd.DataFrame:
    con = abrir(ruta)
    try:
        filas = [{"ACAMPADO": r["acampado"], "SEXO_MONITOR_REQ": r["sexo_monitor_req"], "ESFUERZO": float(r["esfuerzo"])}
                 for r in con.execute("SELECT * FROM dependientes ORDER BY orden")]
    finally:
        con.close()
    return pd.DataFrame(filas)


def guardar_dependientes_df(ruta: str, df: pd.DataFrame) -> None:
    """Actualiza sexo del monitor y esfuerzo de dependientes que ya existen."""
    con = abrir(ruta)
    try:
        with con:
            for d in df.to_dict(orient="records"):
                con.execute("UPDATE dependientes SET sexo_monitor_req = ?, esfuerzo = ? WHERE acampado = ?",
                            (_texto(d.get("SEXO_MONITOR_REQ")).upper() or "-", float(d.get("ESFUERZO") or 0), _texto(d.get("ACAMPADO"))))
    finally:
        con.close()


def agregar_dependiente(ruta: str, acampado: str, sexo_req: str, esfuerzo: float,
                        dias: Iterable[int], dia_reoptimizacion: int) -> None:
    """Dependiente nuevo. Los días ya pasados figura como ausente (no se inventa quién lo cuidó)."""
    acampado = _texto(acampado)
    if not acampado:
        raise ValueError("El dependiente necesita un nombre")
    if sexo_req not in ("M", "F", "-"):
        raise ValueError("El sexo requerido debe ser M, F o -")
    con = abrir(ruta)
    try:
        if normalizar(acampado) in {normalizar(r["acampado"]) for r in con.execute("SELECT acampado FROM dependientes")}:
            raise ValueError(f"Ya existe un dependiente llamado '{acampado}'")
        with con:
            orden = con.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM dependientes").fetchone()[0]
            con.execute("INSERT INTO dependientes (orden, acampado, sexo_monitor_req, esfuerzo) VALUES (?, ?, ?, ?)",
                        (orden, acampado, sexo_req, esfuerzo))
            con.executemany("INSERT INTO dependiente_ausente (acampado, dia) VALUES (?, ?)",
                            [(acampado, d) for d in dias if d < dia_reoptimizacion])
    finally:
        con.close()


# ----------------------------------------------------------------------
# Plazas de llegada y salida (necesarias y "acepta hasta")
# ----------------------------------------------------------------------
def _filas_por_turno(datos: Datos, plazas: Dict, maximos: Dict) -> Dict[str, int]:
    return {t: max([0] + [max(plazas.get((t, d), 0), maximos.get((t, d), 0) or 0) for d in datos.dias]) for t in datos.turnos}


def guardar_plazas_db(ruta: str, datos: Datos, cambios: Iterable[dict]) -> dict:
    """Escribe plazas necesarias y máximas por (turno, día).

    cambios: [{"turno", "dia", "plazas": int>=0, "max": int|None}]. `max` vacío (o <= plazas)
    significa "el turno no acepta más que sus plazas ese día". Valida todo antes de escribir.
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
            limpios.append({"turno": turno, "dia": dia, "plazas": plazas, "max": tope if tope is not None and tope > plazas else None})
    if errores:
        raise ErrorPlazas(errores)
    if not limpios:
        return {"cambios": 0, "filas_añadidas": {}, "backup": None}

    antes = _filas_por_turno(datos, datos.plazas, datos.plazas_max)
    backup = hacer_copia_seguridad(ruta)
    con = abrir(ruta)
    try:
        with con:
            for c in limpios:
                con.execute(
                    "INSERT INTO plazas_dia (turno, dia, plazas, maximo) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(turno, dia) DO UPDATE SET plazas = excluded.plazas, maximo = excluded.maximo",
                    (c["turno"], c["dia"], c["plazas"], c["max"]))
            if any(c["max"] is not None for c in limpios):
                # Los extras cuestan algo al optimizar: se asegura que el peso exista en CONFIG.
                con.execute("INSERT OR IGNORE INTO config (clave, valor, descripcion) VALUES ('W_EXTRA', '40', "
                            "'Peso: cada persona que un turno acepta por encima de sus plazas')")
    finally:
        con.close()

    plazas = dict(datos.plazas)
    maximos = dict(datos.plazas_max)
    for c in limpios:
        plazas[(c["turno"], c["dia"])] = c["plazas"]
        if c["max"] is None:
            maximos.pop((c["turno"], c["dia"]), None)
        else:
            maximos[(c["turno"], c["dia"])] = c["max"]
    despues = _filas_por_turno(datos, plazas, maximos)
    añadidas = {t: despues[t] - antes[t] for t in despues if despues[t] > antes[t]}
    return {"cambios": len(limpios), "filas_añadidas": añadidas, "backup": backup}
