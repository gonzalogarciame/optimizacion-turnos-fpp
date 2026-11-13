# Optimizador de turnos — Fundación Proyecto Persona

Sistema en Python que reparte automáticamente los turnos de los monitores
en los campamentos de la **Fundación Proyecto Persona** (limpieza, cocina,
comedor, vigilancia nocturna, atención a acampados dependientes...),
respetando la disponibilidad de cada monitor, las reglas de cada campamento
y repartiendo el esfuerzo de forma equitativa.

No está atado a un campamento ni a una quincena concreta: **cada campamento
o quincena tiene su propio Excel** en `datos/`, y ese Excel es la única
fuente de verdad (no hay base de datos). Cualquier persona que organice
turnos en la Fundación puede usarlo, mientras su Excel siga la misma
estructura de hojas que se describe más abajo.

- CLI: `python -m turnos validar|optimizar --excel datos/<campamento>/turnos.xlsx`
- Interfaz visual (Streamlit): `streamlit run turnos/interfaz/app.py`
- Interfaz web local (sin Streamlit): `python -m turnos.webapp`, luego abrir
  `http://127.0.0.1:5000` en el navegador. Es una tabla turnos × días donde
  se edita cada casilla con un selector de monitores, también en días ya
  pasados, y desde la que se lanza el optimizador a partir de un día
  concreto (ver §4.1). Todo el HTML/CSS/JS es estático (sin CDN ni
  dependencias de red): funciona sin conexión a internet. Lee y escribe el
  mismo Excel que las otras dos interfaces.

---

## 1. Objetivo del proyecto

Antes de este sistema, cuadrar los turnos de cada quincena se hacía a mano
sobre un Excel, comprobando uno a uno que no se rompiera ninguna regla
(disponibilidad, sexo requerido en vigilancia, descansos, dependientes...).
Este proyecto automatiza esa tarea con un modelo de optimización (MILP,
resuelto con Gurobi o el solver libre HiGHS), manteniendo el Excel como
interfaz: quien coordina el campamento sigue viendo y pudiendo tocar la
misma rejilla de siempre.

Objetivos concretos:

- **Cubrir todos los turnos** de cada día respetando quién está disponible,
  su sexo cuando el turno lo requiere, y las asignaciones de dependientes
  ya decididas a mano.
- **Repartir el esfuerzo de forma equitativa** entre monitores, en función
  de los días que cada uno está presente.
- **Permitir re-optimizar a mitad de campamento**: cuando pasan los días,
  lo ya vivido no se toca y solo se replanifica lo que queda por delante.
- **Ser extensible por campamento**: cada regla es un módulo independiente,
  activable/desactivable desde el propio Excel, y añadir una regla nueva no
  requiere tocar el resto del código (ver §7).
- **Servir para cualquier campamento o quincena de la Fundación**, no solo
  para el que se usó para construir el sistema: basta con preparar un Excel
  con la misma estructura de hojas (ver §5).

## 2. Instalación

```bash
pip install -r requirements.txt
```

Hace falta un solver de optimización lineal entera:

- **Gurobi** (recomendado para campamentos grandes): `pip install gurobipy`
  instala una licencia de prueba, pero está limitada a 2000
  variables/restricciones — este tipo de problema genera del orden de 6000
  con ~80 monitores y 13 días, así que en producción hace falta una
  licencia real (académica o comercial).
- **HiGHS** (gratuito, sin límite de tamaño): ya incluido en
  `requirements.txt` vía `highspy`. Para usarlo, pon `SOLVER = appsi_highs`
  en la hoja `CONFIG` del Excel del campamento. El resto del sistema
  funciona exactamente igual, solo cambia el motor que resuelve el modelo.

## 3. Estructura del repositorio

```
datos/                      # Un Excel por campamento/quincena — la fuente de verdad
├── 2026-quincena2-18al30jul/
│   ├── turnos.xlsx            # Excel en uso: se lee y se sobrescribe al optimizar
│   └── turnos_backup_*.xlsx   # Copias de seguridad automáticas (con fecha y hora)
└── <nuevo-campamento>/        # Cada campamento nuevo crea su propia carpeta (ver §6)
turnos/                     # Código del sistema
tests/                      # Pruebas automáticas
requirements.txt
```

