# MaterialService

## Overview

MaterialService handles the creation, identification, modification, and management of materials assigned to Blender objects within MPFB. It supports multiple material types, each with distinct node tree structures: **stylized skin** (`NodeWrapperStylizedSkin`, STYLIZED_SPEC.md 7.1), **procedural eyes** (the stylized eye material), **MakeSkin** (`.mhmat` materials on clothes and proxies) and **game engine** (simple Principled BSDF).

The service provides a complete material lifecycle: creating empty or skin-specific materials, assigning them to objects, creating per-body-part material slots, and loading/saving materials from `.blend` files.

MaterialService also provides static viewport diffuse colors for different body parts and a color adjustment system that can read and apply tint modifications to materials. All methods are static; the class should never be instantiated.

## Source

`src/mpfb/services/materialservice.py`

## Dependencies

| Dependency | Usage |
|------------|-------|
| `LogService` | Logging via `LogService.get_logger("services.materialservice")` |
| `ObjectService` | Object activation, vertex group queries, material slot assignment |
| `NodeService` | Shader node creation, linking, querying, and manipulation |
| `MakeSkinMaterial` | Parsing `.mhmat` files for texture references (imported at call time) |

## Material Type Identifiers

The `identify_material()` method returns one of these string identifiers:

| Type | Description |
|------|-------------|
| `"empty"` | Material is `None` or has no nodes |
| `"stylized_skin"` | Stylized skin with `BloodTint` parameter in a shader group |
| `"procedural_eyes"` | Stylized eyes with `IrisInner` parameter in a shader group |
| `"makeskin"` | MakeHuman MakeSkin material (has `diffuseIntensity` node) |
| `"gameengine"` | Simple material with a `Principled BSDF` node |
| `"unknown"` | None of the above patterns matched |

`identify_material()` returns these as the `MaterialType` literal rather than a bare `str`, so the type
tests the rest of the module performs against the result are checked against the same six values.

## Module-Level Types

Two annotation aliases are declared at module level. None is part of the calling contract beyond the
shapes they describe.

| Name | Definition | Notes |
|------|------------|-------|
| `MaterialType` | `Literal["empty", "stylized_skin", "procedural_eyes", "makeskin", "gameengine", "unknown"]` | The six answers `identify_material()` can give |
| `ColorAdjustment` | `dict[str, Any]` | The socket-name to default-value mapping `find_color_adjustment()` returns and `apply_color_adjustment()` accepts. The values are whatever `NodeService.get_node_info()` read off the sockets, which for a mix node means a mixture of floats and RGBA sequences, so `Any` is the honest value type |

## Public API

### Material Lifecycle

#### create_empty_material(name, blender_object=None)

Create a new empty material with nodes enabled and `HASHED` blend method. Optionally assign it to a Blender object.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `name` | `str` | — | The name for the new material |
| `blender_object` | `bpy.types.Object \| None` | `None` | Optional object to assign the material to |

**Returns:** `bpy.types.Material` — The newly created material.

---

#### assign_new_or_existing_material(name, blender_object)

Assign a material to an object by name. If a material with the given name already exists in `bpy.data.materials`, it is reused; otherwise, a new empty material is created.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `name` | `str` | — | The name of the material to assign |
| `blender_object` | `bpy.types.Object \| None` | — | The object to assign the material to. A `None` object is accepted: the material is created or looked up but assigned to nothing |

**Returns:** `bpy.types.Material` — The assigned material.

---

#### delete_all_materials(blender_object, also_destroy_groups=False)

Delete all materials from a Blender object. Materials are renamed with an `.unused` suffix before removal. Optionally clears node groups as well. Orphaned material data blocks (zero users) are also removed.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `blender_object` | `bpy.types.Object` | — | The object to remove materials from |
| `also_destroy_groups` | `bool` | `False` | If `True`, also destroy node groups within each material |

**Returns:** None

**Restriction:** the loop over the object's materials does not guard against an empty material slot, which
a mesh's material collection yields as `None`, so an object carrying one raises `AttributeError` partway
through — after earlier slots have already been renamed to `.unused`. 

---

#### create_and_assign_material_slots(basemesh, bodyproxy=None)

Create per-body-part material slots for the basemesh (and optionally a body proxy). Copies the base material and assigns instances to vertex groups: `nipple`, `lips`, `fingernails`, `toenails`, `ears`, and `genitals`. The basemesh must already have at least one material assigned.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `basemesh` | `bpy.types.Object` | — | The base mesh to create material slots on |
| `bodyproxy` | `bpy.types.Object \| None` | `None` | Optional body proxy to also assign slots to |

**Returns:** None

**Raises:** `ValueError` if the basemesh has no initial material.

---

### Material Identification and Queries

#### has_materials(blender_object)

Check if a Blender object has any materials assigned in its material slots.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `blender_object` | `bpy.types.Object` | — | The object to check |

**Returns:** `bool` — `True` if the object has at least one material slot.

---

#### get_material(blender_object, slot=0)

Return the material in the specified material slot.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `blender_object` | `bpy.types.Object` | — | The object to query |
| `slot` | `int` | `0` | The material slot index |

**Returns:** `bpy.types.Material | None` — The material in the slot, or `None` if no materials exist, and also `None` for a slot the user left empty.

---

#### identify_material(material)

