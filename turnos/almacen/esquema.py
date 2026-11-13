"""Esquema de la base de datos SQLite de un campamento.

Un fichero `.db` por campamento sustituye al Excel como fuente de verdad. Es
SQLite (librería estándar de Python): no hay que instalar nada ni hace falta
conexión a internet.

Cómo se corresponde con las hojas del Excel:

    CONFIG                          -> config
    MONITORES, ALIAS                -> monitores, alias
    DISPONIBILIDAD                  -> disponibilidad
    TIPOS_TURNO                     -> tipos_turno
    PLAZAS_POR_DIA + _MAX_POR_DIA   -> plazas_dia (plazas y máximo)
    DEPENDIENTES, ASIG_DEPENDIENTE  -> dependientes, dependiente_ausente (+ asignaciones)
    FIJACIONES                      -> fijaciones
    TURNOS (la rejilla)             -> asignaciones
    RESTRICCIONES                   -> restricciones

`asignaciones` es la rejilla: una fila por casilla ocupada. `pos` es la
posición dentro de la casilla (la fila dentro de su bloque en la rejilla).
`fijada` sustituye al relleno amarillo: el optimizador la respeta.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

VERSION_ESQUEMA = 1

_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config (
    clave       TEXT PRIMARY KEY,
    valor       TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS monitores (
    orden              INTEGER NOT NULL,
    nombre             TEXT PRIMARY KEY,
    sexo               TEXT NOT NULL CHECK (sexo IN ('M', 'F')),
    grupo              TEXT NOT NULL DEFAULT '',
    permite_descanso   INTEGER NOT NULL CHECK (permite_descanso IN (0, 1)),
    penalizar_descanso INTEGER NOT NULL CHECK (penalizar_descanso IN (0, 1)),
    dependiente_1      TEXT,
    dependiente_2      TEXT
);

CREATE TABLE IF NOT EXISTS alias (
    variante TEXT PRIMARY KEY,
    canonico TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS disponibilidad (
    monitor TEXT    NOT NULL REFERENCES monitores (nombre) ON UPDATE CASCADE ON DELETE CASCADE,
    dia     INTEGER NOT NULL,
    codigo  TEXT    NOT NULL CHECK (codigo IN ('D', 'X', 'R')),
    PRIMARY KEY (monitor, dia)
);

CREATE TABLE IF NOT EXISTS tipos_turno (
    orden    INTEGER NOT NULL,
    turno    TEXT PRIMARY KEY,
    plazas   INTEGER NOT NULL,
    sexo_req TEXT    NOT NULL DEFAULT '-' CHECK (sexo_req IN ('M', 'F', '-')),
    esfuerzo REAL    NOT NULL,
    notas    TEXT    NOT NULL DEFAULT ''
);

-- Plazas que hay que cubrir cada día y, opcionalmente, hasta cuántas personas
-- acepta el turno ese día (`maximo` NULL = no acepta más de las necesarias).
CREATE TABLE IF NOT EXISTS plazas_dia (
    turno  TEXT    NOT NULL REFERENCES tipos_turno (turno) ON UPDATE CASCADE ON DELETE CASCADE,
    dia    INTEGER NOT NULL,
    plazas INTEGER NOT NULL CHECK (plazas >= 0),
    maximo INTEGER CHECK (maximo IS NULL OR maximo >= 0),
    PRIMARY KEY (turno, dia)
);

CREATE TABLE IF NOT EXISTS dependientes (
    orden            INTEGER NOT NULL,
    acampado         TEXT PRIMARY KEY,
    sexo_monitor_req TEXT    NOT NULL DEFAULT '-' CHECK (sexo_monitor_req IN ('M', 'F', '-')),
    esfuerzo         REAL    NOT NULL,
    notas            TEXT    NOT NULL DEFAULT ''
);

-- Días en que el acampado no está en el campamento (en el Excel, un '-').
CREATE TABLE IF NOT EXISTS dependiente_ausente (
    acampado TEXT    NOT NULL REFERENCES dependientes (acampado) ON UPDATE CASCADE ON DELETE CASCADE,
    dia      INTEGER NOT NULL,
    PRIMARY KEY (acampado, dia)
);

-- La rejilla de turnos: una fila por casilla ocupada.
--   tipo 'turno'       clave = nombre del turno
--   tipo 'dependiente' clave = acampado
--   tipo 'descanso'    clave = ''
CREATE TABLE IF NOT EXISTS asignaciones (
    tipo    TEXT    NOT NULL CHECK (tipo IN ('turno', 'dependiente', 'descanso')),
    clave   TEXT    NOT NULL,
    dia     INTEGER NOT NULL,
    pos     INTEGER NOT NULL CHECK (pos >= 0),
    monitor TEXT    NOT NULL REFERENCES monitores (nombre) ON UPDATE CASCADE,
    fijada  INTEGER NOT NULL DEFAULT 0 CHECK (fijada IN (0, 1)),
    PRIMARY KEY (tipo, clave, dia, pos)
);
CREATE INDEX IF NOT EXISTS asignaciones_dia ON asignaciones (dia);
CREATE INDEX IF NOT EXISTS asignaciones_monitor ON asignaciones (monitor, dia);

CREATE TABLE IF NOT EXISTS fijaciones (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    dia     INTEGER NOT NULL,
    turno   TEXT    NOT NULL,
    monitor TEXT    NOT NULL REFERENCES monitores (nombre) ON UPDATE CASCADE,
    tipo    TEXT    NOT NULL CHECK (tipo IN ('OBLIGA', 'PROHIBE')),
    origen  TEXT    NOT NULL DEFAULT 'FIJACIONES'
);

CREATE TABLE IF NOT EXISTS restricciones (
    orden       INTEGER NOT NULL,
    nombre      TEXT PRIMARY KEY,
    activa      INTEGER NOT NULL CHECK (activa IN (0, 1)),
    tipo        TEXT    NOT NULL,
    descripcion TEXT    NOT NULL DEFAULT ''
);
"""


def abrir(ruta: str, crear: bool = False) -> sqlite3.Connection:
    """Abre la base de datos (con claves foráneas activas).

    Si no existe y `crear` es False, falla: así un error al escribir la ruta no
    crea una base de datos vacía por accidente.
    """
    existe = Path(ruta).exists()
    if not existe and not crear:
        raise FileNotFoundError(f"No existe la base de datos '{ruta}'")
    if not existe:
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(_DDL)
    con.execute("INSERT OR IGNORE INTO meta (clave, valor) VALUES ('esquema', ?)", (str(VERSION_ESQUEMA),))
    con.commit()
    return con