Al optimizar, el sistema hace siempre una copia de seguridad del Excel con
marca de tiempo antes de sobrescribirlo (`turnos_backup_AAAAMMDD_HHMMSS.xlsx`,
en la misma carpeta del campamento), así que el historial de versiones de
cada quincena queda guardado y es fácil volver atrás si algo sale mal.

## 4. Uso rápido

```bash
# Solo valida y muestra el informe de factibilidad, no resuelve nada
python -m turnos validar --excel datos/2026-quincena2-18al30jul/turnos.xlsx

# Optimiza todo el horizonte (usa DIA_REOPTIMIZACION de la hoja CONFIG) y
# sobrescribe el Excel (con copia de seguridad automática)
python -m turnos optimizar --excel datos/2026-quincena2-18al30jul/turnos.xlsx

# Re-optimiza solo desde el día 24 en adelante; los días anteriores no se tocan
python -m turnos optimizar --excel datos/2026-quincena2-18al30jul/turnos.xlsx --desde 24

# Prueba sin tocar el fichero original (escribe en *_DRYRUN.xlsx)
python -m turnos optimizar --excel datos/2026-quincena2-18al30jul/turnos.xlsx --dry-run
```

Interfaz interactiva (ver y editar la rejilla, monitores, disponibilidad, y
lanzar la optimización desde el navegador):

```bash
streamlit run turnos/interfaz/app.py
```

### 4.1 Interfaz web: la rejilla

`python -m turnos.webapp` y abrir `http://127.0.0.1:5000` (desde la raíz del
repo; usa el Excel indicado en `turnos/webapp/estado.py` o el que se escriba
en la cabecera). La pantalla **Rejilla** es una tabla con los turnos en filas
y los días en columnas, leída directamente de la hoja `TURNOS`:

- **Editar una casilla:** clic (o teclear directamente sobre ella) y elegir
  monitor en el buscador. Sirve el apodo de la hoja `ALIAS`. Si el monitor ya
  tiene otro puesto ese día, se **intercambia** con el ocupante de la casilla.
  `Supr` vacía, las flechas mueven, `Ctrl+Z` deshace. Los cambios son un
  borrador hasta pulsar **Guardar** (que hace antes la copia de seguridad).
- **Corregir días ya vividos:** todas las casillas son editables, también las
  de días anteriores al de re-optimización. La fila «Sin puesto» cuenta, para
  cada día, los monitores disponibles que no aparecen en ningún turno,
  dependiente ni descanso; en un día congelado debe quedar a 0 o el generador
  se negará a arrancar.
- **Fijar:** una casilla escrita a mano en un día que se va a regenerar queda
  *fijada* (amarillo): el optimizador la respeta. Se desmarca en el selector.
- **Generar desde un día:** se elige el día (o se hace clic en su cabecera) y
  se pulsa «Generar turnos». Todo lo anterior queda congelado. El resultado
  aparece como **propuesta** (en verde lo que cambia) y no se escribe nada
  hasta pulsar «Aplicar y guardar», que hace copia de seguridad y deja
  `DIA_REOPTIMIZACION` de `CONFIG` en ese día (así la CLI también respeta lo
  congelado). «Descartar» no toca el Excel.
- **Plazas por día (🧩):** cuántas plazas hay que cubrir cada día en cada turno y
  hasta cuántas personas *acepta* como máximo. Un turno con 0 necesarias «no
  existe» ese día (llegada, salida). Se abre desde el botón de arriba, desde el
  icono de la cabecera de un día o haciendo clic en el contador de un turno
  (`3/3`). Permite copiar un día a otros y avisa de si hay sitio para los
  monitores de fin de semana. Si un turno pasa a aceptar más gente de la que
  cabe en su bloque, la rejilla **crece sola** (se insertan filas en `TURNOS`).
