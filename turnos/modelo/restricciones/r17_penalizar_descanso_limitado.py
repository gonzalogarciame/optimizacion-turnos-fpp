"""penalizar_descanso_limitado: penaliza dar descanso a quien está pocos días.

    Σ_{m: PENALIZAR_DESCANSO=1, d} r[m,d]     (peso W_DESCANSO_LIM)

Penalización blanda, no prohibición: si hace falta darle descanso a uno de
estos 21 monitores para cuadrar la cobertura, se puede, solo que cuesta más
en el objetivo que hacerlo con otro monitor.
"""
from .base import registrar_penalizacion, restriccion


@restriccion("penalizar_descanso_limitado")
def aplicar(m, datos, cfg):
    idx = [(mo, d) for (mo, d) in m.r_idx if datos.monitores[mo].penalizar_descanso]
    if not idx:
        return
    registrar_penalizacion(m, "penalizar_descanso_limitado", sum(m.r[mo, d] for (mo, d) in idx))
