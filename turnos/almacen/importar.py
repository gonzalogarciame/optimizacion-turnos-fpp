"""Excel -> base de datos: pasa un libro de campamento a un fichero `.db`.

Se lee el libro con las mismas funciones de siempre (así se validan los datos y
se resuelven los apodos de la hoja ALIAS) y se copia el resultado a SQLite.
El libro no se modifica.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Dict, List

import openpyxl

from ..config import leer_config, normalizar_clave
from ..io_excel.lector import _texto, leer_datos
from ..io_excel.rejilla import leer_rejilla
from ..modelo.datos import NO_PRESENTE
from ..modelo.errores import ErrorDatos
from ..nombres import ResolverNombres
from .esquema import abrir


def _valor_texto(valor) -> str:
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def _notas_por_clave(ws, col_clave: str, col_notas: str = "NOTAS") -> Dict[str, str]:
    """{valor de la columna clave: texto de NOTAS} de una hoja con cabecera en la fila 1."""
    cab = {_texto(c.value).upper(): i + 1 for i, c in enumerate(ws[1])}
    if col_clave not in cab or col_notas not in cab:
        return {}
    return {
        _texto(ws.cell(f, cab[col_clave]).value): _texto(ws.cell(f, cab[col_notas]).value)
        for f in range(2, ws.max_row + 1)
        if _texto(ws.cell(f, cab[col_clave]).value)
    }


def importar_excel(ruta_xlsx: str, ruta_db: str, sobrescribir: bool = False) -> Dict[str, int]:
    """Crea `ruta_db` con el contenido del libro. Devuelve un resumen con los recuentos."""
    destino = Path(ruta_db)
    if destino.exists():
        if not sobrescribir:
            raise FileExistsError(f"Ya existe '{ruta_db}'. Usa sobrescribir para reemplazarla.")
    wb = openpyxl.load_workbook(ruta_xlsx, data_only=False)

    cfg_excel = leer_config(wb["CONFIG"])  # valida CONFIG y comprueba DIA_REOPTIMIZACION
    # Se lee todo el horizonte como "nada es histórico": así no se exige que el pasado esté completo.
    datos = leer_datos(ruta_xlsx, desde=cfg_excel.dia_inicio)
    rejilla = leer_rejilla(ruta_xlsx, datos)

    alias_pares: List[tuple] = []
    ws_alias = wb["ALIAS"]
    for f in range(2, ws_alias.max_row + 1):
        variante, canonico = _texto(ws_alias.cell(f, 1).value), _texto(ws_alias.cell(f, 2).value)
        if variante and canonico:
            alias_pares.append((variante, canonico))
    resolver = ResolverNombres.construir(datos.monitores.keys(), alias_pares)

    notas_turnos = _notas_por_clave(wb["TIPOS_TURNO"], "TURNO")
    notas_dep = _notas_por_clave(wb["DEPENDIENTES"], "ACAMPADO")

    # Se escribe en un fichero temporal y se renombra al final: un fallo no deja una base a medias.
    temporal = destino.with_name(destino.name + ".tmp")
    if temporal.exists():
        temporal.unlink()
    con = abrir(str(temporal), crear=True)
    try:
        with con:
            # CONFIG: tal cual está en el libro (con su descripción)
            ws = wb["CONFIG"]
            for f in range(2, ws.max_row + 1):
                clave, valor = ws.cell(f, 1).value, ws.cell(f, 2).value
                if clave is None or str(clave).strip() == "" or valor is None:
                    continue
                con.execute(
                    "INSERT OR REPLACE INTO config (clave, valor, descripcion) VALUES (?, ?, ?)",
                    (normalizar_clave(clave), _valor_texto(valor), _texto(ws.cell(f, 3).value)),
                )

            con.executemany(
                "INSERT INTO monitores (orden, nombre, sexo, grupo, permite_descanso, penalizar_descanso, dependiente_1, dependiente_2) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(i, m.nombre, m.sexo, m.grupo, int(m.permite_descanso), int(m.penalizar_descanso), m.dependiente_1, m.dependiente_2)
                 for i, m in enumerate(datos.monitores.values())],
            )
            for variante, canonico in alias_pares:
                con.execute(
                    "INSERT OR REPLACE INTO alias (variante, canonico) VALUES (?, ?)",
                    (variante, resolver.resolver_opcional(canonico) or canonico),
                )
            con.executemany(
                "INSERT INTO disponibilidad (monitor, dia, codigo) VALUES (?, ?, ?)",
                [(m, d, c) for (m, d), c in datos.disponibilidad.items()],
            )

            con.executemany(
                "INSERT INTO tipos_turno (orden, turno, plazas, sexo_req, esfuerzo, notas) VALUES (?, ?, ?, ?, ?, ?)",
                [(i, t.turno, t.plazas_default, t.sexo_req, t.esfuerzo, notas_turnos.get(t.turno, ""))
                 for i, t in enumerate(datos.turnos.values())],
            )
            con.executemany(
                "INSERT INTO plazas_dia (turno, dia, plazas, maximo) VALUES (?, ?, ?, ?)",
                [(t, d, datos.plazas[(t, d)], datos.plazas_max.get((t, d))) for t in datos.turnos for d in datos.dias],
            )

            con.executemany(
                "INSERT INTO dependientes (orden, acampado, sexo_monitor_req, esfuerzo, notas) VALUES (?, ?, ?, ?, ?)",
                [(i, p.acampado, p.sexo_monitor_req, p.esfuerzo, notas_dep.get(p.acampado, ""))
                 for i, p in enumerate(sorted(datos.dependientes.values(), key=lambda p: p.fila))],
            )
            con.executemany(
                "INSERT INTO dependiente_ausente (acampado, dia) VALUES (?, ?)",
                [(a, d) for (a, d), v in datos.asig_dependiente.items() if v is NO_PRESENTE],
            )

            # La rejilla: una fila por casilla ocupada (el amarillo pasa a `fijada`)
            filas = []
            for sec in rejilla["secciones"]:
                tipo = sec["tipo"]
                for pos, fila in enumerate(sec["filas"]):
                    for dia, c in fila["celdas"].items():
                        nombre = c.get("v")
                        if not nombre or nombre == "-":
                            continue
                        if c.get("u") or nombre not in datos.monitores:
                            raise ErrorDatos(f"TURNOS: '{nombre}' (día {dia}) no es un monitor conocido")
                        clave = sec["titulo"] if tipo == "turno" else fila["etiqueta"] if tipo == "dependiente" else ""
                        filas.append((tipo, clave, int(dia), pos, nombre, int(bool(c.get("f")) and tipo != "descanso")))
            con.executemany(
                "INSERT INTO asignaciones (tipo, clave, dia, pos, monitor, fijada) VALUES (?, ?, ?, ?, ?, ?)", filas
            )

            con.executemany(
                "INSERT INTO fijaciones (dia, turno, monitor, tipo, origen) VALUES (?, ?, ?, ?, ?)",
                [(f.dia, f.turno, f.monitor, f.tipo, f.origen) for f in datos.fijaciones if f.origen == "FIJACIONES"],
            )
            con.executemany(
                "INSERT INTO restricciones (orden, nombre, activa, tipo, descripcion) VALUES (?, ?, ?, ?, ?)",
                [(i, r.nombre, int(r.activa), r.tipo, r.descripcion) for i, r in enumerate(datos.restricciones.values())],
            )
            con.executemany(
                "INSERT OR REPLACE INTO meta (clave, valor) VALUES (?, ?)",
                [("origen_excel", str(Path(ruta_xlsx).name)), ("importado", _dt.datetime.now().isoformat(timespec="seconds"))],
            )

        resumen = {
            "monitores": len(datos.monitores),
            "dependientes": len(datos.dependientes),
            "turnos": len(datos.turnos),
            "dias": len(datos.dias),
            "asignaciones": len(filas),
            "fijaciones": sum(1 for f in datos.fijaciones if f.origen == "FIJACIONES"),
        }
    except BaseException:
        con.close()
        if temporal.exists():
            temporal.unlink()
        raise
    con.close()
    if destino.exists():
        destino.unlink()
    temporal.rename(destino)
    return resumen
