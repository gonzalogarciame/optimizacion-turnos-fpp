"""bloques_no_intercalados: si un monitor lleva dos acampados, primero
termina con uno y luego empieza con el otro (no alterna entre ambos).

Variable de orden `o[m,p1,p2] ∈ {0,1}` (1 = p1 va antes que p2):

    ∀ m, p1<p2, días d1 ≥ d2:
        y[m,p1,d1] + y[m,p2,d2] ≤ 1 + o[m,p1,p2]
        y[m,p2,d1] + y[m,p1,d2] ≤ 2 - o[m,p1,p2]

Solo para monitores con `y` libre (§5.2): en el fichero de partida, 3
monitores ya alternan entre sus dos acampados en ASIG_DEPENDIENTE, así que
aplicarles esta regla dejaría el modelo infactible.
"""
from itertools import combinations

from pyomo.environ import Binary, Constraint, Set, Var

from .base import restriccion


@restriccion("bloques_no_intercalados")
def aplicar(m, datos, cfg):
    triples = []
    for mo in sorted(m.monitores_y_libre):
        deps_mo = sorted(p for (mz, p) in m.z_idx if mz == mo)
        for p1, p2 in combinations(deps_mo, 2):
            triples.append((mo, p1, p2))
    if not triples:
        return

    m.o_idx = Set(initialize=triples, dimen=3)
    m.o = Var(m.o_idx, domain=Binary)

    filas = []
    for (mo, p1, p2) in triples:
        for d1 in datos.dias:
            for d2 in datos.dias:
                if d1 < d2:
                    continue
                if (mo, p1, d1) in m.y_idx and (mo, p2, d2) in m.y_idx:
                    filas.append(("A", mo, p1, p2, d1, d2))
                if (mo, p2, d1) in m.y_idx and (mo, p1, d2) in m.y_idx:
                    filas.append(("B", mo, p1, p2, d1, d2))

    def regla(m, tipo, mo, p1, p2, d1, d2):
        if tipo == "A":
            return m.y[mo, p1, d1] + m.y[mo, p2, d2] <= 1 + m.o[mo, p1, p2]
        return m.y[mo, p2, d1] + m.y[mo, p1, d2] <= 2 - m.o[mo, p1, p2]

    m.c_bloques_no_intercalados = Constraint(filas, rule=regla)
