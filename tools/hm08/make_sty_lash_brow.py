"""Paint the STYLIZED lash and brow alpha textures for the stock eyelashes01 and eyebrow001 cards.

    python3 tools/hm08/make_sty_lash_brow.py <mpfb data dir with eyelashes/ and eyebrows/> [out_dir]

Writes sty_lash.png and sty_brow.png (1024², RGBA, near-black RGB, the shape in alpha) into out_dir
(default src/mpfb/data/textures).
- lashes: each lash card is a quad-grid strip; the painter finds every UV island, its four corners
  and its root/tip and inner/outer sides from the card's own obj, gives each face corner a strip
  coordinate (s along the strip, 0 at the inner corner; t across it, 0 at the lid root) and
  rasterises the wing in those coordinates. Upper cards hold one solid tapered wing from the root, half the card at the inner corner, widening
  outwards and ending in a pointed flick at the outer corner; lower cards stay empty.
- brows: the brow card is not a clean grid (its tail ends in a point), and its outline is already a
  brow: a blunt head at the inner end tapering to a pointed tail. The card is filled solid, inset by
  BROW_INSET of the texture and its faceted outline rounded (blur, then a sharp ramp).
No mesh is changed (STYLIZED_SPEC.md 5.3).
"""
import os
import sys
from collections import defaultdict, deque

import numpy as np
from PIL import Image, ImageFilter

SIZE = 1024
SUPERSAMPLE = 4
RGB = (8, 6, 5)
BROW_INSET = 0.004


def read_obj(path):
    verts, uvs, faces = [], [], []
    with open(path, "r", encoding="utf-8") as obj_file:
        for line in obj_file:
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] == "v":
                verts.append([float(x) for x in tokens[1:4]])
            elif tokens[0] == "vt":
                uvs.append([float(x) for x in tokens[1:3]])
            elif tokens[0] == "f":
                faces.append([(int(c.split("/")[0]) - 1, int(c.split("/")[1]) - 1) for c in tokens[1:]])
    return np.array(verts), np.array(uvs), faces


def islands(faces):
    """Faces grouped by shared UV indices."""
    owner = defaultdict(list)
    for index, face in enumerate(faces):
        for _v, uv in face:
            owner[uv].append(index)
    seen, groups = set(), []
    for start in range(len(faces)):
        if start in seen:
            continue
        group, queue = [], deque([start])
        seen.add(start)
        while queue:
            index = queue.popleft()
            group.append(index)
            for _v, uv in faces[index]:
                for other in owner[uv]:
                    if other not in seen:
                        seen.add(other)
                        queue.append(other)
        groups.append(group)
    return groups


def strip_coords(faces, group, verts, uvs):
    """(s, t) per UV index of one quad-grid strip, from grid steps: t counts rows from one long side,
    s counts columns from one short end. Returns the dict and the long and short sides as UV sets."""
    edges = defaultdict(int)
    neighbours = defaultdict(set)
    uv_vert = {}
    for index in group:
        loop = faces[index]
        for k, (v, uv) in enumerate(loop):
            uv_vert[uv] = v
            nxt = loop[(k + 1) % len(loop)][1]
            edges[frozenset((uv, nxt))] += 1
            neighbours[uv].add(nxt)
            neighbours[nxt].add(uv)
    boundary = defaultdict(set)
    for edge, count in edges.items():
        if count == 1:
            a, b = tuple(edge)
            boundary[a].add(b)
            boundary[b].add(a)
    face_count = defaultdict(int)
    for index in group:
        for _v, uv in faces[index]:
            face_count[uv] += 1
    corners = [uv for uv in boundary if face_count[uv] == 1]
    if len(corners) != 4:
        raise ValueError(f"strip with {len(corners)} corners")
    # Walk the boundary loop, cut it at the corners into four sides
    start = corners[0]
    loop, prev, cur = [start], None, start
    while True:
        nxt = next(n for n in boundary[cur] if n != prev)
        if nxt == start:
            break
        loop.append(nxt)
        prev, cur = cur, nxt
    cut = [i for i, uv in enumerate(loop) if uv in corners]
    sides = [loop[cut[i]:cut[i + 1] + 1] if i < 3 else loop[cut[3]:] + [loop[0]] for i in range(4)]
    sides.sort(key=len, reverse=True)
    long_sides, short_sides = sides[:2], sides[2:]

    def steps(seed):
        dist = {uv: 0 for uv in seed}
        queue = deque(seed)
        while queue:
            uv = queue.popleft()
            for n in neighbours[uv]:
                if n not in dist:
                    dist[n] = dist[uv] + 1
                    queue.append(n)
        return dist

    def mean3d(side):
        return verts[[uv_vert[uv] for uv in side]].mean(axis=0)

    return steps, mean3d, long_sides, short_sides, uv_vert


