#!/usr/bin/env python3
"""Build the HM08 `stylized-default` target (STYLIZED_SPEC.md §6.1).

Build-time source only: the result is later baked into sty01's rest shape (§5), it is not
shipped as a user target.

Every edit is a smooth deformation of the HM08 base mesh (all 19,158 vertices, helpers and
joint cubes included, so fitting and rigging follow). Regions come from the default rig's skin
weights, which give soft, symmetric masks for free. Coordinates are base.obj space: Y up,
+Z forward, decimetres.

    python3 tools/hm08/make_stylized_default.py            # writes stylized-default.target.gz
    python3 tools/hm08/make_stylized_default.py --measure  # prints the head/height check only
"""
import argparse
import gzip
import io
import json
import os
import re

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "src", "mpfb", "data")
OUT = os.path.join(HERE, "stylized-default.target.gz")

# §6.1 scales, relative to the HM08 default. "default" is the anime-leaning look the user chose on
# PRXJX2 (much more stylized, facial detail left to textures). "subtle" is the first §6.1 table,
# kept only so the renders can show how far the default moved.
PRESETS = {
    "default": dict(HEAD=1.08, CRANIUM=0.97, EYES=1.22, FLATTEN=0.80, HANDS=1.12, FEET=1.10,
                    NECK=1.06, SHOULDERS=1.06, WAIST=0.96, LOWER_LEG=1.03, SIMPLIFY=0.90,
                    NOSE=0.80, MOUTH=0.82, JAW=0.90, FACE_SIMPLIFY=1.0,
                    EYE_FORWARD=0.025, EAR_FILL=1.0, NOSE_OUT=0.055, MOUTH_OUT=0.045,
                    FACE_DETAIL=1.0),
    "subtle": dict(HEAD=1.08, CRANIUM=1.04, EYES=1.12, FLATTEN=0.40, HANDS=1.12, FEET=1.10,
                   NECK=1.10, SHOULDERS=1.06, WAIST=0.96, LOWER_LEG=1.03, SIMPLIFY=0.85,
                   NOSE=1.0, MOUTH=1.0, JAW=1.0, FACE_SIMPLIFY=0.0,
                   EYE_FORWARD=0.0, EAR_FILL=0.0, NOSE_OUT=0.0, MOUTH_OUT=0.0,
                   FACE_DETAIL=0.0),
}
# HEAD: uniform; CRANIUM: on top of HEAD, above the brow; FLATTEN: share of nostril flare
# relief removed; NECK: thickness, X and Z; SHOULDERS: width at the shoulder joints;
# SIMPLIFY: share of the body's fine relief (muscle, folds, creases) removed. Face: NOSE scales
# the nose toward the cheek plane; MOUTH scales the mouth and lips; JAW narrows the lower face
# toward a smaller chin; FACE_SIMPLIFY takes out the face's mid-scale relief (lid creases,
# philtrum, lip volume, nasolabial folds, brow ridge) so features read from the texture.
# EYE_FORWARD (dm) brings the eyes and lids toward the face's front plane; EAR_FILL is the share
# of the ear's concha and folds filled up toward the rim. NOSE_OUT and MOUTH_OUT (dm) bring the
# nose and the mouth with its surround forward as whole forms, so the smaller features still
# stand out of the face instead of reading flat. FACE_DETAIL is the share of the face's small
# ridges and bumps (cheekbone edge, lip corners, lid rims, nasolabial ridge) cut down after the
# fill: the fill pass only raises, so the ridges between creases stayed.
SIMPLIFY_PASSES = 40  # Taubin passes; sets the scale of relief that counts as detail
FACE_PASSES = 60  # the face pass reaches broader forms: whole lips, lids, the nose bridge
DETAIL_T = 2.0e4  # lowpass4 strength: forms a few edges across go, ~30 edges across stay