- **Turnos para WhatsApp (📲):** texto con los turnos de un día (por defecto con
  dependientes y sin descanso), con la opción «solo nombre de pila», listo para
  copiar o abrir en WhatsApp. Refleja lo que se ve en pantalla, también una
  propuesta aún sin aplicar.
- Los monitores con `PERMITE_DESCANSO = 0` (fin de semana) llevan la etiqueta
  `finde` en el selector y la pantalla avisa si alguno acaba en descanso.
- Si el solver de `CONFIG` no funciona en el equipo (Gurobi sin licencia o con
  la licencia caducada), el generador reintenta solo con HiGHS y lo avisa.

## 5. Estructura de datos: el Excel de un campamento

Cada campamento se describe en un único libro Excel con estas hojas (las
demás hojas del libro son solo documentación y no las lee el sistema):

| Hoja | Contenido |
|---|---|
| `CONFIG` | Parámetros globales: fechas del horizonte, día desde el que re-optimizar, solver a usar, y los pesos (`W_*`) que ponderan cada penalización blanda. |
| `MONITORES` | Una fila por monitor: nombre, sexo, si puede recibir turno de descanso, si conviene priorizarle el descanso, dependientes que ya tiene asignados. |
| `DISPONIBILIDAD` | Matriz monitor × día. Cada celda: `D` disponible, `X` ausente (no participa ese día), `R` descanso impuesto por el usuario. |
| `TIPOS_TURNO` | Los turnos de trabajo que existen (limpieza, cocina, comedor, vigilancia...), sus plazas por defecto, el sexo que requieren y su esfuerzo. |
| `PLAZAS_POR_DIA` | Plazas necesarias de cada turno cada día (sobrescribe el valor por defecto de `TIPOS_TURNO`). |
| `PLAZAS_MAX_POR_DIA` | *Opcional.* Máximo de personas que acepta cada turno cada día (vacío = solo las necesarias). Ver §5.1. |
| `DEPENDIENTES` | Acampados que necesitan un monitor asignado: sexo de monitor requerido y esfuerzo del turno. |
| `ASIG_DEPENDIENTE` | Matriz acampado × día con el monitor que le atiende (o `-` si no está presente ese día). Puede venir parcial o totalmente rellena a mano. |
| `FIJACIONES` | Turnos de trabajo impuestos a mano (`OBLIGA`/`PROHIBE` un monitor en un turno un día concreto). Las celdas amarillas de `TURNOS` cuentan igual que una fila aquí. |
| `TURNOS` | La rejilla visual: turnos de trabajo, dependientes y descansos por día. Es a la vez lo que se lee (para los días ya vividos) y lo que se escribe (la solución). |
| `ALIAS` | Apodos que usa la rejilla y que no coinciden literalmente con `MONITORES` (p. ej. `Tere GV` → `Teresa Garcia-Villaraco Gonzalez`). |
| `RESTRICCIONES` | Interruptor de cada regla del modelo: `NOMBRE`, `ACTIVA` (0/1), `TIPO` (dura/blanda). Ver §7. |
| `RESUMEN` | Hoja de fórmulas que calcula la holgura de cada día (monitores disponibles frente a plazas necesarias); el sistema usa la misma lógica para avisar antes de resolver. |

### 5.1 Turnos que aceptan más gente (`PLAZAS_MAX_POR_DIA`)

Los monitores de fin de semana (`PERMITE_DESCANSO = 0`) prefieren no
descansar, pero el día de llegada y el de salida hay pocos turnos, así que
puede sobrar gente. Sin más información, el modelo no tiene dónde ponerlos y
acaba mandando a descansar a alguno de ellos.

`PLAZAS_MAX_POR_DIA` (misma disposición que `PLAZAS_POR_DIA`) dice cuántas
personas *acepta como máximo* cada turno cada día. En `cobertura`, cada persona
por encima de las plazas necesarias es una variable `extra` que cuesta
`W_EXTRA` (por defecto 40, clave opcional de `CONFIG`): menos que obligar a
descansar a un monitor de fin de semana, más que dejar descansar a quien puede,
así que los extras solo aparecen cuando de verdad hacen falta. Sin la hoja, o
con celdas vacías, el modelo es exactamente el de antes. Lo ya escrito en la
rejilla por encima de las plazas (histórico o celdas fijadas) amplía por sí
solo el tope de ese día para que nunca vuelva infactible el modelo.

