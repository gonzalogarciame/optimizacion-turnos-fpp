"""asignacion_dep_fijada: se respeta ASIG_DEPENDIENTE tal cual está escrita.

    Si la celda (acampado, día) dice 'm0', entonces y[m0,p,d] = 1.

`modelo.construir` ya genera un único índice de `y` para esos casos (no crea
variables para el resto de monitores elegibles, así el modelo no crece de
más); aquí simplemente se fija esa variable a 1 con `.fix()`. Si en el
futuro la matriz llega parcialmente vacía, esas celdas pasan a
POR_DECIDIR y generan variables libres para todos los monitores elegibles
(ver `cobertura_dependiente`), así que este módulo funciona igual.
"""
from ..datos import NO_PRESENTE, POR_DECIDIR
from .base import restriccion


@restriccion("asignacion_dep_fijada")
def aplicar(m, datos, cfg):
    for (p, d), asignado in datos.asig_dependiente.items():
        if asignado in (NO_PRESENTE, POR_DECIDIR):
            continue
        if (asignado, p, d) in m.y_idx:
            m.y[asignado, p, d].fix(1)