LIMB = re.compile(r"^(spine|neck|clavicle|shoulder|upperarm|lowerarm|wrist|metacarpal|finger|"
                  r"pelvis|upperleg|lowerleg|foot|toe|breast|root)")


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
    limbs or waist this target edits."""
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


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def neighbours(n, faces):
    nb = [set() for _ in range(n)]
    for f in faces:
        for i, a in enumerate(f):
            nb[a].update(f[:i] + f[i + 1:])
    return [np.array(sorted(s)) if s else np.array([i]) for i, s in enumerate(nb)]


def laplacian_smooth(p, nb, iterations):
    q = p.copy()
    for _ in range(iterations):
        q = np.array([q[ix].mean(0) for ix in nb])
    return q


def taubin_smooth(p, faces, verts, passes, lam=0.5, mu=-0.53):
    """Low-pass of the surface over `verts` that keeps volume (Taubin 1995): fingers and ears do
    not shrink the way they do under plain Laplacian smoothing. Open-boundary vertices (eye and
    mouth openings) stay put."""
    import scipy.sparse as sp
    keep = np.zeros(len(p), bool)
    keep[verts] = True
    edges = {}
    for f in faces:
        if not keep[f].all():
            continue
        for a, b in zip(f, f[1:] + f[:1]):
            k = (min(a, b), max(a, b))
            edges[k] = edges.get(k, 0) + 1
    e = np.array(list(edges))
    boundary = np.zeros(len(p), bool)
    boundary[e[np.array(list(edges.values())) == 1].ravel()] = True
    n = len(p)
    adj = sp.coo_matrix((np.ones(2 * len(e)), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])),
                        shape=(n, n)).tocsr()
    deg = np.asarray(adj.sum(1)).ravel()
    move = keep & ~boundary & (deg > 0)
    avg = sp.diags(np.where(deg > 0, 1.0 / np.maximum(deg, 1), 0.0)) @ adj
    q = p.copy()
    for _ in range(passes):
        for f in (lam, mu):
            q[move] += f * (avg @ q - q)[move]
    return q


def lowpass4(p, faces, verts, t):
    """Least-squares low-pass over `verts`: q minimises |q - p|^2 + t |M^2 q|^2, M the graph
    Laplacian over 4. Its response 1 / (1 + t k^4) is flat at low frequency, so broad forms keep
    their place and size (no shrinking, unlike Laplacian smoothing), and falls steeply, so
    mid-scale relief goes in one solve where Taubin would need thousands of passes. Open-boundary
    vertices (eye and mouth openings) and everything outside `verts` are held."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl
    n = len(p)
    keep = np.zeros(n, bool)
    keep[verts] = True
    edges, uses = set(), {}
    for f in faces:
        for a, b in zip(f, f[1:] + f[:1]):
            k = (min(a, b), max(a, b))
            edges.add(k)
            if keep[f].all():
                uses[k] = uses.get(k, 0) + 1
    e = np.array(sorted(edges))
    boundary = np.zeros(n, bool)
    boundary[np.array([k for k, c in uses.items() if c == 1]).ravel()] = True
    adj = sp.coo_matrix((np.ones(2 * len(e)), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])),
                        shape=(n, n)).tocsr()
    m = (sp.diags(np.asarray(adj.sum(1)).ravel()) - adj) / 4.0
    m4 = (m @ m) @ (m @ m)
    free = np.nonzero(keep & ~boundary)[0]
    held = np.nonzero(~(keep & ~boundary))[0]
    a = (sp.identity(len(free)) + t * m4[free][:, free]).tocsc()
    rhs = p[free] - t * (m4[free][:, held] @ p[held])
    q = p.copy()
    q[free] = np.column_stack([spl.spsolve(a, rhs[:, i]) for i in range(3)])
    return q


def fill_height(h, faces, verts, iterations):
    """Fill-only relaxation of the scalar field `h` over `verts`: each step raises a vertex to its
    neighbours' mean where that is higher, so pits fill up to the level of what rings them and
    nothing is lowered. Vertices with a neighbour outside `verts` are held."""
    import scipy.sparse as sp
    keep = np.zeros(len(h), bool)
    keep[verts] = True
    e = set()
    for f in faces:
        for a, b in zip(f, f[1:] + f[:1]):
            e.add((min(a, b), max(a, b)))
    e = np.array(sorted(e))
    n = len(h)
    adj = sp.coo_matrix((np.ones(2 * len(e)), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])),
                        shape=(n, n)).tocsr()
    deg = np.asarray(adj.sum(1)).ravel()
    inside = np.asarray(adj @ keep.astype(float)).ravel()
    move = keep & (inside == deg) & (deg > 0)
    avg = sp.diags(1.0 / np.maximum(deg, 1)) @ adj
    q = h.copy()
    for _ in range(iterations):
        q[move] = np.maximum(q, avg @ q)[move]
    return q


def vertex_normals(p, faces):
    """Area-weighted outward vertex normals (HM08 faces wind counter-clockwise from outside)."""
    n = np.zeros_like(p)
    for f in faces:
        fn = np.cross(p[f[1]] - p[f[0]], p[f[2]] - p[f[0]])
        if len(f) == 4:
            fn = fn + np.cross(p[f[2]] - p[f[0]], p[f[3]] - p[f[0]])
        n[f] += fn
    return n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]


