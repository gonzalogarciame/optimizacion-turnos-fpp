# Instrucciones para programar el optimizador de turnos de campamento

> **Para el modelo que va a escribir el código.**
> Lee estas instrucciones enteras antes de escribir una sola línea. Programa en **Python**, con
> **Pyomo** como lenguaje de modelado y **Gurobi** como solver. Todo el código, los comentarios y
> los textos de interfaz van en **español**.
>
> **Fichero de entrada:** `TURNOS_2026_definitivo.xlsx` (se adjunta). Es a la vez la fuente de
> datos y el destino de la solución. No inventes columnas ni hojas: usa exactamente las que trae.

---

## 1. Qué hay que construir

Un sistema que:

1. **Lee** el Excel `TURNOS_2026_definitivo.xlsx` completo y lo valida.
2. **Construye y resuelve** un modelo de optimización lineal entera (MILP) que reparte los turnos
   de los monitores de un campamento durante los días 18–30 de julio de 2026.
3. **Escribe** la solución de vuelta al Excel, en la hoja `TURNOS`, respetando el formato visual
   de rejilla que se usa hoy a mano.
4. Permite **re-optimizar desde cualquier día**: lo anterior a ese día es dato inmutable, lo
   posterior se replanifica, y el usuario puede fijar celdas futuras a mano.
5. Tiene una **interfaz sencilla** (Streamlit) para ver los turnos, editar monitores y
   disponibilidad, fijar turnos y lanzar la optimización.
6. Está estructurado para **añadir restricciones nuevas sin tocar el núcleo**.

El Excel debe seguir siendo usable a mano: es la única fuente de verdad, no hay base de datos.

---

## 2. Estructura del Excel de entrada

El libro tiene 14 hojas. Estas son las que el modelo debe leer (las demás son documentación):

### 2.1 `CONFIG` — parámetros globales (pares clave/valor en columnas A y B)

| Clave | Valor | Significado |
|---|---|---|
| `QUINCENA` | 2 | Identificador |
| `AÑO` | 2026 | Año |
| `MES` | 7 | Mes (julio). Sirve para calcular qué días son fin de semana |
| `DIA_INICIO` | 18 | Primer día del horizonte |
| `DIA_FIN` | 30 | Último día |
| `DIA_REOPTIMIZACION` | 18 | **Los días estrictamente anteriores a este son fijos e inmutables** |
| `SOLVER` | gurobi | Solver |
| `TIME_LIMIT_S` | 120 | Límite de tiempo en segundos |
| `MIP_GAP` | 0.01 | Gap relativo de parada |
| `DIAS_DESCANSO_MINIMO` | 1 | Descansos deseados por ventana |
| `DIAS_VENTANA_DESCANSO` | 6 | Tamaño de la ventana |
| `W_FALTA` | 10000 | Peso de dejar un turno sin cubrir |
| `W_EQUIDAD` | 100 | Peso de la desigualdad de esfuerzo |
| `W_DESCANSO_LIM` | 30 | Peso de dar descanso a quien está pocos días |
| `W_VARIEDAD` | 20 | Peso de cada pareja monitor–dependiente distinta |
| `W_REPETICION` | 5 | Peso de repetir turno dos días seguidos |
| `W_FALTA_DESC` | 50 | Peso de incumplir el descanso mínimo |

Lee **todos** los pesos de aquí. **Nunca los pongas fijos en el código.**

### 2.2 `MONITORES` — una fila por monitor (82 en total)

| Columna | Contenido |
|---|---|
| `NOMBRE` | Clave primaria. Es lo que se ve en la rejilla |
| `SEXO` | `M` o `F` |
| `GRUPO` | `ANTIGUO` (37), `NUEVO` (26) o `FINDE` (19). Informativo |
| `PERMITE_DESCANSO` | `1` normal, `0` = **nunca recibe turno de descanso**. Los 19 de fin de semana llevan `0` |
| `PENALIZAR_DESCANSO` | `1` si conviene evitar darle descanso porque está pocos días (21 monitores). Penalización blanda, no prohibición |
| `DEPENDIENTE_1`, `DEPENDIENTE_2` | Acampados que este monitor ya tiene asignados (para referencia; la asignación real está en `ASIG_DEPENDIENTE`) |
| `DIAS_PRESENTE` | Fórmula de control, no la uses como dato |
| `DISPONIBILIDAD_TXT` | Texto original, solo documental. **No lo parsees**: la disponibilidad real está en la hoja `DISPONIBILIDAD` |

