"""cobertura: cada turno se cubre con sus plazas, con holgura penalizada.

    Σ_m x[m,t,d] + falta[t,d] - extra[t,d] = plazas[t,d]      ∀ t, d

`plazas[t,d]` viene de PLAZAS_POR_DIA (o del valor por defecto de
TIPOS_TURNO si el turno no tiene fila propia ahí). `falta[t,d] >= 0` absorbe
lo que no se pueda cubrir para que el modelo nunca sea infactible solo por
falta de gente; se penaliza con W_FALTA en el objetivo.

`extra[t,d]` solo existe si el turno acepta más gente que sus plazas ese día
(hoja opcional PLAZAS_MAX_POR_DIA, `datos.tope(t,d) > plazas`). Sirve para
los días en que hay pocos turnos (llegada y salida) y sobra gente: en vez de
mandar a descansar a quien prefiere no hacerlo, el turno admite hasta `tope`
personas. Cada una cuesta W_EXTRA, así que solo se usa si hace falta.
Sin PLAZAS_MAX_POR_DIA el modelo es exactamente el de siempre.
"""
from pyomo.environ import Constraint, NonNegativeReals, Set, Var

from .base import registrar_penalizacion, restriccion


@restriccion("cobertura")
def aplicar(m, datos, cfg):
    idx = [(t, d) for t in datos.turnos for d in datos.dias]
    m.falta_idx = Set(initialize=idx, dimen=2)
    m.falta = Var(m.falta_idx, domain=NonNegativeReals)

    extra_idx = [(t, d) for (t, d) in idx if datos.tope(t, d) > datos.plazas[(t, d)]]
    m.extra_idx = Set(initialize=extra_idx, dimen=2)
    m.extra = Var(
        m.extra_idx,
        domain=NonNegativeReals,
        bounds=lambda m, t, d: (0, datos.tope(t, d) - datos.plazas[(t, d)]),
    )

    def regla(m, t, d):
        cubierto = sum(m.x[mo, t, d] for mo in datos.monitores if (mo, t, d) in m.x_idx)
        extra = m.extra[t, d] if (t, d) in m.extra_idx else 0
        return cubierto + m.falta[t, d] - extra == datos.plazas[(t, d)]

    m.c_cobertura = Constraint(m.falta_idx, rule=regla)

    registrar_penalizacion(m, "cobertura", sum(m.falta[t, d] for (t, d) in m.falta_idx))
    if extra_idx:
        registrar_penalizacion(m, "plazas_extra", sum(m.extra[t, d] for (t, d) in m.extra_idx))
