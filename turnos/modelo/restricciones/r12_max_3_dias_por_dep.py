"""max_3_dias_por_dep: como mucho MAX_DIAS_POR_DEP días con el mismo acampado.

    ∀ m,p:   Σ_d y[m,p,d] ≤ MAX_DIAS_POR_DEP   (= 3, o CONFIG!MAX_DIAS_POR_DEP si existe)

Igual que `max_2_dependientes`, solo se aplica a monitores con `y` libre
(§5.2): 11 monitores del fichero de partida ya hacen 4 días con el mismo
acampado en ASIG_DEPENDIENTE, y esta regla se saltaría infactible si se les
aplicara.
"""
from pyomo.environ import Constraint

from .base import restriccion


@restriccion("max_3_dias_por_dep")
def aplicar(m, datos, cfg):
    pares = sorted({(mo, p) for (mo, p) in m.z_idx if mo in m.monitores_y_libre})
    if not pares:
        return

    tope = datos.cfg.max_dias_por_dep

    def regla(m, mo, p):
        dias_validos = [d for d in datos.dias if (mo, p, d) in m.y_idx]
        if not dias_validos:
            return Constraint.Skip
        return sum(m.y[mo, p, d] for d in dias_validos) <= tope

    m.c_max_3_dias_por_dep = Constraint(pares, rule=regla)
