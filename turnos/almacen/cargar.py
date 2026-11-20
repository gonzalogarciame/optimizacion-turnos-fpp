"""Base de datos -> `Datos`.

Hace lo mismo que `io_excel.lector.leer_datos`, pero leyendo de SQLite. El
modelo y el optimizador no notan la diferencia: reciben el mismo `Datos`.

Reglas sobre la rejilla (`asignaciones`), iguales a las del Excel:

* Los días anteriores a DIA_REOPTIMIZACION son historia: todo lo que hay
  escrito se fija tal cual (turnos, descansos y quién lleva a cada dependiente).
* En los días a regenerar solo cuentan las casillas fijadas (`fijada = 1`):
  el optimizador las respeta. Lo demás es la propuesta de la última
  generación y se vuelve a decidir.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..config import ajustar_horizonte, config_desde_pares, normalizar_clave
from ..modelo.datos import (
    NO_PRESENTE,
    POR_DECIDIR,
    Datos,
    Dependiente,
    Fijacion,
    Monitor,
    RestriccionInfo,
    TipoTurno,
)
from ..modelo.derivados import (
    calcular_dias_presente,
    calcular_finde_forzar_blanda,
    calcular_plazas_tope,
    validar_historico_completo,
)
from ..modelo.errores import ErrorDatos
from .esquema import abrir


def leer_datos_db(ruta: str, desde: int = None, hasta: int = None) -> Datos:
    """`desde` = primer día a generar (DIA_REOPTIMIZACION); `hasta` recorta el horizonte."""
    con = abrir(ruta)
    try:
        return _leer(con, desde, hasta)
    finally:
        con.close()


def _leer(con, desde: Optional[int], hasta: Optional[int]) -> Datos:
    pares = {normalizar_clave(r["clave"]): r["valor"] for r in con.execute("SELECT clave, valor FROM config")}
    cfg = ajustar_horizonte(config_desde_pares(pares), desde, hasta)
    dias = cfg.dias
    dia_reopt = cfg.dia_reoptimizacion

    # --- Monitores y disponibilidad --------------------------------------
    monitores: Dict[str, Monitor] = {}
    for r in con.execute("SELECT * FROM monitores ORDER BY orden"):
        monitores[r["nombre"]] = Monitor(
            nombre=r["nombre"],
            sexo=r["sexo"],
            grupo=r["grupo"],
            permite_descanso=bool(r["permite_descanso"]),
            penalizar_descanso=bool(r["penalizar_descanso"]),
            dependiente_1=r["dependiente_1"] or None,
            dependiente_2=r["dependiente_2"] or None,
        )
    # Un campamento recién creado en blanco aún no tiene monitores: validar_previa avisa de ello.

    disponibilidad: Dict[Tuple[str, int], str] = {
        (r["monitor"], r["dia"]): r["codigo"]
        for r in con.execute("SELECT monitor, dia, codigo FROM disponibilidad WHERE dia BETWEEN ? AND ?", (dias[0], dias[-1]))
    }
    faltan = [(m, d) for m in monitores for d in dias if (m, d) not in disponibilidad]
    if faltan:
        m, d = faltan[0]
        raise ErrorDatos(
            f"DISPONIBILIDAD: falta el dato de '{m}' el día {d}; {len(faltan)} casillas sin dato en total"
        )

    # --- Turnos y plazas --------------------------------------------------
    turnos: Dict[str, TipoTurno] = {}
    orden_turno: Dict[str, int] = {}
    for r in con.execute("SELECT * FROM tipos_turno ORDER BY orden"):
        turnos[r["turno"]] = TipoTurno(
            turno=r["turno"],
            plazas_default=int(r["plazas"]),
            sexo_req=r["sexo_req"],
            esfuerzo=float(r["esfuerzo"]),
            fila_ini=None,
            fila_fin=None,
        )
        orden_turno[r["turno"]] = r["orden"]

    filas_plazas = {(r["turno"], r["dia"]): r for r in con.execute("SELECT turno, dia, plazas, maximo FROM plazas_dia")}
    plazas: Dict[Tuple[str, int], int] = {}
    plazas_max: Dict[Tuple[str, int], int] = {}
    for turno, tt in turnos.items():
        for dia in dias:
            fila = filas_plazas.get((turno, dia))
            plazas[(turno, dia)] = int(fila["plazas"]) if fila is not None else tt.plazas_default
            if fila is not None and fila["maximo"] is not None and fila["maximo"] > plazas[(turno, dia)]:
                plazas_max[(turno, dia)] = int(fila["maximo"])

    # --- Dependientes -----------------------------------------------------
    dependientes: Dict[str, Dependiente] = {}
    for r in con.execute("SELECT * FROM dependientes ORDER BY orden"):
        dependientes[r["acampado"]] = Dependiente(
            acampado=r["acampado"],
            sexo_monitor_req=r["sexo_monitor_req"],
            esfuerzo=float(r["esfuerzo"]),
            fila=int(r["orden"]),
        )
    # Puede no haber dependientes (un campamento sin acampados que atender).
    ausentes = {(r["acampado"], r["dia"]) for r in con.execute("SELECT acampado, dia FROM dependiente_ausente")}

    # --- La rejilla -------------------------------------------------------
    cuida: Dict[Tuple[str, int], Tuple[str, bool]] = {}
    historico_x: Dict[Tuple[str, str, int], int] = {}
    historico_r: Dict[Tuple[str, int], int] = {}
    amarillas: List[Tuple[int, int, int, Fijacion]] = []
    for r in con.execute(
        "SELECT tipo, clave, dia, pos, monitor, fijada FROM asignaciones WHERE dia BETWEEN ? AND ?",
        (dias[0], dias[-1]),
    ):
        tipo, clave, dia = r["tipo"], r["clave"], r["dia"]
        if tipo == "dependiente":
            cuida[(clave, dia)] = (r["monitor"], bool(r["fijada"]))
        elif tipo == "descanso":
            if dia < dia_reopt:
                historico_r[(r["monitor"], dia)] = 1
        else:
            if clave not in turnos:
                raise ErrorDatos(f"asignaciones: el turno '{clave}' (día {dia}) no existe en los tipos de turno")
            if dia < dia_reopt:
                historico_x[(r["monitor"], clave, dia)] = 1
            elif r["fijada"]:
                amarillas.append((orden_turno[clave], r["pos"], dia, Fijacion(
                    dia=dia, turno=clave, monitor=r["monitor"], tipo="OBLIGA", origen="TURNOS(amarillo)")))

    asig_dependiente: Dict[Tuple[str, int], Optional[str]] = {}
    for acampado in dependientes:
        for dia in dias:
            if (acampado, dia) in ausentes:
                asig_dependiente[(acampado, dia)] = NO_PRESENTE
            elif (acampado, dia) in cuida and (cuida[(acampado, dia)][1] or dia < dia_reopt):
                asig_dependiente[(acampado, dia)] = cuida[(acampado, dia)][0]
            else:
                asig_dependiente[(acampado, dia)] = POR_DECIDIR

    # --- Fijaciones -------------------------------------------------------
    fijaciones: List[Fijacion] = []
    for r in con.execute("SELECT dia, turno, monitor, tipo, origen FROM fijaciones ORDER BY id"):
        if r["dia"] < dias[0] or r["dia"] > dias[-1]:
            continue
        if r["turno"] not in turnos:
            raise ErrorDatos(f"FIJACIONES: el turno '{r['turno']}' no existe")
        fijaciones.append(Fijacion(dia=r["dia"], turno=r["turno"], monitor=r["monitor"], tipo=r["tipo"], origen=r["origen"]))
    fijaciones += [f for _, _, _, f in sorted(amarillas, key=lambda a: a[:3])]

    # --- Restricciones ----------------------------------------------------
    restricciones: Dict[str, RestriccionInfo] = {
        r["nombre"]: RestriccionInfo(nombre=r["nombre"], activa=bool(r["activa"]), tipo=r["tipo"].upper(), descripcion=r["descripcion"])
        for r in con.execute("SELECT * FROM restricciones ORDER BY orden")
    }

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
        dias_presente=calcular_dias_presente(disponibilidad, monitores, dias),
        restricciones=restricciones,
        avisos=[],
        plazas_max=plazas_max,
        plazas_tope=calcular_plazas_tope(plazas, historico_x, fijaciones),
    )
    validar_historico_completo(datos)
    calcular_finde_forzar_blanda(datos)
    return datos
