"""vigilancia_no_comedor: quien vigila de noche no va a comedor al día
siguiente (las cuatro vigilancias, incluidas las de dependiente).

    ∀ m, d ∈ D\\{último}:
        Σ_{t ∈ VIGILANCIA} x[m,t,d] + x[m,comedor,d+1] ≤ 1
"""
from pyomo.environ import Constraint

from .base import restriccion

VIGILANCIA = [
    "vigilancia_chicos",
    "vigilancia_chicas",
    "vigilancia_D_chicos",
    "vigilancia_D_chicas",
]


@restriccion("vigilancia_no_comedor")
def aplicar(m, datos, cfg):
    dias = datos.dias
    vigilancia = [t for t in VIGILANCIA if t in datos.turnos]
    if "comedor" not in datos.turnos or not vigilancia:
        return

    def regla(m, mo, i):
        d, d1 = dias[i], dias[i + 1]
        izq = sum(m.x[mo, t, d] for t in vigilancia if (mo, t, d) in m.x_idx)
        if (mo, "comedor", d1) not in m.x_idx:
            return Constraint.Skip
        return izq + m.x[mo, "comedor", d1] <= 1

    m.c_vigilancia_no_comedor = Constraint(list(datos.monitores), range(len(dias) - 1), rule=regla)
