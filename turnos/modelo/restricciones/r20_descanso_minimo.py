"""descanso_minimo: en cada ventana de DIAS_VENTANA_DESCANSO días, cada
monitor con presencia amplia debería tener al menos DIAS_DESCANSO_MINIMO
descansos.

    Σ_{d∈ventana} r[m,d] + falta_desc[m,v] ≥ DIAS_DESCANSO_MINIMO

Penaliza Σ falta_desc con peso W_FALTA_DESC. Las ventanas son deslizantes
(solapadas) sobre el horizonte de días.

"Presencia amplia" = está al menos `DIAS_VENTANA_DESCANSO` días (si viene
menos días que una ventana entera, no tiene sentido exigirle un descanso
dentro de ella). Los monitores con PERMITE_DESCANSO=0 (grupo FINDE) quedan
fuera por definición: nunca tienen `r`, así que esta regla no les aplica
(ya lo hace `finde_sin_descanso`).
"""
from pyomo.environ import Constraint, NonNegativeReals, Set, Var

from .base import registrar_penalizacion, restriccion


@restriccion("descanso_minimo")
def aplicar(m, datos, cfg):
    dias = datos.dias
    ventana = datos.cfg.dias_ventana_descanso
    minimo = datos.cfg.dias_descanso_minimo
    if ventana <= 0 or len(dias) < ventana:
        return

    monitores_validos = [
        mo
        for mo in datos.monitores
        if datos.monitores[mo].permite_descanso and datos.dias_presente.get(mo, 0) >= ventana
    ]
    if not monitores_validos:
        return

    ventanas = [tuple(dias[i:i + ventana]) for i in range(len(dias) - ventana + 1)]

    idx = [(mo, v) for mo in monitores_validos for v in range(len(ventanas))]
    m.falta_desc_idx = Set(initialize=idx, dimen=2)
    m.falta_desc = Var(m.falta_desc_idx, domain=NonNegativeReals)

    def regla(m, mo, v):
        dias_ventana = ventanas[v]
        descansos = sum(m.r[mo, d] for d in dias_ventana if (mo, d) in m.r_idx)
        return descansos + m.falta_desc[mo, v] >= minimo

    m.c_descanso_minimo = Constraint(m.falta_desc_idx, rule=regla)

    registrar_penalizacion(m, "descanso_minimo", sum(m.falta_desc[i] for i in m.falta_desc_idx))