### 2.3 `DISPONIBILIDAD` — matriz monitor × día

Fila 1: `NOMBRE`, `18`, `19`, …, `30`. Cada celda tiene un código:

- `D` = disponible (puede recibir cualquier turno).
- `X` = ausente (no está ese día; **no puede recibir nada, ni siquiera descanso**).
- `R` = descanso impuesto por el usuario (no puede trabajar; ese día descansa obligatoriamente).

Distinguir `X` de `R` es esencial: `X` es "no forma parte del problema ese día"; `R` es "está,
pero se le asigna descanso a la fuerza".

### 2.4 `TIPOS_TURNO` — definición de los turnos de trabajo

| `TURNO` | `PLAZAS` | `SEXO_REQ` | `ESFUERZO` | `FILA_INI` | `FILA_FIN` |
|---|---|---|---|---|---|
| `lavaplatos` | 3 | `-` | 2 | 2 | 4 |
| `limpieza` | 5 | `-` | 2 | 5 | 9 |
| `cocina` | 3 | `-` | 2 | 10 | 12 |
| `comedor` | 4 | `-` | 2 | 13 | 16 |
| `paseo_piscina_siesta` | 4 | `-` | 2 | 17 | 20 |
| `vigilancia_chicos` | 2 | `M` | 2 | 21 | 22 |
| `vigilancia_chicas` | 2 | `F` | 2 | 23 | 24 |
| `vigilancia_D_chicos` | 1 | `M` | 2 | 25 | 25 |
| `vigilancia_D_chicas` | 1 | `F` | 2 | 26 | 26 |
| `descanso` | 0 | `-` | 0 | — | — |

- `SEXO_REQ`: `M` solo chicos, `F` solo chicas, `-` cualquiera.
- `ESFUERZO` y `PLAZAS` son **editables por el usuario**: léelos de esta hoja en cada ejecución.
- `FILA_INI`/`FILA_FIN` indican qué filas de la rejilla `TURNOS` ocupa cada bloque.
- `vigilancia_D_*` = **vigilancia de dependientes**. Es nocturna, igual que las otras vigilancias.
- Las **cuatro** vigilancias son nocturnas. `comedor` y `lavaplatos` son turnos distintos.

> Nota: en el fichero que se entrega todos los esfuerzos valen 2 y los de dependiente 3–4. Son
> valores que el usuario ajustará. El modelo debe funcionar con cualesquiera valores que
> encuentre en la hoja; no supongas un esfuerzo concreto.

### 2.5 `PLAZAS_POR_DIA` — plazas turno × día (sobrescribe a `TIPOS_TURNO`)

Matriz con las plazas necesarias de cada turno cada día. **Usa esta hoja como fuente de plazas**;
`TIPOS_TURNO.PLAZAS` es solo el valor por defecto. Los días 18 (llegada) y 30 (salida) tienen 0
plazas de `limpieza` y `paseo_piscina_siesta` porque hay menos actividad.

### 2.6 `DEPENDIENTES` — una fila por acampado dependiente (17 en total)

| Columna | Contenido |
|---|---|
| `ACAMPADO` | Clave. Nombre tal cual aparece en la columna A de la rejilla |
| `SEXO_MONITOR_REQ` | `M`, `F` o `-`. **El único campo que usa el modelo.** Sexo que debe tener el monitor que le atiende. `-` = cualquiera (niños pequeños) |
| `ESFUERZO` | Esfuerzo del turno de dependiente, **variable por acampado** (3–4 en el fichero). Mayor que el de cualquier turno normal |
| `FILA` | Fila que ocupa en la rejilla `TURNOS` |

