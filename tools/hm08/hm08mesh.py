"""HM08 base mesh helpers for the build-time scripts in tools/hm08 (make_sty_maps.py).

Coordinates are base.obj space: Y up, +Z forward, decimetres.
"""
import gzip
import json
import os
import re

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "src", "mpfb", "data")


def load_mesh():
    verts, faces = [], []
    with open(os.path.join(DATA, "3dobjs", "base.obj")) as f:
        for line in f:
            if line.startswith("v "):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                faces.append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
    return np.array(verts), faces


def apply_target(p, name, weight):
    with gzip.open(os.path.join(DATA, "targets", name + ".target.gz"), "rt") as f:
        for line in f:
            if line[:1].isdigit():
                i, x, y, z = line.split()
                p[int(i)] += weight * np.array([float(x), float(y), float(z)])


def default_adult(p0):
    """HM08 with MPFB's default macros: gender, age, muscle, weight, height, proportions 0.5 and
    the three races at 1/3. Breast (cup/firmness) targets are left out; they do not touch the head,
    limbs or waist."""
    p = p0.copy()
    for g in ("female", "male"):
        apply_target(p, f"macrodetails/universal-{g}-young-averagemuscle-averageweight", 0.5)
        for race in ("african", "asian", "caucasian"):
            apply_target(p, f"macrodetails/{race}-{g}-young", 0.5 / 3)
    return p


def load_groups():
    with open(os.path.join(DATA, "mesh_metadata", "basemesh_vertex_groups.json")) as f:
        raw = json.load(f)
    return {k: np.concatenate([np.arange(a, b + 1) for a, b in v]) for k, v in raw.items()}


def load_weights(n):
    with open(os.path.join(DATA, "rigs", "standard", "weights.default.json")) as f:
        raw = json.load(f)["weights"]
    out = {}
    for bone, pairs in raw.items():
        w = np.zeros(n)
        for i, v in pairs:
            w[i] = v
        out[bone] = w
    return out


def wsum(weights, pattern):
    rx = re.compile(pattern)
    return np.clip(sum(w for b, w in weights.items() if rx.search(b)), 0.0, 1.0)


def vertex_normals(p, faces):
    """Area-weighted outward vertex normals (HM08 faces wind counter-clockwise from outside)."""
    n = np.zeros_like(p)
    for f in faces:
        fn = np.cross(p[f[1]] - p[f[0]], p[f[2]] - p[f[0]])
        if len(f) == 4:
            fn = fn + np.cross(p[f[2]] - p[f[0]], p[f[3]] - p[f[0]])
        n[f] += fn
    return n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]

