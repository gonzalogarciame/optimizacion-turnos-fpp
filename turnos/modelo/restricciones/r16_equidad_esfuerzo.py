"""equidad_esfuerzo: reparte el esfuerzo entre monitores.

    carga[m] = Σ_{t,d} esf[t]·x[m,t,d] + Σ_{p,d} esf_dep[p]·y[m,p,d]
    carga_norm[m] = carga[m] / dias_presente[m]
    cmax ≥ carga_norm[m]  ∀m        cmin ≤ carga_norm[m]  ∀m

Se minimiza (con peso W_EQUIDAD en el objetivo) la diferencia entre el más y el
menos cargado (`cmax - cmin`) MÁS la suma de lo que cada monitor se aleja de
una carga de referencia `t` (variable libre, queda en la mediana):

    dev[m] ≥ carga_norm[m] - t        dev[m] ≥ t - carga_norm[m]

Solo con `cmax - cmin` los monitores que quedan entre los dos extremos no
tienen ningún incentivo para acercarse unos a otros (y alguien podía acabar
con 7 descansos en 8 días mientras otro solo tenía 1). La suma de
desviaciones empuja a todos hacia el mismo valor. Se normaliza por días de
presencia (un parámetro fijo, así la expresión sigue siendo lineal) porque
cada monitor está presente un número distinto de días.

No entran en el reparto: los monitores de fin de semana (no están los mismos
días que el resto) ni los que están muy pocos días (con 2 días de presencia,
un solo turno ya los dispara y fijarían el rango de todos los demás).

Con `y` fijada por ASIG_DEPENDIENTE, la parte de dependiente de `carga[m]`
es una constante para ese monitor, pero se incluye igual: el reparto de los
turnos de trabajo `x` debe compensar a quien ya carga con un dependiente.

Si en `resolver.py` se activa el modo de dos fases, la fase 2 añade la cota
`cmax - cmin <= optimo_fase1 * (1 + MIP_GAP)` y reoptimiza el resto de
términos del objetivo con este valor casi fijado.
"""
from pyomo.environ import Constraint, NonNegativeReals, Set, Var

# Días de presencia mínimos para entrar en el reparto (si todos están menos días, el máximo que haya)
MIN_DIAS_EQUIDAD = 4

from .base import restriccion


@restriccion("equidad_esfuerzo")
def aplicar(m, datos, cfg):
    con_dias = [mo for mo in datos.monitores if datos.dias_presente.get(mo, 0) > 0]
    if not con_dias:
        return
    umbral = min(MIN_DIAS_EQUIDAD, max(datos.dias_presente[mo] for mo in con_dias))
    monitores_validos = [mo for mo in con_dias
                         if datos.dias_presente[mo] >= umbral and datos.monitores[mo].permite_descanso]
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

    # Desviación de cada monitor respecto a la carga de referencia
    m.equi_ref = Var(domain=NonNegativeReals)
    m.equi_monitores = Set(initialize=monitores_validos)
    m.dev_equidad = Var(m.equi_monitores, domain=NonNegativeReals)

    def regla_dev_arriba(m, mo):
        return m.dev_equidad[mo] >= carga_expr(mo) / datos.dias_presente[mo] - m.equi_ref

    def regla_dev_abajo(m, mo):
        return m.dev_equidad[mo] >= m.equi_ref - carga_expr(mo) / datos.dias_presente[mo]

    m.c_dev_arriba = Constraint(m.equi_monitores, rule=regla_dev_arriba)
    m.c_dev_abajo = Constraint(m.equi_monitores, rule=regla_dev_abajo)