def scale_about(p, w, pivot, s):
    """Blend p toward a uniform (or per-axis) scale about pivot by per-vertex weight w."""
    return p + w[:, None] * (np.asarray(s) - 1.0) * (p - pivot)


def build(p0, faces, groups, weights, preset="default"):
    s = PRESETS[preset]
    HEAD, CRANIUM, EYES, FLATTEN = s["HEAD"], s["CRANIUM"], s["EYES"], s["FLATTEN"]
    HANDS, FEET, NECK, SHOULDERS = s["HANDS"], s["FEET"], s["NECK"], s["SHOULDERS"]
    WAIST, LOWER_LEG, SIMPLIFY = s["WAIST"], s["LOWER_LEG"], s["SIMPLIFY"]
    NOSE, MOUTH, JAW, FACE_SIMPLIFY = s["NOSE"], s["MOUTH"], s["JAW"], s["FACE_SIMPLIFY"]
    NOSE_OUT, MOUTH_OUT = s["NOSE_OUT"], s["MOUTH_OUT"]
    EYE_FORWARD, EAR_FILL, FACE_DETAIL = s["EYE_FORWARD"], s["EAR_FILL"], s["FACE_DETAIL"]
    p = p0.copy()
    jc = lambda name: p[groups[name]].mean(0)
    side = np.sign(p0[:, 0])
    body = groups["body"]

    w_face = np.clip(sum(w for b, w in weights.items() if not LIMB.match(b)), 0.0, 1.0)
    w_neck = wsum(weights, r"^neck")
    w_hand = {s: wsum(weights, rf"^(wrist|metacarpal|finger).*\.{s}$") for s in "LR"}
    w_foot = {s: wsum(weights, rf"^(foot|toe).*\.{s}$") for s in "LR"}
    w_arm = wsum(weights, r"^(shoulder01|upperarm|lowerarm|wrist|metacarpal|finger)") + \
        0.5 * wsum(weights, r"^clavicle")
    w_torso = wsum(weights, r"^(spine|pelvis)")

    # Lower leg +3%: everything below the knee moves down in proportion to its distance below it,
    # so the shin stretches and the foot travels with the ankle.
    knee_y, ankle_y = jc("joint-l-knee")[1], jc("joint-l-ankle")[1]
    p[:, 1] -= (LOWER_LEG - 1.0) * np.clip(knee_y - p0[:, 1], 0.0, knee_y - ankle_y)

    # Feet +10% about the ankle column at sole height, so soles stay flat.
    for sd, j in (("L", "joint-l-ankle"), ("R", "joint-r-ankle")):
        a = jc(j)
        pivot = np.array([a[0], p[body, 1].min(), a[2]])
        p = scale_about(p, w_foot[sd], pivot, FEET)

    # Hands +12% about the wrist joint.
    for sd, j in (("L", "joint-l-hand"), ("R", "joint-r-hand")):
        p = scale_about(p, w_hand[sd], jc(j), HANDS)

    # Waist -4%: X/Z squeeze of the torso, peaking at the narrowest torso height.
    torso = body[(np.abs(p0[body, 0]) < 1.6) & (p0[body, 1] > 1.0) & (p0[body, 1] < 4.0)
                 & (w_torso[body] > 0.9)]
    ys = np.linspace(1.5, 3.8, 24)
    widths = [np.ptp(p0[torso][np.abs(p0[torso, 1] - y) < 0.05, 0]) for y in ys]
    waist_y = ys[int(np.argmin(widths))]
    band = np.exp(-((p0[:, 1] - waist_y) / 0.7) ** 2) * w_torso
    axis = np.array([0.0, 0.0, p0[torso, 2].mean()])
    p = scale_about(p, band, axis, [WAIST, 1.0, WAIST])

    # Shoulders +6%: the arms (and half the clavicle) shift out by 6% of the shoulder joint width.
    sh_x = jc("joint-l-shoulder")[0]
    p[:, 0] += (SHOULDERS - 1.0) * sh_x * side * np.clip(w_arm, 0.0, 1.0)

    # Neck +10% thicker, X/Z about the neck's own axis; the head is masked out.
    neck_c = p[w_neck > 0.5].mean(0)
    w_neck_core = smoothstep(0.1, 0.5, w_neck) * (1.0 - w_face)
    p = scale_about(p, w_neck_core, np.array([0.0, 0.0, neck_c[2]]), [NECK, 1.0, NECK])

    # Head +8% about the top of the neck.
    neck_top = jc("joint-neck") * 0.5 + jc("joint-head") * 0.5
    p = scale_about(p, w_face, neck_top, HEAD)

    # Cranium -3% against the +8% head: weighted from the brow up, so the crown comes down and the
    # forehead is shorter (PRXJX2: "forehead too large", the growing cranium read as alien). The
    # pivot sits on the forehead's front, so the forehead stays put and only the crown and the
    # back of the skull move: a pivot at the head's centre dished the profile.
    eye_y = jc("joint-l-eye")[1]
    front_head = body[(np.abs(p[body, 0]) < 0.1) & (np.abs(p[body, 1] - eye_y - 0.4) < 0.1)]
    w_cran = w_face * smoothstep(eye_y - 0.1, eye_y + 0.6, p[:, 1])
    p = scale_about(p, w_cran, np.array([0.0, eye_y, p[front_head, 2].max()]), CRANIUM)

    # Eye sockets and lids +12% about each eyeball centre; the eyeball helpers ride along (D6).
    # +12% is against the default adult, so the head's +8% is divided out here.
    for j, helper in (("joint-l-eye", "helper-l-eye"), ("joint-r-eye", "helper-r-eye")):
        c = jc(j)
        r_eye = np.linalg.norm(p[groups[helper]] - c, axis=1).max()
        r = np.linalg.norm(p - c, axis=1)
        p = scale_about(p, 1.0 - smoothstep(r_eye * 1.3, r_eye * 2.6, r), c, EYES / HEAD)
        # Eyes sit closer to the face's front plane, so they stop reading as deep sockets.
        p[:, 2] += EYE_FORWARD * (1.0 - smoothstep(r_eye * 1.5, r_eye * 3.2, r))

    # Nostril flare: remove FLATTEN of the relief left after smoothing. Ears are kept out: a
    # Laplacian flatten collapses the thin helix rim and leaves the concha as a hole (PRXJX2:
    # "ears look like mere holes"); the face fill below simplifies them instead.
    nb = neighbours(len(p), faces)
    smooth = laplacian_smooth(p, nb, 8)
    front = body[np.abs(p0[body, 0]) < 0.4]
    nose_tip = p[front[np.argmax(p[front, 2] * (p0[front, 1] > eye_y - 0.8) * (p0[front, 1] < eye_y))]]
    nostrils = nose_tip + np.array([0.0, -0.12, -0.12])
    w_flat = (1.0 - smoothstep(0.14, 0.26, np.linalg.norm(p - nostrils, axis=1))) * \
        smoothstep(nostrils[1] - 0.16, nostrils[1] - 0.06, p[:, 1])  # stop above the upper lip
    head_band = body[(np.abs(p0[body, 1] - eye_y) < 0.4) & (w_face[body] > 0.9)]
    w_ear = np.zeros(len(p))
    for sd in (1.0, -1.0):
        cand = head_band[side[head_band] == sd]
        ear = p[cand[np.argmax(np.abs(p[cand, 0]))]] - np.array([sd * 0.1, 0.0, 0.0])
        w_ear = np.maximum(w_ear, 1.0 - smoothstep(0.25, 0.45, np.linalg.norm(p - ear, axis=1)))
    w_flat[~np.isin(np.arange(len(p)), body)] = 0.0
    p = p - (FLATTEN * w_flat)[:, None] * (p - smooth)

    # Nose and mouth shrink only what stands in front of the face around them, so the cheeks,
    # brow and philtrum stay where they are. (Scaling the whole region toward a pivot inside the
    # head pulled the midface in with them and made the face concave on PRXJX2.)
    # Nose: its height above the cheek plane scales by NOSE; the part that stands out also
    # narrows and shortens toward the nose's centre. Faded out above the eye line and below the
    # nostrils.
    if NOSE != 1.0:
        hs = HEAD  # offsets below are in default-adult decimetres; the head has been scaled
        cheek = front_face = body[(w_face[body] > 0.9) & (p0[body, 2] > 0.8)]
        cheek = cheek[(np.abs(p[cheek, 0]) > 0.30 * hs) & (np.abs(p[cheek, 0]) < 0.36 * hs)
                      & (np.abs(p[cheek, 1] - nose_tip[1] - 0.15 * hs) < 0.15 * hs)]
        cheek_z = np.median(p[cheek, 2])
        h = np.maximum(p[:, 2] - cheek_z, 0.0)
        w = np.isin(np.arange(len(p)), front_face) * \
            (1.0 - smoothstep(0.20 * hs, 0.30 * hs, np.abs(p[:, 0]))) * \
            (1.0 - smoothstep(eye_y - 0.15 * hs, eye_y + 0.05 * hs, p[:, 1])) * \
            smoothstep(nose_tip[1] - 0.14 * hs, nose_tip[1] - 0.08 * hs, p[:, 1])
        t = w * smoothstep(0.0, 0.12 * hs, h)
        nose_mid = nose_tip[1] + 0.12 * hs
        p[:, 2] -= (1.0 - NOSE) * w * h
        p[:, 0] -= (1.0 - NOSE) * t * p[:, 0]
        p[:, 1] -= (1.0 - NOSE) * t * (p[:, 1] - nose_mid)

    # Mouth: narrower and shorter about the lip centre, in the face's own plane, and the lips'
    # height above the philtrum/chin line scales by MOUTH^1.5 (flatter, simpler lips).
    mouth = jc("joint-mouth")  # the jaw's hinge, level with the nose; not the lips
    hs = HEAD
    mid = front[(p[front, 1] < nose_tip[1] - 0.12 * hs) & (p[front, 1] > nose_tip[1] - 0.40 * hs)
                & (w_face[front] > 0.9)]
    lip = p[mid[np.argmax(p[mid, 2])]]
    if MOUTH != 1.0:
        base_z = lip[2] - 0.06 * hs
        w = w_face * (1.0 - smoothstep(0.30 * hs, 0.45 * hs, np.abs(p[:, 0]))) * \
            (1.0 - smoothstep(0.10 * hs, 0.18 * hs, np.abs(p[:, 1] - lip[1]))) * \
            smoothstep(base_z - 0.25 * hs, base_z, p[:, 2])
        p[:, 0] -= (1.0 - MOUTH) * w * p[:, 0]
        p[:, 1] -= (1.0 - MOUTH) * w * (p[:, 1] - lip[1])
        p[:, 2] -= (1.0 - MOUTH ** 1.5) * w * np.maximum(p[:, 2] - base_z, 0.0)

    # Jaw: narrow the lower face toward a smaller chin, from the cheekbones down.
    if JAW != 1.0:
        w_jaw = w_face * (1.0 - smoothstep(mouth[1] - 0.05, nose_tip[1] + 0.05, p[:, 1]))
        w_jaw *= smoothstep(jc("joint-jaw")[2] - 0.3, jc("joint-jaw")[2] + 0.4, p[:, 2])
        p = scale_about(p, w_jaw, np.array([0.0, mouth[1], 0.0]), [JAW, 1.0, 1.0])

    # Nose and mouth forward (PRXJX2: "face is too flat, pull nose and mouth slightly outward").
    # Each moves as a whole, with a smooth falloff about a centre set behind the feature, so the
    # nostrils, philtrum and lip corners come along and no edge or crease forms; the cheeks, eyes
    # and chin stay put. The mouth's falloff takes the teeth and tongue helpers with it.
    nose_c = nose_tip + np.array([0.0, 0.08, -0.12]) * hs
    lip_c = lip + np.array([0.0, -0.06, -0.15]) * hs
    for out_dm, c, r0, r1 in ((NOSE_OUT, nose_c, 0.10, 0.26), (MOUTH_OUT, lip_c, 0.16, 0.32)):
        if out_dm:
            d = np.linalg.norm(p - c, axis=1)
            p[:, 2] += out_dm * w_face * (1.0 - smoothstep(r0 * hs, r1 * hs, d))

    # Face simplify: a broad low-pass over the head, so creases (lids, philtrum, nasolabial
    # folds) fill in and the eyes, brows and lips come from the texture. Only the outward part of
    # the low-pass is kept, along the surface normal: a plain low-pass pulls the cheeks, brow and
    # nose bridge back toward the recessed eye and mouth openings (fixed boundaries), which made
    # the face concave on PRXJX2. Filling only keeps every form at or in front of where it was.
    # The falloff fades out down the neck.
    if FACE_SIMPLIFY:
        head = body[w_face[body] > 0.05]
        n = vertex_normals(p, faces)
        out = np.maximum(((taubin_smooth(p, faces, head, FACE_PASSES) - p) * n).sum(1), 0.0)
        p = p + (FACE_SIMPLIFY * smoothstep(0.3, 0.9, w_face) * out)[:, None] * n

    # Face detail cut (PRXJX2: "still some mesh detail we should lose from the face"): a two-sided
    # 4th-order low-pass along the normal takes out the mid-scale relief the fill left (cheekbone
    # edge, under-eye bags, temple and brow ridges). Its flat low-frequency response keeps the
    # broad face where it is (no dishing); the eye and mouth openings are held as boundaries, the
    # nose and lips are masked out so they keep their shape and push, ears go to the ear fill.
    if FACE_DETAIL:
        head = body[w_face[body] > 0.05]
        n = vertex_normals(p, faces)
        dn = ((lowpass4(p, faces, head, DETAIL_T) - p) * n).sum(1)
        keep = np.maximum(1.0 - smoothstep(0.12 * hs, 0.20 * hs, np.linalg.norm(p - nose_c, axis=1)),
                          1.0 - smoothstep(0.17 * hs, 0.24 * hs, np.linalg.norm(p - lip_c, axis=1)))
        w_det = FACE_DETAIL * smoothstep(0.3, 0.9, w_face) * (1.0 - w_ear) * (1.0 - keep)
        p = p + (w_det * dn)[:, None] * n

    # Ears: the concha and antihelix fill up toward the rim, so the ear reads as one simple shell
    # instead of a rim around a hole. Height above the head's side, along each ear's outward
    # axis, is raised to the mean of its neighbours wherever that is higher (a fill-only
    # relaxation of the height field), with the rim and the ear's root held.
    if EAR_FILL:
        n = vertex_normals(p, faces)
        for sd in (1.0, -1.0):
            axis = np.array([sd, 0.0, -0.3]) / np.hypot(1.0, 0.3)
            ear_v = body[(w_ear[body] > 0.3) & (side[body] == sd) & ((n[body] @ axis) > 0.0)]
            h = p @ axis
            filled = fill_height(h, faces, ear_v, 300)
            p = p + (EAR_FILL * w_ear * (filled - h))[:, None] * axis


    # Simplify: take out most of the fine relief over the whole body (muscle definition, skin
    # folds, lip and lid creases) so the forms read as broad shapes (spec R1, R4). Helpers and
    # joint cubes are left alone.
    # Ears keep their rim (the face fill already took out the inner folds).
    p = p + (SIMPLIFY * (1.0 - w_ear))[:, None] * (taubin_smooth(p, faces, body, SIMPLIFY_PASSES) - p)

    # Keep the soles on the ground plane.
    p[:, 1] += p0[body, 1].min() - p[body, 1].min()
    return p