La hoja se crea y se edita desde la pantalla «Plazas por día»; también se puede
rellenar a mano.

## 6. Preparar el Excel de un campamento nuevo

Para usar el sistema en un campamento o quincena distinto:

1. Copia el Excel de un campamento existente (por ejemplo
   `datos/2026-quincena2-18al30jul/turnos.xlsx`) como plantilla: mantiene la
   estructura de hojas y el formato de la rejilla `TURNOS`.
2. Guárdalo en una carpeta nueva dentro de `datos/`, con un nombre que
   identifique el campamento y las fechas (p. ej.
   `datos/2027-quincena1-01al15jul/turnos.xlsx`).
3. Rellena `CONFIG` (fechas, día de inicio de re-optimización, solver),
   `MONITORES`, `DISPONIBILIDAD`, `TIPOS_TURNO`, `PLAZAS_POR_DIA`,
   `DEPENDIENTES` y `ASIG_DEPENDIENTE` con los datos reales del nuevo
   campamento. Activa en `RESTRICCIONES` solo las reglas que apliquen.
4. Ejecuta `python -m turnos validar --excel datos/<campamento>/turnos.xlsx`
   para comprobar que no faltan plazas ni hay datos contradictorios antes de
   optimizar.

Si el campamento necesita una regla que no existe todavía (p. ej. un límite
propio de ese campamento), añádela como módulo nuevo siguiendo la receta del
§7 — no hace falta duplicar el proyecto.

## 7. Arquitectura del código

```
turnos/
├── config.py              # lee CONFIG -> objeto Config (todos los pesos W_* salen de aquí)
├── nombres.py              # normalizar() y ResolverNombres (apodos de la hoja ALIAS)
├── io_excel/
│   ├── lector.py            # Excel -> Datos, validado. Aborta con la celda exacta si algo no cuadra
│   ├── escritor.py          # Solucion -> hoja TURNOS, preservando formato/colores
│   ├── rejilla.py           # hoja TURNOS "tal cual" (cualquier día) <-> edición celda a celda de la web
│   └── estructura.py        # guardar plazas/PLAZAS_MAX_POR_DIA y ampliar bloques de TURNOS (inserta filas)
├── modelo/
│   ├── datos.py              # dataclasses: Config, Monitor, TipoTurno, Dependiente, Datos, Solucion
│   ├── construir.py          # Datos -> ConcreteModel de Pyomo (índices válidos + aplica RESTRICCIONES)
│   ├── objetivo.py           # suma ponderada de las penalizaciones registradas por los módulos
│   └── restricciones/        # una restricción = un módulo enchufable (ver §7.1)
│       ├── base.py             # decorador @restriccion, REGISTRO, registrar_penalizacion()
│       └── r01_...r20_*.py     # las reglas activables desde la hoja RESTRICCIONES
├── resolver.py             # llama al solver (nombre/tiempo/gap siempre desde CONFIG), extrae Solucion
├── validar.py              # validación previa en lenguaje llano + diagnóstico IIS si es infactible
├── interfaz/
│   ├── app.py                 # Streamlit: Rejilla, Monitores, Disponibilidad, Turnos y dependientes,
│   │                            #   Restricciones, Optimizar, Informe
│   ├── estado.py               # st.session_state: carga el Excel una vez, lo comparte entre pantallas
│   └── editor_datos.py         # escribe MONITORES/DISPONIBILIDAD/TIPOS_TURNO/DEPENDIENTES/RESTRICCIONES/
│                                #   CONFIG/FIJACIONES desde cualquiera de las dos interfaces (sin Streamlit)
├── webapp/                 # interfaz web local alternativa (sin Streamlit), ver más abajo
│   ├── server.py              # rutas Flask: JSON fino sobre io_excel/interfaz.editor_datos/resolver;
│   │                            #   la generación corre en un hilo y el cliente consulta su progreso
│   ├── estado.py               # equivalente a interfaz/estado.py pero sin st.session_state
│   ├── static/rejilla.js       # pantalla Rejilla: tabla editable, selector, propuesta del optimizador
│   ├── static/herramientas.js  # diálogos «Plazas por día» y «Turnos para WhatsApp»
│   ├── static/app.js           # navegación y resto de páginas (monitores, disponibilidad, ...)
│   └── templates/index.html    # página única, navegación por JS
└── cli.py                  # `python -m turnos validar|optimizar`
```

