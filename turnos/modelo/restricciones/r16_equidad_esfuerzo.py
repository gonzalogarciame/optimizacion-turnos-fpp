"""equidad_esfuerzo: reparte el esfuerzo entre monitores.

    carga[m] = Σ_{t,d} esf[t]·x[m,t,d] + Σ_{p,d} esf_dep[p]·y[m,p,d]
    carga_norm[m] = carga[m] / dias_presente[m]
    cmax ≥ carga_norm[m]  ∀m        cmin ≤ carga_norm[m]  ∀m

Minimizar `cmax - cmin` (con peso W_EQUIDAD en el objetivo) iguala el
esfuerzo normalizado entre monitores. Se normaliza por días de presencia
(un parámetro fijo, así la expresión sigue siendo lineal) porque cada
monitor está presente un número distinto de días.

Con `y` fijada por ASIG_DEPENDIENTE, la parte de dependiente de `carga[m]`
es una constante para ese monitor, pero se incluye igual: el reparto de los
turnos de trabajo `x` debe compensar a quien ya carga con un dependiente.

Si en `resolver.py` se activa el modo de dos fases, la fase 2 añade la cota
`cmax - cmin <= optimo_fase1 * (1 + MIP_GAP)` y reoptimiza el resto de
términos del objetivo con este valor casi fijado.
"""
from pyomo.environ import Constraint, NonNegativeReals, Var

from .base import restriccion


@restriccion("equidad_esfuerzo")
def aplicar(m, datos, cfg):
    monitores_validos = [mo for mo in datos.monitores if datos.dias_presente.get(mo, 0) > 0]
    if not monitores_validos:
        return

    x_por_monitor: dict = {}
    for (mo, t, d) in m.x_idx:
        x_por_monitor.setdefault(mo, []).append((t, d))
    y_por_monitor: dict = {}
    for (mo, p, d) in m.y_idx:
        y_por_monitor.setdefault(mo, []).append((p, d))

    def carga_expr(mo):
        trabajo = sum(datos.turnos[t].esfuerzo * m.x[mo, t, d] for (t, d) in x_por_monitor.get(mo, []))
        dependiente = sum(
            datos.dependientes[p].esfuerzo * m.y[mo, p, d] for (p, d) in y_por_monitor.get(mo, [])
        )
        return trabajo + dependiente

    m.cmax = Var(domain=NonNegativeReals)
    m.cmin = Var(domain=NonNegativeReals)

    def regla_max(m, mo):
        dp = datos.dias_presente[mo]
        return m.cmax >= carga_expr(mo) / dp

    def regla_min(m, mo):
        dp = datos.dias_presente[mo]
        return m.cmin <= carga_expr(mo) / dp

    m.c_equidad_max = Constraint(monitores_validos, rule=regla_max)
    m.c_equidad_min = Constraint(monitores_validos, rule=regla_min)
