"""Various functions for working with materials"""

import os, bpy, typing
from typing import Any

from .logservice import LogService
from .objectservice import ObjectService
from .nodeservice import NodeService

_LOG = LogService.get_logger("services.materialservice")

MaterialType = typing.Literal["empty", "stylized_skin", "procedural_eyes", "makeskin", "gameengine", "unknown"]
"""The six answers ``identify_material()`` can give.

A literal rather than a bare ``str``, so that the type tests the rest of the module performs against
the result are checked against the same set of values the identifier can actually return."""

# On the node finders: NodeService's find_* methods answer Node | None, and NodeService.add_link()
# does not check the nodes it is handed, so a None reaches links.new() as one. Where a method below
# passes a found node on without testing it, the cast records the precondition which makes the
# lookup safe -- usually that identify_material() has already answered for this material, or that
# the node was created by the same method a moment earlier.
#
# On socket default values: NodeSocket does not declare default_value. It is declared on each concrete
# socket subclass instead, which is what nodeservice's own hasattr() guard acknowledges, so every read
# or write of one below casts the socket to the subclass it is at runtime. The colour writes then meet
# bpy_prop_array, which no python sequence satisfies although assigning a tuple to a fixed size float
# array is ordinary at runtime, so those additionally carry a narrow ignore.

ColorAdjustment = dict[str, Any]
"""The socket-name to default-value mapping that ``find_color_adjustment()`` returns and
``apply_color_adjustment()`` accepts.

The values are whatever ``NodeService.get_node_info()`` read off the sockets, which for a mix node
means a mixture of floats and RGBA sequences, so ``Any`` is the honest value type."""


