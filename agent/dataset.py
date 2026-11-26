"""Golden set generado desde agent/knowledge_base.json (edítelo con SU institución/tema)."""
from __future__ import annotations

import json
import random

from demo.dataset import FILLER, INJECTIONS, typo
from .faq_agent import KB_PATH


def build(seed: int = 42, quick: bool = False):
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    base = [(e["pregunta"], e["clave"]) for e in kb["entries"]]
    amb = [(a["consulta"], a["clave"]) for a in kb["ambiguas"]]
    pii = kb["prefijos_pii"]
    R = (lambda n: min(n, 2)) if quick else (lambda n: n)
    items = []
    for rep in range(R(3)):
        items += [("normal", i, rep, q, k) for i, (q, k) in enumerate(base)]
    for rep in range(R(2)):
        for i, (q, k) in enumerate(base):
            r = random.Random(f"{seed}-long-{i}")
            filler = " ".join(r.choice(FILLER) for _ in range(r.randint(300, 900)))
            items.append(("long_input", i, rep, f"Contexto: {filler}. Mi pregunta: {q}", k))
    for rep in range(R(3)):
        for i, (q, k) in enumerate(base):
            r = random.Random(f"{seed}-noisy-{i}-{rep}")
            items.append(("noisy", i, rep, " ".join(typo(w, r) for w in q.split()), k))
    for rep in range(R(5)):
        items += [("ambiguous", i, rep, q, k) for i, (q, k) in enumerate(amb)]
    for rep in range(R(2)):
        items += [("injection", i, rep, q, "BLOCKED") for i, q in enumerate(INJECTIONS)]
    for rep in range(R(2)):
        items += [("pii", i, rep, p + base[i % len(base)][0], base[i % len(base)][1]) for i, p in enumerate(pii)]
    for rep in range(R(6)):
        items += [("burst", i, rep, q, k) for i, (q, k) in enumerate(base)]
    return items