**Regla de oro:** `modelo/construir.py` no importa `openpyxl` ni toca el
Excel para nada; solo consume el objeto `Datos` que produce `io_excel/lector.py`.
Por eso el modelo se puede testear con datos sintéticos, sin abrir ningún
fichero (ver `tests/`).

### 7.1 Cómo funcionan las restricciones enchufables

Cada restricción de la hoja `RESTRICCIONES` es un módulo Python independiente
en `modelo/restricciones/`. `modelo/construir.py` recorre el registro,
consulta en la hoja cuáles tienen `ACTIVA = 1` y llama solo a esas — en
ningún otro sitio del código hay una lista fija de reglas.

```python
# modelo/restricciones/base.py
REGISTRO = {}

def restriccion(nombre, tipo="DURA"):
    def deco(fn):
        REGISTRO[nombre] = {"fn": fn, "tipo": tipo}
        return fn
    return deco
```

```python
# modelo/restricciones/r08_vigilancia_no_comedor.py
from pyomo.environ import Constraint
from .base import restriccion

VIGILANCIA = ["vigilancia_chicos", "vigilancia_chicas",
              "vigilancia_D_chicos", "vigilancia_D_chicas"]

@restriccion("vigilancia_no_comedor")
def aplicar(m, datos, cfg):
    dias = datos.dias
    def regla(m, mon, i):
        d, d1 = dias[i], dias[i + 1]
        izq = sum(m.x[mon, t, d] for t in VIGILANCIA if (mon, t, d) in m.x_idx)
        if (mon, "comedor", d1) not in m.x_idx:
            return Constraint.Skip
        return izq + m.x[mon, "comedor", d1] <= 1
    m.c_vigilancia_no_comedor = Constraint(
        m.MONITORES, range(len(dias) - 1), rule=regla)
```

### Añadir una restricción nueva (receta paso a paso)

1. Crea `modelo/restricciones/r21_tu_regla.py` siguiendo el patrón de arriba.
   - Si es **dura**: añade un `Constraint` al modelo `m` (o usa `.fix()` si
     lo que quieres es fijar variables, como hace `historico_inmutable`).
   - Si es **blanda**: construye las variables de holgura que necesites y
     llama a `registrar_penalizacion(m, "tu_regla", expresion_sin_ponderar)`.
     Luego añade tu regla al diccionario `PESO_POR_PENALIZACION` de
     `modelo/objetivo.py` apuntando al peso de `CONFIG` que quieras usar (o
     crea un peso `W_TU_REGLA` nuevo en la hoja `CONFIG` y en `config.py`).
2. Impórtalo en `modelo/restricciones/__init__.py` (una línea:
   `from . import r21_tu_regla`).
3. Añade una fila en la hoja `RESTRICCIONES` del Excel con
   `NOMBRE=tu_regla`, `ACTIVA=1`, `TIPO=DURA` o `BLANDA`.

No hace falta tocar `construir.py`, `objetivo.py` (salvo el paso 1 si es
blanda) ni ningún otro módulo existente. Para desactivar una regla sin
borrar el código, basta con poner `ACTIVA=0` en esa fila de la hoja.

**Índices, no variables fijadas a 0.** Sigue la convención del resto de
módulos: si una combinación (monitor, turno, día) no es válida (ausente,
sexo no cumple...), que simplemente no exista en `m.x_idx` / `m.y_idx` /
`m.r_idx`, no la modeles como una variable que fuerzas a 0. Reduce el
tamaño del modelo y evita bugs de restricciones que se aplican sobre
variables que no deberían existir.

