"""max_2_dependientes: un monitor atiende como mucho a 2 acampados distintos.

    ∀ m:  Σ_p z[m,p] ≤ 2

`z[m,p]` y sus restricciones de enlace (`y ≤ z`, `z ≤ Σ_d y`) las crea
`modelo.construir` como parte de la estructura base del modelo (§4.2: z es
una variable, no una restricción). Aquí solo se añade el tope de 2.

IMPORTANTE (§5.2 de las instrucciones): esta regla **no** se aplica a
monitores cuya columna de dependiente está totalmente fijada por
ASIG_DEPENDIENTE (`m.monitores_y_libre` los excluye). Aplicarla sobre datos
ya fijados a mano puede volver el modelo infactible en el primer intento:
en el fichero de partida, 11 monitores ya llevan más de 2/3 días con el
mismo acampado porque así se decidió manualmente.
"""
from pyomo.environ import Constraint

from .base import restriccion


@restriccion("max_2_dependientes")
def aplicar(m, datos, cfg):
    monitores = sorted(mo for mo in m.monitores_y_libre if any(mo == mz for (mz, _p) in m.z_idx))
    if not monitores:
        return

    def regla(m, mo):
        pares = [p for (mz, p) in m.z_idx if mz == mo]
        if not pares:
            return Constraint.Skip
        return sum(m.z[mo, p] for p in pares) <= 2

    m.c_max_2_dependientes = Constraint(monitores, rule=regla)
