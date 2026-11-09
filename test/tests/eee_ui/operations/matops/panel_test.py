"""Tests for the MatOps panel and scene-property registration."""

import bpy
from .... import dynamic_import



def test_panel_is_registered():
    assert hasattr(bpy.types, 'MPFB_PT_MatopsPanel')


