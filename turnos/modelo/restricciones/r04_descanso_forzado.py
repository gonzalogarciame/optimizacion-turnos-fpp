"""descanso_forzado: las celdas R de DISPONIBILIDAD son descanso obligatorio.

    disponibilidad[m,d] == 'R'  =>  r[m,d] = 1

Solo se aplica donde existe `r[m,d]` (monitor con PERMITE_DESCANSO=1, o
excepcionalmente 0 si `finde_forzar_blanda` obligó a crear la variable, ver
r07_finde_sin_descanso.py). `lector.py` ya valida que ningún monitor con
PERMITE_DESCANSO=0 tenga código R "normal" en DISPONIBILIDAD.
"""
from pyomo.environ import Constraint

from .base import restriccion


@restriccion("descanso_forzado")
def aplicar(m, datos, cfg):
    pares = [
        (mo, d)
        for (mo, d) in m.r_idx
        if datos.disponibilidad[(mo, d)] == "R"
    ]
    if not pares:
        return

    def regla(m, mo, d):
        return m.r[mo, d] == 1

    m.c_descanso_forzado = Constraint(pares, rule=regla)