Determine the type of a material by examining its node tree structure. Checks for characteristic nodes and parameters to classify the material.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `material` | `bpy.types.Material \| None` | — | The material to identify. A `None` material gives `"empty"` |

**Returns:** `MaterialType` — One of the six material type identifiers (see the section above).

---

### Material Modification

#### set_normalmap(material, filename)

Set a normal map texture on a material. Creates the necessary normal map and image texture nodes if they don't exist, and connects them to the Principled BSDF or bump node. Works only with `makeskin` materials; any other type raises `ValueError`.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `material` | `bpy.types.Material` | — | The material to modify |
| `filename` | `str` | — | Absolute path to the normal map image file |

**Returns:** None

**Raises:** `ValueError` if the material type doesn't support normal maps.

---

#### find_color_adjustment(blender_object)

Return all color adjustments currently applied to the object's first material slot. Finds the mix node connected to the Principled BSDF's Base Color input and returns its socket values.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `blender_object` | `bpy.types.Object \| None` | — | The object to query. A `None` object is logged and gives `None` |

**Returns:** `ColorAdjustment | None` — Dictionary of socket values from the color adjustment node, or `None` if not found.

---

#### apply_color_adjustment(blender_object, color_adjustment)

Apply color adjustments to the object's first material slot. Sets the default values of the mix node connected to the Principled BSDF's Base Color input.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `blender_object` | `bpy.types.Object \| None` | — | The object to modify. A `None` object is logged and the method returns |
| `color_adjustment` | `ColorAdjustment` | — | Dictionary of socket values to apply |

**Returns:** None

**Restriction:** unlike `find_color_adjustment()`, which returns early when the material has no mix node
connected to the Principled BSDF's Base Color, this method does not test for one. The `None` reaches
`NodeService.set_socket_default_values()`, which answers a node with no `inputs` attribute with a log line and
no change — so applying an adjustment to a material without a mix node silently does nothing and reports
nothing.

---

### Material I/O

#### as_blend_path(path)

Parse a blend file asset path string into its three components. The path format is `path/to/file.blend/Category/AssetName`.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `path` | `str` | — | The blend file asset path string |

**Returns:** `tuple[str, str, str]` — `(blend_path, directory_name, asset_name)`.

---

#### save_material_in_blend_file(blender_object, path_to_blend_file, material_number=None, fake_user=False)

Save materials from an object to a `.blend` file. If `material_number` is `None`, saves all materials; otherwise, saves only the specified slot.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `blender_object` | `bpy.types.Object` | — | The object whose materials to save |
| `path_to_blend_file` | `str` | — | Path to the destination `.blend` file |
| `material_number` | `int \| None` | `None` | Specific material slot to save, or `None` for all |
| `fake_user` | `bool` | `False` | Whether to set fake user on saved materials |

**Returns:** None

**This method does not work as described.** Its two branches are the wrong way round: passing a slot
number writes every slot and ignores the number, while leaving the default `None` subscripts
`material_slots[None]` and raises `TypeError`. It has no callers anywhere in the tree. 

---

#### load_material_from_blend_file(path, blender_object=None)

Load a material from a `.blend` file. The path should be in the format `file.blend/Material/MaterialName`. The material is made local after loading. Optionally assigns it to a Blender object.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `path` | `str` | — | Blend file asset path (see `as_blend_path`) |
| `blender_object` | `bpy.types.Object \| None` | `None` | Optional object to assign the material to |

**Returns:** `bpy.types.Material` — The loaded material.

---

### Viewport Colors

#### get_skin_diffuse_color()

Return the static RGBA viewport display color for skin materials.

**Returns:** `list[float]` — `[0.721, 0.568, 0.431, 1.0]`

---

#### get_generic_bodypart_diffuse_color()

Return the static RGBA viewport display color for body part materials (eyebrows, eyelashes, hair, tongue).

**Returns:** `list[float]` — `[0.194, 0.030, 0.014, 1.0]`

---

#### get_generic_clothes_diffuse_color()

Return the static RGBA viewport display color for clothes materials.

**Returns:** `list[float]` — `[0.6, 0.6, 0.6, 1.0]`

---

#### get_eye_diffuse_color()

Return the static RGBA viewport display color for eye materials.

**Returns:** `list[float]` — `[0.95, 0.95, 0.95, 1.0]`

---

#### get_teeth_diffuse_color()

Return the static RGBA viewport display color for teeth materials.

**Returns:** `list[float]` — `[0.95, 0.95, 0.95, 1.0]`

---

#### get_diffuse_colors()

Return all static viewport display colors as a dictionary, keyed by MPFB object type.

**Returns:** `dict[str, list[float]]` — Maps object types (`"Eyes"`, `"Teeth"`, `"Basemesh"`, `"Clothes"`, etc.) to RGBA color lists.

---

## Examples

### Creating Materials for a Character

```python
from mpfb.services.materialservice import MaterialService

# Create per-body-part material slots
MaterialService.create_and_assign_material_slots(basemesh, bodyproxy=proxy)
```

### Identifying and Modifying Materials

```python
from mpfb.services.materialservice import MaterialService

# Identify the material type
material = basemesh.data.materials[0]
mat_type = MaterialService.identify_material(material)
print(f"Material type: {mat_type}")  # e.g., "stylized_skin"

# Set a normal map
MaterialService.set_normalmap(material, "/path/to/normal_map.png")
```

