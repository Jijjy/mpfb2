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
