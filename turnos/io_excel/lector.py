"""Excel -> objeto Datos, ya validado.

Este módulo es el único que sabe cómo está organizado el libro de turnos de
un campamento (ver README, "Estructura de datos"). Produce un objeto
`modelo.datos.Datos` que `modelo.construir` consume sin volver a tocar el
Excel.

Cualquier nombre de monitor que aparezca en la rejilla y no se reconozca ni
en `MONITORES` ni en `ALIAS` aborta la lectura con un error que indica la
celda exacta (no se ignora en silencio).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from ..config import leer_config, leer_pares_clave_valor
from ..nombres import ErrorNombreNoReconocido, ResolverNombres, normalizar
from ..modelo.datos import (
    AUSENTE,
    CODIGOS_DISPONIBILIDAD,
    Datos,
    Dependiente,
    Fijacion,
    Monitor,
    NO_PRESENTE,
    POR_DECIDIR,
    RestriccionInfo,
    TURNO_DESCANSO,
    TipoTurno,
)

# Colores de relleno que la hoja TURNOS usa para "celda fijada a mano"
# (amarillo). Si en el futuro el Excel usa un tono distinto, añádelo aquí.
RGB_AMARILLO = {"FFFFE599", "FFFFFF00", "FFFFF2CC", "FFFFD966", "00FFFF00"}


class ErrorLecturaExcel(Exception):
    """Error de validación al leer el Excel: incluye la celda si aplica."""


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _es_amarillo(cell) -> bool:
    fill = cell.fill
    if fill is None or fill.patternType != "solid":
        return False
    color = fill.fgColor
    if color is None:
        return False
    if getattr(color, "type", None) == "rgb" and color.rgb in RGB_AMARILLO:
        return True
    return False


def _mapa_dias_por_columna(ws: Worksheet, fila_cabecera: int, col_ini: int, col_fin: int) -> Dict[int, int]:
    """Lee la fila de cabecera y devuelve {día: nº de columna}.

    Admite cabeceras como '18', 18 o 'DIA 18'.
    """
    mapa: Dict[int, int] = {}
    for col in range(col_ini, col_fin + 1):
        valor = ws.cell(fila_cabecera, col).value
        if valor is None:
            continue
        if isinstance(valor, (int, float)):
            mapa[int(valor)] = col
            continue
        m = re.search(r"(\d+)", str(valor))
        if m:
            mapa[int(m.group(1))] = col
    return mapa


class LectorExcel:
    def __init__(self, ruta: str, desde: int = None):
        self.ruta = ruta
        self.desde = desde
        self.wb = openpyxl.load_workbook(ruta, data_only=False)
        self._avisos: List[str] = []

    # ------------------------------------------------------------------
    def leer(self) -> Datos:
        wb = self.wb

        cfg = leer_config(wb["CONFIG"])
        if self.desde is not None:
            from ..config import sobrescribir_dia_reoptimizacion

            cfg = sobrescribir_dia_reoptimizacion(cfg, self.desde)
        dias = cfg.dias

        alias_pares = self._leer_alias(wb["ALIAS"])
        monitores = self._leer_monitores(wb["MONITORES"])
        resolver = ResolverNombres.construir(monitores.keys(), alias_pares)

        disponibilidad = self._leer_disponibilidad(wb["DISPONIBILIDAD"], monitores, resolver, dias)
        tipos_turno_todos = self._leer_tipos_turno(wb["TIPOS_TURNO"])
        turnos = {k: v for k, v in tipos_turno_todos.items() if k != TURNO_DESCANSO}
        plazas = self._leer_plazas_por_dia(wb["PLAZAS_POR_DIA"], turnos, dias)
        plazas_max = self._leer_plazas_max(wb, turnos, plazas, dias)
        dependientes = self._leer_dependientes(wb["DEPENDIENTES"])
        asig_dependiente = self._leer_asig_dependiente(
            wb["ASIG_DEPENDIENTE"], dependientes, resolver, dias
        )
        fijaciones = self._leer_fijaciones(wb["FIJACIONES"], resolver, turnos)
        restricciones = self._leer_restricciones(wb["RESTRICCIONES"])

        historico_x, historico_r, fijaciones_amarillas = self._leer_turnos_grid(
            wb["TURNOS"], turnos, dependientes, resolver, dias, cfg.dia_reoptimizacion
        )
        fijaciones = fijaciones + fijaciones_amarillas
        plazas_tope = self._calcular_plazas_tope(plazas, historico_x, fijaciones)

        dias_presente = self._calcular_dias_presente(disponibilidad, monitores, dias)

        datos = Datos(
            cfg=cfg,
            dias=dias,
            monitores=monitores,
            turnos=turnos,
            dependientes=dependientes,
            disponibilidad=disponibilidad,
            plazas=plazas,
            asig_dependiente=asig_dependiente,
            fijaciones=fijaciones,
            historico_x=historico_x,
            historico_r=historico_r,
            dias_presente=dias_presente,
            restricciones=restricciones,
            avisos=self._avisos,
            plazas_max=plazas_max,
            plazas_tope=plazas_tope,
        )

        self._validar_historico_completo(datos)
        self._calcular_finde_forzar_blanda(datos)
        return datos

    # ------------------------------------------------------------------
    def _leer_alias(self, ws: Worksheet) -> List[Tuple[str, str]]:
        pares = []
        for fila in range(2, ws.max_row + 1):
            variante = _texto(ws.cell(fila, 1).value)
            canonico = _texto(ws.cell(fila, 2).value)
            if variante and canonico:
                pares.append((variante, canonico))
        return pares

    def _leer_monitores(self, ws: Worksheet) -> Dict[str, Monitor]:
        cab = {_texto(c.value).upper(): idx + 1 for idx, c in enumerate(ws[1])}
        requeridas = ["NOMBRE", "SEXO", "GRUPO", "PERMITE_DESCANSO", "PENALIZAR_DESCANSO"]
        faltan = [c for c in requeridas if c not in cab]
        if faltan:
            raise ErrorLecturaExcel(f"MONITORES: faltan columnas {faltan}")

        monitores: Dict[str, Monitor] = {}
        for fila in range(2, ws.max_row + 1):
            nombre = _texto(ws.cell(fila, cab["NOMBRE"]).value)
            if not nombre:
                continue
            sexo = _texto(ws.cell(fila, cab["SEXO"]).value).upper()
            if sexo not in ("M", "F"):
                raise ErrorLecturaExcel(f"MONITORES!{ws.cell(fila, cab['SEXO']).coordinate}: sexo '{sexo}' inválido (debe ser M o F)")
            grupo = _texto(ws.cell(fila, cab["GRUPO"]).value)
            permite = bool(int(ws.cell(fila, cab["PERMITE_DESCANSO"]).value or 0))
            penalizar = bool(int(ws.cell(fila, cab["PENALIZAR_DESCANSO"]).value or 0))
            dep1 = _texto(ws.cell(fila, cab.get("DEPENDIENTE_1", 0)).value) or None if "DEPENDIENTE_1" in cab else None
            dep2 = _texto(ws.cell(fila, cab.get("DEPENDIENTE_2", 0)).value) or None if "DEPENDIENTE_2" in cab else None
            if nombre in monitores:
                raise ErrorLecturaExcel(f"MONITORES!A{fila}: nombre '{nombre}' repetido")
            monitores[nombre] = Monitor(
                nombre=nombre,
                sexo=sexo,
                grupo=grupo,
                permite_descanso=permite,
                penalizar_descanso=penalizar,
                dependiente_1=dep1,
                dependiente_2=dep2,
            )
        if not monitores:
            raise ErrorLecturaExcel("MONITORES: no se ha leído ningún monitor")
        return monitores

    def _leer_disponibilidad(self, ws: Worksheet, monitores, resolver, dias) -> Dict[Tuple[str, int], str]:
        mapa_dias = _mapa_dias_por_columna(ws, 1, 2, ws.max_column)
        faltan = [d for d in dias if d not in mapa_dias]
        if faltan:
            raise ErrorLecturaExcel(f"DISPONIBILIDAD: faltan columnas para los días {faltan}")

        disponibilidad: Dict[Tuple[str, int], str] = {}
        for fila in range(2, ws.max_row + 1):
            nombre_crudo = ws.cell(fila, 1).value
            if _texto(nombre_crudo) == "":
                continue
            try:
                nombre = resolver.resolver(nombre_crudo, f"DISPONIBILIDAD!A{fila}")
            except ErrorNombreNoReconocido as exc:
                raise ErrorLecturaExcel(str(exc)) from exc
            if nombre not in monitores:
                raise ErrorLecturaExcel(
                    f"DISPONIBILIDAD!A{fila}: '{nombre_crudo}' no está en MONITORES"
                )
            for dia in dias:
                col = mapa_dias[dia]
                codigo = _texto(ws.cell(fila, col).value).upper()
                if codigo not in CODIGOS_DISPONIBILIDAD:
                    raise ErrorLecturaExcel(
                        f"DISPONIBILIDAD!{ws.cell(fila, col).coordinate}: código '{codigo}' inválido "
                        f"(debe ser D, X o R)"
                    )
                disponibilidad[(nombre, dia)] = codigo

        faltan_celdas = [
            (m, d) for m in monitores for d in dias if (m, d) not in disponibilidad
        ]
        if faltan_celdas:
            m, d = faltan_celdas[0]
            raise ErrorLecturaExcel(
                f"DISPONIBILIDAD: falta la fila de '{m}' (o el día {d}); "
                f"{len(faltan_celdas)} celdas sin dato en total"
            )
        return disponibilidad

    def _leer_tipos_turno(self, ws: Worksheet) -> Dict[str, TipoTurno]:
        cab = {_texto(c.value).upper(): idx + 1 for idx, c in enumerate(ws[1])}
        requeridas = ["TURNO", "PLAZAS", "SEXO_REQ", "ESFUERZO", "FILA_INI", "FILA_FIN"]
        faltan = [c for c in requeridas if c not in cab]
        if faltan:
            raise ErrorLecturaExcel(f"TIPOS_TURNO: faltan columnas {faltan}")

        tipos: Dict[str, TipoTurno] = {}
        for fila in range(2, ws.max_row + 1):
            turno = _texto(ws.cell(fila, cab["TURNO"]).value)
            plazas = ws.cell(fila, cab["PLAZAS"]).value
            if not turno or not isinstance(plazas, (int, float)):
                continue  # fila de nota al pie (texto largo en columna A, resto vacío)
            sexo_req = _texto(ws.cell(fila, cab["SEXO_REQ"]).value).upper() or "-"
            if sexo_req not in ("M", "F", "-"):
                raise ErrorLecturaExcel(f"TIPOS_TURNO!{ws.cell(fila, cab['SEXO_REQ']).coordinate}: SEXO_REQ '{sexo_req}' inválido")
            esfuerzo = ws.cell(fila, cab["ESFUERZO"]).value
            fila_ini = ws.cell(fila, cab["FILA_INI"]).value
            fila_fin = ws.cell(fila, cab["FILA_FIN"]).value
            tipos[turno] = TipoTurno(
                turno=turno,
                plazas_default=int(plazas or 0),
                sexo_req=sexo_req,
                esfuerzo=float(esfuerzo or 0),
                fila_ini=int(fila_ini) if fila_ini not in (None, "") else None,
                fila_fin=int(fila_fin) if fila_fin not in (None, "") else None,
            )
        if TURNO_DESCANSO not in tipos:
            raise ErrorLecturaExcel("TIPOS_TURNO: falta la fila 'descanso'")
        return tipos

    def _leer_plazas_por_dia(self, ws: Worksheet, turnos: Dict[str, TipoTurno], dias) -> Dict[Tuple[str, int], int]:
        mapa_dias = _mapa_dias_por_columna(ws, 1, 2, ws.max_column)
        faltan = [d for d in dias if d not in mapa_dias]
        if faltan:
            raise ErrorLecturaExcel(f"PLAZAS_POR_DIA: faltan columnas para los días {faltan}")

        plazas: Dict[Tuple[str, int], int] = {}
        turnos_vistos = set()
        for fila in range(2, ws.max_row + 1):
            turno = _texto(ws.cell(fila, 1).value)
            if not turno:
                continue
            if turno not in turnos:
                self._avisos.append(
                    f"PLAZAS_POR_DIA!A{fila}: turno '{turno}' no existe en TIPOS_TURNO; se ignora"
                )
                continue
            turnos_vistos.add(turno)
            for dia in dias:
                col = mapa_dias[dia]
                valor = ws.cell(fila, col).value
                plazas[(turno, dia)] = int(valor) if valor not in (None, "") else 0

        # Turnos sin fila en PLAZAS_POR_DIA: se usa el valor por defecto de TIPOS_TURNO.
        for turno, tt in turnos.items():
            if turno not in turnos_vistos:
                for dia in dias:
                    plazas[(turno, dia)] = tt.plazas_default
                self._avisos.append(
                    f"PLAZAS_POR_DIA: turno '{turno}' no tiene fila propia; "
                    f"se usan las {tt.plazas_default} plazas por defecto de TIPOS_TURNO todos los días"
                )
        return plazas

    def _leer_plazas_max(self, wb, turnos, plazas, dias) -> Dict[Tuple[str, int], int]:
        """Hoja opcional PLAZAS_MAX_POR_DIA: máximo de personas que acepta un turno un día.

        Misma disposición que PLAZAS_POR_DIA (turno en la columna A, un día por
        columna). Una celda vacía, o con un valor <= las plazas, significa "no
        acepta más gente de la necesaria". Si la hoja no existe, ningún turno
        acepta extras (comportamiento de siempre).
        """
        if "PLAZAS_MAX_POR_DIA" not in wb.sheetnames:
            return {}
        ws = wb["PLAZAS_MAX_POR_DIA"]
        mapa_dias = _mapa_dias_por_columna(ws, 1, 2, ws.max_column)
        maximos: Dict[Tuple[str, int], int] = {}
        for fila in range(2, ws.max_row + 1):
            turno = _texto(ws.cell(fila, 1).value)
            if not turno:
                continue
            if turno not in turnos:
                self._avisos.append(f"PLAZAS_MAX_POR_DIA!A{fila}: turno '{turno}' no existe en TIPOS_TURNO; se ignora")
                continue
            for dia in dias:
                col = mapa_dias.get(dia)
                valor = ws.cell(fila, col).value if col else None
                if valor in (None, ""):
                    continue
                try:
                    n = int(valor)
                except (TypeError, ValueError):
                    raise ErrorLecturaExcel(
                        f"PLAZAS_MAX_POR_DIA!{ws.cell(fila, col).coordinate}: '{valor}' no es un número de plazas"
                    )
                if n < 0:
                    raise ErrorLecturaExcel(f"PLAZAS_MAX_POR_DIA!{ws.cell(fila, col).coordinate}: no puede ser negativo")
                if n > plazas[(turno, dia)]:
                    maximos[(turno, dia)] = n
        return maximos

    @staticmethod
    def _calcular_plazas_tope(plazas, historico_x, fijaciones) -> Dict[Tuple[str, int], int]:
        """Días en que lo ya escrito (histórico o celdas fijadas) supera las plazas.

        Sin esto, una casilla de más en la rejilla haría infactible la igualdad de
        `cobertura`; así el turno simplemente acepta esa gente ese día.
        """
        escritos = set(historico_x)
        escritos |= {(f.monitor, f.turno, f.dia) for f in fijaciones if f.tipo == "OBLIGA"}
        cuenta: Dict[Tuple[str, int], int] = {}
        for (_, turno, dia) in escritos:
            cuenta[(turno, dia)] = cuenta.get((turno, dia), 0) + 1
        return {k: n for k, n in cuenta.items() if n > plazas.get(k, 0)}

    def _leer_dependientes(self, ws: Worksheet) -> Dict[str, Dependiente]:
        cab = {_texto(c.value).upper(): idx + 1 for idx, c in enumerate(ws[1])}
        requeridas = ["ACAMPADO", "SEXO_MONITOR_REQ", "ESFUERZO", "FILA"]
        faltan = [c for c in requeridas if c not in cab]
        if faltan:
            raise ErrorLecturaExcel(f"DEPENDIENTES: faltan columnas {faltan}")

        dependientes: Dict[str, Dependiente] = {}
        for fila in range(2, ws.max_row + 1):
            acampado = _texto(ws.cell(fila, cab["ACAMPADO"]).value)
            fila_grid_valor = ws.cell(fila, cab["FILA"]).value
            if not acampado or fila_grid_valor in (None, ""):
                # Filas de nota al pie de la hoja (texto en columna A sin FILA numérica).
                continue
            sexo_req = _texto(ws.cell(fila, cab["SEXO_MONITOR_REQ"]).value).upper() or "-"
            if sexo_req not in ("M", "F", "-"):
                raise ErrorLecturaExcel(
                    f"DEPENDIENTES!{ws.cell(fila, cab['SEXO_MONITOR_REQ']).coordinate}: "
                    f"SEXO_MONITOR_REQ '{sexo_req}' inválido"
                )
            esfuerzo = ws.cell(fila, cab["ESFUERZO"]).value
            fila_grid = ws.cell(fila, cab["FILA"]).value
            dependientes[acampado] = Dependiente(
                acampado=acampado,
                sexo_monitor_req=sexo_req,
                esfuerzo=float(esfuerzo or 0),
                fila=int(fila_grid),
            )
        if not dependientes:
            raise ErrorLecturaExcel("DEPENDIENTES: no se ha leído ningún dependiente")
        return dependientes

    def _leer_asig_dependiente(self, ws: Worksheet, dependientes, resolver, dias):
        mapa_dias = _mapa_dias_por_columna(ws, 1, 2, ws.max_column)
        faltan = [d for d in dias if d not in mapa_dias]
        if faltan:
            raise ErrorLecturaExcel(f"ASIG_DEPENDIENTE: faltan columnas para los días {faltan}")

        acampados_hoja = {}
        for fila in range(2, ws.max_row + 1):
            acampado = _texto(ws.cell(fila, 1).value)
            if acampado:
                acampados_hoja[normalizar(acampado)] = (acampado, fila)

        asig: Dict[Tuple[str, int], Optional[str]] = {}
        for acampado, dep in dependientes.items():
            clave = normalizar(acampado)
            if clave not in acampados_hoja:
                raise ErrorLecturaExcel(
                    f"ASIG_DEPENDIENTE: no se encuentra la fila del acampado '{acampado}' "
                    f"(sí está en DEPENDIENTES)"
                )
            _, fila = acampados_hoja[clave]
            for dia in dias:
                col = mapa_dias[dia]
                cell = ws.cell(fila, col)
                valor = _texto(cell.value)
                if valor == "" :
                    asig[(acampado, dia)] = POR_DECIDIR
                elif valor == "-":
                    asig[(acampado, dia)] = NO_PRESENTE
                else:
                    try:
                        asig[(acampado, dia)] = resolver.resolver(valor, f"ASIG_DEPENDIENTE!{cell.coordinate}")
                    except ErrorNombreNoReconocido as exc:
                        raise ErrorLecturaExcel(str(exc)) from exc
        return asig

    def _leer_fijaciones(self, ws: Worksheet, resolver, turnos) -> List[Fijacion]:
        cab = {_texto(c.value).upper(): idx + 1 for idx, c in enumerate(ws[1])}
        requeridas = ["DIA", "TURNO", "NOMBRE", "TIPO"]
        faltan = [c for c in requeridas if c not in cab]
        if faltan:
            raise ErrorLecturaExcel(f"FIJACIONES: faltan columnas {faltan}")

        fijaciones: List[Fijacion] = []
        for fila in range(2, ws.max_row + 1):
            dia_valor = ws.cell(fila, cab["DIA"]).value
            if not isinstance(dia_valor, (int, float)):
                continue  # fila de nota al pie u otra fila no numérica
            turno = _texto(ws.cell(fila, cab["TURNO"]).value)
            nombre_crudo = ws.cell(fila, cab["NOMBRE"]).value
            tipo = _texto(ws.cell(fila, cab["TIPO"]).value).upper()
            if tipo not in ("OBLIGA", "PROHIBE"):
                raise ErrorLecturaExcel(f"FIJACIONES!{ws.cell(fila, cab['TIPO']).coordinate}: TIPO '{tipo}' inválido")
            if turno not in turnos:
                raise ErrorLecturaExcel(f"FIJACIONES!{ws.cell(fila, cab['TURNO']).coordinate}: turno '{turno}' no existe")
            try:
                nombre = resolver.resolver(nombre_crudo, f"FIJACIONES!{ws.cell(fila, cab['NOMBRE']).coordinate}")
            except ErrorNombreNoReconocido as exc:
                raise ErrorLecturaExcel(str(exc)) from exc
            fijaciones.append(Fijacion(dia=int(dia_valor), turno=turno, monitor=nombre, tipo=tipo, origen="FIJACIONES"))
        return fijaciones

    def _leer_restricciones(self, ws: Worksheet) -> Dict[str, RestriccionInfo]:
        cab = {_texto(c.value).upper(): idx + 1 for idx, c in enumerate(ws[1])}
        requeridas = ["NOMBRE", "ACTIVA", "TIPO"]
        faltan = [c for c in requeridas if c not in cab]
        if faltan:
            raise ErrorLecturaExcel(f"RESTRICCIONES: faltan columnas {faltan}")
        col_desc = cab.get("DESCRIPCIÓN") or cab.get("DESCRIPCION")

        restricciones: Dict[str, RestriccionInfo] = {}
        for fila in range(2, ws.max_row + 1):
            nombre = _texto(ws.cell(fila, cab["NOMBRE"]).value)
            if not nombre:
                continue
            activa = bool(int(ws.cell(fila, cab["ACTIVA"]).value or 0))
            tipo = _texto(ws.cell(fila, cab["TIPO"]).value).upper()
            descripcion = _texto(ws.cell(fila, col_desc).value) if col_desc else ""
            restricciones[nombre] = RestriccionInfo(nombre=nombre, activa=activa, tipo=tipo, descripcion=descripcion)
        return restricciones

    # ------------------------------------------------------------------
    def _leer_turnos_grid(self, ws: Worksheet, turnos, dependientes, resolver, dias, dia_reopt):
        mapa_dias = _mapa_dias_por_columna(ws, 1, 2, ws.max_column)
        faltan = [d for d in dias if d not in mapa_dias]
        if faltan:
            raise ErrorLecturaExcel(f"TURNOS: faltan columnas para los días {faltan}")

        historico_x: Dict[Tuple[str, str, int], int] = {}
        historico_r: Dict[Tuple[str, int], int] = {}
        fijaciones_amarillas: List[Fijacion] = []

        # --- Bloques de turno de trabajo (filas 2..fila_fin del último turno) ---
        for turno, tt in turnos.items():
            if tt.fila_ini is None:
                continue
            for fila in range(tt.fila_ini, tt.fila_fin + 1):
                for dia in dias:
                    col = mapa_dias[dia]
                    cell = ws.cell(fila, col)
                    valor = _texto(cell.value)
                    if valor == "":
                        continue
                    try:
                        nombre = resolver.resolver(valor, f"TURNOS!{cell.coordinate}")
                    except ErrorNombreNoReconocido as exc:
                        raise ErrorLecturaExcel(str(exc)) from exc
                    if dia < dia_reopt:
                        historico_x[(nombre, turno, dia)] = 1
                    elif _es_amarillo(cell):
                        fijaciones_amarillas.append(
                            Fijacion(dia=dia, turno=turno, monitor=nombre, tipo="OBLIGA", origen="TURNOS(amarillo)")
                        )

        # --- Bloque DESCANSO ---
        fila_label = None
        for fila in range(2, ws.max_row + 1):
            if _texto(ws.cell(fila, 1).value).upper() == "DESCANSO":
                fila_label = fila
                break
        if fila_label is None:
            raise ErrorLecturaExcel("TURNOS: no se encuentra la etiqueta 'DESCANSO' en la columna A")

        for fila in range(fila_label + 1, ws.max_row + 1):
            for dia in dias:
                col = mapa_dias[dia]
                cell = ws.cell(fila, col)
                valor = _texto(cell.value)
                if valor == "":
                    continue
                try:
                    nombre = resolver.resolver(valor, f"TURNOS!{cell.coordinate}")
                except ErrorNombreNoReconocido as exc:
                    raise ErrorLecturaExcel(str(exc)) from exc
                if dia < dia_reopt:
                    historico_r[(nombre, dia)] = 1
                # Los descansos futuros no se leen: la lista de DESCANSO la
                # regenera siempre el sistema al escribir la solución.

        return historico_x, historico_r, fijaciones_amarillas

    # ------------------------------------------------------------------
    def _calcular_dias_presente(self, disponibilidad, monitores, dias) -> Dict[str, int]:
        return {
            m: sum(1 for d in dias if disponibilidad[(m, d)] in ("D", "R"))
            for m in monitores
        }

    def _validar_historico_completo(self, datos: Datos) -> None:
        """Cada monitor presente un día < D debe aparecer en x, r o y fijado.

        Si falta, la hoja TURNOS no se rellenó del todo para un día que se
        supone inmutable: abortamos con un mensaje claro en vez de fijar
        una variable a un valor desconocido.
        """
        dia_reopt = datos.cfg.dia_reoptimizacion
        # (monitor, dia) -> True si aparece en algún bloque de trabajo o descanso
        cubiertos = set()
        for (m, t, d) in datos.historico_x:
            cubiertos.add((m, d))
        for (m, d) in datos.historico_r:
            cubiertos.add((m, d))
        for (acampado, d), monitor in datos.asig_dependiente.items():
            if d < dia_reopt and monitor not in (None, "", NO_PRESENTE, POR_DECIDIR):
                cubiertos.add((monitor, d))

        incompletos = []
        for m in datos.monitores:
            for d in datos.dias:
                if d >= dia_reopt:
                    continue
                if datos.disponibilidad[(m, d)] in ("D", "R") and (m, d) not in cubiertos:
                    incompletos.append((m, d))
        if incompletos:
            m, d = incompletos[0]
            raise ErrorLecturaExcel(
                f"TURNOS: día histórico {d} (< DIA_REOPTIMIZACION={dia_reopt}) incompleto: "
                f"'{m}' está disponible ese día pero no aparece asignado a ningún turno, "
                f"dependiente ni descanso en la rejilla ({len(incompletos)} casos en total). "
                f"Corrige la rejilla o baja DIA_REOPTIMIZACION."
            )

        # Comprobar que ninguna celda de días < D fijada en dos sitios a la vez.
        for (acampado, d), monitor in datos.asig_dependiente.items():
            if d < dia_reopt and monitor not in (None, "", NO_PRESENTE, POR_DECIDIR):
                if (monitor, d) in datos.historico_r:
                    raise ErrorLecturaExcel(
                        f"TURNOS: '{monitor}' aparece a la vez como descanso y como "
                        f"monitor de '{acampado}' el día {d}"
                    )

    def _calcular_finde_forzar_blanda(self, datos: Datos) -> None:
        """Detecta si algún día no hay plazas para que TODO el grupo FINDE trabaje.

        Ver §5.1 'finde_sin_descanso' de las instrucciones: si la capacidad de
        turnos + dependientes de un día es menor que el número de monitores
        con PERMITE_DESCANSO=0 presentes ese día, la restricción "dura" haría
        el modelo infactible por construcción. En ese caso se degrada a
        blanda (penalización muy alta en vez de prohibición estructural).

        La capacidad "libre" descuenta los huecos que ya tienen dueño fijo
        ese día (una fijación OBLIGA de FIJACIONES/celda amarilla, o un
        cuidador ya escrito en ASIG_DEPENDIENTE): esos huecos no están
        disponibles para nadie más, y si el propio monitor forzado ya tiene
        sitio asegurado ahí, tampoco cuenta como alguien "sin sitio". Sin
        este descuento, una quincena con muchas fijaciones manuales en un
        día concreto podría parecer que sobra capacidad cuando en realidad
        ya está toda repartida (fue precisamente lo que pasó al fijar a
        mano el día 18 completo: 16 turnos + 17 dependientes ya ocupados no
        dejaban sitio para 7 monitoras de FINDE adicionales presentes ese
        día).
        """
        for dia in datos.dias:
            # Con PLAZAS_MAX_POR_DIA los turnos admiten gente de más: ese es el sitio
            # que tienen los monitores de fin de semana para no descansar.
            capacidad_total = sum(datos.tope(t, dia) for t in datos.turnos)
            capacidad_total += sum(
                1
                for (acampado, d), v in datos.asig_dependiente.items()
                if d == dia and v is not NO_PRESENTE
            )

            ya_con_sitio = {
                f.monitor for f in datos.fijaciones if f.dia == dia and f.tipo == "OBLIGA"
            }
            ya_con_sitio |= {
                v
                for (acampado, d), v in datos.asig_dependiente.items()
                if d == dia and v not in (NO_PRESENTE, POR_DECIDIR)
            }

            capacidad_libre = capacidad_total - len(ya_con_sitio)

            forzados_sin_sitio = [
                m
                for m, mon in datos.monitores.items()
                if not mon.permite_descanso
                and datos.disponibilidad[(m, dia)] in ("D", "R")
                and m not in ya_con_sitio
            ]

            if len(forzados_sin_sitio) > capacidad_libre:
                datos.finde_forzar_blanda = True
                datos.avisos.append(
                    f"Día {dia}: {len(forzados_sin_sitio)} monitores de fin de semana sin "
                    f"PERMITE_DESCANSO obligados a trabajar ({', '.join(forzados_sin_sitio)}) "
                    f"pero solo quedan {capacidad_libre} plazas libres tras las fijaciones ya "
                    f"hechas ese día; 'finde_sin_descanso' se degrada a blanda para ellos."
                )


def leer_datos(ruta: str, desde: int = None) -> Datos:
    return LectorExcel(ruta, desde=desde).leer()
