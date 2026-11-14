"""Groom the demo curve hairstyles the hair-editor pack lacks: a chin-length bob and voluminous curls.

    blender -b -P tools/demo/groom_hair.py -- [path.blend]

or `mise run groom`. Both styles are derived from the pack's shoulder-length styles (hair.blend in the MPFB user
data dir, left untouched) and saved as named CURVES objects in a user blend, by default <out>/hair/demo_hair.blend
(<out> as in make_demo.py). make_demo.py loads them through the curve-hair form's "blend" key, and builds this file
first when it is missing.

    demo_bob    straight_hair_to_shoulder with every strand cut at a cut line that runs from just below the chin in
                front to the nape behind, the last few centimetres bent in under the line.
    demo_curls  hair_to_shoulder pushed out from the head for volume, then wound into spirals. A strand's spiral
                phase depends on where on the scalp it grows, smoothly, so neighbouring strands curl together and a
                clump averaged from them keeps the curl. The pack's own Curl Hair Curves modifier curls each strand
                on its own, which a clump averages away, so it is switched off.

The geometry the pack's modifier stack (Duplicate, Frizz, Noise, ...) grows the children from is the guide strands
this script rewrites; the modifier settings in STYLES are applied on top.
"""
import math
import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# Default MPFB human, as the pack was groomed on it (metres, Z up, the face looks along -Y)
HEAD_CENTRE = np.array((0.0, 0.01, 1.58))

BOB = {
    "source": "straight_hair_to_shoulder",
    # The cut line: its height in front (y < 0) and at the back, linear in between
    "cut_front": 1.45,
    "cut_back": 1.47,
    # How far the last part of each strand is bent in toward the neck, and over what length
    "tuck": 0.012,
    "tuck_length": 0.04,
}
CURLS = {
    "source": "hair_to_shoulder",
    # Outward push at the tip, from the head centre; the root stays put
    "volume": 0.06,
    # Spiral radius, turns along the strand and the fraction of the strand before the curl starts
    "curl_radius": 0.022,
    "curl_turns": 2.5,
    "curl_start": 0.2,
    # Wavelength of the scalp field the spiral phase follows; long against a clump's width
    "phase_wavelength": 0.12,
    # Points per guide strand after resampling, enough for the spiral
    "points": 64,
}
# Modifier inputs set on each derived style: {modifier name: {input name: value}}
STYLES = {
    "demo_bob": (BOB, {
        "Frizz Hair Curves": {"Factor": 0.0},
        "Curl Hair Curves": {"Factor": 0.0},
    }),
    "demo_curls": (CURLS, {
        "Curl Hair Curves": {"Factor": 0.0},
        "Frizz Hair Curves": {"Factor": 0.05},
        "Hair Curves Noise": {"Factor": 0.0},
        "Hair Curves Noise.001": {"Factor": 0.0},
    }),
}


def out_path():
    base = os.path.abspath(os.environ.get("MPFB_DEMO_OUT") or os.path.join(HERE, "out"))
    return os.path.join(base, "hair", "demo_hair.blend")


def _pack_path():
    import make_demo
    HairEditorService = make_demo._import("services.haireditorservices", "HairEditorService")
    path = HairEditorService.get_hair_blend_path()
    if path is None:
        raise IOError("no hair-editor asset pack installed in the MPFB user data dir")
    return path


def _read(curves):
    """(positions (n, 3), first point index per curve, point count per curve)."""
    positions = np.empty(len(curves.points) * 3, dtype=np.float64)
    curves.points.foreach_get("position", positions)
    first = np.empty(len(curves.curves), dtype=np.int64)
    curves.curves.foreach_get("first_point_index", first)
    count = np.empty(len(curves.curves), dtype=np.int64)
    curves.curves.foreach_get("points_length", count)
    return positions.reshape(-1, 3), first, count


def _write(curves, strands):
    """Give each curve the points of its strand, a list of (k, 3) arrays, one per curve in order."""
    sizes = [len(s) for s in strands]
    curves.resize_curves(sizes)
    positions = np.concatenate(strands, axis=0).astype(np.float32)
    curves.points.foreach_set("position", positions.ravel())
    curves.update_tag()


def _resample(strand, n):
    """n points evenly spaced along the strand's length."""
    seg = np.linalg.norm(np.diff(strand, axis=0), axis=1)
    s = np.concatenate(((0.0,), np.cumsum(seg)))
    if s[-1] <= 0.0:
        return np.repeat(strand[:1], n, axis=0)
    t = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(t, s, strand[:, k]) for k in range(3)], axis=1)


