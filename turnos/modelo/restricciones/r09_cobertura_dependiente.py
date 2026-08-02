"""cobertura_dependiente: cada dependiente presente tiene exactamente un
monitor; si no está presente, no se genera ninguna variable (no hay nada
que exigir).

    ∀ p, d presente:      Σ_m y[m,p,d] = 1
    ∀ p, d no presente:   (sin variables, sin restricción)
"""
from pyomo.environ import Constraint

from ..datos import NO_PRESENTE
from .base import restriccion


@restriccion("cobertura_dependiente")
def aplicar(m, datos, cfg):
    pares = [
        (p, d)
        for p in datos.dependientes
        for d in datos.dias
        if datos.asig_dependiente.get((p, d), NO_PRESENTE) is not NO_PRESENTE
    ]

    def regla(m, p, d):
        return sum(m.y[mo, p, d] for mo in datos.monitores if (mo, p, d) in m.y_idx) == 1

    m.c_cobertura_dependiente = Constraint(pares, rule=regla)