Los 17 dependientes son: Albert, Alejandro Jara, David Sosa, Dylan Lopes Vara, Juan Daniel Duque,
Lucía Hernandez, Pablo Riveros, Sergio Salazar, Yamira, Yeray, Marcelo, David Cardozo,
Daniel Racionero, Damaris, **María, Silvia y Adriana**, Rayan y Abraham.

> `María, Silvia y Adriana` es un único dependiente (un grupo de tres niñas tratado como uno
> solo). Antes existía además una entrada `Casa Hogar` que era el mismo grupo duplicado; ya se ha
> eliminado. No la busques ni la recrees.

### 2.7 `ASIG_DEPENDIENTE` — matriz acampado × día, ya rellena

Cada celda contiene el monitor que atiende a ese dependiente ese día, o `-` si el acampado no
está presente. **En este fichero está completamente rellena a mano**: son datos de entrada fijos.

- Celda con nombre → asignación fija: el modelo la respeta, no la decide.
- Celda con `-` → el acampado no está ese día; no consume monitor.
- Celda vacía (no ocurre en este fichero, pero puede pasar) → la decide el modelo.

`Rayan` y `Abraham` están presentes solo los días 18–19, 24–26 y 30 (el resto `-`). Los demás
dependientes están los 13 días.

### 2.8 `FIJACIONES` — turnos de trabajo impuestos a mano

| `DIA` | `TURNO` | `NOMBRE` | `TIPO` |
|---|---|---|---|
| 19 | limpieza | Antonio Martin | OBLIGA |
| 24 | vigilancia_D_chicos | Antonio Martin | OBLIGA |
| 25 | lavaplatos | Antonio Martin | OBLIGA |
| 25 | vigilancia_chicas | Inés Morales | OBLIGA |
| 25 | vigilancia_chicas | Lucía Tourne | OBLIGA |
| 30 | comedor | Antonio Martin | OBLIGA |

`OBLIGA` ⇒ ese monitor hace ese turno ese día (fija la variable a 1). `PROHIBE` ⇒ la fija a 0.
Estas mismas fijaciones aparecen pintadas de amarillo en la rejilla `TURNOS`. Trata la hoja
`FIJACIONES` como fuente canónica, y **también** interpreta como fijación cualquier celda amarilla
que el usuario escriba en `TURNOS` en días ≥ `DIA_REOPTIMIZACION`.

### 2.9 `TURNOS` — la rejilla (entrada y salida)

Es el tablero visual. Estructura por filas:

- Fila 1: cabecera `TURNOS`, `DIA 18` … `DIA 30`.
- Filas 2–26: bloques de turno de trabajo, según `FILA_INI`/`FILA_FIN` de `TIPOS_TURNO`. La
  etiqueta del bloque está en la columna A con celdas combinadas.
- Filas 27–43: **una fila por dependiente** (17 filas), etiqueta = nombre del acampado. Aquí se
  vuelca `ASIG_DEPENDIENTE`.
- Fila 45 en adelante, bajo la etiqueta `DESCANSO`: lista de los monitores que descansan cada día
  (longitud variable). Este bloque lo regenera el sistema al escribir la solución.

Al **leer** para re-optimizar: por cada día `< DIA_REOPTIMIZACION`, cada nombre de la rejilla se
traduce a una asignación fija. Al **escribir**: solo se tocan las celdas de días
`≥ DIA_REOPTIMIZACION` que no estén fijadas.

### 2.10 `ALIAS` — apodos → nombre canónico

La rejilla usa apodos que no coinciden literalmente con `MONITORES` (`Gabi Sainz` →
`Gabriela Sainz`, `Tere GV` → `Teresa Garcia-Villaraco Gonzalez`, `Fati B` → `Fati Ballesteros`…).
**Antes de casar cualquier nombre de la rejilla contra `MONITORES`, pásalo por esta tabla.** Si
encuentras en la rejilla un nombre que no está ni en `MONITORES` ni en `ALIAS`, **aborta con un
error que indique la celda exacta** (p. ej. `TURNOS!F14: 'Sergio Rogríguez' no reconocido`). No lo
ignores en silencio.

Normaliza los nombres para comparar: minúsculas, sin tildes, sin espacios dobles.

