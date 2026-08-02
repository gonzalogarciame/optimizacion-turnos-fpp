"""Llama al solver (Gurobi, vía Pyomo) y extrae la solución.

El nombre del solver, el límite de tiempo y el gap SIEMPRE se leen de
`datos.cfg` (hoja CONFIG); nunca están fijos aquí.
"""
from __future__ import annotations

import time
from typing import Optional

import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

from .modelo.datos import Datos, Solucion
from .validar import diagnosticar_infactibilidad

TERMINACIONES_FACTIBLES = {
    TerminationCondition.optimal,
    TerminationCondition.feasible,
    TerminationCondition.maxTimeLimit,
    TerminationCondition.maxIterations,
}

TERMINACIONES_INFACTIBLES = {
    TerminationCondition.infeasible,
    TerminationCondition.infeasibleOrUnbounded,
}


def _opciones_solver(nombre_solver: str, cfg) -> dict:
    if "gurobi" in nombre_solver:
        return {"TimeLimit": cfg.time_limit_s, "MIPGap": cfg.mip_gap}
    if "highs" in nombre_solver:
        return {"time_limit": cfg.time_limit_s, "mip_rel_gap": cfg.mip_gap}
    if nombre_solver in ("cbc", "glpk"):
        return {"seconds": cfg.time_limit_s, "ratioGap": cfg.mip_gap}
    return {}


def _crear_solver(cfg):
    opt = pyo.SolverFactory(cfg.solver)
    opciones = _opciones_solver(cfg.solver, cfg)
    for clave, valor in opciones.items():
        try:
            opt.options[clave] = valor
        except Exception:
            pass
    return opt


def resolver_modelo(modelo, datos: Datos, dos_fases: bool = False) -> Solucion:
    cfg = datos.cfg

    if dos_fases and hasattr(modelo, "cmax") and hasattr(modelo, "cmin"):
        _resolver_dos_fases(modelo, datos)

    opt = _crear_solver(cfg)
    inicio = time.time()
    resultado = opt.solve(modelo, tee=False, load_solutions=False)
    duracion = time.time() - inicio

    condicion = resultado.solver.termination_condition

    if condicion in TERMINACIONES_INFACTIBLES:
        diagnostico = diagnosticar_infactibilidad(modelo, datos)
        return Solucion(
            x={}, y={}, r={}, falta={},
            estado="infactible",
            tiempo_s=duracion,
            diagnostico=diagnostico,
        )

    if condicion not in TERMINACIONES_FACTIBLES:
        return Solucion(
            x={}, y={}, r={}, falta={},
            estado=f"sin_solucion ({condicion})",
            tiempo_s=duracion,
            diagnostico=[
                f"El solver terminó con estado '{condicion}' y estatus "
                f"'{resultado.solver.status}'. No hay solución que extraer."
            ],
        )

    modelo.solutions.load_from(resultado)

    x = {idx: int(round(pyo.value(modelo.x[idx]))) for idx in modelo.x_idx}
    y = {idx: int(round(pyo.value(modelo.y[idx]))) for idx in modelo.y_idx}
    r = {idx: int(round(pyo.value(modelo.r[idx]))) for idx in modelo.r_idx}
    falta = {}
    if hasattr(modelo, "falta_idx"):
        falta = {idx: float(pyo.value(modelo.falta[idx])) for idx in modelo.falta_idx}

    gap = None
    try:
        objetivo = pyo.value(modelo.objetivo)
        limite = resultado.problem.upper_bound if modelo.objetivo.sense == pyo.minimize else resultado.problem.lower_bound
        if limite is not None and objetivo not in (None, 0):
            gap = abs(objetivo - limite) / max(abs(objetivo), 1e-9)
    except Exception:
        objetivo = None

    estado = "optimo" if condicion == TerminationCondition.optimal else "factible (límite de tiempo o gap)"

    return Solucion(
        x=x, y=y, r=r, falta=falta,
        estado=estado,
        gap=gap,
        tiempo_s=duracion,
        objetivo=objetivo,
        diagnostico=[],
    )


def _resolver_dos_fases(modelo, datos: Datos) -> None:
    """Fase 1: minimiza solo cmax-cmin. Fase 2 (en `resolver_modelo`): fija
    esa diferencia (con un margen MIP_GAP) y deja que el objetivo completo
    reparta el resto. Evita soluciones "degeneradas" donde el equilibrio de
    esfuerzo es óptimo mil formas distintas y el solver elige una cualquiera.
    """
    cfg = datos.cfg
    objetivo_original = modelo.objetivo
    objetivo_original.deactivate()

    modelo._obj_fase1 = pyo.Objective(expr=modelo.cmax - modelo.cmin, sense=pyo.minimize)

    opt = _crear_solver(cfg)
    resultado = opt.solve(modelo, tee=False, load_solutions=False)
    if resultado.solver.termination_condition not in TERMINACIONES_FACTIBLES:
        modelo._obj_fase1.deactivate()
        objetivo_original.activate()
        return

    modelo.solutions.load_from(resultado)
    optimo_fase1 = pyo.value(modelo.cmax) - pyo.value(modelo.cmin)

    modelo._obj_fase1.deactivate()
    objetivo_original.activate()

    cota = optimo_fase1 * (1 + cfg.mip_gap) + 1e-6
    modelo.c_equidad_fase2 = pyo.Constraint(expr=(modelo.cmax - modelo.cmin) <= cota)
