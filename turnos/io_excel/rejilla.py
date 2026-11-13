"""Lectura y escritura "cruda" de la rejilla `TURNOS` (para la interfaz web).

`lector.py` convierte la rejilla en datos para el modelo (solo los días
históricos y las celdas amarillas). Aquí se hace otra cosa: devolver la
rejilla **tal cual está escrita** (cualquier día, tenga o no solución) para
poder mostrarla y editarla celda a celda, y escribir solo las celdas que el
usuario ha cambiado.

Una celda se identifica por (tipo, fila de la hoja TURNOS, día):

- `turno`: una plaza de un turno de trabajo (filas `FILA_INI..FILA_FIN`).
- `dependiente`: el monitor que atiende a un acampado ese día. La fuente de
  verdad del modelo es `ASIG_DEPENDIENTE`; `TURNOS` es su reflejo visual, así
  que al editar se escriben las dos hojas.
- `descanso`: lista de monitores que descansan ese día.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List

import openpyxl

from ..modelo.datos import NO_PRESENTE, POR_DECIDIR, Datos
from ..nombres import ErrorNombreNoReconocido, ResolverNombres, normalizar
from .escritor import AMARILLO, SIN_RELLENO, _mapa_dias_por_columna, hacer_copia_seguridad
from .lector import _es_amarillo, _texto

NO_PRESENTE_TXT = "-"
_DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
_FILAS_LIBRES_DESCANSO = 3


class ErrorEdicionRejilla(Exception):
    """Cambios inválidos: no se ha escrito nada. `errores` lista cada causa."""

    def __init__(self, errores: List[str]):
        self.errores = errores
        super().__init__("; ".join(errores))


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def _leer_alias(wb) -> List[tuple]:
    if "ALIAS" not in wb.sheetnames:
        return []
    ws = wb["ALIAS"]
    pares = []
    for fila in range(2, ws.max_row + 1):
        variante = _texto(ws.cell(fila, 1).value)
        canonico = _texto(ws.cell(fila, 2).value)
        if variante and canonico:
            pares.append((variante, canonico))
    return pares


def _fila_etiqueta_descanso(ws) -> int:
    for fila in range(2, ws.max_row + 1):
        if _texto(ws.cell(fila, 1).value).upper() == "DESCANSO":
            return fila
    raise ValueError("TURNOS: no se encuentra la etiqueta 'DESCANSO' en la columna A")


def info_dias(datos: Datos) -> List[dict]:
    """Día del mes + día de la semana (para marcar fines de semana)."""
    salida = []
    for d in datos.dias:
        try:
            dow = _dt.date(datos.cfg.anio, datos.cfg.mes, d).weekday()
            salida.append({"dia": d, "semana": _DIAS_SEMANA[dow], "finde": dow >= 5,
                           "fecha": _dt.date(datos.cfg.anio, datos.cfg.mes, d).isoformat()})
        except ValueError:
            salida.append({"dia": d, "semana": "", "finde": False, "fecha": None})
    return salida


def _celda_trabajo(cell, resolver: ResolverNombres) -> dict:
    texto = _texto(cell.value)
    if not texto:
        return {"v": "", "f": False}
    try:
        nombre, desconocido = resolver.resolver(texto), False
    except ErrorNombreNoReconocido:
        nombre, desconocido = texto, True
    celda = {"v": nombre, "f": _es_amarillo(cell)}
    if desconocido:
        celda["u"] = True
    return celda


# ----------------------------------------------------------------------
# Lectura
# ----------------------------------------------------------------------
def leer_rejilla(ruta: str, datos: Datos) -> dict:
    """Devuelve la rejilla completa lista para serializar a JSON.

    {"secciones": [{"clave","tipo","titulo","sexo_req","plazas","filas":[
        {"fila": n, "etiqueta": str, "sexo_req": str, "celdas": {dia: {"v","f"[,"u"]}}}]}]}
    `v` es el nombre canónico del monitor ("" vacía, "-" acampado ausente).
    `f` indica celda fijada: el optimizador la respeta al regenerar.
    """
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["TURNOS"]
    pares_alias = _leer_alias(wb)
    resolver = ResolverNombres.construir(datos.monitores.keys(), pares_alias)
    mapa = _mapa_dias_por_columna(ws, 1, 2, ws.max_column)
    faltan = [d for d in datos.dias if d not in mapa]
    if faltan:
        raise ValueError(f"TURNOS: faltan columnas para los días {faltan}")

    # Apodos por monitor, para que el buscador de la pantalla los reconozca.
    alias: Dict[str, List[str]] = {}
    for variante, canonico in pares_alias:
        nombre = resolver.resolver_opcional(canonico) or canonico
        alias.setdefault(nombre, []).append(variante)

    secciones: List[dict] = []

    # --- Turnos de trabajo ---------------------------------------------
    turnos = sorted(
        (t for t in datos.turnos.values() if t.fila_ini is not None),
        key=lambda t: t.fila_ini,
    )
    for tt in turnos:
        filas = []
        for n, fila in enumerate(range(tt.fila_ini, tt.fila_fin + 1), start=1):
            filas.append({
                "fila": fila,
                "etiqueta": f"{tt.turno} {n}",
                "sexo_req": tt.sexo_req,
                "celdas": {str(d): _celda_trabajo(ws.cell(fila, mapa[d]), resolver) for d in datos.dias},
            })
        secciones.append({
            "clave": f"turno:{tt.turno}",
            "tipo": "turno",
            "titulo": tt.turno,
            "sexo_req": tt.sexo_req,
            "plazas": {str(d): int(datos.plazas.get((tt.turno, d), 0)) for d in datos.dias},
            # Lo que el turno acepta por encima de sus plazas (PLAZAS_MAX_POR_DIA), y el tope
            # real de cada día (incluye lo ya escrito a mano, que puede superar a lo declarado).
            "max": {str(d): datos.plazas_max.get((tt.turno, d)) for d in datos.dias},
            "tope": {str(d): int(datos.tope(tt.turno, d)) for d in datos.dias},
            "filas": filas,
        })

    # --- Dependientes ---------------------------------------------------
    filas_dep = []
    for dep in sorted(datos.dependientes.values(), key=lambda p: p.fila):
        celdas = {}
        for d in datos.dias:
            asignado = datos.asig_dependiente.get((dep.acampado, d), POR_DECIDIR)
            if asignado is NO_PRESENTE:
                celdas[str(d)] = {"v": NO_PRESENTE_TXT, "f": False}
            elif asignado != POR_DECIDIR:
                celdas[str(d)] = {"v": asignado, "f": True}
            else:
                # Sin fijar a mano: lo que haya en TURNOS es la propuesta de la última optimización.
                celda = _celda_trabajo(ws.cell(dep.fila, mapa[d]), resolver)
                celda["f"] = False
                celdas[str(d)] = celda
        filas_dep.append({
            "fila": dep.fila,
            "etiqueta": dep.acampado,
            "sexo_req": dep.sexo_monitor_req,
            "celdas": celdas,
        })
    secciones.append({
        "clave": "dependientes",
        "tipo": "dependiente",
        "titulo": "Dependientes",
        "sexo_req": "-",
        "plazas": {},
        "filas": filas_dep,
    })

    # --- Descanso -------------------------------------------------------
    fila_label = _fila_etiqueta_descanso(ws)
    ultima_usada = fila_label
    for fila in range(fila_label + 1, ws.max_row + 1):
        if any(_texto(ws.cell(fila, mapa[d]).value) for d in datos.dias):
            ultima_usada = fila
    fila_fin = min(ws.max_row, ultima_usada + _FILAS_LIBRES_DESCANSO)
    filas_desc = []
    for n, fila in enumerate(range(fila_label + 1, fila_fin + 1), start=1):
        filas_desc.append({
            "fila": fila,
            "etiqueta": f"descanso {n}",
            "sexo_req": "-",
            "celdas": {str(d): _celda_trabajo(ws.cell(fila, mapa[d]), resolver) for d in datos.dias},
        })
    secciones.append({
        "clave": "descanso",
        "tipo": "descanso",
        "titulo": "Descanso",
        "sexo_req": "-",
        "plazas": {},
        "filas": filas_desc,
    })

    return {"secciones": secciones, "alias": alias}


def descansos_asignados(ruta: str, datos: Datos) -> Dict[str, List[int]]:
    """Días de descanso que hay escritos en la sección DESCANSO de TURNOS, por monitor."""
    seccion = next((s for s in leer_rejilla(ruta, datos)["secciones"] if s["tipo"] == "descanso"), None)
    res: Dict[str, List[int]] = {}
    for fila in (seccion["filas"] if seccion else []):
        for dia, celda in fila["celdas"].items():
            nombre = celda.get("v")
            if nombre and nombre != "-":
                res.setdefault(nombre, []).append(int(dia))
    return {n: sorted(set(ds)) for n, ds in res.items()}


def asignaciones_trabajo(ruta: str, datos: Datos) -> Dict[str, Dict[str, str]]:
    """Turnos y dependientes escritos en TURNOS: {monitor: {dia: "turno" | "dependiente: X"}}."""
    res: Dict[str, Dict[str, str]] = {}
    for sec in leer_rejilla(ruta, datos)["secciones"]:
        if sec["tipo"] not in ("turno", "dependiente"):
            continue
        for fila in sec["filas"]:
            etiqueta = sec["titulo"] if sec["tipo"] == "turno" else f"dependiente {fila['etiqueta']}"
            for dia, celda in fila["celdas"].items():
                nombre = celda.get("v")
                if nombre and nombre != "-":
                    res.setdefault(nombre, {})[dia] = etiqueta
    return res


# ----------------------------------------------------------------------
# Escritura
# ----------------------------------------------------------------------
def _filas_validas(datos: Datos, ws) -> Dict[str, set]:
    turnos = set()
    for tt in datos.turnos.values():
        if tt.fila_ini is not None:
            turnos.update(range(tt.fila_ini, tt.fila_fin + 1))
    dependientes = {dep.fila: dep.acampado for dep in datos.dependientes.values()}
    fila_label = _fila_etiqueta_descanso(ws)
    return {
        "turno": turnos,
        "dependiente": set(dependientes),
        "descanso": set(range(fila_label + 1, ws.max_row + 1)),
        "_acampado": dependientes,
    }


def _normalizar_cambios(datos: Datos, ws, cambios: List[dict], resolver: ResolverNombres) -> List[dict]:
    validas = _filas_validas(datos, ws)
    errores: List[str] = []
    limpios: List[dict] = []
    for c in cambios:
        tipo = c.get("tipo")
        try:
            fila, dia = int(c.get("fila")), int(c.get("dia"))
        except (TypeError, ValueError):
            errores.append(f"Cambio mal formado: {c}")
            continue
        if tipo not in ("turno", "dependiente", "descanso") or fila not in validas[tipo]:
            errores.append(f"Fila {fila} no es una fila de '{tipo}' de la hoja TURNOS")
            continue
        if dia not in datos.dias:
            errores.append(f"Día {dia} fuera del horizonte {datos.dias[0]}–{datos.dias[-1]}")
            continue
        valor = _texto(c.get("valor"))
        if valor == NO_PRESENTE_TXT:
            if tipo != "dependiente":
                errores.append(f"Día {dia}, fila {fila}: '-' solo vale para dependientes")
                continue
        elif valor:
            try:
                valor = resolver.resolver(valor)
            except ErrorNombreNoReconocido:
                errores.append(f"Día {dia}: '{valor}' no es un monitor conocido")
                continue
            if valor not in datos.monitores:
                errores.append(f"Día {dia}: '{valor}' no está en MONITORES")
                continue
        limpios.append({
            "tipo": tipo, "fila": fila, "dia": dia, "valor": valor,
            "fijado": bool(c.get("fijado")) and valor not in ("", NO_PRESENTE_TXT),
        })
    if errores:
        raise ErrorEdicionRejilla(errores)
    return limpios


def guardar_cambios_rejilla(ruta: str, datos: Datos, cambios: List[dict]) -> dict:
    """Escribe solo las celdas cambiadas en `TURNOS` (y `ASIG_DEPENDIENTE`).

    Valida todo antes de tocar el fichero y hace antes una copia de
    seguridad con marca de tiempo. Devuelve {"escritas": n, "backup": ruta}.
    """
    wb = openpyxl.load_workbook(ruta, data_only=False)
    ws = wb["TURNOS"]
    resolver = ResolverNombres.construir(datos.monitores.keys(), _leer_alias(wb))
    limpios = _normalizar_cambios(datos, ws, cambios, resolver)
    if not limpios:
        return {"escritas": 0, "backup": None}

    mapa = _mapa_dias_por_columna(ws, 1, 2, ws.max_column)
    acampado_de_fila = {dep.fila: dep.acampado for dep in datos.dependientes.values()}

    ws_asig = wb["ASIG_DEPENDIENTE"]
    mapa_asig = _mapa_dias_por_columna(ws_asig, 1, 2, ws_asig.max_column)
    fila_asig: Dict[str, int] = {}
    for fila in range(2, ws_asig.max_row + 1):
        nombre = _texto(ws_asig.cell(fila, 1).value)
        if nombre:
            fila_asig[normalizar(nombre)] = fila

    for c in limpios:
        celda = ws.cell(c["fila"], mapa[c["dia"]])
        valor = c["valor"]
        if c["tipo"] == "dependiente":
            acampado = acampado_de_fila[c["fila"]]
            fila_a = fila_asig.get(normalizar(acampado))
            if fila_a is None or c["dia"] not in mapa_asig:
                raise ErrorEdicionRejilla([f"ASIG_DEPENDIENTE: no se encuentra a '{acampado}' el día {c['dia']}"])
            ws_asig.cell(fila_a, mapa_asig[c["dia"]]).value = valor or None
            celda.value = valor or None
            celda.fill = AMARILLO if valor not in ("", NO_PRESENTE_TXT) else SIN_RELLENO
        else:
            celda.value = valor or None
            if c["fijado"]:
                celda.fill = AMARILLO
            elif _es_amarillo(celda):
                celda.fill = SIN_RELLENO

    backup = hacer_copia_seguridad(ruta)
    wb.save(ruta)
    return {"escritas": len(limpios), "backup": backup}
