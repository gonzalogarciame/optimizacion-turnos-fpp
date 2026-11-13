"""Errores de datos compartidos por todas las fuentes (Excel, base de datos)."""
from __future__ import annotations


class ErrorDatos(Exception):
    """Los datos leídos no son válidos o no son coherentes entre sí."""
