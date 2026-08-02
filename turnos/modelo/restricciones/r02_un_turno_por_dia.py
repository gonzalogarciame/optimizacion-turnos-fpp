"""un_turno_por_dia: cada monitor presente hace exactamente una cosa al día.

    ∀ m, d con disponibilidad ∈ {D,R}:
        Σ_t x[m,t,d] + Σ_p y[m,p,d] + r[m,d] = 1

Esto ya impone que trabajo, dependiente y descanso son mutuamente
excluyentes. Si el monitor no tiene variable `r` ese día (PERMITE_DESCANSO=0
y no hace falta degradar la regla, o está ausente), el término `r[m,d]`
simplemente no aparece en la suma.
"""
from pyomo.environ import Constraint

from .base import restriccion


@restriccion("un_turno_por_dia")
def aplicar(m, datos, cfg):
    pares = [
        (mo, d)
        for mo in datos.monitores
        for d in datos.dias
        if datos.disponibilidad[(mo, d)] in ("D", "R")
    ]

    def regla(m, mo, d):
        trabajo = sum(m.x[mo, t, d] for t in datos.turnos if (mo, t, d) in m.x_idx)
        dependiente = sum(m.y[mo, p, d] for p in datos.dependientes if (mo, p, d) in m.y_idx)
        descanso = m.r[mo, d] if (mo, d) in m.r_idx else 0
        return trabajo + dependiente + descanso == 1

    m.c_un_turno_por_dia = Constraint(pares, rule=regla)