def measure(p, groups, weights):
    """Head height (crown to chin) over total height, on the body mesh."""
    body = groups["body"]
    w_face = np.clip(sum(w for b, w in weights.items() if not LIMB.match(b)), 0.0, 1.0)
    b = p[body]
    crown, sole = b[:, 1].max(), b[:, 1].min()
    neck_z = p[groups["joint-neck"]].mean(0)[2]
    chin_set = (np.abs(b[:, 0]) < 0.05) & (w_face[body] > 0.5) & (b[:, 2] > neck_z + 0.6)
    chin = b[chin_set, 1].min()
    return (crown - chin) / (crown - sole), crown - chin, crown - sole


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true")
    args = ap.parse_args()
    raw, faces = load_mesh()
    p0 = default_adult(raw)
    groups, weights = load_groups(), load_weights(len(p0))
    p = build(p0, faces, groups, weights)
    subtle = build(p0, faces, groups, weights, "subtle")
    for label, q in (("hm08 raw", raw), ("hm08 default adult", p0), ("stylized-default", p),
                     ("subtle (first 6.1)", subtle)):
        r, h, t = measure(q, groups, weights)
        print(f"{label}: head {h:.3f} dm, height {t:.3f} dm, head/height {r:.4f} "
              f"({1 / r:.2f} heads)")
    if args.measure:
        return
    d = p - p0
    keep = np.abs(d).max(1) >= 1e-5
    with io.TextIOWrapper(gzip.GzipFile(OUT, "wb", mtime=0)) as f:  # mtime=0: reproducible bytes
        f.write("# stylized-default: STYLIZED_SPEC.md 6.1, built by make_stylized_default.py\n")
        for i in np.nonzero(keep)[0]:
            f.write(f"{i} {d[i, 0]:.5f} {d[i, 1]:.5f} {d[i, 2]:.5f}\n")
    print(f"wrote {OUT}: {keep.sum()} vertices")


if __name__ == "__main__":
    main()