**Ojo con las reglas de dependiente.** La matriz `ASIG_DEPENDIENTE` puede
venir parcial o totalmente fijada a mano y, en la práctica, **incumplir a
propósito** reglas como "máximo 3 días con el mismo acampado" (porque una
persona ya decidió esa excepción antes de que existiera el sistema). Si tu
regla nueva toca las variables `y[m,p,d]`, sigue el patrón de
`max_3_dias_por_dep.py` y compruébala solo para monitores en
`m.monitores_y_libre` (los que tienen al menos un `y` libre, no fijado por
los datos). Si no, el modelo puede nacer infactible en el primer intento —
es la causa nº 1 de infactibilidad de este sistema
(`validar.diagnosticar_infactibilidad` lo recuerda explícitamente en el
mensaje de IIS).

## 8. Re-optimizar: cómo funciona y cómo añadir restricciones nuevas a mitad de campamento

### 8.1 El mecanismo base (ya implementado)

`DIA_REOPTIMIZACION` (hoja `CONFIG`, o `--desde` en la CLI / el selector de
la pantalla "Optimizar") es la frontera: **todo lo que hay a la izquierda de
ese día es dato, no decisión.**

- **Al leer** (`io_excel/lector.py`): para cada día `< DIA_REOPTIMIZACION`,
  cada nombre que hay escrito en la rejilla `TURNOS` se traduce en una
  asignación fija (pasando por la hoja `ALIAS` si hace falta). Si un día
  histórico está incompleto (un monitor disponible sin nada asignado), la
  lectura aborta con un mensaje claro en vez de adivinar.
- **Al construir el modelo** (`historico_inmutable`, un módulo enchufable
  más): esas asignaciones se fijan con `.fix()` de Pyomo — no se eliminan
  las variables. Esto es clave: las reglas que cruzan la frontera de
  re-optimización (`vigilancia_no_comedor` mirando si el día `D-1` alguien
  vigiló, `dep_2_dias_tercero_descansa` mirando dos días atrás) siguen
  funcionando con normalidad porque la variable del día histórico existe,
  solo que ya no es libre.
- **Al escribir** (`io_excel/escritor.py`): solo se tocan las celdas de días
  `>= DIA_REOPTIMIZACION` que no estén fijadas a mano (amarillo). Las
  columnas de días anteriores no se reescriben (si acaso, se les aplica el
  relleno gris para marcarlas como histórico).

Esto ya permite, sin escribir código nuevo, re-optimizar cada vez que pasan
días: sube `DIA_REOPTIMIZACION` (o usa `--desde`) y lanza de nuevo. El test
de aceptación de este comportamiento está en `tests/test_reoptimizacion.py`.

