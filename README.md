# Optimizador de turnos del campamento (quincena del 18–30 de julio de 2026)

Sistema en Python + Pyomo + Gurobi que reparte los turnos de los monitores de
un campamento. El Excel `TURNOS_2026_definitivo.xlsx` es la **única fuente de
verdad**: de ahí se lee el problema y ahí se escribe la solución. No hay base
de datos.

- CLI: `python -m turnos validar|optimizar ...`
- Interfaz: `streamlit run turnos/interfaz/app.py`

Instrucciones completas del problema: [`INSTRUCCIONES_IMPLEMENTACION.md`](INSTRUCCIONES_IMPLEMENTACION.md).
Este README explica cómo se implementó, cómo se ejecuta y, sobre todo, cómo
**añadir restricciones nuevas** y **re-optimizar a mitad de quincena**.

---

## 1. Instalación

```bash
pip install -r requirements.txt
```

Necesitas una licencia de Gurobi (la que viene con `pip install gurobipy` es
de prueba y limita el modelo a 2000 variables/restricciones — este problema
genera del orden de 6000; ver §7 "Limitaciones conocidas"). Para desarrollar
o probar sin licencia real, cambia `CONFIG!SOLVER` a `appsi_highs` (solver
libre, ya incluido en `requirements.txt` vía `highspy`); el resto del
sistema funciona exactamente igual, solo cambia el motor de resolución.

## 2. Uso rápido

```bash
# Solo valida y muestra el informe de factibilidad, no resuelve nada
python -m turnos validar --excel TURNOS_2026_definitivo.xlsx

# Optimiza todo el horizonte (usa DIA_REOPTIMIZACION de CONFIG) y sobrescribe
# el Excel (con copia de seguridad automática con marca de tiempo)
python -m turnos optimizar --excel TURNOS_2026_definitivo.xlsx

# Re-optimiza solo desde el día 24 en adelante; 18-23 quedan intactos
python -m turnos optimizar --excel TURNOS_2026_definitivo.xlsx --desde 24

# Prueba sin tocar el fichero original (escribe en *_DRYRUN.xlsx)
python -m turnos optimizar --excel TURNOS_2026_definitivo.xlsx --dry-run
```

Interfaz interactiva:

```bash
streamlit run turnos/interfaz/app.py
```

## 3. Estructura del código

```
turnos/
├── config.py              # lee CONFIG -> objeto Config (todos los pesos W_* salen de aquí)
├── nombres.py              # normalizar() y ResolverNombres (apodos de la hoja ALIAS)
├── io_excel/
│   ├── lector.py            # Excel -> Datos, validado. Aborta con la celda exacta si algo no cuadra
│   └── escritor.py          # Solucion -> hoja TURNOS, preservando formato/colores
├── modelo/
│   ├── datos.py              # dataclasses: Config, Monitor, TipoTurno, Dependiente, Datos, Solucion
│   ├── construir.py          # Datos -> ConcreteModel de Pyomo (índices válidos + aplica RESTRICCIONES)
│   ├── objetivo.py           # suma ponderada de las penalizaciones registradas por los módulos
│   └── restricciones/        # una restricción = un módulo enchufable (ver §4)
│       ├── base.py             # decorador @restriccion, REGISTRO, registrar_penalizacion()
│       └── r01_...r20_*.py     # las 20 reglas de la hoja RESTRICCIONES
├── resolver.py             # llama al solver (nombre/tiempo/gap siempre desde CONFIG), extrae Solucion
├── validar.py              # validación previa en lenguaje llano (§7) + diagnóstico IIS si es infactible
├── interfaz/
│   ├── app.py                 # Streamlit: 5 pantallas (Rejilla, Monitores, Disponibilidad, Optimizar, Informe)
│   ├── estado.py               # st.session_state: carga el Excel una vez, lo comparte entre pantallas
│   └── editor_datos.py         # escribe MONITORES/DISPONIBILIDAD/FIJACIONES desde la interfaz
└── cli.py                  # `python -m turnos validar|optimizar`
```

**Regla de oro:** `modelo/construir.py` no importa `openpyxl` ni toca el
Excel para nada; solo consume el objeto `Datos` que produce `io_excel/lector.py`.
Por eso el modelo se puede testear con datos sintéticos, sin abrir ningún
fichero (ver `tests/`).

## 4. Cómo funcionan las restricciones enchufables

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

**Ojo con las reglas de dependiente.** `ASIG_DEPENDIENTE` puede venir
parcial o totalmente fijada a mano y **a propósito** incumplir reglas como
"máximo 3 días con el mismo acampado". Si tu regla nueva toca las variables
`y[m,p,d]`, sigue el patrón de `max_3_dias_por_dep.py` y compruébala solo
para monitores en `m.monitores_y_libre` (los que tienen al menos un `y`
libre, no fijado por los datos). Si no, el modelo puede nacer infactible en
el primer intento — es la causa nº 1 de infactibilidad de este sistema
(`validar.diagnosticar_infactibilidad` lo recuerda explícitamente en el
mensaje de IIS).

## 5. Re-optimizar: cómo funciona y cómo añadir restricciones nuevas a mitad de quincena

### 5.1 El mecanismo base (ya implementado)

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

Esto ya te permite, sin escribir código nuevo, re-optimizar cada vez que
pasan días: sube `DIA_REOPTIMIZACION` (o usa `--desde`) y lanza de nuevo. El
test de aceptación de este comportamiento está en
`tests/test_reoptimizacion.py` (y se comprobó a mano con el Excel real: los
días 18-23 salen carácter por carácter idénticos re-optimizando desde el 18
o desde el 24, ver §8).