class MaterialService():
    """The MaterialService class is a utility class designed to handle various operations related to MPFB materials in Blender.
    It provides a collection of static methods that facilitate the creation, modification, and management of materials assigned
    to Blender objects. The class is not meant to be instantiated; instead, its static methods should be used directly.

    Its key responsibilities are:

    - Creating, adding and removing materials
    - Identifying material
    - Checking the validity of materials
    - I/O operations for loading and saving materials

    Overall, the MaterialService class provides a comprehensive set of tools for managing MPFB materials in Blender,
    making it easier to work with complex material setups and ensuring consistency across different objects and scenes."""

    def __init__(self) -> None:
        """You should not instance MaterialService. Use its static methods instead."""
        raise RuntimeError("You should not instance MaterialService. Use its static methods instead.")

    @staticmethod
    def delete_all_materials(blender_object: bpy.types.Object, also_destroy_groups: bool = False) -> None:
        """Deletes all materials from the given blender object.

        Args:
            blender_object (bpy.types.Object): The blender object to delete materials from.
            also_destroy_groups (bool): Whether to also destroy the groups that were created for the materials.
        """
        materials = typing.cast(bpy.types.Mesh, blender_object.data).materials
        _LOG.dump("Current materials", (materials, len(materials)))
        for material in materials:            
            mat = typing.cast(bpy.types.Material, material)
            mat.name = mat.name + ".unused"
            if also_destroy_groups:
                # Material.node_tree is None until use_nodes is set, which every material MPFB
                # makes or loads has had set.
                NodeService.clear_node_tree(typing.cast(bpy.types.NodeTree, mat.node_tree), also_destroy_groups=True)
        while len(materials) > 0:
            materials.pop()
        for block in bpy.data.materials:
            if block.users == 0:
                bpy.data.materials.remove(block)

    @staticmethod
    def has_materials(blender_object: bpy.types.Object) -> bool:
        """Check if object has any materials at all assigned"""
        if not blender_object.material_slots:
            return False
        return len(blender_object.material_slots) > 0

    @staticmethod
    def get_material(blender_object: bpy.types.Object, slot: int = 0) -> bpy.types.Material | None:
        """Return the material in the object's given material slot"""
        if not blender_object.material_slots or len(blender_object.material_slots) < 1:
            return None
        return blender_object.material_slots[slot].material

    @staticmethod
    def identify_material(material: bpy.types.Material | None) -> MaterialType:
        """Try to figure out which kind of material we have"""
        if not material:
            return "empty"
        node_tree = typing.cast(bpy.types.NodeTree, material.node_tree)
        nodes = node_tree.nodes

        if len(nodes) == 0:
            return "empty"

        for node in nodes:
            node_info = NodeService.get_node_info(node)
            if node_info and node_info["type"] == "ShaderNodeGroup" and node_info["values"]:
                # Material is potentially a procedural type material
                _LOG.debug("node_info", node_info)
                if "BloodTint" in node_info["values"]:
                    # STYLIZED skin (NodeWrapperStylizedSkin), STYLIZED_SPEC.md 7.1
                    return "stylized_skin"
                if "IrisInner" in node_info["values"]:
                    return "procedural_eyes"

        # Since we're not stylized skin nor procedural eyes, next guess is makeskin. The
        # diffuseIntensity is there in most cases.
        if NodeService.find_node_by_name(node_tree, "diffuseIntensity"):
            return "makeskin"

        # The final guess is GameEngine.
        # This might give a false positive if someone added a material with a principled node
        # to a MH object
        if NodeService.find_node_by_name(node_tree, "Principled BSDF"):
            return "gameengine"

        return "unknown"

    @staticmethod
    def _set_normalmap_in_nodetree(node_tree: bpy.types.NodeTree, filename: str) -> None:
        _LOG.debug("Will set normalmap", filename)

        links = node_tree.links

        normalmap = NodeService.find_first_node_by_type_name(node_tree, "ShaderNodeNormalMap")
        _LOG.debug("Normalmap in initial sweep", normalmap)

        image_node = None
        if normalmap:
            # There is already a normalmap, no need to create another
            image_node = NodeService.find_node_linked_to_socket(node_tree, normalmap, "Color")
            _LOG.debug("Image node in pre-existing setup", image_node)
        else:
            # Will need to create setup for normalmap and its texture node
            principled = NodeService.find_first_node_by_type_name(node_tree, "ShaderNodeBsdfPrincipled")
            _LOG.debug("Principled", principled)

            normalmap = NodeService.create_normal_map_node(node_tree, xpos=-300)
            _LOG.debug("Normalmap", normalmap)

            # A material without a principled node would raise out of find_node_linked_to_socket()
            # here, which tests its own arguments; see the note at the top of the module.
            bump = NodeService.find_node_linked_to_socket(node_tree, typing.cast(bpy.types.Node, principled), "Normal")
            to_socket = None
            _LOG.debug("Bump", bump)
            if bump:
                # There is a bump map, so hook the normalmap to that
                to_socket = bump.inputs["Normal"]
            else:
                # find_node_linked_to_socket() raises on a None node, so the call on the line above
                # has already ruled out a missing principled node by the time we get here.
                to_socket = typing.cast(bpy.types.Node, principled).inputs["Normal"]

            _LOG.debug("to_socket", to_socket)

            from_socket = normalmap.outputs["Normal"]
            _LOG.debug("from_socket", from_socket)

            links.new(from_socket, to_socket)

        if not image_node:
            image_node = NodeService.create_image_texture_node(node_tree, xpos=-600)
            _LOG.debug("Image node, newly created", image_node)

            from_socket = image_node.outputs["Color"]
            to_socket = normalmap.inputs["Color"]

            links.new(from_socket, to_socket)

        image_file_name = os.path.basename(filename)
        image: bpy.types.Image
        if image_file_name in bpy.data.images:
            _LOG.debug("image was previously loaded", filename)
            image = bpy.data.images[image_file_name]
        else:
            image = bpy.data.images.load(filename)
        # Image.colorspace_settings cannot be None: DNA_image_types.h:246 declares it as an embedded
        # ColorManagedColorspaceSettings struct rather than a pointer, so there is nothing for it to be
        # null for. The RNA enum behind its name carries only "NONE" statically, because the real
        # colorspace list is populated from OCIO at runtime, so no stub can know "Non-Color".
        colorspace = typing.cast(bpy.types.ColorManagedInputColorspaceSettings, image.colorspace_settings)
        colorspace.name = "Non-Color"  # pyright: ignore[reportAttributeAccessIssue]

        # Only ShaderNodeTexImage carries an image. image_node is either the node found linked to
        # the normal map's Color socket, which is one, or the one created above.
        typing.cast(bpy.types.ShaderNodeTexImage, image_node).image = image

    @staticmethod
    def set_normalmap(material: bpy.types.Material, filename: str) -> None:
        """Try to modify the material so that it uses the normal map"""
        material_type = MaterialService.identify_material(material)

        node_tree = typing.cast(bpy.types.NodeTree, material.node_tree)

        if material_type == "makeskin":
            MaterialService._set_normalmap_in_nodetree(node_tree, filename)
            return

        raise ValueError('Cannot set normalmap in material of type ' + material_type)

    @staticmethod
    def assign_new_or_existing_material(name: str, blender_object: bpy.types.Object | None) -> bpy.types.Material:
        """Assigns a new material to the given blender object.

        Args:
            name (str): The name of the material to assign.
            blender_object (bpy.types.Object | None): The blender object to assign the material to.

        Returns:
            bpy.types.Material: The material that was assigned.
        """
        if name in bpy.data.materials:
            material = bpy.data.materials[name]
            if not blender_object is None:
                typing.cast(bpy.types.Mesh, blender_object.data).materials.append(material)
        else:
            material = MaterialService.create_empty_material(name, blender_object)
        return material

    @staticmethod
    def create_empty_material(name: str, blender_object: bpy.types.Object | None = None) -> bpy.types.Material:
        """
        Create a new empty material with the given name, and assign it to the blender object
        if given.
        """

        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.blend_method = 'HASHED'
        if blender_object is not None:
            typing.cast(bpy.types.Mesh, blender_object.data).materials.append(material)
        return material

    @staticmethod
    def as_blend_path(path: str) -> tuple[str, str, str]:
        """
        Converts a relative path to an asset in a blender library to an absolute path to the blend,
        the location of the asset in the blend and the name of the asset, ie return:

        (path, location, name)
        """
        blend_path, dir_name, asset_name = (part.strip() for part in path.rsplit('/', 2))
        return blend_path, dir_name, asset_name

    @staticmethod
    def save_material_in_blend_file(blender_object: bpy.types.Object, path_to_blend_file: str,
                                    material_number: int | None = None, fake_user: bool = False) -> None:
        """
        Save the material(s) on the active object to a blend file. If material_number is None, save all
        the object's materials. Otherwise, save material slot with that number. This writes into the file
        but will not overwrite it, although it might overwrite something already in it.

        TODO: Note that the two branches below are the wrong way round, so the method does the opposite of
        what this docstring says and raises when material_number is left at its default.
        """
        if material_number is not None:
            for mat_slot in blender_object.material_slots:
                mat = mat_slot.material
                bpy.data.libraries.write(str(path_to_blend_file), {typing.cast(bpy.types.Material, mat)}, fake_user=fake_user)
        else:
            # The index is None on this branch, which is the inverted test described above.
            mat = blender_object.material_slots[typing.cast(int, material_number)].material
            bpy.data.libraries.write(str(path_to_blend_file), {typing.cast(bpy.types.Material, mat)}, fake_user=fake_user)
        print('Wrote blend file into:', path_to_blend_file)

    @staticmethod
    def load_material_from_blend_file(path: str, blender_object: bpy.types.Object | None = None) -> bpy.types.Material:
        """
        Load a material from a blend file determined by path, to a new material slot.
        """
        path, dir_name, asset_name = MaterialService.as_blend_path(path)
        print('Loading material @: ', path, dir_name, asset_name)
        # BlendDataLibraries.load() is declared -> None in the stubs, although its own docstring there
        # says it returns the context manager this with statement relies on.
        with bpy.data.libraries.load(path) as (in_basket, out_basket):  # pyright: ignore[reportGeneralTypeIssues]
            # Weird syntax.
            setattr(out_basket, dir_name, [asset_name])

        mat = getattr(out_basket, dir_name)[0]
        mat.make_local()

        if blender_object is not None:
            typing.cast(bpy.types.Mesh, blender_object.data).materials.append(mat)
        return mat

    @staticmethod
    def _assign_material_instance(blender_object: bpy.types.Object, material: bpy.types.Material,
                                  group_name: str) -> None:
        _LOG.enter()
        _LOG.debug("blender_object, material, group_name", (blender_object, material, group_name))

        if not ObjectService.has_vertex_group(blender_object, group_name):
            return

        ObjectService.activate_blender_object(blender_object)
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

        typing.cast(bpy.types.Mesh, blender_object.data).materials.append(material)
        slot_number = blender_object.material_slots.find(material.name)
        _LOG.dump("slot_number", slot_number)

        # activate_blender_object() above made blender_object the active one, so context.object is set.
        typing.cast(bpy.types.Object, bpy.context.object).active_material_index = slot_number

        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.vertex_group_set_active(group=group_name)
        bpy.ops.object.vertex_group_select()
        bpy.ops.object.material_slot_assign()

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

    @staticmethod
    def create_and_assign_material_slots(basemesh: bpy.types.Object, bodyproxy: bpy.types.Object | None = None) -> None:
        """Creates and assigns material slots for each body vertex group.

        Args:
            basemesh (bpy.types.Object): The base mesh to assign material slots to.
            bodyproxy (bpy.types.Object | None): The body proxy to assign material slots to (optional).
        """

        if not MaterialService.has_materials(basemesh):
            raise ValueError("Basemesh must have the initial material created before calling this method")

        _LOG.debug("basemesh, proxymesh", (basemesh, bodyproxy))

        # has_materials() above established that there is at least one slot, and a slot created by
        # MPFB always carries a material.
        base_material = typing.cast(bpy.types.Material, basemesh.material_slots[0].material)

        prefix = str(basemesh.name).split(".")[0]

        _LOG.debug("prefix", prefix)

        if bodyproxy is not None:
            MaterialService.delete_all_materials(bodyproxy)
            MaterialService.assign_new_or_existing_material(base_material.name, bodyproxy)

        for group_name in ["nipple", "lips", "fingernails", "toenails", "ears", "genitals"]:
            _LOG.debug("About to create material instance for", group_name)
            material_instance = base_material.copy()
            material_instance.name = prefix + "." + group_name
            _LOG.debug("Material final name", material_instance.name)
            if basemesh and ObjectService.has_vertex_group(basemesh, group_name):
                MaterialService._assign_material_instance(basemesh, material_instance, group_name)
            if bodyproxy and ObjectService.has_vertex_group(bodyproxy, group_name):
                MaterialService._assign_material_instance(bodyproxy, material_instance, group_name)
            else:
                _LOG.debug("Not adding slot to bodyproxy because it is none or group does not exist", (bodyproxy, group_name))

    @staticmethod
    def find_color_adjustment(blender_object: bpy.types.Object | None) -> ColorAdjustment | None:
        """Return a dict with all color adjustments that were applied to the blender object's material slots.

        Args:
            blender_object (bpy.types.Object | None): The blender object to find color adjustments for. A
                None object is logged and None is returned.

        Returns:
            A dict with all color adjustments that were applied to the blender object's material slots.'
        """
        if not blender_object:
            _LOG.debug("The blender object was none")
            return None
        material = MaterialService.get_material(blender_object)
        if not material:
            _LOG.debug("The blender object did not have a material")
            return None

        if not material.node_tree:
            raise ValueError('Could not find node tree on material for ' + str(blender_object))

        principled = NodeService.find_first_node_by_type_name(material.node_tree, "ShaderNodeBsdfPrincipled")
        if not principled:
            _LOG.debug("The material did not have a principled node, maybe not a makeskin material? ", blender_object)
            return None

        mix = NodeService.find_node_linked_to_socket(material.node_tree, principled, "Base Color")

        if not mix:
            _LOG.debug("There was no mix node")
            return None

        info = NodeService.get_node_info(mix)

        if not info or "values" not in info:
            raise ValueError('Could not find values:' + str(info))

        return info["values"]

    @staticmethod
    def apply_color_adjustment(blender_object: bpy.types.Object | None, color_adjustment: ColorAdjustment) -> None:
        """Apply a color adjustment to the blender object's material slots.

        Args:
            blender_object (bpy.types.Object | None): The blender object to apply the color adjustment
                to. A None object is logged and the method returns without doing anything.
            color_adjustment (ColorAdjustment): The color adjustment to apply.
        """
        if not blender_object:
            _LOG.debug("The blender object was none")
            return
        if not blender_object:
            _LOG.debug("The color adjustment was none")
            return

        material = MaterialService.get_material(blender_object)
        if not material:
            _LOG.debug("The blender object did not have a material")
            return

        if not material.node_tree:
            raise ValueError('Could not find node tree on material for ' + str(blender_object))

        principled = NodeService.find_first_node_by_type_name(material.node_tree, "ShaderNodeBsdfPrincipled")
        if not principled:
            _LOG.debug("The material did not have a principled node, maybe not a makeskin material? ", blender_object)
            return

        mix = NodeService.find_node_linked_to_socket(material.node_tree, principled, "Base Color")

        # find_color_adjustment() returns early when there is no mix node; this method does not
        # test, and set_socket_default_values() silently does nothing for a None, so applying an
        # adjustment to a material without one changes nothing and reports nothing.
        NodeService.set_socket_default_values(typing.cast(bpy.types.Node, mix), color_adjustment)

    @staticmethod
    def get_skin_diffuse_color() -> list[float]:
        """Return a static color for the skin material, for example to be used in the viewport."""
        return [0.721, 0.568, 0.431, 1.0]

    @staticmethod
    def get_generic_bodypart_diffuse_color() -> list[float]:
        """Return a static color for a bodypart material, for example to be used in the viewport."""
        return [0.194, 0.030, 0.014, 1.0]

    @staticmethod
    def get_generic_clothes_diffuse_color() -> list[float]:
        """Return a static color for a clothes material, for example to be used in the viewport."""
        return [0.6, 0.6, 0.6, 1.0]

    @staticmethod
    def get_eye_diffuse_color() -> list[float]:
        """Return a static color for the eye material, for example to be used in the viewport."""
        return [0.95, 0.95, 0.95, 1.0]

    @staticmethod
    def get_teeth_diffuse_color() -> list[float]:
        """Return a static color for the teeth material, for example to be used in the viewport."""
        return [0.95, 0.95, 0.95, 1.0]

    @staticmethod
    def get_diffuse_colors() -> dict[str, list[float]]:
        """Return all static colors for all materials."""
        colors = dict()
        colors["Eyes"] = MaterialService.get_eye_diffuse_color()
        colors["Teeth"] = MaterialService.get_teeth_diffuse_color()
        colors["Proxymeshes"] = MaterialService.get_skin_diffuse_color()
        colors["Proxymesh"] = MaterialService.get_skin_diffuse_color()
        colors["Bodyproxy"] = MaterialService.get_skin_diffuse_color()
        colors["Basemesh"] = MaterialService.get_skin_diffuse_color()
        colors["Clothes"] = MaterialService.get_generic_clothes_diffuse_color()

        for key in ["Bodypart", "Eyebrows", "Eyelashes", "Hair", "Tongue"]:
            colors[key] = MaterialService.get_generic_bodypart_diffuse_color()

        return colors