def groom_bob(curves, p):
    """Cut every strand at the cut line and tuck its end in. Strands that start below the line are removed."""
    positions, first, count = _read(curves)
    keep, strands = [], []
    for i in range(len(first)):
        strand = positions[first[i]:first[i] + count[i]]
        # The cut line is lower in front: y runs from about -0.1 (face) to 0.1 (back of the head)
        front = np.clip(0.5 - strand[:, 1] / 0.2, 0.0, 1.0)
        cut = p["cut_back"] + (p["cut_front"] - p["cut_back"]) * front
        below = np.nonzero(strand[:, 2] < cut)[0]
        if len(below) and below[0] < 2:
            continue
        if len(below):
            j = below[0]
            # Interpolate the crossing between point j-1 (above) and j (below)
            a, b = strand[j - 1], strand[j]
            da, db = a[2] - cut[j - 1], b[2] - cut[j]
            strand = np.concatenate((strand[:j], [a + (b - a) * (da / (da - db))]))
        strand = _resample(strand, max(len(strand), 8))
        seg = np.linalg.norm(np.diff(strand, axis=0), axis=1)
        from_tip = np.concatenate((np.cumsum(seg[::-1])[::-1], (0.0,)))
        w = np.clip(1.0 - from_tip / p["tuck_length"], 0.0, 1.0) ** 2
        inward = HEAD_CENTRE[None, :2] - strand[:, :2]
        inward /= np.maximum(np.linalg.norm(inward, axis=1)[:, None], 1e-6)
        strand[:, :2] += inward * (p["tuck"] * w)[:, None]
        keep.append(i)
        strands.append(strand)
    _keep_curves(curves, keep)
    _write(curves, strands)


def _keep_curves(curves, keep):
    drop = sorted(set(range(len(curves.curves))) - set(keep))
    if drop:
        curves.remove_curves(indices=drop)


def _phase(root, wavelength):
    """A smooth field over the scalp, in radians, so that strands with nearby roots get nearly the same phase."""
    k = 2.0 * math.pi / wavelength
    x, y, z = root
    return (math.sin(k * x + 1.3 * math.sin(k * 0.7 * z)) + math.sin(k * 0.8 * y + 0.5) + math.cos(k * 0.9 * z - 0.6 * x * k)) * math.pi


def groom_curls(curves, p):
    """Push the strands out for volume and wind them into scalp-coherent spirals."""
    positions, first, count = _read(curves)
    strands = []
    for i in range(len(first)):
        strand = _resample(positions[first[i]:first[i] + count[i]], p["points"])
        t = np.linspace(0.0, 1.0, len(strand))
        out = strand - HEAD_CENTRE
        out[:, 2] *= 0.3  # mostly sideways, a little up and down
        out[:, 1] = np.maximum(out[:, 1], 0.0)  # never forward, over the face
        out /= np.maximum(np.linalg.norm(out, axis=1)[:, None], 1e-6)
        strand = strand + out * (p["volume"] * t ** 0.8)[:, None]

        axis = strand[-1] - strand[0]
        length = np.linalg.norm(axis)
        if length < 1e-4:
            strands.append(strand)
            continue
        axis /= length
        helper = np.array((0.0, 0.0, 1.0)) if abs(axis[2]) < 0.9 else np.array((1.0, 0.0, 0.0))
        u = np.cross(axis, helper)
        u /= np.linalg.norm(u)
        v = np.cross(axis, u)
        ramp = np.clip((t - p["curl_start"]) / 0.15, 0.0, 1.0)
        ramp = ramp * ramp * (3.0 - 2.0 * ramp)
        theta = 2.0 * math.pi * p["curl_turns"] * t + _phase(strand[0], p["phase_wavelength"])
        radius = p["curl_radius"] * ramp
        strand = strand + radius[:, None] * (np.cos(theta)[:, None] * u + np.sin(theta)[:, None] * v)
        strands.append(strand)
    _write(curves, strands)


def _set_inputs(obj, settings):
    ModifierService = __import__("make_demo")._import("services.modifierservice", "ModifierService")
    for mod_name, inputs in settings.items():
        modifier = obj.modifiers.get(mod_name)
        if modifier is None:
            raise KeyError(f"{obj.name} has no modifier {mod_name!r}")
        ids = {item.name: item.identifier for item in modifier.node_group.interface.items_tree
               if getattr(item, "in_out", None) == "INPUT"}
        for name, value in inputs.items():
            ModifierService.set_node_group_input(modifier, ids[name], value)


def groom(path=None):
    """Derive the demo styles from the pack and save them in a new blend at path. Returns the path."""
    path = path or out_path()
    pack = _pack_path()
    sources = sorted({p["source"] for p, _settings in STYLES.values()})
    with bpy.data.libraries.load(pack, link=False) as (data_from, data_to):
        missing = [s for s in sources if s not in data_from.objects]
        if missing:
            raise KeyError(f"{pack} has no {missing}")
        data_to.objects = list(sources)  # the loader swaps the names in this list for the objects
    loaded = list(data_to.objects)
    groomers = {"demo_bob": groom_bob, "demo_curls": groom_curls}
    styles = []
    for name, (params, settings) in STYLES.items():
        obj = loaded[sources.index(params["source"])]
        obj.name = name
        obj.data = obj.data.copy()
        obj.data.name = name
        if obj.active_material is not None:
            obj.active_material.name = name
        groomers[name](obj.data, params)
        _set_inputs(obj, settings)
        styles.append(obj)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.data.libraries.write(path, set(styles), fake_user=True, compress=True)
    print(f"GROOM saved {[o.name for o in styles]} in {path}")
    return path


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    groom(argv[0] if argv else None)