### 2.11 `RESTRICCIONES` — interruptores de las reglas

Una fila por restricción, con `NOMBRE`, `ACTIVA` (0/1), `TIPO` (DURA/BLANDA) y `DESCRIPCIÓN`. El
constructor del modelo recorre esta hoja y aplica solo las que tengan `ACTIVA = 1`. Los nombres de
esta hoja son los mismos que usarás como identificadores de los módulos de restricción (§5).

### 2.12 `RESUMEN` — comprobación de factibilidad (solo fórmulas)

Para cada día calcula monitores disponibles (y por sexo), plazas necesarias, dependientes
presentes y la holgura. Úsalo tú también en la validación previa (§7): si algún día la holgura es
negativa, avisa antes de resolver.

---

## 3. Arquitectura del código

```
turnos/
├── config.py              # lee CONFIG -> objeto Config
├── nombres.py             # normalizar() y resolver_alias()
├── io_excel/
│   ├── lector.py          # Excel -> objeto Datos (validado)
│   └── escritor.py        # Solucion -> Excel (preserva formato y colores)
├── modelo/
│   ├── datos.py           # dataclasses: Monitor, TipoTurno, Dependiente, Datos, Solucion
│   ├── construir.py       # Datos -> ConcreteModel de Pyomo
│   ├── restricciones/     # una restricción = un módulo registrado
│   │   ├── base.py        # decorador @restriccion y REGISTRO
│   │   ├── r01_cobertura.py
│   │   └── ...
│   └── objetivo.py
├── resolver.py            # llama a Gurobi, extrae la solución
├── validar.py             # factibilidad previa + diagnóstico IIS
├── interfaz/app.py        # Streamlit
└── cli.py                 # python -m turnos optimizar --desde 24
```

**Regla de oro:** `construir.py` no lee del Excel. `lector.py` produce un objeto `Datos` ya
validado y el modelo solo consume `Datos`. Así el modelo se puede testear sin Excel.

### 3.1 Restricciones enchufables

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

`construir.py` recorre `REGISTRO`, mira en la hoja `RESTRICCIONES` cuáles están activas y aplica
solo esas. **Añadir una regla nueva = crear un fichero `rNN_*.py` y una fila en `RESTRICCIONES`.**
Documenta este mecanismo en el README con este mismo ejemplo.

---

## 4. Modelo matemático

### 4.1 Conjuntos

| Símbolo | Descripción |
|---|---|
| `M` | Monitores |
| `T` | Turnos de trabajo (todos los de `TIPOS_TURNO` menos `descanso`) |
| `D` | Días, de `DIA_INICIO` a `DIA_FIN` |
| `P` | Dependientes |

### 4.2 Variables

```
x[m,t,d] ∈ {0,1}   monitor m hace el turno t el día d
y[m,p,d] ∈ {0,1}   monitor m atiende al dependiente p el día d
r[m,d]   ∈ {0,1}   monitor m descansa el día d
z[m,p]   ∈ {0,1}   m atiende a p algún día (para contar variedad)
```

**Genera solo los índices válidos.** No crees `x[m,t,d]` si el monitor está ausente ese día
(`X`) o si su sexo no cumple `SEXO_REQ[t]`; no crees `y[m,p,d]` si el sexo no cumple
`SEXO_MONITOR_REQ[p]` o si el acampado no está presente; no crees `r[m,d]` si el monitor está
ausente o si `PERMITE_DESCANSO[m] = 0`. Un índice inexistente reduce el modelo; no lo modeles como
una variable fijada a 0. Guarda el conjunto de índices válidos de `x` en `m.x_idx` (y análogos)
para poder comprobar pertenencia en las reglas.

### 4.3 Variables de holgura (para no ser infactible por falta de gente)

```
falta[t,d] ≥ 0            plazas del turno t que quedan sin cubrir el día d
falta_desc[m,v] ≥ 0       incumplimiento del descanso mínimo en la ventana v
```

---

## 5. Restricciones

Los nombres coinciden con la hoja `RESTRICCIONES`. Cada una es un módulo enchufable.

### 5.1 Duras

