"""finde_sin_descanso: PERMITE_DESCANSO=0 => ese monitor nunca recibe descanso.

Caso normal (holgura suficiente todos los días, ver `validar.py` y
`lector._calcular_finde_forzar_blanda`): no existe `r[m,d]` para estos
monitores (ya se excluyeron al generar `r_idx` en `modelo.construir`), así
que combinado con `un_turno_por_dia` quedan obligados a trabajo o
dependiente cada día que están presentes. Módulo no-op en ese caso.

Caso degradado (`datos.finde_forzar_blanda = True`, algún día no hay plazas
ni para el propio grupo FINDE): `modelo.construir` sí crea `r[m,d]` para
estos monitores, y aquí penalizamos su uso con el mismo peso `W_FALTA` que
un turno sin cubrir, para que el solver solo recurra a ello si es
estrictamente necesario para no quedar infactible.
"""
from .base import registrar_penalizacion, restriccion


@restriccion("finde_sin_descanso")
def aplicar(m, datos, cfg):
    if not datos.finde_forzar_blanda:
        return

    idx = [
        (mo, d)
        for (mo, d) in m.r_idx
        if not datos.monitores[mo].permite_descanso
    ]
    if not idx:
        return

    registrar_penalizacion(m, "finde_sin_descanso_forzado", sum(m.r[mo, d] for (mo, d) in idx))