Ese test usa `tests/fixtures/TURNOS_2026_definitivo_original.xlsx` (una
copia congelada del Excel de partida), no el Excel de la raíz del repo: ese
lo edita el usuario día a día, y sus datos reales pueden legítimamente dejar
de cumplir invariantes genéricos ("ningún monitor de FINDE descansa nunca")
en cuanto se llena un día de fijaciones manuales y `finde_sin_descanso` se
degrada a blanda a propósito (ver §5.1 'finde_sin_descanso' arriba). Los
tests necesitan un fichero estable para poder afirmar esos invariantes con
seguridad; si cambias la estructura del Excel de partida, actualiza también
el fixture.

### 5.2 Qué pasa si además de re-optimizar necesitas una **restricción nueva**

Este es el caso que probablemente te importa: han pasado unos días, el
campamento pide una regla que no estaba prevista (p. ej. "a partir de ahora,
nadie hace `cocina` dos veces en la misma ventana de 3 días") y quieres
aplicarla **solo hacia adelante**, sin retocar lo ya vivido.

Pasos:

1. **Escribe la restricción nueva** siguiendo la receta de §4. Escribe la
   regla pensando en el conjunto de días `datos.dias` completo (18–30): no
   hace falta que sepa nada de `DIA_REOPTIMIZACION`.
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
   `ASIG_DEPENDIENTE`, ver §5.2 de las instrucciones). En ese caso, filtra
   explícitamente `d >= cfg.dia_reoptimizacion` al construir los índices de
   tu restricción, exactamente como hacen `r12_max_3_dias_por_dep.py` o
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

### 5.3 Ejemplo completo

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
| ...`. Después: `python -m turnos optimizar --desde 25`.

Si en cambio la regla nueva SÍ debe respetar lo ya hecho como excepción del
pasado (p. ej. "a partir de ahora, máximo 2 noches de vigilancia por
semana" y algún monitor ya lleva 3 entre el 18 y el 24), hay que decidir
explícitamente qué hacer con ese monitor — igual que se decidió para
`ASIG_DEPENDIENTE` (§5.2 de las instrucciones): o se excluye de la regla
(patrón `monitores_y_libre`), o se penaliza en blando en vez de prohibir en
duro. Es una decisión de negocio, no técnica; el mecanismo para
implementarla ya está — es el filtro del paso 3.

## 6. Validación y diagnóstico de infactibilidad

`validar.py` reproduce en Python la misma lógica que la hoja `RESUMEN`
(holgura por día, por sexo, dependientes sin monitor elegible, fijaciones
contradictorias) y se ejecuta siempre antes de ofrecer el botón "Optimizar"
(o antes de resolver en la CLI, salvo `--forzar`).

Si aun así Gurobi devuelve infactible, `validar.diagnosticar_infactibilidad`
vuelve a resolver con la interfaz `gurobi_persistent` de Pyomo, calcula el
IIS nativo de Gurobi (`model.computeIIS()`) y traduce las restricciones (y
las variables fijadas) del conflicto a sus nombres de Pyomo, con un mensaje
que apunta primero a la causa más habitual: una restricción de dependiente
aplicada sobre `y` ya fijada por `ASIG_DEPENDIENTE` (§5.2 de las
instrucciones).

## 7. Limitaciones conocidas

- **Licencia de Gurobi.** `pip install gurobipy` instala una licencia de
  prueba limitada a 2000 variables y 2000 restricciones. Este problema, con
  los 82 monitores y 13 días del fichero de partida, genera del orden de
  6500 variables. Con esa licencia, Gurobi devuelve
  `GurobiError: Model too large for size-limited license`. Se necesita una
  licencia real (académica o comercial) para producción; para desarrollar o
  hacer pruebas de extremo a extremo sin ella, usa `CONFIG!SOLVER =
  appsi_highs` (solver libre sin límite de tamaño, mismo resultado
  estructural). Todo el pipeline (lectura, validación, construcción,
  resolución, escritura, IIS aparte) se probó de extremo a extremo con
  `appsi_highs` sobre el Excel real: solución óptima, 0 turnos sin cubrir,
  las 6 fijaciones respetadas, ningún monitor con dos cosas el mismo día,
  ningún monitor de fin de semana descansando, nadie vigilando y yendo a
  comedor al día siguiente, y re-optimizar desde el día 24 deja 18–23
  carácter por carácter idénticos a la solución original.
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

## 8. Cómo se comprobó (checklist de las instrucciones, §11)

Ejecutado sobre `TURNOS_2026_definitivo.xlsx` con `appsi_highs`:

1. `DIA_REOPTIMIZACION=18` (todo por planificar): solución óptima, gap 0%.
2. `Σ falta = 0`: todos los turnos cubiertos.
3. Comprobado por código (no a ojo, ver historial de la sesión de
   desarrollo): 0 monitores con dos cosas el mismo día; 0 descansos
   indebidos de monitores de fin de semana; 0 casos de vigilancia seguida de
   comedor al día siguiente; las 6 filas de `FIJACIONES` respetadas;
   `cmax - cmin ≈ 2.6` (esfuerzo repartido).
4. Cambiado `DIA_REOPTIMIZACION` a 24 sobre el Excel ya resuelto: los días
   18–23 salen exactamente iguales (0 diferencias de celda); 24–30 se
   recalculan (255 de 889 celdas cambian, mismo objetivo óptimo — hay
   múltiples soluciones igual de buenas).
5. La detección de nombres no reconocidos y de holgura negativa se
   comprobó por inspección de código (`lector._validar_historico_completo`,
   `nombres.ResolverNombres.resolver`, `validar._validar_holgura_por_dia`);
   quien quiera repetirlo a mano: borra una celda de `DISPONIBILIDAD` y pon
   una `X` de más un día ajustado, y confirma que `python -m turnos validar`
   lo señala antes de intentar resolver.