**`cobertura`** — cada turno se cubre con sus plazas, con holgura:
```
∀ t, d:   Σ_m x[m,t,d] + falta[t,d] = plazas[t,d]      (plazas de PLAZAS_POR_DIA)
```

**`un_turno_por_dia`** — cada monitor presente hace exactamente una cosa al día:
```
∀ m, d con disponibilidad ∈ {D,R}:
   Σ_t x[m,t,d] + Σ_p y[m,p,d] + r[m,d] = 1
```
Esto ya impone que los turnos son **únicos por monitor y día**: trabajo, dependiente y descanso se
excluyen entre sí. (Si `PERMITE_DESCANSO[m]=0`, el término `r[m,d]` no existe y la suma es sobre
trabajo y dependiente.)

**`disponibilidad`** — si la celda es `X`, no existe ninguna variable para ese `(m,d)` (ya
garantizado al generar índices).

**`descanso_forzado`** — si la celda es `R`, entonces `r[m,d] = 1`.

**`sexo_turno`** — `vigilancia_chicos` y `vigilancia_D_chicos` solo chicos; `vigilancia_chicas` y
`vigilancia_D_chicas` solo chicas (ya garantizado al generar índices de `x`).

**`sexo_dependiente`** — `y[m,p,d]` solo existe si `SEXO_MONITOR_REQ[p] = '-'` o
`sexo[m] = SEXO_MONITOR_REQ[p]` (ya garantizado al generar índices de `y`).

**`finde_sin_descanso`** — `PERMITE_DESCANSO[m] = 0` ⇒ no existe `r[m,d]`. **Ojo:** combinado con
`un_turno_por_dia`, esto obliga a que cada monitor de fin de semana reciba trabajo o dependiente
cada día que está. Es una restricción fuerte. Comprueba en `RESUMEN` que hay plazas suficientes los
días 18–19 y 24–26. Si algún día no las hubiera, degrada esta regla a blanda (penaliza `r` con un
peso muy alto en vez de eliminar la variable) para no volver infactible el modelo.

**`vigilancia_no_comedor`** — quien hace cualquiera de las cuatro vigilancias una noche no puede ir
a comedor al día siguiente:
```
∀ m, d ∈ D\{último}:
   Σ_{t ∈ VIGILANCIA} x[m,t,d] + x[m,comedor,d+1] ≤ 1
```

**`cobertura_dependiente`** — cada dependiente presente tiene exactamente un monitor; si no está,
ninguno:
```
∀ p, d presente:      Σ_m y[m,p,d] = 1
∀ p, d no presente:   (no se generan variables)
```

**`asignacion_dep_fijada`** — se respeta `ASIG_DEPENDIENTE`: si la celda dice `m0`, entonces
`y[m0,p,d] = 1`. En este fichero eso fija **toda** la matriz `y`. El código debe funcionar igual si
en el futuro llega parcialmente vacía.

**`max_2_dependientes`** — un monitor atiende como mucho a 2 acampados distintos:
```
∀ m,p,d:  y[m,p,d] ≤ z[m,p]        ∀ m,p:  z[m,p] ≤ Σ_d y[m,p,d]
∀ m:      Σ_p z[m,p] ≤ 2
```

**`max_3_dias_por_dep`** — como mucho 3 días con el mismo acampado:
```
∀ m,p:   Σ_d y[m,p,d] ≤ MAX_DIAS_POR_DEP        (= 3, léelo de CONFIG si existe)
```

**`bloques_no_intercalados`** — si un monitor lleva dos acampados, primero termina con uno y luego
empieza con el otro (no alterna). Formulación con variable de orden `o[m,p1,p2] ∈ {0,1}`:
```
∀ m, p1<p2, días d1 ≥ d2:
   y[m,p1,d1] + y[m,p2,d2] ≤ 1 + o[m,p1,p2]
   y[m,p2,d1] + y[m,p1,d2] ≤ 2 - o[m,p1,p2]
```