def rasterise(uvs, faces, group, coords, shape, canvas):
    """Fill canvas (supersampled alpha) with shape(s, t) over every triangle of the island's faces."""
    height, width = canvas.shape
    for index in group:
        loop = [uv for _v, uv in faces[index]]
        for k in range(1, len(loop) - 1):
            tri = [loop[0], loop[k], loop[k + 1]]
            p = np.array([[uvs[i][0] * width, (1.0 - uvs[i][1]) * height] for i in tri])
            st = np.array([coords[i] for i in tri])
            x0, y0 = np.floor(p.min(axis=0)).astype(int)
            x1, y1 = np.ceil(p.max(axis=0)).astype(int)
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            d = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
            if abs(d) < 1e-12:
                continue
            w0 = ((p[1, 1] - p[2, 1]) * (xs - p[2, 0]) + (p[2, 0] - p[1, 0]) * (ys - p[2, 1])) / d
            w1 = ((p[2, 1] - p[0, 1]) * (xs - p[2, 0]) + (p[0, 0] - p[2, 0]) * (ys - p[2, 1])) / d
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            s = w0 * st[0, 0] + w1 * st[1, 0] + w2 * st[2, 0]
            t = w0 * st[0, 1] + w1 * st[1, 1] + w2 * st[2, 1]
            value = shape(s, t) & inside
            yy, xx = np.nonzero(value)
            yy, xx = yy + y0, xx + x0
            ok = (yy >= 0) & (yy < height) & (xx >= 0) & (xx < width)
            canvas[yy[ok], xx[ok]] = 1.0


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def lash_wing(s, t):
    """Solid wing from the lid root: 55% of the card at the inner corner, the full card from 60% along,
    then a pointed flick: the lower edge rises to meet the upper one at the outer end."""
    top = 0.55 + 0.45 * smoothstep(s / 0.6)
    bottom = 0.85 * smoothstep((s - 0.80) / 0.20) ** 1.3
    return (t >= bottom - 0.02) & (t <= top) & (s >= 0.015) & (s <= 0.985)


def paint(obj_path, kind):
    verts, uvs, faces = read_obj(obj_path)
    canvas = np.zeros((SIZE * SUPERSAMPLE, SIZE * SUPERSAMPLE), dtype=np.float32)
    groups = islands(faces)
    if kind == "brow":
        for group in groups:
            rasterise(uvs, faces, group, defaultdict(lambda: (0.0, 0.0)), lambda s, t: np.ones_like(s, dtype=bool), canvas)
        mask = Image.fromarray((canvas * 255).astype(np.uint8), "L")
        inset = int(BROW_INSET * SIZE * SUPERSAMPLE) | 1
        mask = mask.filter(ImageFilter.MinFilter(inset)).filter(ImageFilter.GaussianBlur(inset))
        ramp = np.clip((np.asarray(mask, dtype=np.float32) / 255.0 - 0.5) * 4.0 + 0.5, 0.0, 1.0)
        return finish(ramp)
    upper_y, infos = {}, []
    for group in groups:
        steps, mean3d, long_sides, short_sides, uv_vert = strip_coords(faces, group, verts, uvs)
        island_verts = verts[sorted({uv_vert[uv] for uv in uv_vert})]
        side_x = np.sign(island_verts[:, 0].mean())
        infos.append((group, steps, mean3d, long_sides, short_sides, island_verts, side_x))
        upper_y.setdefault(side_x, []).append(island_verts[:, 1].mean())
    for group, steps, mean3d, long_sides, short_sides, island_verts, side_x in infos:
        # MakeHuman obj: y up, z forward. Inner end: the short side nearer the face midline.
        inner = min(short_sides, key=lambda side: abs(mean3d(side)[0]))
        if len(upper_y[side_x]) > 1 and island_verts[:, 1].mean() < max(upper_y[side_x]) - 1e-6:
            continue  # lower lashes: empty
        # Root: the long side further back (the tips stand forward of the lid)
        root = min(long_sides, key=lambda side: mean3d(side)[2])
        t_steps, s_steps = steps(root), steps(inner)
        t_max, s_max = max(t_steps.values()), max(s_steps.values())
        coords = {uv: (s_steps[uv] / s_max, t_steps[uv] / t_max) for uv in t_steps}
        rasterise(uvs, faces, group, coords, lash_wing, canvas)
    return finish(canvas)


def finish(canvas):
    alpha = canvas.reshape(SIZE, SUPERSAMPLE, SIZE, SUPERSAMPLE).mean(axis=(1, 3))
    image = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    image[..., :3] = RGB
    image[..., 3] = np.round(alpha * 255).astype(np.uint8)
    return Image.fromarray(image, "RGBA")


def main():
    data = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "..", "src", "mpfb", "data", "textures")
    for kind, sub, name in (("lash", "eyelashes/eyelashes01/eyelashes01.obj", "sty_lash.png"),
                            ("brow", "eyebrows/eyebrow001/eyebrow001.obj", "sty_brow.png")):
        path = os.path.join(out_dir, name)
        paint(os.path.join(data, sub), kind).save(path, optimize=True)
        print("wrote", path)


if __name__ == "__main__":
    main()
