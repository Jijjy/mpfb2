"""Tests for HairCardService CLUMP mode: closed tapered tubes within the triangle budget."""

import math
from collections import Counter

import bpy
import pytest

from .. import dynamic_import

HairCardService = dynamic_import("mpfb.services.haircardservice", "HairCardService")


def _groom(name, roots_per_side=6, strands_per_root=4, length=0.3):
    """A grid of small strand bundles, each strand curling a little so the clump tubes have a curve to follow."""
    strands = []
    for row in range(roots_per_side):
        for column in range(roots_per_side):
            for strand in range(strands_per_root):
                x = 0.1 * column + 0.004 * strand
                y = 0.1 * row + 0.002 * strand
                strands.append([(x + 0.03 * math.sin(step), y + 0.02 * step, length * step / 7.0) for step in range(8)])
    curves = bpy.data.hair_curves.new(name)
    curves.add_curves([len(strand) for strand in strands])
    curves.points.foreach_set("position", [c for strand in strands for point in strand for c in point])
    curves.update_tag()
    obj = bpy.data.objects.new(name, curves)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


@pytest.mark.parametrize("max_tris", [300, 1000, 6000])
def test_clump_mode_gives_a_closed_mesh_within_max_tris(max_tris):
    hair_obj = _groom(f"haircard_clump_{max_tris}")
    mesh = HairCardService.build_clump_mesh(hair_obj, cluster_count=36, min_strands=1, seed=0, samples=10, max_tris=max_tris)
    assert mesh is not None
    mesh.calc_loop_triangles()
    assert 0 < len(mesh.loop_triangles) <= max_tris

    # Closed: every edge is shared by exactly two faces, and no vertex is left over
    edge_use = Counter(key for polygon in mesh.polygons for key in polygon.edge_keys)
    assert set(edge_use.values()) == {2}
    assert len({index for polygon in mesh.polygons for index in polygon.vertices}) == len(mesh.vertices)

    # Outward facing: the signed volume of a closed mesh is positive
    volume = sum(mesh.vertices[a].co.dot(mesh.vertices[b].co.cross(mesh.vertices[c].co))
                 for a, b, c in (tri.vertices for tri in mesh.loop_triangles)) / 6.0
    assert volume > 0.0
    assert "UVMap" in mesh.uv_layers


def test_clump_triangle_budget_merges_clumps():
    hair_obj = _groom("haircard_clump_merge")
    per_clump = HairCardService.clump_triangle_count(9)
    assert HairCardService.clump_ring_sides(9)[0] == 6 and HairCardService.clump_ring_sides(9)[-1] == 3
    unmerged = HairCardService.build_clump_mesh(hair_obj, 36, 1, 0, 10, 100000)
    merged = HairCardService.build_clump_mesh(hair_obj, 36, 1, 0, 10, per_clump * 10)
    assert len(unmerged.polygons) == 36 * per_clump
    assert len(merged.polygons) == 10 * per_clump


def test_clump_rings_keep_their_width_when_the_side_count_drops():
    """Each ring has a vertex at both ends of its wide axis, so the face-on width is the same for every side count."""
    for count in range(3, 7):
        fractions = HairCardService.clump_ring_fractions(count)
        assert len(fractions) == count and fractions == sorted(fractions) and 0.0 in fractions and 0.5 in fractions
        assert all(0.0 <= f < 1.0 for f in fractions)
        widths = [math.cos(2.0 * math.pi * f) for f in fractions]
        assert max(widths) - min(widths) == pytest.approx(2.0)

    # A fully morphed ring has the outline of the next side count, seen from any direction
    def extent(ring, angle):
        along = [wide * math.cos(angle) + flat * math.sin(angle) for _f, wide, flat in ring]
        return max(along) - min(along)

    for count, next_count in ((6, 5), (5, 4), (4, 3), (6, 3)):
        morphed = HairCardService.clump_ring_shape(count, next_count, 1.0)
        plain = HairCardService.clump_ring_shape(next_count, next_count, 0.0)
        assert len(morphed) == count and [v[0] for v in morphed] == sorted(v[0] for v in morphed)
        for step in range(36):
            assert extent(morphed, step * math.pi / 36) == pytest.approx(extent(plain, step * math.pi / 36))
