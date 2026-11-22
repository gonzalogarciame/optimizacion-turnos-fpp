"""Datos derivados de `Datos` y comprobaciones de coherencia.

Son los mismos sea cual sea la fuente (Excel o base de datos): primero la
fuente rellena lo que lee tal cual, y después se llama a estas funciones.
"""
from __future__ import annotations

import math
from typing import Dict, Tuple

from .datos import NO_PRESENTE, POR_DECIDIR, Datos
from .errores import ErrorDatos


def calcular_dias_presente(disponibilidad, monitores, dias) -> Dict[str, int]:
    return {
        m: sum(1 for d in dias if disponibilidad[(m, d)] in ("D", "R"))
        for m in monitores
    }


def limites_descanso(dias_presente: int, min_pct: float, max_pct: float, estricto: bool = True) -> Tuple[int, int]:
    """(mínimo, máximo) de días de descanso de un monitor que está `dias_presente` días.

    Estricto (el campamento entero): se redondea hacia dentro para que el porcentaje real nunca quede
    fuera de [min_pct, max_pct]. Si no cabe ningún entero (p. ej. 1 día presente) devuelve mínimo >
    máximo y la regla no se aplica a ese monitor.

    No estricto (solo un tramo del campamento): se redondea hacia fuera. Con pocos días el redondeo
    hacia dentro exigiría más descansos de los que hay en total (p. ej. 2 de 6 días es el 33 %).
    """
    if estricto:
        lo = math.ceil(min_pct * dias_presente / 100 - 1e-9)
        hi = math.floor(max_pct * dias_presente / 100 + 1e-9)
    else:
        lo = math.floor(min_pct * dias_presente / 100 + 1e-9)
        hi = math.ceil(max_pct * dias_presente / 100 - 1e-9)
    return max(lo, 0), hi


def calcular_plazas_tope(plazas, historico_x, fijaciones) -> Dict[Tuple[str, int], int]:
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


def validar_historico_completo(datos: Datos) -> None:
    """Cada monitor presente un día < D debe aparecer en x, r o y fijado.

    Si falta, la rejilla no se rellenó del todo para un día que se supone
    inmutable: abortamos con un mensaje claro en vez de fijar una variable a
    un valor desconocido.
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
        raise ErrorDatos(
            f"TURNOS: día histórico {d} (< DIA_REOPTIMIZACION={dia_reopt}) incompleto: "
            f"'{m}' está disponible ese día pero no aparece asignado a ningún turno, "
            f"dependiente ni descanso en la rejilla ({len(incompletos)} casos en total). "
            f"Corrige la rejilla o baja DIA_REOPTIMIZACION."
        )

    # Comprobar que ninguna celda de días < D fijada en dos sitios a la vez.
    for (acampado, d), monitor in datos.asig_dependiente.items():
        if d < dia_reopt and monitor not in (None, "", NO_PRESENTE, POR_DECIDIR):
            if (monitor, d) in datos.historico_r:
                raise ErrorDatos(
                    f"TURNOS: '{monitor}' aparece a la vez como descanso y como "
                    f"monitor de '{acampado}' el día {d}"
                )


def calcular_finde_forzar_blanda(datos: Datos) -> None:
    """Detecta si algún día no hay plazas para que TODO el grupo FINDE trabaje.

    Si la capacidad de turnos + dependientes de un día es menor que el número
    de monitores con PERMITE_DESCANSO=0 presentes ese día, la restricción
    "dura" haría el modelo infactible por construcción. En ese caso se degrada
    a blanda (penalización muy alta en vez de prohibición estructural).

    La capacidad "libre" descuenta los huecos que ya tienen dueño fijo ese día
    (una fijación OBLIGA o un cuidador ya fijado de un dependiente): esos
    huecos no están disponibles para nadie más, y si el propio monitor forzado
    ya tiene sitio asegurado ahí, tampoco cuenta como alguien "sin sitio".
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
                f"Día {dia}: no hay sitio para {len(forzados_sin_sitio)} monitor(es) de fin de semana "
                f"({', '.join(forzados_sin_sitio)}): quedan {capacidad_libre} plazas libres. "
                f"Tendrán que descansar. Para evitarlo, haz que algún turno acepte más gente ese día "
                f"(hoja PLAZAS_MAX_POR_DIA)."
            )
