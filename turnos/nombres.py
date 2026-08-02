"""Normalización de nombres y resolución de apodos (hoja ALIAS).

La rejilla `TURNOS` se rellena a mano y usa apodos ("Gabi Sainz", "Tere GV"...)
que no coinciden literalmente con el nombre canónico de `MONITORES`. Antes de
comparar dos nombres hay que normalizarlos (minúsculas, sin tildes, sin
espacios dobles) y, si no coinciden, buscarlos en la tabla de alias.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Optional


def normalizar(nombre: str) -> str:
    """minúsculas, sin tildes, espacios colapsados y recortados."""
    if nombre is None:
        return ""
    txt = str(nombre).strip()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = txt.lower()
    txt = " ".join(txt.split())
    return txt


class ErrorNombreNoReconocido(Exception):
    """Un nombre de la rejilla no existe ni en MONITORES ni en ALIAS."""

    def __init__(self, nombre: str, celda: str):
        self.nombre = nombre
        self.celda = celda
        super().__init__(f"{celda}: '{nombre}' no reconocido")


@dataclass
class ResolverNombres:
    """Traduce cualquier variante escrita en la rejilla a su nombre canónico.

    - `canonicos`: nombres tal cual aparecen en MONITORES (o DEPENDIENTES).
    - `alias`: variante -> canónico, leído de la hoja ALIAS.
    """

    canonicos: Dict[str, str] = field(default_factory=dict)  # normalizado -> canónico
    alias: Dict[str, str] = field(default_factory=dict)      # normalizado(variante) -> canónico

    @classmethod
    def construir(cls, nombres_canonicos, pares_alias):
        r = cls()
        for nombre in nombres_canonicos:
            r.canonicos[normalizar(nombre)] = nombre
        for variante, canonico in pares_alias:
            r.alias[normalizar(variante)] = canonico
        return r

    def resolver(self, nombre: str, celda: str = "") -> str:
        """Devuelve el nombre canónico o lanza ErrorNombreNoReconocido."""
        if nombre is None:
            raise ErrorNombreNoReconocido(nombre, celda)
        texto = str(nombre).strip()
        if texto == "" or texto == "-":
            raise ErrorNombreNoReconocido(nombre, celda)
        clave = normalizar(texto)
        if clave in self.canonicos:
            return self.canonicos[clave]
        if clave in self.alias:
            canonico = self.alias[clave]
            # El alias podría apuntar a algo que a su vez hay que normalizar
            # contra la lista de canónicos (por si hay errores de tecleo).
            clave_canonico = normalizar(canonico)
            if clave_canonico in self.canonicos:
                return self.canonicos[clave_canonico]
            return canonico
        raise ErrorNombreNoReconocido(texto, celda)

    def resolver_opcional(self, nombre: str) -> Optional[str]:
        """Como `resolver` pero devuelve None en vez de lanzar excepción."""
        try:
            return self.resolver(nombre)
        except ErrorNombreNoReconocido:
            return None
