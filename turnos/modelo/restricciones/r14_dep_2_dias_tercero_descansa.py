"""dep_2_dias_tercero_descansa: dos días seguidos de dependiente obligan a
descansar el tercero.

    ∀ m, d con d, d+1, d+2 ∈ D:
        Σ_p y[m,p,d] + Σ_p y[m,p,d+1] - 1 ≤ r[m,d+2]

Se omite si `d+2` cae fuera del horizonte, si `r[m,d+2]` no existe (monitor
ausente o sin PERMITE_DESCANSO), o si el monitor tiene `y` totalmente fijada
(§5.2): 5 monitores del fichero de partida ya encadenan 3 días seguidos con
dependiente en ASIG_DEPENDIENTE.
"""
from pyomo.environ import Constraint

from .base import restriccion


@restriccion("dep_2_dias_tercero_descansa")
def aplicar(m, datos, cfg):
    dias = datos.dias
    filas = []
    for mo in sorted(m.monitores_y_libre):
        for i, d in enumerate(dias):
            if i + 2 >= len(dias):
                break
            d1, d2 = dias[i + 1], dias[i + 2]
            if (mo, d2) not in m.r_idx:
                continue
            filas.append((mo, d, d1, d2))
    if not filas:
        return

    def regla(m, mo, d, d1, d2):
        dep_d = sum(m.y[mo, p, d] for p in datos.dependientes if (mo, p, d) in m.y_idx)
        dep_d1 = sum(m.y[mo, p, d1] for p in datos.dependientes if (mo, p, d1) in m.y_idx)
        return dep_d + dep_d1 - 1 <= m.r[mo, d2]

    m.c_dep_2_dias_tercero_descansa = Constraint(filas, rule=regla)
