"""descanso_porcentaje: cada monitor descansa entre DESCANSO_MIN_PCT % y DESCANSO_MAX_PCT %
de los días que está disponible.

    lo[m] ≤ Σ_d r[m,d] + bajo[m] - alto[m]   y   Σ_d r[m,d] - alto[m] + bajo[m] ≤ hi[m]

con lo = ceil(min% · días), hi = floor(max% · días) (ver `limites_descanso`). Cuenta
también los descansos de los días ya fijados (histórico).

Es una regla dura, pero con holgura (`bajo`/`alto`) fuertemente penalizada (W_DESCANSO_PCT,
menor que W_FALTA): cuando no se puede cumplir (datos que lo impiden, como un tramo corto
cuyo histórico ya se pasa del máximo) el modelo no queda infactible: incumple lo mínimo y
el Informe marca a quién afecta.

No se aplica a los monitores de fin de semana (no descansan) ni a quien está tan pocos días
que ningún número entero de descansos cabe en el margen.
"""
from pyomo.environ import Constraint, NonNegativeReals, Set, Var

from ..derivados import limites_descanso
from .base import registrar_penalizacion, restriccion


@restriccion("descanso_porcentaje")
def aplicar(m, datos, cfg):
    limites = {}
    for mo, mon in datos.monitores.items():
        if not mon.permite_descanso:
            continue
        lo, hi = limites_descanso(datos.dias_presente.get(mo, 0), datos.cfg.descanso_min_pct, datos.cfg.descanso_max_pct,
                                  estricto=not datos.cfg.horizonte_recortado)
        if lo <= hi:
            limites[mo] = (lo, hi)
    if not limites:
        return

    m.desc_pct_monitores = Set(initialize=list(limites))
    m.desc_pct_bajo = Var(m.desc_pct_monitores, domain=NonNegativeReals)
    m.desc_pct_alto = Var(m.desc_pct_monitores, domain=NonNegativeReals)

    def descansos(m, mo):
        return sum(m.r[mo, d] for d in datos.dias if (mo, d) in m.r_idx)

    m.c_desc_pct_min = Constraint(m.desc_pct_monitores, rule=lambda m, mo: descansos(m, mo) + m.desc_pct_bajo[mo] >= limites[mo][0])
    m.c_desc_pct_max = Constraint(m.desc_pct_monitores, rule=lambda m, mo: descansos(m, mo) - m.desc_pct_alto[mo] <= limites[mo][1])

    registrar_penalizacion(m, "descanso_porcentaje",
                           sum(m.desc_pct_bajo[mo] + m.desc_pct_alto[mo] for mo in m.desc_pct_monitores))
