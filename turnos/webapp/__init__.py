"""Interfaz web local (Flask) del optimizador de turnos.

Alternativa a `interfaz` (Streamlit): mismo Excel, mismas funciones de
`io_excel` e `interfaz.editor_datos` por debajo, pero con una rejilla propia
en HTML/JS en vez de `st.data_editor` (más cómoda para tablas grandes) y sin
ninguna dependencia cargada por red: todo el HTML/CSS/JS es estático y se
sirve desde este paquete, así que funciona sin conexión a internet.

No sustituye a `interfaz`: las dos interfaces conviven y leen/escriben el
mismo fichero Excel a través del mismo código.

Lanzar con:

    python -m turnos.webapp
"""
