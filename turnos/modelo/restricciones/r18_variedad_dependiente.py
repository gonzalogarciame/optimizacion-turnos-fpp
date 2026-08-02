"""variedad_dependiente: penaliza el número de parejas monitor-acampado
distintas (Σ z[m,p]), para favorecer que cada monitor repita con el mismo
acampado en vez de acumular muchos distintos.

`z[m,p]` lo crea `modelo.construir` como variable base (§4.2). En este
fichero ASIG_DEPENDIENTE está completamente fijada, así que todos los
`z[m,p]` que existen ya vienen determinados por los datos: el término es
"inactivo de hecho" (no cambia qué solución es óptima, es una constante),
pero se deja programado para cuando el usuario deje días de dependiente sin
asignar.
"""
from .base import registrar_penalizacion, restriccion


@restriccion("variedad_dependiente")
def aplicar(m, datos, cfg):
    if not len(m.z_idx):
        return
    registrar_penalizacion(m, "variedad_dependiente", sum(m.z[mo, p] for (mo, p) in m.z_idx))