**`dep_2_dias_tercero_descansa`** — dos días seguidos de dependiente obligan a descansar el tercero:
```
∀ m, d con d,d+1,d+2 ∈ D:
   Σ_p y[m,p,d] + Σ_p y[m,p,d+1] - 1 ≤ r[m,d+2]
```
Omite la restricción cuando `d+2 > DIA_FIN` (al final del campamento no hay tercer día) o cuando
`r[m,d+2]` no existe (monitor ausente o de fin de semana).

**`historico_inmutable`** — para días `< DIA_REOPTIMIZACION`, fija `x`, `y`, `r` a lo leído de la
rejilla con `.fix()` de Pyomo (no elimines las variables). Así las reglas que cruzan días
(`vigilancia_no_comedor`, `dep_2_dias_tercero_descansa`) siguen valiendo en la frontera de
re-optimización.

### 5.2 Muy importante: las reglas de dependiente NO se aplican a lo ya fijado

**Esto es lo que hará fracasar la implementación si se ignora.** La matriz `ASIG_DEPENDIENTE`
viene rellena a mano y **incumple a propósito** varias de las reglas anteriores. Comprobado sobre
el fichero que se entrega:

| Regla | Incumplimientos en el dato fijado |
|---|---|
| `max_3_dias_por_dep` | **11 monitores** hacen 4 días con el mismo acampado |
| `dep_2_dias_tercero_descansa` | **5 monitores** encadenan 3 días seguidos |
| `bloques_no_intercalados` | **3 monitores** alternan entre sus dos acampados |

Si generas esas tres restricciones sobre las variables `y` que ya están fijadas, **Gurobi
devuelve infactible en el primer intento**. Reglas de implementación:

1. Una restricción de dependiente **solo se genera sobre monitores cuyos `y` no estén todos
   fijados**. Si un monitor tiene toda su columna de dependiente dada por `ASIG_DEPENDIENTE` (el
   caso de este fichero), **no le apliques** `max_2_dependientes`, `max_3_dias_por_dep`,
   `bloques_no_intercalados` ni `dep_2_dias_tercero_descansa`.
2. Si en el futuro la matriz llega **parcialmente vacía**, sí genera la restricción: acota
   correctamente lo que queda libre.
3. **Reporta, no corrijas.** Si detectas un incumplimiento en el dato fijado, escríbelo en un
   informe (o en la hoja `REVISAR`), pero no reescribas lo que una persona decidió.

Consecuencia práctica en este fichero: como `y` está entera fijada, el modelo **solo decide `x` y
`r`** (los turnos de trabajo y los descansos). Las reglas de dependiente quedan satisfechas por
construcción y sirven para cuando el usuario deje días libres.

### 5.3 Blandas (holguras y penalizaciones en el objetivo)

- **`equidad_esfuerzo`** — reparte el esfuerzo (ver §6).
- **`penalizar_descanso_limitado`** — penaliza `r[m,d]` cuando `PENALIZAR_DESCANSO[m] = 1`.
- **`variedad_dependiente`** — penaliza `Σ z[m,p]` (menos parejas = menos variedad). Inactiva de
  hecho en este fichero porque `y` está fijada, pero déjala programada.
- **`no_repetir_turno`** — penaliza repetir el mismo turno dos días seguidos: variable
  `rep[m,t,d] ≥ x[m,t,d] + x[m,t,d+1] - 1`, penaliza `Σ rep`.
- **`descanso_minimo`** — en cada ventana de `DIAS_VENTANA_DESCANSO` días, cada monitor con
  presencia amplia debería tener al menos `DIAS_DESCANSO_MINIMO` descansos:
  `Σ_{d∈ventana} r[m,d] + falta_desc[m,v] ≥ DIAS_DESCANSO_MINIMO`, penaliza `Σ falta_desc`.

---

## 6. Función objetivo

Minimiza la suma ponderada:

```
min   W_FALTA        · Σ falta[t,d]
    + W_EQUIDAD      · (cmax - cmin)
    + W_DESCANSO_LIM · Σ_{m: PENALIZAR_DESCANSO=1, d} r[m,d]
    + W_VARIEDAD     · Σ z[m,p]
    + W_REPETICION   · Σ rep[m,t,d]
    + W_FALTA_DESC   · Σ falta_desc[m,v]
```

