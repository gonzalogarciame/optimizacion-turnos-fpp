"""sexo_dependiente: el monitor de un dependiente cumple SEXO_MONITOR_REQ.

Ya garantizado al generar `y_idx` en `modelo.construir` (se compara
`DEPENDIENTES.SEXO_MONITOR_REQ` contra `MONITORES.SEXO`; '-' admite
cualquiera). Módulo no-op, solo para que exista el interruptor en
RESTRICCIONES.
"""
from .base import restriccion


@restriccion("sexo_dependiente")
def aplicar(m, datos, cfg):
    return None
