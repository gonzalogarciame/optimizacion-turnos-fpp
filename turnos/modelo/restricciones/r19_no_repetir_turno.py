"""no_repetir_turno: penaliza repetir el mismo turno dos días seguidos.

    rep[m,t,d] ≥ x[m,t,d] + x[m,t,d+1] - 1        (rep continua, >= 0)
    penaliza Σ rep[m,t,d]                           (peso W_REPETICION)

No hace falta que `rep` sea binaria: al minimizar su suma con peso positivo,
el solver la deja en `max(0, x_d + x_{d+1} - 1)`, que es exactamente el
indicador de "repite turno" que se quiere penalizar.
"""
from pyomo.environ import Constraint, NonNegativeReals, Set, Var

from .base import registrar_penalizacion, restriccion


@restriccion("no_repetir_turno")
def aplicar(m, datos, cfg):
    dias = datos.dias
    idx = []
    for (mo, t, d) in m.x_idx:
        i = dias.index(d)
        if i + 1 >= len(dias):
            continue
        d1 = dias[i + 1]
        if (mo, t, d1) in m.x_idx:
            idx.append((mo, t, d, d1))
    if not idx:
        return

    m.rep_idx = Set(initialize=idx, dimen=4)
    m.rep = Var(m.rep_idx, domain=NonNegativeReals)

    def regla(m, mo, t, d, d1):
        return m.rep[mo, t, d, d1] >= m.x[mo, t, d] + m.x[mo, t, d1] - 1

    m.c_no_repetir_turno = Constraint(m.rep_idx, rule=regla)

    registrar_penalizacion(m, "no_repetir_turno", sum(m.rep[i] for i in m.rep_idx))
