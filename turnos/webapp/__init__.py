"""Interfaz web local (Flask) del optimizador de turnos.

Trabaja sobre el mismo Excel y las mismas funciones de `io_excel` que la CLI,
con una rejilla propia en HTML/JS y sin ninguna dependencia cargada por red:
todo el HTML/CSS/JS es estático y se sirve desde este paquete, así que
funciona sin conexión a internet.

No sustituye a `interfaz`: las dos interfaces conviven y leen/escriben el
mismo fichero Excel a través del mismo código.

Lanzar con:

    python -m turnos.webapp
"""
