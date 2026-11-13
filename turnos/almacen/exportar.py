"""Base de datos -> libro de Excel (para compartir, imprimir o archivar).

El libro sale con el mismo diseño de siempre, así que `leer_datos` lo entiende y
`importar_excel` puede volver a convertirlo en una base de datos.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from ..config import config_desde_pares, normalizar_clave
from ..io_excel.escritor import AMARILLO
from ..modelo.datos import TURNO_DESCANSO
from .cargar import leer_datos_db
from .esquema import abrir
from .rejilla import leer_rejilla_db

_NEGRITA = Font(bold=True)


def _hoja(wb, nombre, cabecera, filas):
    ws = wb.create_sheet(nombre)
    ws.append(cabecera)
    for c in ws[1]:
        c.font = _NEGRITA
    for f in filas:
        ws.append(f)
    ws.column_dimensions["A"].width = 30
    return ws


def exportar_excel(ruta_db: str, ruta_xlsx: str) -> str:
    con = abrir(ruta_db)
    try:
        pares = {normalizar_clave(r["clave"]): r["valor"] for r in con.execute("SELECT clave, valor FROM config")}
        dia_reopt = config_desde_pares(pares).dia_reoptimizacion
        config = [(r["clave"], r["valor"], r["descripcion"]) for r in con.execute("SELECT * FROM config")]
        monitores = con.execute("SELECT * FROM monitores ORDER BY orden").fetchall()
        alias = [(r["variante"], r["canonico"]) for r in con.execute("SELECT variante, canonico FROM alias ORDER BY variante")]
        disp = {(r["monitor"], r["dia"]): r["codigo"] for r in con.execute("SELECT monitor, dia, codigo FROM disponibilidad")}
        tipos = con.execute("SELECT * FROM tipos_turno ORDER BY orden").fetchall()
        plazas = {(r["turno"], r["dia"]): (r["plazas"], r["maximo"]) for r in con.execute("SELECT * FROM plazas_dia")}
        deps = con.execute("SELECT * FROM dependientes ORDER BY orden").fetchall()
        ausentes = {(r["acampado"], r["dia"]) for r in con.execute("SELECT acampado, dia FROM dependiente_ausente")}
        fijaciones = con.execute("SELECT dia, turno, monitor, tipo, origen FROM fijaciones ORDER BY id").fetchall()
        restricciones = con.execute("SELECT * FROM restricciones ORDER BY orden").fetchall()
    finally:
        con.close()
    datos = leer_datos_db(ruta_db, desde=config_desde_pares(pares).dia_inicio)
    dias = datos.dias
    rejilla = leer_rejilla_db(ruta_db, datos)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _hoja(wb, "CONFIG", ["CLAVE", "VALOR", "DESCRIPCIÓN"], [[c, _numero(v), d] for c, v, d in config])
    _hoja(wb, "MONITORES",
          ["NOMBRE", "SEXO", "GRUPO", "PERMITE_DESCANSO", "PENALIZAR_DESCANSO", "DEPENDIENTE_1", "DEPENDIENTE_2"],
          [[m["nombre"], m["sexo"], m["grupo"], m["permite_descanso"], m["penalizar_descanso"], m["dependiente_1"], m["dependiente_2"]]
           for m in monitores])
    _hoja(wb, "DISPONIBILIDAD", ["NOMBRE", *dias], [[m["nombre"], *[disp[(m["nombre"], d)] for d in dias]] for m in monitores])

    # --- TURNOS (la rejilla) y las filas que ocupa cada bloque
    ws = wb.create_sheet("TURNOS")
    ws.append(["TURNOS", *[f"DIA {d}" for d in dias]])
    for c in ws[1]:
        c.font = _NEGRITA
    ws.column_dimensions["A"].width = 30
    fila_actual = 2
    filas_turno, fila_dep = {}, {}
    for sec in rejilla["secciones"]:
        if sec["tipo"] == "turno":
            ini = fila_actual
            for i, fila in enumerate(sec["filas"]):
                _escribir_fila(ws, fila_actual, sec["titulo"] if i == 0 else None, fila, dias)
                fila_actual += 1
            filas_turno[sec["titulo"]] = (ini, fila_actual - 1)
        elif sec["tipo"] == "dependiente":
            for fila in sec["filas"]:
                _escribir_fila(ws, fila_actual, fila["etiqueta"], fila, dias)
                fila_dep[fila["etiqueta"]] = fila_actual
                fila_actual += 1
        else:
            fila_actual += 1  # fila en blanco antes de DESCANSO
            ws.cell(fila_actual, 1).value = "DESCANSO"
            ws.cell(fila_actual, 1).font = _NEGRITA
            fila_actual += 1
            for fila in sec["filas"]:
                _escribir_fila(ws, fila_actual, None, fila, dias)
                fila_actual += 1

    _hoja(wb, "TIPOS_TURNO", ["TURNO", "PLAZAS", "SEXO_REQ", "ESFUERZO", "FILA_INI", "FILA_FIN", "NOTAS"],
          [[t["turno"], t["plazas"], t["sexo_req"], t["esfuerzo"], *filas_turno[t["turno"]], t["notas"]] for t in tipos]
          + [[TURNO_DESCANSO, 0, "-", 0, None, None, "No es un turno de trabajo."]])
    _hoja(wb, "PLAZAS_POR_DIA", ["TURNO", *dias],
          [[t["turno"], *[plazas.get((t["turno"], d), (t["plazas"], None))[0] for d in dias]] for t in tipos])
    if any(m is not None for _, m in plazas.values()):
        _hoja(wb, "PLAZAS_MAX_POR_DIA", ["TURNO", *dias],
              [[t["turno"], *[plazas.get((t["turno"], d), (0, None))[1] for d in dias]] for t in tipos])
    _hoja(wb, "DEPENDIENTES", ["ACAMPADO", "SEXO_MONITOR_REQ", "ESFUERZO", "FILA", "NOTAS"],
          [[p["acampado"], p["sexo_monitor_req"], p["esfuerzo"], fila_dep[p["acampado"]], p["notas"]] for p in deps])

    asig = wb.create_sheet("ASIG_DEPENDIENTE")
    asig.append(["ACAMPADO", *dias])
    for c in asig[1]:
        c.font = _NEGRITA
    asig.column_dimensions["A"].width = 30
    celdas_dep = {f["etiqueta"]: f["celdas"] for s in rejilla["secciones"] if s["tipo"] == "dependiente" for f in s["filas"]}
    for p in deps:
        fila = [p["acampado"]]
        for d in dias:
            c = celdas_dep[p["acampado"]][str(d)]
            if (p["acampado"], d) in ausentes:
                fila.append("-")
            elif c["v"] and c["v"] != "-" and (c["f"] or d < dia_reopt):
                fila.append(c["v"])  # lo fijado y todo el pasado cuentan como asignado
            else:
                fila.append(None)
        asig.append(fila)
        for j, v in enumerate(fila[1:], start=2):
            if v and v != "-":
                asig.cell(asig.max_row, j).fill = AMARILLO

    _hoja(wb, "FIJACIONES", ["DIA", "TURNO", "NOMBRE", "TIPO", "ORIGEN"],
          [[f["dia"], f["turno"], f["monitor"], f["tipo"], f["origen"]] for f in fijaciones])
    _hoja(wb, "RESTRICCIONES", ["NOMBRE", "ACTIVA", "TIPO", "DESCRIPCIÓN"],
          [[r["nombre"], r["activa"], r["tipo"], r["descripcion"]] for r in restricciones])
    _hoja(wb, "ALIAS", ["VARIANTE", "CANONICO"], alias)

    Path(ruta_xlsx).parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta_xlsx)
    return ruta_xlsx


def _numero(valor: str):
    """Los valores de CONFIG se guardan como texto: se devuelven como número cuando lo son."""
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return valor
    return int(f) if f.is_integer() and "." not in str(valor) else f


def _escribir_fila(ws, fila_xl: int, etiqueta, fila_rejilla: dict, dias) -> None:
    if etiqueta:
        ws.cell(fila_xl, 1).value = etiqueta
    for j, d in enumerate(dias, start=2):
        c = fila_rejilla["celdas"][str(d)]
        if c["v"]:
            ws.cell(fila_xl, j).value = c["v"]
            if c["f"] and c["v"] != "-":
                ws.cell(fila_xl, j).fill = AMARILLO