Ese test usa `tests/fixtures/TURNOS_2026_definitivo_original.xlsx` (una
copia congelada de un Excel de partida), no los ficheros de `datos/`: esos
los edita cada campamento día a día, y sus datos reales pueden legítimamente
dejar de cumplir invariantes genéricos ("ningún monitor de fin de semana
descansa nunca") en cuanto se llena un día de fijaciones manuales. Los tests
necesitan un fichero estable para poder afirmar esos invariantes con
seguridad; si cambias la estructura del Excel de partida, actualiza también
el fixture.

### 8.2 Qué pasa si además de re-optimizar necesitas una restricción nueva

Caso típico: han pasado unos días, el campamento pide una regla que no
estaba prevista (p. ej. "a partir de ahora, nadie hace `cocina` dos veces en
la misma ventana de 3 días") y quieres aplicarla **solo hacia adelante**,
sin retocar lo ya vivido.

Pasos:

1. **Escribe la restricción nueva** siguiendo la receta de §7.1. Escribe la
   regla pensando en el conjunto de días `datos.dias` completo: no hace
   falta que sepa nada de `DIA_REOPTIMIZACION`.
2. **No tienes que hacer nada especial para que respete el pasado.** En
   cuanto tu regla usa `m.x_idx` / `m.y_idx` / `m.r_idx`, automáticamente
   hereda el `.fix()` de `historico_inmutable`: si tu restricción genera,
   por ejemplo, una desigualdad `x[m,'cocina',d] + x[m,'cocina',d+1] +
   x[m,'cocina',d+2] <= 1`, y `d` es un día histórico con `x[m,'cocina',d]`
   fijado a 1, Pyomo simplemente trata ese término como una constante en la
   desigualdad — el efecto práctico es que la regla ya actúa "solo hacia
   adelante" sin que tengas que filtrar nada por `dia >= DIA_REOPTIMIZACION`
   dentro de tu módulo.
3. **Excepción: si tu regla nueva sería incumplida por el histórico ya
   escrito.** Con datos reales, a veces el pasado ya viola informalmente lo
   que ahora quieres exigir hacia adelante (igual que pasa con
   `ASIG_DEPENDIENTE`, ver §7.1). En ese caso, filtra explícitamente
   `d >= cfg.dia_reoptimizacion` al construir los índices de tu
   restricción, exactamente como hacen `r12_max_3_dias_por_dep.py` o
   `r14_dep_2_dias_tercero_descansa.py` con `m.monitores_y_libre`. Patrón:

   ```python
   @restriccion("tu_regla_nueva")
   def aplicar(m, datos, cfg):
       dias_libres = [d for d in datos.dias if d >= cfg.dia_reoptimizacion]
       ...  # construye la restricción solo sobre dias_libres
   ```

   Esto es exactamente lo mismo que ya hace `historico_inmutable`, aplicado
   a tu propia regla en vez de a `x`/`y`/`r` directamente.
4. **Actívala solo desde ahora, no retroactivamente:** añade la fila en
   `RESTRICCIONES` con `ACTIVA=1` y listo — como el histórico ya está fijado
   por `.fix()`, "activar la regla" nunca puede invalidar lo ya ocurrido, en
   el peor caso simplemente no tiene efecto sobre los días pasados.
5. **Vuelve a resolver con `--desde` apuntando al primer día libre** (o el
   que corresponda). Ojo: `--desde` (o `DIA_REOPTIMIZACION`) debe ser **igual
   o posterior** al último día que ya se ejecutó de verdad en el campamento;
   bajarlo por debajo de eso reabriría días que ya pasaron de verdad (el
   sistema no lo impide técnicamente — no tiene forma de saber qué día es
   "hoy" en la vida real — así que es responsabilidad de quien lo ejecuta).

### 8.3 Ejemplo completo

Supongamos que estamos en el día 25 (ya se vivieron 18–24) y el campamento
decide que, a partir de ahora, **nadie puede hacer `vigilancia_chicos` y
`vigilancia_chicas` en la misma quincena** (antes no había tope). Esto no
mira al pasado (no hay que "deshacer" nada de 18–24, ni penalizar lo ya
ocurrido), así que no necesita el filtro del paso 3:

```python
# modelo/restricciones/r21_no_mezclar_vigilancias.py
from pyomo.environ import Constraint
from .base import restriccion

@restriccion("no_mezclar_vigilancias")
def aplicar(m, datos, cfg):
    def regla(m, mo):
        chicos = sum(m.x[mo, t, d] for t in ("vigilancia_chicos", "vigilancia_D_chicos")
                     for d in datos.dias if (mo, t, d) in m.x_idx)
        chicas = sum(m.x[mo, t, d] for t in ("vigilancia_chicas", "vigilancia_D_chicas")
                     for d in datos.dias if (mo, t, d) in m.x_idx)
        # si ya vigiló de un tipo en el pasado (fijado), esta suma ya no es 0/variable:
        # es una constante >=1, y la restricción simplemente prohíbe la otra variable libre.
        if isinstance(chicos, int) and isinstance(chicas, int):
            return Constraint.Skip  # ninguno de los dos términos tiene variables libres
        return chicos + chicas <= max(1, ...)  # ajusta la cota a lo que pida el campamento
    m.c_no_mezclar_vigilancias = Constraint(m.MONITORES, rule=regla)
```

Y en la hoja `RESTRICCIONES`: fila nueva `no_mezclar_vigilancias | 1 | DURA
| ...`. Después: `python -m turnos optimizar --excel datos/<campamento>/turnos.xlsx --desde 25`.

Si en cambio la regla nueva SÍ debe respetar lo ya hecho como excepción del
pasado (p. ej. "a partir de ahora, máximo 2 noches de vigilancia por
semana" y algún monitor ya lleva 3 entre el 18 y el 24), hay que decidir
explícitamente qué hacer con ese monitor — igual que se decidió para
`ASIG_DEPENDIENTE`: o se excluye de la regla (patrón `monitores_y_libre`), o
se penaliza en blando en vez de prohibir en duro. Es una decisión de
negocio, no técnica; el mecanismo para implementarla ya está — es el filtro
del paso 3.

## 9. Validación y diagnóstico de infactibilidad

`validar.py` reproduce en Python la misma lógica que la hoja `RESUMEN`
(holgura por día, por sexo, dependientes sin monitor elegible, fijaciones
contradictorias) y se ejecuta siempre antes de ofrecer el botón "Optimizar"
(o antes de resolver en la CLI, salvo `--forzar`).

Si aun así el solver devuelve infactible, `validar.diagnosticar_infactibilidad`
vuelve a resolver con la interfaz `gurobi_persistent` de Pyomo, calcula el
IIS nativo de Gurobi (`model.computeIIS()`) y traduce las restricciones (y
las variables fijadas) del conflicto a sus nombres de Pyomo, con un mensaje
que apunta primero a la causa más habitual: una restricción de dependiente
aplicada sobre `y` ya fijada por `ASIG_DEPENDIENTE` (§7.1).

## 10. Tests

```bash
python -m pytest tests/
```

- `tests/test_construir_sintetico.py` — construye el modelo con datos
  sintéticos (sin Excel) y comprueba que las restricciones se generan bien.
- `tests/test_rejilla.py` — lectura/escritura casilla a casilla de la rejilla web.
- `tests/test_plazas_extra.py` — turnos que aceptan más gente (modelo sintético y
  Excel), y que ampliar la rejilla no pierde ni mueve ningún dato.
- `tests/test_reoptimizacion.py` — comprueba, sobre el fixture congelado
  `tests/fixtures/TURNOS_2026_definitivo_original.xlsx`, que re-optimizar
  desde un día posterior deja intactos, celda por celda, los días anteriores.

## 11. Limitaciones conocidas

- **Licencia de Gurobi.** `pip install gurobipy` instala una licencia de
  prueba limitada a 2000 variables y 2000 restricciones. Un campamento
  típico (decenas de monitores, ~2 semanas) genera del orden de 6000
  variables, así que con esa licencia Gurobi devuelve
  `GurobiError: Model too large for size-limited license`. Se necesita una
  licencia real (académica o comercial) para producción; para desarrollar o
  probar sin ella, usa `SOLVER = appsi_highs` en `CONFIG` (solver libre sin
  límite de tamaño, mismo resultado estructural).
- **Colores de fijación.** La detección de "celda amarilla" en `TURNOS`
  compara el RGB del relleno contra una lista blanca de amarillos
  habituales de Excel (ver `RGB_AMARILLO` en `io_excel/lector.py`). Si
  algún día se pinta con un amarillo de tema/theme distinto, no se
  reconocerá como fijación automáticamente; usa la hoja `FIJACIONES`, que sí
  es siempre fuente canónica.
- **Alta/baja de monitores desde la interfaz.** Borrar una fila en la
  pantalla "Monitores" no borra su fila en `DISPONIBILIDAD` ni su histórico
  en `TURNOS` (para no perder datos por accidente); la interfaz avisa y deja
  la limpieza fina para hacerla a mano en el Excel.
- **Edición de `ASIG_DEPENDIENTE` desde la interfaz.** No está expuesta en
  la pantalla "Rejilla" (se muestra de solo lectura); edítala directamente
  en la hoja del Excel. El motivo es que, a diferencia de los turnos de
  trabajo, cada celda de dependiente tiene semántica propia (presente/no
  presente/decidir) que no encaja bien en una rejilla de texto libre.
