"""disponibilidad: nadie recibe nada un día en que está ausente (X).

Esto ya está garantizado al generar los índices `x_idx`/`y_idx`/`r_idx` en
`modelo.construir` (§4.2 de las instrucciones: "un índice inexistente reduce
el modelo; no lo modeles como una variable fijada a 0"). No hay ninguna
restricción que añadir aquí: el módulo existe solo para que la hoja
RESTRICCIONES tenga un interruptor documentado junto al resto de reglas.
Desactivarlo en la hoja no tiene efecto (la ausencia es estructural).
"""
from .base import restriccion


@restriccion("disponibilidad")
def aplicar(m, datos, cfg):
    return None
