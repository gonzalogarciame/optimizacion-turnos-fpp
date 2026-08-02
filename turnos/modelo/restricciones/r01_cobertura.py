"""cobertura: cada turno se cubre con sus plazas, con holgura penalizada.

    Σ_m x[m,t,d] + falta[t,d] = plazas[t,d]      ∀ t, d

`plazas[t,d]` viene de PLAZAS_POR_DIA (o del valor por defecto de
TIPOS_TURNO si el turno no tiene fila propia ahí). `falta[t,d] >= 0` absorbe
lo que no se pueda cubrir para que el modelo nunca sea infactible solo por
falta de gente; se penaliza con W_FALTA en el objetivo.
"""
from pyomo.environ import Constraint, NonNegativeReals, Set, Var

from .base import registrar_penalizacion, restriccion


@restriccion("cobertura")
def aplicar(m, datos, cfg):
    idx = [(t, d) for t in datos.turnos for d in datos.dias]
    m.falta_idx = Set(initialize=idx, dimen=2)
    m.falta = Var(m.falta_idx, domain=NonNegativeReals)

    def regla(m, t, d):
        cubierto = sum(m.x[mo, t, d] for mo in datos.monitores if (mo, t, d) in m.x_idx)
        return cubierto + m.falta[t, d] == datos.plazas[(t, d)]

    m.c_cobertura = Constraint(m.falta_idx, rule=regla)

    registrar_penalizacion(m, "cobertura", sum(m.falta[t, d] for (t, d) in m.falta_idx))
