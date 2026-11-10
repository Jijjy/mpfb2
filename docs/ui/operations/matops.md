# Operations — "Material"

**Source:** `src/mpfb/ui/operations/matops/`

**Parent panel:** `MPFB_PT_Operations_Panel` ("Operations")

## Overview

The "Material" panel provides operators for modifying the materials on an MPFB character's mesh objects. It has one operator: **Set normalmap**, which adds or replaces a normal map texture in an existing MakeSkin material.

The panel is shown for any recognised MakeHuman object that is not a skeleton (armature). This means it appears for the basemesh, body proxy meshes, and clothing items, but not for rigs.

## Panel

### MPFB_PT_MatopsPanel ("Material")

| Attribute | Value |
|---|---|
| `bl_label` | "Material" |
| `bl_category` | `OPERATIONSCATEGORY` |
| `bl_parent_id` | `MPFB_PT_Operations_Panel` |
| `bl_options` | `{'DEFAULT_CLOSED'}` |
| Base class | `Abstract_Panel` |

The panel draws one box, **Adjust material**, with the **Set normalmap** button (opens a file browser).

## Operators

### MPFB_OT_Set_Normalmap_Operator

| Attribute | Value |
|---|---|
| `bl_idname` | `mpfb.set_normalmap` |
| `bl_label` | "Set normalmap" |
| `bl_options` | `{'REGISTER', 'UNDO'}` |
| Poll | `ANY_MAKEHUMAN_OBJECT_ACTIVE` |
| File dialog | `ImportHelper` — opens a PNG file browser |

Opens a file browser filtered to `.png` files. After the user selects a file, calls `MaterialService.set_normalmap(material, filepath)` to either add a normal map node to the existing material or replace the existing one.

This is a quick way to apply a custom normal map baked from a sculpt (e.g. one produced using the [sculpt setup](sculpt.md) workflow) to the character's skin material without manually editing the node tree.

## Related

- [Operations index](index.md)
- [Sculpt setup](sculpt.md) — can produce normal maps for use with `mpfb.set_normalmap`
- [UI Layer overview](../index.md)
- [Meta classes](../meta.md)