Esfuerzo de cada monitor (suma de trabajo y dependiente):
```
carga[m] = Σ_{t,d} esf[t]·x[m,t,d] + Σ_{p,d} esf_dep[p]·y[m,p,d]
```

Como cada monitor está presente un número distinto de días, **normaliza** dividiendo por los días
presentes (un parámetro, así sigue siendo lineal):
```
dias_presente[m] = nº de días con disponibilidad D o R
carga_norm[m] = carga[m] / dias_presente[m]
cmax ≥ carga_norm[m]  ∀m        cmin ≤ carga_norm[m]  ∀m
```

Minimizar `cmax - cmin` iguala el esfuerzo entre monitores — que es justo lo que pide el usuario
("un monitor de presencia completa ha de tener un esfuerzo similar al de los demás"). Si aparecen
soluciones degeneradas, resuelve en **dos fases**: fase 1 minimiza `cmax - cmin`; fase 2 fija
`cmax - cmin ≤ óptimo·(1+ε)` y optimiza el resto de términos.

> Con `y` fijada, la parte de dependiente de `carga[m]` es constante, pero **inclúyela igualmente**:
> forma parte del esfuerzo total y el reparto de los turnos de trabajo `x` debe compensar a quien ya
> carga con un dependiente.

---

## 7. Validación previa y diagnóstico

Antes de resolver, `validar.py` comprueba y reporta en lenguaje llano:

- Holgura por día (usa la lógica de `RESUMEN`): si es negativa, *"Día 22: hacen falta 40 monitores
  y hay 54 disponibles"* → en este fichero siempre es positiva, pero compruébalo.
- Por sexo: plazas de `vigilancia_chicos`/`vigilancia_D_chicos` frente a chicos disponibles; ídem
  chicas.
- Dependientes sin ningún monitor elegible ese día.
- Nombres de la rejilla no reconocidos en `MONITORES` ni `ALIAS` (con celda exacta).
- Fijaciones contradictorias (un monitor obligado a dos turnos el mismo día).

Si pese a las holguras Gurobi devuelve infactible, calcula el **IIS**
(`model.computeIIS()` por la interfaz de Gurobi) y traduce las restricciones del conflicto a
mensajes legibles. La causa más probable de infactibilidad es haber aplicado una regla de
dependiente sobre variables fijadas (§5.2): revísalo primero.

---

## 8. Re-optimización desde un día D

1. Lee `DIA_REOPTIMIZACION` de `CONFIG` (o del argumento `--desde D` de la CLI).
2. Para cada día `< D`, traduce cada nombre de la rejilla a una variable fijada (pasando por
   `ALIAS`). Si un nombre no se reconoce, aborta indicando la celda.
3. Para días `≥ D`, aplica `FIJACIONES` y las celdas amarillas de `TURNOS`.
4. Resuelve.
5. Escribe **solo** las celdas de días `≥ D` que no estén fijadas. Las columnas anteriores no se
   tocan.

Haz siempre una copia de seguridad con marca de tiempo antes de sobrescribir el Excel, y ofrece un
`--dry-run` que escriba a un fichero nuevo.

---

## 9. Escritura de la solución

En la hoja `TURNOS`, respetando el formato:

- Cada turno de trabajo: escribe los nombres asignados en las filas del bloque
  (`FILA_INI`..`FILA_FIN`).
- Dependientes: vuelca `ASIG_DEPENDIENTE` en sus filas (27–43).
- Bloque `DESCANSO`: regenera la lista de monitores que descansan cada día, ordenada
  alfabéticamente, longitud variable, limpiando las celdas sobrantes de ejecuciones previas.
- Colores: **amarillo** = celda fijada por el usuario; **gris claro** = día histórico
  (`< DIA_REOPTIMIZACION`); **sin relleno** = decidido en esta ejecución; **rojo** = conflicto
  detectado al leer.

Escribe el nombre canónico de `MONITORES`, no el apodo.

---

## 10. Interfaz (Streamlit)

Pantallas:

1. **Rejilla** — mismo layout que el Excel. Días `< D` en gris y bloqueados. Celdas futuras
   editables con un desplegable de monitores disponibles y elegibles ese día. Marcar una celda como
   fija la guarda en `FIJACIONES`.
