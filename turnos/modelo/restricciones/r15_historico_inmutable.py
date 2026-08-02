"""historico_inmutable: los días < DIA_REOPTIMIZACION quedan fijados con
`.fix()`, no eliminados.

Se fijan `x` y `r` (tanto a 1 donde corresponda como, explícitamente, a 0 en
el resto) para cada monitor en cada día histórico, según lo leído de la
rejilla `TURNOS`. No hace falta tocar `y`: `modelo.construir` ya genera un
único índice de `y` por cada celda fijada de ASIG_DEPENDIENTE (que aplica a
todos los días, históricos o no) y `asignacion_dep_fijada` lo fija a 1.

Se usa `.fix()` en vez de quitar las variables para que las reglas que
cruzan la frontera de re-optimización (`vigilancia_no_comedor`,
`dep_2_dias_tercero_descansa`) sigan valiendo con normalidad.
"""
from .base import restriccion


@restriccion("historico_inmutable")
def aplicar(m, datos, cfg):
    dia_reopt = datos.cfg.dia_reoptimizacion

    for (mo, t, d) in m.x_idx:
        if d < dia_reopt:
            valor = 1 if (mo, t, d) in datos.historico_x else 0
            m.x[mo, t, d].fix(valor)

    for (mo, d) in m.r_idx:
        if d < dia_reopt:
            valor = 1 if (mo, d) in datos.historico_r else 0
            m.r[mo, d].fix(valor)