2. **Monitores** — alta/baja, sexo, dependientes, `PERMITE_DESCANSO`, `PENALIZAR_DESCANSO`. Botón
   "añadir monitor" que crea la fila y su columna de disponibilidad.
3. **Disponibilidad** — editor matricial `D`/`X`/`R` con colores.
4. **Optimizar** — selector del día desde el que replanificar, botón "Optimizar", estado del solver
   (tiempo, gap), y panel de diagnóstico (§7).
5. **Informe** — carga por monitor (barras ordenadas), descansos por monitor, días de dependiente
   por monitor y por acampado, turnos sin cubrir.

Botones "Guardar en Excel" y "Descargar Excel". La interfaz lee y escribe sobre el Excel, no sobre
una base de datos, para preservar el uso manual.

---

## 11. Cómo validar que el sistema funciona

1. Carga `TURNOS_2026_definitivo.xlsx` con `DIA_REOPTIMIZACION = 18` (todo el horizonte por
   planificar, salvo lo fijado).
2. Resuelve. Debe encontrar solución factible (las holguras lo garantizan) y **cubrir todos los
   turnos** (`Σ falta` = 0), dado que la holgura es positiva todos los días.
3. Comprueba en la solución:
   - Ningún monitor con dos cosas el mismo día.
   - Ningún monitor de fin de semana con descanso.
   - Nadie que vigile una noche y vaya a comedor al día siguiente.
   - Las 6 fijaciones de `FIJACIONES` respetadas.
   - Esfuerzo normalizado repartido (mira `cmax - cmin`; debería ser pequeño).
4. Cambia `DIA_REOPTIMIZACION` a 24 y verifica que los días 18–23 salen idénticos a la ejecución
   anterior y solo cambian 24–30.
5. Prueba a poner una celda `X` de más en `DISPONIBILIDAD` un día ajustado y confirma que el
   diagnóstico lo detecta antes de resolver.

---

## 12. Resumen de las reglas del problema (checklist)

Reglas que el modelo debe cumplir, todas recogidas arriba:

1. Cada turno se cubre con el número de plazas indicado (con holgura penalizada). ✔ `cobertura`
2. Cada monitor hace **un solo turno al día** (trabajo, dependiente o descanso, excluyentes). ✔ `un_turno_por_dia`
3. Nadie recibe turno un día que está ausente. ✔ `disponibilidad`
4. Las vigilancias requieren el sexo correspondiente; los dependientes, el sexo de
   `SEXO_MONITOR_REQ` (o cualquiera si es `-`). ✔ `sexo_turno`, `sexo_dependiente`
5. Los monitores de fin de semana **no** tienen descanso. ✔ `finde_sin_descanso`
6. Quien vigila de noche no va a comedor al día siguiente (las cuatro vigilancias). ✔ `vigilancia_no_comedor`
7. Cada dependiente presente tiene exactamente un monitor. ✔ `cobertura_dependiente`
8. Se respetan las asignaciones de dependiente ya hechas a mano. ✔ `asignacion_dep_fijada`
9. Un monitor atiende como mucho a 2 acampados distintos. ✔ `max_2_dependientes`
10. Como mucho 3 días con el mismo acampado. ✔ `max_3_dias_por_dep`
11. Si lleva dos acampados, primero uno y después el otro (sin alternar). ✔ `bloques_no_intercalados`
12. Dos días seguidos de dependiente ⇒ el tercero, descanso. ✔ `dep_2_dias_tercero_descansa`
13. Los días anteriores a la re-optimización son inmutables. ✔ `historico_inmutable`
14. Reparto equitativo del esfuerzo entre monitores. ✔ `equidad_esfuerzo`
15. Se penaliza dar descanso a quien está pocos días. ✔ `penalizar_descanso_limitado`
16. Se debe poder **añadir restricciones nuevas fácilmente**. ✔ mecanismo enchufable (§3.1)

Las reglas 9–12 **no se aplican a monitores cuyo dependiente ya está fijado** (§5.2): es la clave
para que el modelo no nazca infactible con este fichero.
