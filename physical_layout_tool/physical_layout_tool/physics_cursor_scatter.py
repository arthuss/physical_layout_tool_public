# coding: utf-8
# Version: 1.7.0.0 (GPU Drawer Integration)
bl_info = {
    "name": "Mouse Scatter Tool (Advanced Animation)",
    "blender": (4, 4, 0),
    "category": "Object",
    "author": "EXEGET",
    "version": (1, 7, 0, 0), # Version erhöht für GPU Drawer
    "location": "View3D > Sidebar > PhysicalTool Tab",
    "description": "Advanced mouse-based object scattering with on-the-fly instancing/static conversion. GPU previews.",
}

import bpy
import random
from mathutils import Vector, Euler, Matrix, Quaternion
from mathutils.bvhtree import BVHTree
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
import math
import time
import traceback
import numpy as np # Task 1: Sicherstellen, dass numpy importiert ist

# --- Globale Variablen für C++ Modul und Flag (werden durch Import aus __init__.py gefüllt) ---
scatter_accel = None
NATIVE_MODULE_AVAILABLE = False
# ---

# Import für das C++ Modul und das Verfügbarkeits-Flag aus dem Hauptpaket
try:
    from . import scatter_accel as pkg_ext_scatter_accel
    from . import NATIVE_MODULE_AVAILABLE as pkg_NATIVE_MODULE_AVAILABLE

    scatter_accel = pkg_ext_scatter_accel
    NATIVE_MODULE_AVAILABLE = pkg_NATIVE_MODULE_AVAILABLE

    _module_name = __name__
    if NATIVE_MODULE_AVAILABLE and scatter_accel:
        print(f"INFO [{_module_name}]: Native C++ Modul 'scatter_accel' und Flag 'NATIVE_MODULE_AVAILABLE' erfolgreich über Paket-Namespace bezogen.")
    elif NATIVE_MODULE_AVAILABLE and not scatter_accel:
        print(f"WARNUNG [{_module_name}]: 'NATIVE_MODULE_AVAILABLE' ist True aus Paket, aber 'scatter_accel' ist None. Setze lokal auf nicht verfügbar.")
        NATIVE_MODULE_AVAILABLE = False
        scatter_accel = None
    elif not NATIVE_MODULE_AVAILABLE:
        print(f"INFO [{_module_name}]: Native C++ Modul NICHT verfügbar (gemäß Paket-Namespace: 'NATIVE_MODULE_AVAILABLE' ist False).")
        if scatter_accel is not None:
            print(f"WARNUNG [{_module_name}]: 'NATIVE_MODULE_AVAILABLE' ist False, aber 'scatter_accel' war nicht None. Wird auf None gesetzt.")
            scatter_accel = None
except ImportError as e_imp:
    _module_name = __name__
    print(f"KRITISCH [{_module_name}]: ImportError beim Versuch, C++ Modul/Flag aus Hauptpaket ('..') zu importieren: {e_imp}.")
    print(f"  [{_module_name}]: C++ Beschleunigung wird für dieses Modul DEAKTIVIERT.")
    scatter_accel = None
    NATIVE_MODULE_AVAILABLE = False
except Exception as e_gen_imp:
    _module_name = __name__
    print(f"KRITISCH [{_module_name}]: Allgemeiner Fehler (Typ: {type(e_gen_imp).__name__}) beim Import von C++ Modul/Flag aus Hauptpaket: {e_gen_imp}.")
    print(f"  [{_module_name}]: C++ Beschleunigung wird für dieses Modul DEAKTIVIERT.")
    scatter_accel = None
    NATIVE_MODULE_AVAILABLE = False

# Task 1: Importiere die neuen Drawer-Klassen
from .scatter_draw_helper import CircleWireframeDrawer, GPUMeshGhostPreview

from bpy.props import (
    StringProperty,
    IntProperty,
    FloatProperty,
    PointerProperty,
    BoolProperty,
    EnumProperty,
    CollectionProperty,
    FloatVectorProperty # Hinzugefügt für Farben
)
from bpy.types import PropertyGroup

# --- Global Debug Setting ---
SCATTER_DEBUG_MODE = True # Set to False for release builds to suppress tracebacks

# --- Standardized Logging Function ---
def log_scatter_exception(e, context_message="", operator_instance=None, level="ERROR"):
    op_name_part = ""
    if operator_instance and hasattr(operator_instance, 'bl_idname'):
        op_name_part = f" [{operator_instance.bl_idname}]"
    elif operator_instance and hasattr(operator_instance, '__class__') and hasattr(operator_instance.__class__, '__name__'):
        op_name_part = f" [{operator_instance.__class__.__name__}]"
    header = f"--- SCATTER TOOL {level}{op_name_part} ---"
    print(header)
    if context_message:
        print(f"Context: {context_message}")
    print(f"Error Type: {type(e).__name__}")
    print(f"Error Message: {str(e)}")
    if SCATTER_DEBUG_MODE:
        print("Traceback:")
        traceback.print_exc()
    print("-" * len(header))

# --- Helper function to get or create collection ---
def get_or_create_scatter_target_collection(collection_name_str, context, parent_collection_obj=None):
    if not collection_name_str: return None
    if collection_name_str in bpy.data.collections: return bpy.data.collections[collection_name_str]
    else:
        active_scene = context.scene if hasattr(context, 'scene') and context.scene else bpy.context.scene
        if not active_scene:
            print(f"SCATTER_UTIL Error (get_or_create): Scene not found for collection '{collection_name_str}'.")
            return None
        parent_to_use = parent_collection_obj if parent_collection_obj else active_scene.collection
        if not parent_to_use:
            print(f"SCATTER_UTIL Error (get_or_create): No parent collection for '{collection_name_str}'.")
            return None
        try:
            new_collection = bpy.data.collections.new(name=collection_name_str)
            parent_to_use.children.link(new_collection)
            return new_collection
        except Exception as e:
            log_scatter_exception(e, f"Creating collection '{collection_name_str}'")
            return None

# --- PropertyGroup for individual scatter object entries in the list ---
class ScatterObjectEntry(PropertyGroup):
    obj: PointerProperty(
        name="Object",
        type=bpy.types.Object,
        description="An object for random selection during scattering" # EN
    )

# --- Main Settings PropertyGroup ---
class MouseScatterSettings(PropertyGroup):
    scatter_objects_list: CollectionProperty(
        type=ScatterObjectEntry,
        name="Objects to Scatter"
    )
    active_scatter_object_index: IntProperty(
        name="Active Scatter Object Index",
        default=0
    )
    ground_object: PointerProperty(
        name="Ground Mesh",
        type=bpy.types.Object,
        description="The object to raycast against (in OBJECT mode)", # EN
        poll=lambda self, object: object.type == 'MESH'
    )
    raycast_mode: EnumProperty(
        name="Raycast Mode",
        items=[
            ('VIEW', "From View (Flat Grid)", "Place on Z=0 plane based on view"),
            ('VIEW_DEPTH', "From View (Raycast)", "Raycast from view direction into scene"),
            ('OBJECT', "To Ground Object", "Raycast against a specific ground mesh")
        ],
        default='VIEW_DEPTH',
        description="Determines how the placement position is found"
    )
    placement_mode: EnumProperty(
        name="Placement Mode",
        items=[
            ('GHOST_IMMEDIATE', "Immediate (GPU Ghost Preview)", "Place object at ghost location. Marks for instancing or creates plain object."), # Angepasst
            ('ANIMATED_DROP_DIRECT', "Animated Drop (GPU Drop Marker)", "Object starts falling from mouse click (GPU marker). Marks for instancing or creates plain object."), # Angepasst
        ],
        default='GHOST_IMMEDIATE',
        description="Determines how objects are placed or start their animation"
    )
    use_brush_mode: BoolProperty(
        name="Brush Mode",
        default=False,
        description="Place objects continuously while dragging mouse"
    )
    brush_spacing: FloatProperty(
        name="Brush Spacing",
        default=0.5,
        min=0.01,
        description="Minimum distance between placed objects in brush mode"
    )
    use_scatter_on_scatter: BoolProperty(
        name="Stack on Scatters",
        default=True,
        description="Attempt to place/land objects on already scattered objects"
    )
    snap_to_center_on_stack: BoolProperty(
        name="Snap to Center on Stack",
        default=False,
        description="Positions object above the target's center when stacking"
    )
    prevent_overlap: BoolProperty(
        name="Prevent Overlap",
        default=False,
        description="Prevents placement/drop start if overlap occurs"
    )
    overlap_check_distance: FloatProperty(
        name="Overlap Check Distance",
        default=-0.01,
        min=-1.0,
        soft_max=50.0,
        description="Maximum distance for overlap check"
    )
    apply_transforms_to_sources_on_invoke: BoolProperty(
        name="Apply Transforms to Sources on Start",
        default=False,
        description="Automatically applies transforms to all objects in the 'Objects to Scatter' list when the operator starts. This affects the original objects."
    )
    offset_application_mode: EnumProperty(
        name="Offset Application",
        items=[('WORLD_Z', "World Z-Offset", "Offset along World Z-axis"), ('NORMAL', "Normal Offset", "Offset along surface normal")],
        default='WORLD_Z', description="How the height offset is applied"
    )
    height_min: FloatProperty(name="Min Height Offset", default=0.0, min=-10.0, max=10.0, precision=4)
    height_max: FloatProperty(name="Max Height Offset", default=0.0, min=-10.0, max=10.0, precision=4)
    rot_x_min: FloatProperty(name="Min X Rot (deg)", default=0.0)
    rot_x_max: FloatProperty(name="Max X Rot (deg)", default=30.0)
    rot_y_min: FloatProperty(name="Min Y Rot (deg)", default=0.0)
    rot_y_max: FloatProperty(name="Max Y Rot (deg)", default=30.0)
    rot_z_min: FloatProperty(name="Min Z Rot (deg)", default=-180.0)
    rot_z_max: FloatProperty(name="Max Z Rot (deg)", default=180.0)
    scale_min: FloatProperty(name="Min Scale", default=1.0, min=0.01)
    scale_max: FloatProperty(name="Max Scale", default=1.0, min=0.01)
    drop_anim_steps: IntProperty(name="Drop Anim Steps", default=30, min=1, max=600)
    drop_anim_speed_step: FloatProperty(name="Drop Anim Speed/Step", default=1.0, min=0.001, soft_max=10.0, unit='LENGTH', precision=3)
    enable_tumble_during_drop: BoolProperty(name="Enable Tumble During Drop", default=True)
    tumble_rotation_intensity_factor: FloatProperty(name="Tumble Rot Intensity", default=0.2, min=0.0, max=1.0, subtype='FACTOR', precision=3)
    tumble_offset_xy_max_step: FloatProperty(name="Max Tumble XY Offset/Step", default=0.02, min=0.0, unit='LENGTH', precision=4)
    tumble_frequency_during_drop: FloatProperty(name="Tumble Frequency", default=0.75, min=0.0, max=1.0, subtype='FACTOR', precision=2)
    create_debug_empties_on_land: BoolProperty(name="Debug Landings", default=False, description="Creates empties at landing/hit points for debugging drop animation")
    landing_z_correction: FloatProperty( name="Landing Z Correction", default=0.015, precision=4, unit='LENGTH', description="Small Z adjustment for landed objects to prevent clipping")
    use_post_land_spawn: BoolProperty(
        name="Post-Landing Spawn (Multiball)",
        default=False,
        description="After the main object lands, copies are spawned and animate outwards."
    )
    post_land_spawn_count_min: IntProperty(
        name="Min Spawn Count",
        default=3, min=1, max=20,
        description="Minimum number of copies to spawn"
    )
    post_land_spawn_count_max: IntProperty(
        name="Max Spawn Count",
        default=6, min=1, max=20,
        description="Maximum number of copies to spawn"
    )
    post_land_spawn_distance_min: FloatProperty(
        name="Min Spawn/Roll Distance",
        default=0.3, min=0.01, max=100.0,
        description="Minimum scatter/roll distance (base value, can be scaled by object size)"
    )
    post_land_spawn_distance_max: FloatProperty(
        name="Max Spawn/Roll Distance",
        default=0.7, min=0.01, max=100.0,
        description="Maximum scatter/roll distance (base value, can be scaled by object size)"
    )
    post_land_spawn_scale_distance_by_mesh_size: BoolProperty(
        name="Scale Spawn Distance by Object Size",
        default=False,
        description="Scales Min/Max Spawn Distances based on the main landed object's size"
    )
    post_land_spawn_mesh_size_influence: FloatProperty(
        name="Object Size Influence on Distance",
        default=4.0, min=0.01, max=10.0,
        description="Multiplier for object size effect on spawn distances. 1.0 means distances are multiplied by avg X/Y dimension."
    )
    post_land_spawn_duration_frames: IntProperty(
        name="Spawn Anim Duration (Frames)",
        default=20, min=1, max=120,
        description="Duration of the scatter animation in frames"
    )
    post_land_spawn_copy_main_obj_transform: BoolProperty(
        name="Copy Main Object Transform",
        default=True,
        description="Spawned objects inherit scale and rotation from the main landed object"
    )
    post_land_spawn_offset_from_surface: FloatProperty(
        name="Spawn Surface Offset Z",
        default=0.02, min=0.0, max=2.0,
        description="Small Z offset for spawned objects from the surface (to prevent clipping)"
    )
    post_land_spawn_roll_revolutions: FloatProperty(
        name="Roll Revolutions",
        default=1.0, min=0.0, max=10.0,
        description="Number of full revolutions during the roll-out animation"
    )
    post_land_spawn_use_virtual_gravity: BoolProperty(
        name="Use Virtual Gravity",
        default=False,
        description="Makes spawned objects roll more realistically downhill on slopes"
    )

    # Task 2: MouseScatterSettings erweitern
    marker_color: FloatVectorProperty(
        name="Drop Marker Color", default=(0.1, 0.7, 1.0, 0.8),
        subtype='COLOR', size=4, min=0.0, max=1.0,
        description="Color and alpha for the animated drop marker"
    )
    marker_radius: FloatProperty(
        name="Drop Marker Radius", default=0.07,
        min=0.005, max=1.0, precision=3,
        description="Radius of the animated drop marker"
    )
    marker_segments: IntProperty(
        name="Drop Marker Segments", default=20,
        min=3, max=64,
        description="Number of segments for the circular drop marker"
    )
    marker_line_width: FloatProperty(
        name="Drop Marker Line Width", default=1.5,
        min=0.5, max=10.0, precision=1,
        description="Line width for the drop marker"
    )
    ghost_color: FloatVectorProperty(
        name="Ghost Preview Color", default=(0.2, 0.9, 0.2, 0.35),
        subtype='COLOR', size=4, min=0.0, max=1.0,
        description="Color and alpha for the GPU-based ghost preview"
    )

# --- List Operators --- (bleiben unverändert)
class OBJECT_OT_add_scatter_object_entry(bpy.types.Operator):
    bl_idname = "scatter_list.add_entry"; bl_label = "Add Empty Slot"; bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        try:
            settings = context.scene.mouse_scatter_settings
            settings.scatter_objects_list.add()
            settings.active_scatter_object_index = len(settings.scatter_objects_list) - 1
        except Exception as e:
            log_scatter_exception(e, "Adding scatter object entry", self)
            self.report({'ERROR'}, "Error adding list entry.")
            return {'CANCELLED'}
        return {'FINISHED'}

class OBJECT_OT_remove_scatter_object_entry(bpy.types.Operator):
    bl_idname = "scatter_list.remove_entry"; bl_label = "Remove Selected Slot"; bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        try:
            settings = context.scene.mouse_scatter_settings
            return len(settings.scatter_objects_list) > 0 and 0 <= settings.active_scatter_object_index < len(settings.scatter_objects_list)
        except Exception: return False
    def execute(self, context):
        try:
            settings = context.scene.mouse_scatter_settings; index = settings.active_scatter_object_index
            if 0 <= index < len(settings.scatter_objects_list):
                settings.scatter_objects_list.remove(index)
                list_len = len(settings.scatter_objects_list)
                if list_len == 0: settings.active_scatter_object_index = 0
                elif index >= list_len: settings.active_scatter_object_index = list_len - 1
            else: self.report({'WARNING'}, "Invalid index selected for removal."); return {'CANCELLED'}
        except Exception as e:
            log_scatter_exception(e, "Removing scatter object entry", self)
            self.report({'ERROR'}, "Error removing list entry.")
            return {'CANCELLED'}
        return {'FINISHED'}

class OBJECT_OT_move_scatter_object_entry(bpy.types.Operator):
    bl_idname = "scatter_list.move_entry"; bl_label = "Move Slot"; bl_options = {'REGISTER', 'UNDO'}; direction: EnumProperty(items=(('UP', 'Up', ''), ('DOWN', 'Down', '')), name="Direction")
    @classmethod
    def poll(cls, context):
        try:
            settings = context.scene.mouse_scatter_settings
            return len(settings.scatter_objects_list) > 1 and 0 <= settings.active_scatter_object_index < len(settings.scatter_objects_list)
        except Exception: return False
    def execute(self, context):
        try:
            settings = context.scene.mouse_scatter_settings; index = settings.active_scatter_object_index
            if not (0 <= index < len(settings.scatter_objects_list)): self.report({'WARNING'}, "Invalid index selected for moving."); return {'CANCELLED'}
            if self.direction == 'UP' and index > 0: settings.scatter_objects_list.move(index, index - 1); settings.active_scatter_object_index -= 1
            elif self.direction == 'DOWN' and index < len(settings.scatter_objects_list) - 1: settings.scatter_objects_list.move(index, index + 1); settings.active_scatter_object_index += 1
        except Exception as e:
            log_scatter_exception(e, f"Moving scatter object entry (direction: {self.direction})", self)
            self.report({'ERROR'}, "Error moving list entry.")
            return {'CANCELLED'}
        return {'FINISHED'}

class OBJECT_OT_add_selected_to_scatter_list(bpy.types.Operator):
    bl_idname = "scatter_list.add_selected"; bl_label = "Add Selected"; bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context): return any(obj.type == 'MESH' for obj in context.selected_objects)
    def execute(self, context):
        try:
            settings = context.scene.mouse_scatter_settings; added_count = 0; existing_objs = {entry.obj for entry in settings.scatter_objects_list if entry.obj}
            for obj in context.selected_objects:
                if obj.type == 'MESH' and obj not in existing_objs: new_entry = settings.scatter_objects_list.add(); new_entry.obj = obj; existing_objs.add(obj); added_count += 1
            if added_count > 0: self.report({'INFO'}, f"{added_count} object(s) added to scatter list.")
            else: self.report({'INFO'}, "No new suitable objects selected or already in list.")
        except Exception as e:
            log_scatter_exception(e, "Adding selected objects to scatter list", self)
            self.report({'ERROR'}, "Error adding selected objects to list.")
            return {'CANCELLED'}
        return {'FINISHED'}

class OBJECT_OT_clear_scatter_list(bpy.types.Operator):
    bl_idname = "scatter_list.clear_all"; bl_label = "Clear List"; bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        try: return len(context.scene.mouse_scatter_settings.scatter_objects_list) > 0
        except Exception: return False
    def execute(self, context):
        try:
            settings = context.scene.mouse_scatter_settings; settings.scatter_objects_list.clear(); settings.active_scatter_object_index = 0; self.report({'INFO'}, "Scatter list cleared.")
        except Exception as e:
            log_scatter_exception(e, "Clearing scatter list", self)
            self.report({'ERROR'}, "Error clearing scatter list.")
            return {'CANCELLED'}
        return {'FINISHED'}

class OBJECT_OT_apply_transforms_to_scatter_objects(bpy.types.Operator):
    bl_idname = "scatter_list.apply_transforms"
    bl_label = "Apply Transforms (Scatter List)"
    bl_description = "Applies Location, Rotation, and Scale to all objects in the scatter list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        try:
            settings = context.scene.mouse_scatter_settings
            return len(settings.scatter_objects_list) > 0 and any(entry.obj for entry in settings.scatter_objects_list)
        except Exception: return False

    def execute(self, context):
        settings = context.scene.mouse_scatter_settings
        original_active = context.view_layer.objects.active
        original_selected_names = {obj.name for obj in context.selected_objects if obj}
        original_mode = context.mode
        if original_mode != 'OBJECT':
            try: bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as e:
                log_scatter_exception(e, "Setting OBJECT mode in apply_transforms", self)
                self.report({'ERROR'}, "Could not switch to Object Mode.")
                return {'CANCELLED'}

        applied_count = 0
        for entry in settings.scatter_objects_list:
            obj = entry.obj
            if obj and obj.name in context.view_layer.objects:
                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
                    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
                    applied_count += 1
                except ReferenceError as e_ref:
                    log_scatter_exception(e_ref, f"Applying transforms, object '{obj.name}' became invalid", self)
                    self.report({'WARNING'}, f"Object '{obj.name}' became invalid while applying transforms.")
                except RuntimeError as e_rt:
                    log_scatter_exception(e_rt, f"Applying transforms to '{obj.name}'", self)
                    self.report({'WARNING'}, f"Could not apply transforms to '{obj.name}': {e_rt}")
                except Exception as e_gen:
                    log_scatter_exception(e_gen, f"Unexpected error applying transforms to '{obj.name}'", self)
                    self.report({'ERROR'}, f"Unexpected error with '{obj.name}': {e_gen}")

        try:
            bpy.ops.object.select_all(action='DESELECT')
            for name in original_selected_names:
                obj_to_reselect = bpy.data.objects.get(name)
                if obj_to_reselect and obj_to_reselect.name in context.view_layer.objects:
                    try: obj_to_reselect.select_set(True)
                    except ReferenceError: pass
            if original_active and original_active.name in context.view_layer.objects:
                try: context.view_layer.objects.active = original_active
                except ReferenceError: pass
            if context.mode == 'OBJECT' and original_mode != 'OBJECT':
                try: bpy.ops.object.mode_set(mode=original_mode)
                except RuntimeError: pass
        except Exception as e_cleanup:
            log_scatter_exception(e_cleanup, "Restoring selection/mode in apply_transforms", self, level="WARNING")

        if applied_count > 0: self.report({'INFO'}, f"Transforms applied to {applied_count} object(s) in scatter list.")
        else: self.report({'INFO'}, "No objects found in scatter list to apply transforms or error occurred.")
        return {'FINISHED'}

class OBJECT_OT_prepare_scatter_instances(bpy.types.Operator):
    bl_idname = "scatter_list.prepare_instances"; bl_label = "Prepare Instances for Physics"; bl_description = "Converts scatter instances to real objects and adds Rigid Body. Needed before simulation/baking if 'Mark for Instancing' was enabled"; bl_options = {'REGISTER', 'UNDO'}
    _original_active = None; _original_selected = []
    @classmethod
    def poll(cls, context):
        try:
            im_settings = getattr(context.scene, 'instance_manager_settings', None)
            if not im_settings: return False
            inst_coll = bpy.data.collections.get(im_settings.instance_collection_name)
            if not inst_coll: return False
            return any(obj.data and obj.data.users > 1 and obj.name in inst_coll.objects for obj in context.scene.objects)
        except Exception: return False

    def execute(self, context):
        self._original_active = context.view_layer.objects.active
        self._original_selected = [o.name for o in context.selected_objects if o]
        prepared_count = 0

        im_settings = getattr(context.scene, 'instance_manager_settings', None)
        if not im_settings:
            self.report({'ERROR'}, "Instance Manager settings not found.")
            return {'CANCELLED'}

        if hasattr(bpy.ops.object, 'prepare_managed_instances_modal'):
            try:
                instance_col = bpy.data.collections.get(im_settings.instance_collection_name)
                if not instance_col:
                    self.report({'INFO'}, f"Instance Collection '{im_settings.instance_collection_name}' not found for preparing.")
                    self._restore_selection(context)
                    return {'FINISHED'}

                bpy.ops.object.select_all(action='DESELECT')
                selected_for_prepare = 0
                for obj in instance_col.objects:
                    if obj.data and obj.data.users > 1 :
                        try:
                            obj.select_set(True)
                            selected_for_prepare +=1
                        except ReferenceError: pass

                if selected_for_prepare > 0:
                    bpy.ops.object.prepare_managed_instances_modal('INVOKE_DEFAULT')
                    self.report({'INFO'}, f"Triggered 'Make Instances Editable' for {selected_for_prepare} objects.")
                    prepared_count = selected_for_prepare
                else:
                    self.report({'INFO'}, "No managed instances found to prepare in the instance collection.")

            except RuntimeError as e_op_call_rt:
                log_scatter_exception(e_op_call_rt, "RuntimeError calling prepare_managed_instances_modal", self)
                self.report({'ERROR'}, f"RuntimeError calling 'Make Instances Editable': {e_op_call_rt}")
            except Exception as e_op_call:
                log_scatter_exception(e_op_call, "Calling prepare_managed_instances_modal", self)
                self.report({'ERROR'}, f"Error calling 'Make Instances Editable': {e_op_call}")
        else:
            self.report({'WARNING'}, "'Make Instances Editable' operator not found (from Instance Manager).")

        self._restore_selection(context)
        if prepared_count > 0 or not hasattr(bpy.ops.object, 'prepare_managed_instances_modal') :
            self.report({'INFO'}, f"Prepare Instances process initiated. Check console for details from Instance Manager.")
        return {'FINISHED'}

    def _restore_selection(self, context):
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for obj_name in self._original_selected:
                obj_orig_sel = bpy.data.objects.get(obj_name)
                if obj_orig_sel and obj_orig_sel.name in context.view_layer.objects:
                    try: obj_orig_sel.select_set(True)
                    except ReferenceError: pass

            original_active_obj = bpy.data.objects.get(self._original_active.name if self._original_active else None)
            if original_active_obj and original_active_obj.name in context.view_layer.objects:
                try: context.view_layer.objects.active = original_active_obj
                except ReferenceError: pass
            elif self._original_selected:
                first_selected_name = next(iter(self._original_selected), None)
                if first_selected_name:
                    first_sel_obj = bpy.data.objects.get(first_selected_name)
                    if first_sel_obj and first_sel_obj.name in context.view_layer.objects:
                        try: context.view_layer.objects.active = first_sel_obj
                        except ReferenceError: pass
        except Exception as e:
            log_scatter_exception(e, "Restoring selection in _restore_selection", self if hasattr(self, 'bl_idname') else None, level="WARNING")

# --- AnimatedFallingObject & PostLandSpawnObject Classes --- (bleiben unverändert)
class AnimatedFallingObject:
    def __init__(self, obj_ref, total_steps, source_mesh_name_for_processing):
        self.obj = obj_ref
        self.name = obj_ref.name if obj_ref else "InvalidObject"
        self.current_step = 0
        self.drop_steps_total = total_steps
        self.landed = False
        self.debug_empties_names = []
        self.spawn_triggered = False
        self.processed_on_land = False
        self.source_mesh_name_for_processing = source_mesh_name_for_processing

class PostLandSpawnObject:
    def __init__(self, obj_ref, start_pos_world, end_pos_world, duration_frames, settings_ref,
                 initial_orientation_quat, surface_normal_at_spawn, initial_scale_vector,
                 source_mesh_name_for_processing):
        self.obj = obj_ref
        self.start_pos_world = start_pos_world.copy()
        self.end_pos_world = end_pos_world.copy()
        self.current_anim_frame = 0
        self.duration_frames = max(1, duration_frames)
        self.settings_ref = settings_ref
        self.animation_done = False
        self.initial_orientation_quat = initial_orientation_quat.copy()
        self.source_mesh_name_for_processing = source_mesh_name_for_processing

        if self.obj:
            self.obj.rotation_mode = 'QUATERNION'
            self.obj.rotation_quaternion = self.initial_orientation_quat
            self.obj.scale = initial_scale_vector.copy()

        obj_dims = Vector((0.1,0.1,0.1))
        if self.obj:
            try:
                depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_obj = self.obj.evaluated_get(depsgraph)
                obj_dims = eval_obj.dimensions
            except Exception as e:
                log_scatter_exception(e, f"Getting evaluated object/dimensions for PostLandSpawnObject '{self.obj.name if self.obj else 'Unknown'}'")

        self.move_vector_world = self.end_pos_world - self.start_pos_world
        self.total_path_distance = self.move_vector_world.length
        self.move_direction_world = Vector((0,0,0))
        if self.total_path_distance > 0.0001:
            self.move_direction_world = self.move_vector_world.normalized()

        self.roll_axis_world = Vector((0,0,0))
        norm_spawn_safe = surface_normal_at_spawn if surface_normal_at_spawn and surface_normal_at_spawn.length > 0.001 else Vector((0,0,1))
        if self.move_direction_world.length > 0.5:
            cross_product_vec = norm_spawn_safe.cross(self.move_direction_world)
            if cross_product_vec.length > 0.00001:
                self.roll_axis_world = cross_product_vec.normalized()

        avg_dim_for_radius = (obj_dims.x + obj_dims.y) / 2.0
        object_radius = max(0.001, avg_dim_for_radius / 2.0)

        self.total_roll_radians = 0.0
        if self.total_path_distance > 0.001 and settings_ref.post_land_spawn_roll_revolutions > 0:
            circumference = 2 * math.pi * object_radius
            if circumference > 0.001:
                self.total_roll_radians = (self.total_path_distance / circumference) * settings_ref.post_land_spawn_roll_revolutions * (2 * math.pi)

        if self.obj and self.obj.animation_data:
            try: self.obj.animation_data_clear()
            except Exception as e_anim: log_scatter_exception(e_anim, f"Clearing animation data for PostLandSpawnObject '{self.obj.name}'")
        if self.obj: self.obj.location = self.start_pos_world

    def update(self):
        if self.animation_done or not self.obj or self.obj.name not in bpy.data.objects:
            self.animation_done = True
            return True
        try:
            if self.current_anim_frame <= self.duration_frames:
                factor = self.current_anim_frame / self.duration_frames
                self.obj.location = self.start_pos_world.lerp(self.end_pos_world, factor)
                if self.total_roll_radians > 0.001 and self.roll_axis_world.length > 0.5:
                    current_rotation_angle = self.total_roll_radians * factor
                    delta_roll_quat = Quaternion(self.roll_axis_world, current_rotation_angle)
                    self.obj.rotation_quaternion = delta_roll_quat @ self.initial_orientation_quat
                self.current_anim_frame += 1
                return False
            else:
                self.animation_done = True
                self.obj.location = self.end_pos_world
                if self.total_roll_radians > 0.001 and self.roll_axis_world.length > 0.5:
                    final_roll_quat = Quaternion(self.roll_axis_world, self.total_roll_radians)
                    self.obj.rotation_quaternion = final_roll_quat @ self.initial_orientation_quat
                if self.obj.animation_data:
                    self.obj.animation_data_clear()
                return True
        except Exception as e:
            log_scatter_exception(e, f"Updating PostLandSpawnObject '{self.obj.name if self.obj else 'Unknown'}'", level="WARNING")
            self.animation_done = True
            return True

# --- Main Scatter Operator (OBJECT_OT_mouse_scatter) ---
class OBJECT_OT_mouse_scatter(bpy.types.Operator):
    bl_idname = "object.mouse_scatter"
    bl_label = "Mouse Scatter & Drop"
    bl_options = {'REGISTER', 'UNDO'}

    _timer: bpy.types.Timer = None
    _mouse_x: int = 0
    _mouse_y: int = 0
    _session_source_collection: bpy.types.Collection = None

    # Task 1: Entferne alte Ghost-Member, füge neue Drawer-Member hinzu
    # _ghost: bpy.types.Object = None # ENTFERNT
    # ghost_name_cached: StringProperty() # ENTFERNT
    _drop_marker_drawer: CircleWireframeDrawer = None
    _ghost_drawer: GPUMeshGhostPreview = None

    _current_scatter_source_obj: bpy.types.Object = None
    _is_dragging: bool = False
    _last_placed_loc: Vector = None
    _last_action_time = 0.0
    _falling_objects_data: list = []
    _post_land_spawn_objects: list = []
    _scatter_debug_empties_names: list = []
    _last_overlap_report_time = 0.0

    # Alte Ghost-Management-Methoden sind entfernt (create_preview, remove_ghost_object, update_preview)

    def _get_processing_settings_for_cpp(self, context) -> dict: # Unverändert
        im_settings = getattr(context.scene, 'instance_manager_settings', None)
        if not im_settings:
            self.report({'WARNING'}, "Instance Manager Settings not found for C++ processing.")
            return None
        return {
            "mode_is_instancing": im_settings.use_instancing,
            "apply_rigidbody_static": im_settings.use_rigid_for_non_instances,
            "instance_collection_name": im_settings.instance_collection_name,
            "static_collection_name": im_settings.static_collection_name,
            "instance_name_base_suffix": "_inst"
        }

    def _apply_rigid_body_to_object(self, context, obj_to_modify): # Unverändert
        if not obj_to_modify or obj_to_modify.rigid_body:
            return False

        phys_settings_main = getattr(context.scene, 'physical_tool_settings', None)
        default_mass = getattr(phys_settings_main, 'mass', 1.0)
        default_shape = getattr(phys_settings_main, 'collision_shape', 'CONVEX_HULL')
        default_margin = getattr(phys_settings_main, 'collision_margin', 0.001)

        original_active = context.view_layer.objects.active
        original_selected_names = {o.name for o in context.selected_objects if o}

        original_hide_viewport = obj_to_modify.hide_get(view_layer=context.view_layer)
        original_hide_select = obj_to_modify.hide_select
        if original_hide_viewport: obj_to_modify.hide_set(False, view_layer=context.view_layer)
        if original_hide_select: obj_to_modify.hide_select = False

        bpy.ops.object.select_all(action='DESELECT')
        success = False
        try:
            obj_to_modify.select_set(True)
            context.view_layer.objects.active = obj_to_modify
            bpy.ops.rigidbody.object_add()

            if obj_to_modify.rigid_body:
                rb = obj_to_modify.rigid_body
                rb.type = 'ACTIVE'
                rb.mass = default_mass
                rb.collision_shape = default_shape
                rb.use_margin = True
                rb.collision_margin = default_margin
                rb.linear_damping = 0.04
                rb.angular_damping = 0.1
                rb.use_deactivation = True
                rb.use_start_deactivated = False
                context.view_layer.update()
                success = True
            else:
                self.report({'WARNING'}, f"Rigid Body could not be added to '{obj_to_modify.name}' (after ops call).")
        except RuntimeError as e_rt:
            log_scatter_exception(e_rt, f"Adding/configuring Rigid Body to '{obj_to_modify.name}'", self)
            self.report({'WARNING'}, f"Could not add/configure Rigid Body for '{obj_to_modify.name}': {e_rt}")
        except Exception as e_gen:
            log_scatter_exception(e_gen, f"General error adding/configuring Rigid Body to '{obj_to_modify.name}'", self)
        finally:
            bpy.ops.object.select_all(action='DESELECT')
            for name in original_selected_names:
                sel_obj = bpy.data.objects.get(name)
                if sel_obj and sel_obj.name in context.view_layer.objects:
                    try: sel_obj.select_set(True)
                    except ReferenceError: pass

            active_obj_restored = bpy.data.objects.get(original_active.name) if original_active else None
            if active_obj_restored and active_obj_restored.name in context.view_layer.objects:
                 try: context.view_layer.objects.active = active_obj_restored
                 except ReferenceError: pass
            elif original_selected_names:
                first_selected_name = next(iter(original_selected_names), None)
                if first_selected_name:
                    first_sel_obj_restored = bpy.data.objects.get(first_selected_name)
                    if first_sel_obj_restored and first_sel_obj_restored.name in context.view_layer.objects:
                        try: context.view_layer.objects.active = first_sel_obj_restored
                        except ReferenceError: pass

            if obj_to_modify and obj_to_modify.name in bpy.data.objects:
                if original_hide_viewport: obj_to_modify.hide_set(True, view_layer=context.view_layer)
                if original_hide_select: obj_to_modify.hide_select = True
        return success

    def _cleanup_and_finish_for_error(self, context): # Task 4 angepasst
        if self._timer:
            try: context.window_manager.event_timer_remove(self._timer)
            except Exception as e_timer: log_scatter_exception(e_timer, "Removing timer in cleanup", self, level="WARNING")
            self._timer = None

        # Task 4: Cleanup new drawers
        if self._drop_marker_drawer:
            self._drop_marker_drawer.cleanup()
            self._drop_marker_drawer = None
        if self._ghost_drawer:
            self._ghost_drawer.cleanup()
            self._ghost_drawer = None

        self._cleanup_scatter_debug_objects(context)

        self._falling_objects_data.clear()
        self._post_land_spawn_objects.clear()

        try:
            if context.window: context.window.cursor_modal_set('DEFAULT')
        except Exception as e_cursor: log_scatter_exception(e_cursor, "Resetting cursor in cleanup", self, level="WARNING")

        if context.area:
            try: context.area.tag_redraw()
            except ReferenceError: pass
            except Exception as e_redraw: log_scatter_exception(e_redraw, "Tagging redraw in cleanup", self, level="WARNING")

    def _get_random_transform_settings_dict(self, settings: bpy.types.PropertyGroup) -> dict: # Unverändert
        return {
            "rot_x_min_deg": settings.rot_x_min, "rot_x_max_deg": settings.rot_x_max,
            "rot_y_min_deg": settings.rot_y_min, "rot_y_max_deg": settings.rot_y_max,
            "rot_z_min_deg": settings.rot_z_min, "rot_z_max_deg": settings.rot_z_max,
            "scale_min": settings.scale_min, "scale_max": settings.scale_max,
        }

    def get_random_scatter_object(self, settings): # Unverändert
        if not settings.scatter_objects_list: return None
        valid_objects = [entry.obj for entry in settings.scatter_objects_list if entry.obj and entry.obj.type == 'MESH']
        return random.choice(valid_objects) if valid_objects else None

    def check_overlap_bvh(self, obj_to_check, context, settings, ignore_obj=None): # Unverändert (nutzt Blender-Objekt, was für GPU Ghost problematisch ist)
        # Task 6 Hinweis: Dieser Overlap-Check muss für GPU-Ghost angepasst oder temporär deaktiviert/vereinfacht werden.
        # Aktuell wird er mit dem Blueprint-Objekt in place_object aufgerufen, bevor C++ ins Spiel kommt.
        # Für den *visuellen* Feedback des GPU-Ghosts ist er noch nicht integriert.
        try:
            if not obj_to_check or obj_to_check.name not in bpy.data.objects or \
               not obj_to_check.data or not hasattr(obj_to_check.data, 'polygons'):
                return False
        except ReferenceError: return False
        depsgraph = context.evaluated_depsgraph_get()
        try: eval_obj_to_check = obj_to_check.evaluated_get(depsgraph)
        except (ReferenceError, RuntimeError) as e:
            log_scatter_exception(e, f"Getting evaluated obj_to_check '{obj_to_check.name if obj_to_check else 'Unknown'}' in overlap check", operator_instance=self, level="DEBUG")
            return False
        if not eval_obj_to_check or not eval_obj_to_check.data or \
           not hasattr(eval_obj_to_check.data, 'polygons') or not eval_obj_to_check.data.polygons:
            return False
        try: bvh_obj_to_check = BVHTree.FromObject(eval_obj_to_check, depsgraph, deform=True, cage=False)
        except (RuntimeError, Exception) as e:
            log_scatter_exception(e, f"Creating BVH for obj_to_check '{eval_obj_to_check.name}' in overlap check", operator_instance=self, level="DEBUG")
            return False
        for obj_iter_name in context.scene.objects.keys():
            obj = bpy.data.objects.get(obj_iter_name)
            if not obj: continue
            try:
                if obj == obj_to_check or obj == settings.ground_object or obj == ignore_obj: continue
                if obj.type != 'MESH': continue
                is_potential_obstacle = (obj.rigid_body and obj.rigid_body.type == 'ACTIVE') or \
                                        (self._session_source_collection and self._session_source_collection.name in bpy.data.collections and obj.name.startswith(self._session_source_collection.name))

                im_settings = getattr(context.scene, 'instance_manager_settings', None)
                if im_settings:
                    if im_settings.instance_collection_name and im_settings.instance_collection_name in bpy.data.collections:
                        if obj.name in bpy.data.collections[im_settings.instance_collection_name].objects:
                            is_potential_obstacle = True
                    if im_settings.static_collection_name and im_settings.static_collection_name in bpy.data.collections:
                         if obj.name in bpy.data.collections[im_settings.static_collection_name].objects:
                            is_potential_obstacle = True

                if not is_potential_obstacle: continue
                if not obj.data or not hasattr(obj.data, 'polygons') or not obj.data.polygons: continue
            except ReferenceError: continue
            except Exception as e_iter_check:
                log_scatter_exception(e_iter_check, f"Checking iterated object '{obj.name}' in overlap check", operator_instance=self, level="DEBUG")
                continue
            dist_sq = (obj.matrix_world.translation - obj_to_check.location).length_squared
            obj_to_check_radius = obj_to_check.dimensions.length / 2 if obj_to_check.dimensions else 0.1
            obj_radius = obj.dimensions.length / 2 if obj.dimensions else 0.1
            combined_radius_threshold = (obj_to_check_radius + obj_radius + settings.overlap_check_distance)**2
            if dist_sq > combined_radius_threshold : continue
            try: target_eval = obj.evaluated_get(depsgraph)
            except (ReferenceError, RuntimeError) as e_eval_target:
                log_scatter_exception(e_eval_target, f"Evaluating target object '{obj.name}' in overlap check", operator_instance=self, level="DEBUG")
                continue
            if not target_eval or not target_eval.data or \
               not hasattr(target_eval.data, 'polygons') or not target_eval.data.polygons:
                continue
            try: bvh_target = BVHTree.FromObject(target_eval, depsgraph, deform=True, cage=False)
            except (RuntimeError, Exception) as e_bvh_target:
                log_scatter_exception(e_bvh_target, f"Creating BVH for target '{target_eval.name}' in overlap check", operator_instance=self, level="DEBUG")
                continue
            if bvh_obj_to_check.overlap(bvh_target): return True
        return False

    def place_object(self, context, settings, mouse_x, mouse_y): # Task 6 angepasst
        # Diese Methode wird nur für GHOST_IMMEDIATE relevant sein.
        # Sie erzeugt das temporäre "Marker"-Objekt, das dann von C++ verarbeitet wird.
        if not self._ghost_drawer or not self._ghost_drawer.get_is_visible() or not self._ghost_drawer._batch:
            self.report({'DEBUG'}, "GPU Ghost invalid or hidden, cannot place.")
            return None
        if not self._current_scatter_source_obj or self._current_scatter_source_obj.name not in bpy.data.objects:
            self.report({'WARNING'}, "Current source object invalid for place_object.")
            return None
        if not self._current_scatter_source_obj.data:
            self.report({'WARNING'}, f"Source object '{self._current_scatter_source_obj.name}' has no mesh data.")
            return None

        # Das "Blueprint"-Objekt wird hier erstellt und erhält die Transform des GPU-Ghosts
        marker_obj = None
        source_obj_for_marker = self._current_scatter_source_obj
        try:
            marker_obj = source_obj_for_marker.copy()
            if marker_obj.data == source_obj_for_marker.data and source_obj_for_marker.data:
                marker_obj.data = source_obj_for_marker.data.copy()

            marker_obj.matrix_world = self._ghost_drawer.transform_matrix.copy()
            # Rotation mode wird durch matrix_world gesetzt, aber zur Sicherheit:
            marker_obj.rotation_mode = 'QUATERNION' # Oder entsprechend aus Matrix extrahieren
            # marker_obj.rotation_quaternion = self._ghost_drawer.transform_matrix.to_quaternion()

            base_marker_name = f"{source_obj_for_marker.name}_Marker"
            i = 0; final_marker_name = base_marker_name
            while final_marker_name in bpy.data.objects:
                i += 1; final_marker_name = f"{base_marker_name}.{i:03d}"
            marker_obj.name = final_marker_name

            context.scene.collection.objects.link(marker_obj)
            context.view_layer.update()
        except Exception as e_marker_create:
            log_scatter_exception(e_marker_create, "Creating temporary marker in place_object", self)
            if marker_obj and marker_obj.name in bpy.data.objects:
                try: bpy.data.objects.remove(marker_obj, do_unlink=True)
                except Exception: pass
            return None

        if settings.prevent_overlap:
            # Verwendet das gerade erstellte Blender-Objekt für den BVH-Check
            if self.check_overlap_bvh(marker_obj, context, settings, ignore_obj=marker_obj):
                current_time = time.time()
                if current_time - self._last_overlap_report_time > 1.0:
                    self.report({'INFO'}, "Placement prevented: Overlap (Immediate).")
                    self._last_overlap_report_time = current_time
                if marker_obj and marker_obj.name in bpy.data.objects: bpy.data.objects.remove(marker_obj, do_unlink=True)
                return None

        # Ab hier bleibt die Logik für C++-Verarbeitung oder Fallback gleich,
        # da sie auf dem `marker_obj` (einem Blender-Objekt) basiert.
        final_placed_obj_location = None
        cpp_processing_settings = self._get_processing_settings_for_cpp(context)

        if cpp_processing_settings and NATIVE_MODULE_AVAILABLE and scatter_accel:
            single_object_data_cpp = {
                "original_marker_name": marker_obj.name,
                "source_mesh_name": source_obj_for_marker.data.name,
                "matrix_world": [list(row) for row in marker_obj.matrix_world],
            }
            try:
                instruction = scatter_accel.analyze_single_object_for_processing(single_object_data_cpp, cpp_processing_settings)

                action = instruction.get("action")
                original_marker_name_from_cpp = instruction.get("original_marker_name")

                marker_to_process = bpy.data.objects.get(original_marker_name_from_cpp)
                if not marker_to_process:
                    self.report({'WARNING'}, f"Marker '{original_marker_name_from_cpp}' for action '{action}' not found. Scatter item lost.")
                    return None

                if action == "CREATE_INSTANCE_FROM_SOURCE":
                    mesh_data_to_instance_name = instruction.get("mesh_to_instance")
                    original_scatter_source_mesh_data = bpy.data.meshes.get(mesh_data_to_instance_name)

                    if not original_scatter_source_mesh_data:
                        self.report({'WARNING'}, f"Original scatter source mesh '{mesh_data_to_instance_name}' for instance not found.")
                        if marker_to_process.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process, do_unlink=True)
                        return None

                    instance_base_name = instruction.get("new_instance_name_base", f"{marker_to_process.name}_processed_inst")
                    final_inst_name = instance_base_name; i_inst = 0
                    while final_inst_name in bpy.data.objects:
                        i_inst += 1; final_inst_name = f"{instance_base_name}.{i_inst:03d}"

                    new_instance = bpy.data.objects.new(name=final_inst_name, object_data=original_scatter_source_mesh_data)
                    new_instance.matrix_world = Matrix(instruction.get("matrix_world"))

                    target_col_name = instruction.get("target_collection_name")
                    target_col = get_or_create_scatter_target_collection(target_col_name, context)

                    if target_col: target_col.objects.link(new_instance)
                    else:
                        self.report({'WARNING'}, f"Target instance collection '{target_col_name}' not found or creatable. Linking to scene.")
                        context.scene.collection.objects.link(new_instance)

                    final_placed_obj_location = new_instance.location.copy()
                    if marker_to_process.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process, do_unlink=True)

                elif action == "CONVERT_MARKER_TO_STATIC_RIGID" or action == "CONVERT_MARKER_TO_STATIC":
                    target_col_name = instruction.get("target_collection_name")
                    target_col = get_or_create_scatter_target_collection(target_col_name, context)

                    if marker_to_process.name in context.scene.collection.objects:
                        context.scene.collection.objects.unlink(marker_to_process)

                    if target_col: target_col.objects.link(marker_to_process)
                    else:
                        self.report({'WARNING'}, f"Target static collection '{target_col_name}' not found or creatable. Leaving in scene.")
                        if marker_to_process.name not in context.scene.collection.objects:
                             context.scene.collection.objects.link(marker_to_process)

                    if instruction.get("add_rigidbody", False):
                        self._apply_rigid_body_to_object(context, marker_to_process)

                    final_placed_obj_location = marker_to_process.location.copy()

                else:
                    self.report({'INFO'}, f"Action '{action}' (reason: {instruction.get('reason', 'N/A')}) for {marker_to_process.name}. Marker removed.")
                    if marker_to_process.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process, do_unlink=True)
                    return None

            except Exception as e_proc:
                log_scatter_exception(e_proc, f"C++ processing/execution for {marker_obj.name}", self)
                if marker_obj and marker_obj.name in bpy.data.objects: bpy.data.objects.remove(marker_obj, do_unlink=True)
                return None
        else:
            im_settings = getattr(context.scene, 'instance_manager_settings', None)
            use_legacy_marking = True
            if im_settings:
                use_legacy_marking = im_settings.use_instancing

            self.report({'DEBUG'}, "C++ module/settings not available for on-the-fly. Using fallback (marker in session collection).")
            if use_legacy_marking:
                 marker_obj["is_scatter_instance"] = True

            if marker_obj.name in context.scene.collection.objects:
                context.scene.collection.objects.unlink(marker_obj)

            if self._session_source_collection and self._session_source_collection.name in bpy.data.collections:
                self._session_source_collection.objects.link(marker_obj)
            else:
                self.report({'ERROR'}, "Session source collection invalid in fallback. Linking marker to scene.")
                context.scene.collection.objects.link(marker_obj)

            final_placed_obj_location = marker_obj.location.copy()

        context.view_layer.update()
        return final_placed_obj_location

    def mouse_raycast(self, context, settings, mouse_x, mouse_y, use_custom_ray=False, custom_origin=None, custom_direction=None, max_distance_override=None, ignore_object_for_raycast=None): # Unverändert
        # Wichtig: ignore_object_for_raycast ist ein Blender-Objekt.
        # Wenn wir GPU-Ghost haben, gibt es kein Blender-Objekt zum Ignorieren beim Raycast für *dessen* Position.
        # Dies ist relevant, wenn der Ghost selbst auf etwas raycasten würde.
        try:
            region = context.region; rv3d = context.region_data
            if not region or not rv3d: return False, None, None, None
        except ReferenceError as e:
            log_scatter_exception(e, "Getting region/rv3d in mouse_raycast", self, level="WARNING")
            return False, None, None, None
        except Exception as e_gen_region:
            log_scatter_exception(e_gen_region, "Unexpected error getting region/rv3d in mouse_raycast", self, level="WARNING")
            return False, None, None, None

        origin, direction = None, None
        if use_custom_ray and custom_origin is not None and custom_direction is not None:
            origin = custom_origin
            direction = custom_direction.normalized() if custom_direction.length > 0 else Vector((0,0,-1))
        else:
            coord = (mouse_x, mouse_y)
            try:
                origin = region_2d_to_origin_3d(region, rv3d, coord)
                direction = region_2d_to_vector_3d(region, rv3d, coord)
            except ValueError as e_val:
                log_scatter_exception(e_val, "Converting 2D to 3D ray in mouse_raycast (ValueError)", self, level="DEBUG")
                return False, None, None, None
            except AttributeError as e_attr:
                log_scatter_exception(e_attr, "Converting 2D to 3D ray in mouse_raycast (AttributeError)", self, level="DEBUG")
                return False, None, None, None
            except Exception as e_conv:
                log_scatter_exception(e_conv, "Unexpected error converting 2D to 3D ray in mouse_raycast", self, level="WARNING")
                return False, None, None, None
            if not origin or not direction or direction.length == 0: return False, None, None, None
            direction.normalize()

        original_hide_state = None
        obj_was_hidden_for_raycast = False
        obj_to_ignore_actual = None
        try:
            if ignore_object_for_raycast and hasattr(ignore_object_for_raycast, 'name') and ignore_object_for_raycast.name in bpy.data.objects:
                obj_to_ignore_actual = ignore_object_for_raycast
        except ReferenceError: pass

        if obj_to_ignore_actual and obj_to_ignore_actual.name in context.view_layer.objects:
            try:
                original_hide_state = obj_to_ignore_actual.hide_get()
                if not original_hide_state:
                    obj_to_ignore_actual.hide_set(True)
                    context.view_layer.update()
                    obj_was_hidden_for_raycast = True
            except (ReferenceError, RuntimeError) as e_hide_ignore:
                log_scatter_exception(e_hide_ignore, f"Hiding ignore_object '{obj_to_ignore_actual.name}' for raycast", self, level="DEBUG")
                obj_was_hidden_for_raycast = False
            except Exception as e_gen_hide_ignore:
                log_scatter_exception(e_gen_hide_ignore, f"Unexpected error hiding ignore_object '{obj_to_ignore_actual.name}' for raycast", self, level="DEBUG")
                obj_was_hidden_for_raycast = False


        hit_success_final = False; loc_final, norm_final, obj_hit_final = None, None, None
        depsgraph = context.evaluated_depsgraph_get()
        max_dist_for_ray = max_distance_override if max_distance_override is not None else 10000.0

        try:
            if settings.raycast_mode == 'VIEW' and not use_custom_ray:
                if direction.z != 0:
                    t = -origin.z / direction.z
                    if t > 0.0001 and t * direction.length < max_dist_for_ray :
                        loc_final = origin + t * direction; norm_final = Vector((0.0, 0.0, 1.0)); obj_hit_final = None; hit_success_final = True
            elif settings.raycast_mode == 'OBJECT' and not use_custom_ray:
                ground_obj = settings.ground_object
                if ground_obj and ground_obj.name in bpy.data.objects and ground_obj.name in context.view_layer.objects:
                    if obj_to_ignore_actual and ground_obj == obj_to_ignore_actual:
                        pass
                    else:
                        eval_ground_obj = ground_obj.evaluated_get(depsgraph)
                        if eval_ground_obj and eval_ground_obj.type == 'MESH' and eval_ground_obj.data and hasattr(eval_ground_obj.data, 'polygons') and len(eval_ground_obj.data.polygons) > 0:
                            inv_matrix = eval_ground_obj.matrix_world.inverted()
                            origin_obj_space = inv_matrix @ origin
                            direction_obj_space = inv_matrix.to_3x3() @ direction
                            obj_hit_success, loc_obj_space, norm_obj_space, _ = eval_ground_obj.ray_cast(origin_obj_space, direction_obj_space, distance=max_dist_for_ray, depsgraph=depsgraph)
                            if obj_hit_success:
                                loc_final = eval_ground_obj.matrix_world @ loc_obj_space
                                if norm_obj_space and norm_obj_space.length > 0.0001: norm_final = (eval_ground_obj.matrix_world.to_3x3().inverted_safe().transposed() @ norm_obj_space).normalized()
                                else: norm_final = Vector((0.0,0.0,1.0))
                                obj_hit_final = ground_obj; hit_success_final = True
                elif ground_obj: pass
            else:
                hit_success, loc, norm, _, obj_hit, _ = context.scene.ray_cast(depsgraph, origin, direction, distance=max_dist_for_ray)
                if hit_success:
                    if obj_to_ignore_actual and obj_hit == obj_to_ignore_actual:
                        pass
                    else:
                        loc_final = loc
                        norm_final = norm.normalized() if norm and norm.length > 0.0001 else Vector((0.0,0.0,1.0))
                        obj_hit_final = obj_hit
                        hit_success_final = True
        except (RuntimeError, ReferenceError) as e_ray:
            log_scatter_exception(e_ray, "Performing ray_cast operation", self, level="DEBUG")
        except Exception as e_gen_ray:
            log_scatter_exception(e_gen_ray, "Unexpected error during ray_cast", self, level="WARNING")
        finally:
            if obj_was_hidden_for_raycast and obj_to_ignore_actual and obj_to_ignore_actual.name in bpy.data.objects and obj_to_ignore_actual.name in context.view_layer.objects :
                try:
                    obj_to_ignore_actual.hide_set(original_hide_state)
                    context.view_layer.update()
                except (ReferenceError, RuntimeError) as e_restore_hide:
                    log_scatter_exception(e_restore_hide, f"Restoring hide state of ignore_object '{obj_to_ignore_actual.name}'", self, level="DEBUG")
                except Exception as e_gen_restore_hide:
                    log_scatter_exception(e_gen_restore_hide, f"Unexpected error restoring hide state of '{obj_to_ignore_actual.name}'", self, level="DEBUG")
        return hit_success_final, loc_final, norm_final, obj_hit_final

    def _cleanup_scatter_debug_objects(self, context): # Unverändert
        if not self._scatter_debug_empties_names: return
        original_mode = None
        try:
            if context.mode != 'OBJECT': original_mode = context.mode; bpy.ops.object.mode_set(mode='OBJECT')
        except Exception as e_mode:
            log_scatter_exception(e_mode, "Setting OBJECT mode in _cleanup_scatter_debug_objects", self, level="WARNING")
            return
        try:
            if context.view_layer.objects.active: context.view_layer.objects.active.select_set(False)
            for o_name in [o.name for o in context.selected_objects if o]:
                obj_sel = bpy.data.objects.get(o_name)
                if obj_sel: obj_sel.select_set(False)
            context.view_layer.objects.active = None
        except ReferenceError: pass
        except Exception as e_desel: log_scatter_exception(e_desel, "Deselecting objects in _cleanup_scatter_debug_objects", self, level="WARNING")

        objects_to_delete_names = list(self._scatter_debug_empties_names)
        self._scatter_debug_empties_names.clear()
        for name in objects_to_delete_names:
            obj = bpy.data.objects.get(name)
            if obj:
                try: bpy.data.objects.remove(obj, do_unlink=True)
                except (ReferenceError, RuntimeError): pass
                except Exception as e_remove: log_scatter_exception(e_remove, f"Removing debug empty '{name}'", self, level="WARNING")
        try:
            if original_mode and context.mode == 'OBJECT': bpy.ops.object.mode_set(mode=original_mode)
        except Exception as e_restore_mode: log_scatter_exception(e_restore_mode, "Restoring original mode in _cleanup_scatter_debug_objects", self, level="WARNING")

    def _create_scatter_debug_empty_at(self, context, location, name_suffix="", parent_falling_obj_wrapper=None): # Unverändert
        settings = context.scene.mouse_scatter_settings
        if not settings.create_debug_empties_on_land: return None
        original_mode = None
        try:
            if context.mode != 'OBJECT': original_mode = context.mode; bpy.ops.object.mode_set(mode='OBJECT')
        except Exception as e_mode:
            log_scatter_exception(e_mode, "Setting OBJECT mode in _create_scatter_debug_empty_at", self, level="WARNING")
            return None
        debug_empty = None
        try:
            bpy.ops.object.empty_add(type='PLAIN_AXES', align='WORLD', location=location, scale=(0.05, 0.05, 0.05))
            debug_empty = context.active_object
            if debug_empty:
                unique_id = f"{name_suffix}_{len(self._scatter_debug_empties_names)}_{random.randint(1000,9999)}"
                debug_empty.name = f"ScatterDebug_{unique_id}"
                self._scatter_debug_empties_names.append(debug_empty.name)
                if parent_falling_obj_wrapper and hasattr(parent_falling_obj_wrapper, 'debug_empties_names'):
                    parent_falling_obj_wrapper.debug_empties_names.append(debug_empty.name)
            else:
                log_scatter_exception(RuntimeError("empty_add did not return an object"), "Creating debug empty", self)
        except Exception as e:
            log_scatter_exception(e, "Creating debug empty", self)
            if debug_empty and debug_empty.name in bpy.data.objects:
                try: bpy.data.objects.remove(debug_empty, do_unlink=True)
                except Exception as e_rem_dbg: log_scatter_exception(e_rem_dbg, f"Removing failed debug empty '{debug_empty.name if debug_empty else 'Unknown'}'", self, level="WARNING")
            debug_empty = None
        try:
            if original_mode and context.mode == 'OBJECT': bpy.ops.object.mode_set(mode=original_mode)
        except Exception as e_restore_mode:
            log_scatter_exception(e_restore_mode, "Restoring original mode in _create_scatter_debug_empty_at", self, level="WARNING")
        return debug_empty

    def _start_animated_drop_object(self, context, settings, mouse_x, mouse_y, use_ghost_transform=False, initial_ghost_matrix=None): # Unverändert
        # Wichtig: `use_ghost_transform` und `initial_ghost_matrix` bezogen sich auf den alten Blender-Objekt-Ghost.
        # Im neuen System ist dies nur relevant, wenn der "Animated Drop" Modus aus dem "Ghost Immediate" Modus getriggert wird
        # (was aktuell nicht der Fall ist). Die Logik für direkten animierten Drop per Klick ist hier korrekt.
        try:
            source_obj_for_drop = self.get_random_scatter_object(settings)
            if not source_obj_for_drop or source_obj_for_drop.name not in bpy.data.objects:
                self.report({'WARNING'}, "No valid object selected to drop."); return None
            if not source_obj_for_drop.data:
                self.report({'WARNING'}, f"Source object '{source_obj_for_drop.name}' has no mesh data for drop.")
                return None
        except ReferenceError as e_ref:
            log_scatter_exception(e_ref, "Getting source object for drop", self)
            self.report({'WARNING'}, "Source object for drop became invalid."); return None
        except Exception as e_gen_src:
            log_scatter_exception(e_gen_src, "Unexpected error getting source object for drop", self)
            self.report({'ERROR'}, "Unexpected error getting source object for drop.")
            return None

        if settings.prevent_overlap and settings.placement_mode == 'ANIMATED_DROP_DIRECT':
            temp_ghost = None # Dieses Objekt ist nur für den Overlap-Check, nicht für die GPU-Darstellung
            try:
                temp_ghost = source_obj_for_drop.copy()
                if temp_ghost.data == source_obj_for_drop.data and source_obj_for_drop.data: temp_ghost.data = source_obj_for_drop.data.copy()
                temp_ghost.name = "TempOverlapCheckGhost_Drop"
                if not temp_ghost.users_collection: context.scene.collection.objects.link(temp_ghost)

                hit, loc, norm, _ = self.mouse_raycast(context, settings, mouse_x, mouse_y, ignore_object_for_raycast=temp_ghost)
                if hit and loc:
                    scale = random.uniform(settings.scale_min, settings.scale_max); temp_ghost.scale = (scale, scale, scale)
                    rot_x = math.radians(random.uniform(settings.rot_x_min, settings.rot_x_max)); rot_y = math.radians(random.uniform(settings.rot_y_min, settings.rot_y_max)); rot_z = math.radians(random.uniform(settings.rot_z_min, settings.rot_z_max))
                    align_rot_quat = norm.normalized().to_track_quat('Z', 'Y') if norm and norm.length > 0.001 else Euler((0,0,0),'XYZ').to_quaternion()
                    rand_rot_eul = Euler((rot_x, rot_y, rot_z), 'XYZ'); temp_ghost.rotation_euler = (align_rot_quat @ rand_rot_eul.to_quaternion()).to_euler('XYZ')
                    context.view_layer.update()
                    h_offset = random.uniform(settings.height_min, settings.height_max)

                    temp_ghost.location = loc
                    if settings.offset_application_mode == 'WORLD_Z':
                        temp_ghost.location.z += h_offset
                    else:
                        temp_ghost.location += (norm.normalized() * h_offset if norm and norm.length > 0.001 else Vector((0,0,h_offset)))
                    context.view_layer.update()

                    if self.check_overlap_bvh(temp_ghost, context, settings, ignore_obj=temp_ghost):
                        current_time = time.time()
                        if current_time - self._last_overlap_report_time > 1.0:
                            self.report({'INFO'}, "Drop prevented: Overlap at start point (Direct Drop)."); self._last_overlap_report_time = current_time
                        if temp_ghost and temp_ghost.name in bpy.data.objects:
                             try: bpy.data.objects.remove(temp_ghost, do_unlink=True)
                             except Exception: pass
                        return None
            except ReferenceError as e_ref_overlap:
                log_scatter_exception(e_ref_overlap, "Overlap check for animated_drop_direct", self)
                if temp_ghost and temp_ghost.name in bpy.data.objects: bpy.data.objects.remove(temp_ghost, do_unlink=True)
                return None
            except Exception as e_overlap:
                log_scatter_exception(e_overlap, "Unexpected error during overlap check for animated_drop_direct", self)
            finally:
                if temp_ghost and temp_ghost.name in bpy.data.objects:
                    try: bpy.data.objects.remove(temp_ghost, do_unlink=True)
                    except Exception as e_rem_tg: log_scatter_exception(e_rem_tg, "Removing temp_ghost in animated_drop_direct", self, level="WARNING")

        original_mode = context.mode
        if original_mode != 'OBJECT':
            try: bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as e_mode:
                log_scatter_exception(e_mode, "Setting OBJECT mode for animated drop", self)
                self.report({'ERROR'}, "Could not switch to Object Mode.")
                return None
        new_obj = None
        try:
            new_obj = source_obj_for_drop.copy()
            if new_obj.data == source_obj_for_drop.data and source_obj_for_drop.data is not None: new_obj.data = source_obj_for_drop.data.copy()
            base_name = source_obj_for_drop.name; count = 1; new_name_candidate = f"{base_name}_DropAnim"
            while new_name_candidate in bpy.data.objects: new_name_candidate = f"{base_name}_DropAnim.{count:03d}"; count += 1
            new_obj.name = new_name_candidate

            for col_other in list(new_obj.users_collection): col_other.objects.unlink(new_obj)
            context.scene.collection.objects.link(new_obj)
        except ReferenceError as e_ref_create:
            log_scatter_exception(e_ref_create, "Creating/linking new drop object", self)
            if new_obj and new_obj.name in bpy.data.objects: bpy.data.objects.remove(new_obj, do_unlink=True)
            if context.mode == 'OBJECT' and original_mode != 'OBJECT':
                try: bpy.ops.object.mode_set(mode=original_mode)
                except RuntimeError: pass
            return None
        except Exception as e_create:
            log_scatter_exception(e_create, "Unexpected error creating/linking new drop object", self)
            self.report({'ERROR'}, f"Error creating drop object: {e_create}")
            if new_obj and new_obj.name in bpy.data.objects: bpy.data.objects.remove(new_obj, do_unlink=True)
            if context.mode == 'OBJECT' and original_mode != 'OBJECT':
                try: bpy.ops.object.mode_set(mode=original_mode)
                except RuntimeError: pass
            return None

        if context.mode == 'OBJECT' and original_mode != 'OBJECT':
            try: bpy.ops.object.mode_set(mode=original_mode)
            except Exception as e_restore_mode_drop: log_scatter_exception(e_restore_mode_drop, "Restoring original mode after creating drop object", self, level="WARNING")

        try:
            if use_ghost_transform and initial_ghost_matrix: # Relevant if drop triggered from a ghost state
                new_obj.matrix_world = initial_ghost_matrix
            else: # Standard direct drop from mouse click
                scale_val = random.uniform(settings.scale_min, settings.scale_max); new_obj.scale = (scale_val, scale_val, scale_val)
                context.view_layer.update()
                rot_x_rad = math.radians(random.uniform(settings.rot_x_min, settings.rot_x_max)); rot_y_rad = math.radians(random.uniform(settings.rot_y_min, settings.rot_y_max)); rot_z_rad = math.radians(random.uniform(settings.rot_z_min, settings.rot_z_max))
                random_euler_rot = Euler((rot_x_rad, rot_y_rad, rot_z_rad), 'XYZ')

                hit_initial, loc_initial, norm_initial, _ = self.mouse_raycast(context, settings, mouse_x, mouse_y, ignore_object_for_raycast=new_obj)

                if hit_initial and norm_initial and norm_initial.length > 0.001:
                    align_quat = norm_initial.normalized().to_track_quat('Z','Y');
                    new_obj.rotation_mode = 'QUATERNION'
                    new_obj.rotation_quaternion = align_quat @ random_euler_rot.to_quaternion()
                else:
                    new_obj.rotation_euler = random_euler_rot
                context.view_layer.update()

                initial_height_offset = random.uniform(settings.height_min, settings.height_max)

                matrix_world_no_loc_drop = new_obj.matrix_world.copy(); matrix_world_no_loc_drop.translation = Vector((0,0,0))
                min_z_local_space_drop = 0.0
                if new_obj.bound_box:
                    local_bbox_corners_rot_scaled = [matrix_world_no_loc_drop @ Vector(corner) for corner in new_obj.bound_box]
                    if local_bbox_corners_rot_scaled: min_z_local_space_drop = min(c.z for c in local_bbox_corners_rot_scaled)

                if hit_initial and loc_initial:
                    start_location_base = loc_initial.copy()
                    start_location_base.z = loc_initial.z - min_z_local_space_drop

                    if settings.offset_application_mode == 'WORLD_Z':
                        start_location = start_location_base + Vector((0,0,initial_height_offset))
                    else:
                        offset_vec_along_normal = (norm_initial.normalized() if norm_initial and norm_initial.length > 0.001 else Vector((0,0,1))) * initial_height_offset
                        start_location = loc_initial + offset_vec_along_normal
                        start_location.z = (loc_initial + offset_vec_along_normal).z - min_z_local_space_drop
                else:
                    region = context.region; rv3d = context.region_data; mouse_on_plane = Vector((0,0,0))
                    if region and rv3d:
                        try:
                            origin_view = region_2d_to_origin_3d(region, rv3d, (mouse_x, mouse_y)); direction_view = region_2d_to_vector_3d(region, rv3d, (mouse_x, mouse_y))
                            if direction_view.z != 0: t = -origin_view.z / direction_view.z;
                            if t > 0: mouse_on_plane = origin_view + t * direction_view
                        except Exception as e_plane_calc: log_scatter_exception(e_plane_calc, "Calculating mouse_on_plane for drop start", self, level="DEBUG")

                    start_location = mouse_on_plane
                    start_location.z = mouse_on_plane.z - min_z_local_space_drop

                    offset_dir = Vector((0,0,1)) if settings.offset_application_mode == 'WORLD_Z' or not (norm_initial and norm_initial.length > 0.001) else norm_initial.normalized()
                    start_location += offset_dir * initial_height_offset
                new_obj.location = start_location
        except ReferenceError as e_ref_transform:
            log_scatter_exception(e_ref_transform, "Transforming new drop object", self)
            if new_obj and new_obj.name in bpy.data.objects: bpy.data.objects.remove(new_obj, do_unlink=True)
            return None
        except Exception as e_gen_transform:
            log_scatter_exception(e_gen_transform, "Unexpected error transforming new drop object", self)
            if new_obj and new_obj.name in bpy.data.objects: bpy.data.objects.remove(new_obj, do_unlink=True)
            return None
        context.view_layer.update()
        falling_obj_wrapper = AnimatedFallingObject(new_obj, settings.drop_anim_steps, source_obj_for_drop.data.name)
        self._falling_objects_data.append(falling_obj_wrapper)
        return new_obj

    def _update_falling_objects(self, context, settings): # Unverändert
        if not self._falling_objects_data: return
        currently_falling_obj_refs = {f_obj.obj for f_obj in self._falling_objects_data if f_obj.obj and not f_obj.landed}

        for i in range(len(self._falling_objects_data) - 1, -1, -1):
            f_obj_wrapper = self._falling_objects_data[i]
            try:
                target_obj = f_obj_wrapper.obj
                if not target_obj or target_obj.name not in bpy.data.objects:
                    self._falling_objects_data.pop(i); continue

                if f_obj_wrapper.landed and f_obj_wrapper.processed_on_land:
                    continue

                if f_obj_wrapper.landed and not f_obj_wrapper.processed_on_land:
                    cpp_processing_settings_drop = self._get_processing_settings_for_cpp(context)
                    if cpp_processing_settings_drop and NATIVE_MODULE_AVAILABLE and scatter_accel:
                        if not f_obj_wrapper.source_mesh_name_for_processing:
                            self.report({'WARNING'}, f"Missing source_mesh_name_for_processing for landed drop object {target_obj.name}.")
                            f_obj_wrapper.processed_on_land = True
                            if target_obj.name in bpy.data.objects: bpy.data.objects.remove(target_obj, do_unlink=True)
                            self._falling_objects_data.pop(i); continue

                        single_object_data_drop_cpp = {
                            "original_marker_name": target_obj.name,
                            "source_mesh_name": f_obj_wrapper.source_mesh_name_for_processing,
                            "matrix_world": [list(row) for row in target_obj.matrix_world],
                        }
                        try:
                            instruction_drop = scatter_accel.analyze_single_object_for_processing(single_object_data_drop_cpp, cpp_processing_settings_drop)
                            action_drop = instruction_drop.get("action")

                            if action_drop == "CREATE_INSTANCE_FROM_SOURCE":
                                mesh_data_to_instance_name_drop = instruction_drop.get("mesh_to_instance")
                                original_mesh_data_drop = bpy.data.meshes.get(mesh_data_to_instance_name_drop)
                                if not original_mesh_data_drop:
                                    self.report({'WARNING'}, f"Source mesh '{mesh_data_to_instance_name_drop}' for drop instance not found.")
                                    if target_obj.name in bpy.data.objects: bpy.data.objects.remove(target_obj, do_unlink=True)
                                    self._falling_objects_data.pop(i); continue

                                inst_base_name_drop = instruction_drop.get("new_instance_name_base", f"{target_obj.name}_drop_inst")
                                final_inst_name_drop = inst_base_name_drop; i_inst_d = 0
                                while final_inst_name_drop in bpy.data.objects:
                                    i_inst_d += 1; final_inst_name_drop = f"{inst_base_name_drop}.{i_inst_d:03d}"

                                new_instance_drop = bpy.data.objects.new(name=final_inst_name_drop, object_data=original_mesh_data_drop)
                                new_instance_drop.matrix_world = Matrix(instruction_drop.get("matrix_world"))

                                target_col_name_drop = instruction_drop.get("target_collection_name")
                                target_col_drop = get_or_create_scatter_target_collection(target_col_name_drop, context)
                                if target_col_drop: target_col_drop.objects.link(new_instance_drop)
                                else: context.scene.collection.objects.link(new_instance_drop)

                                if target_obj.name in bpy.data.objects: bpy.data.objects.remove(target_obj, do_unlink=True)
                                self.report({'DEBUG'}, f"Drop object {target_obj.name if hasattr(target_obj, 'name') else 'Unknown'} converted to instance {new_instance_drop.name}.")
                                target_obj = new_instance_drop # Update ref for post-spawn

                            elif action_drop == "CONVERT_MARKER_TO_STATIC_RIGID" or action_drop == "CONVERT_MARKER_TO_STATIC":
                                target_col_name_drop_s = instruction_drop.get("target_collection_name")
                                target_col_drop_s = get_or_create_scatter_target_collection(target_col_name_drop_s, context)

                                if target_obj.name in context.scene.collection.objects: # Ensure it's in scene before trying to unlink
                                    is_linked_to_scene = any(target_obj.name in col.objects for col in bpy.data.scenes[context.scene.name].collection.children_recursive if target_obj.name in col.objects) or \
                                                         target_obj.name in context.scene.collection.objects
                                    if is_linked_to_scene:
                                        context.scene.collection.objects.unlink(target_obj) # Unlink from main scene collection

                                if target_col_drop_s: target_col_drop_s.objects.link(target_obj)
                                else: # Fallback if target collection not found/creatable
                                    self.report({'WARNING'}, f"Static collection '{target_col_name_drop_s}' not found for {target_obj.name}. Re-linking to scene.")
                                    if target_obj.name not in context.scene.collection.objects: # Only link if not already there
                                        context.scene.collection.objects.link(target_obj)


                                if instruction_drop.get("add_rigidbody", False):
                                    self._apply_rigid_body_to_object(context, target_obj)
                                self.report({'DEBUG'}, f"Drop object {target_obj.name} converted to static.")

                            else:
                                self.report({'DEBUG'}, f"Drop object {target_obj.name} skipped processing (action: {action_drop}). Removing.")
                                if target_obj.name in bpy.data.objects: bpy.data.objects.remove(target_obj, do_unlink=True)

                        except Exception as e_proc_drop:
                            log_scatter_exception(e_proc_drop, f"C++ processing for landed drop object {target_obj.name}", self)
                            if target_obj.name in bpy.data.objects: bpy.data.objects.remove(target_obj, do_unlink=True)
                            self._falling_objects_data.pop(i); continue


                    else:
                        self.report({'DEBUG'}, f"Drop object {target_obj.name} using fallback (to session collection).")
                        im_settings_drop = getattr(context.scene, 'instance_manager_settings', None)
                        use_legacy_marking_drop = True
                        if im_settings_drop: use_legacy_marking_drop = im_settings_drop.use_instancing

                        if use_legacy_marking_drop:
                             target_obj["is_scatter_instance"] = True

                        if target_obj.name in context.scene.collection.objects:
                            context.scene.collection.objects.unlink(target_obj)
                        if self._session_source_collection and self._session_source_collection.name in bpy.data.collections:
                            self._session_source_collection.objects.link(target_obj)
                        else: context.scene.collection.objects.link(target_obj)

                    f_obj_wrapper.processed_on_land = True

                    # Check if target_obj still exists before triggering spawn
                    if target_obj and target_obj.name in bpy.data.objects:
                        if settings.use_post_land_spawn and not f_obj_wrapper.spawn_triggered:
                            self._trigger_post_land_spawn(context, settings, target_obj)
                            f_obj_wrapper.spawn_triggered = True

                    if not target_obj or target_obj.name not in bpy.data.objects :
                        self._falling_objects_data.pop(i)
                    continue

                # --- Animation part (if not landed yet) ---
                has_landed_this_frame = False
                if f_obj_wrapper.current_step >= f_obj_wrapper.drop_steps_total:
                    has_landed_this_frame = True
                else:
                    if settings.enable_tumble_during_drop and random.random() < settings.tumble_frequency_during_drop:
                        intensity = settings.tumble_rotation_intensity_factor
                        tumble_rot_x = math.radians(random.uniform(settings.rot_x_min, settings.rot_x_max) * intensity)
                        tumble_rot_y = math.radians(random.uniform(settings.rot_y_min, settings.rot_y_max) * intensity)
                        tumble_rot_z = math.radians(random.uniform(settings.rot_z_min, settings.rot_z_max) * intensity)
                        delta_euler = Euler((tumble_rot_x, tumble_rot_y, tumble_rot_z), 'XYZ')
                        current_quat = target_obj.rotation_quaternion if target_obj.rotation_mode == 'QUATERNION' else target_obj.rotation_euler.to_quaternion()
                        target_obj.rotation_quaternion = current_quat @ delta_euler.to_quaternion()
                        target_obj.rotation_mode = 'QUATERNION'
                        max_offset_step = settings.tumble_offset_xy_max_step
                        local_offset = Vector((random.uniform(-max_offset_step, max_offset_step), random.uniform(-max_offset_step, max_offset_step), 0.0))
                        global_offset = target_obj.matrix_world.to_3x3() @ local_offset
                        target_obj.location += global_offset

                    obj_dims = target_obj.dimensions if target_obj.dimensions.length > 0.001 else Vector((0.1,0.1,0.1))
                    ray_origin_offset_factor = 0.1
                    ray_origin_z_offset_local = obj_dims.z * ray_origin_offset_factor
                    ray_origin_up_vector_world = target_obj.matrix_world.to_3x3() @ Vector((0,0,1))

                    ray_origin = target_obj.matrix_world.translation - ray_origin_up_vector_world * (obj_dims.z * 0.5 - ray_origin_z_offset_local)
                    ray_direction = -ray_origin_up_vector_world.normalized()

                    max_ray_dist = settings.drop_anim_speed_step + obj_dims.z * (1 + ray_origin_offset_factor) + abs(settings.landing_z_correction) + 0.1

                    hit_collision, loc_collision, norm_collision, hit_obj_for_collision = self.mouse_raycast(
                        context, settings, 0, 0, use_custom_ray=True, custom_origin=ray_origin, custom_direction=ray_direction,
                        max_distance_override=max_ray_dist, ignore_object_for_raycast=target_obj
                    )

                    if hit_collision and loc_collision:
                        if hit_obj_for_collision in currently_falling_obj_refs and hit_obj_for_collision != target_obj:
                            target_obj.location.z -= settings.drop_anim_speed_step
                        else:
                            self._create_scatter_debug_empty_at(context, loc_collision, f"{target_obj.name}_HitP_S{f_obj_wrapper.current_step}", f_obj_wrapper)

                            matrix_world_no_loc_fall = target_obj.matrix_world.copy()
                            matrix_world_no_loc_fall.translation = Vector((0,0,0))
                            min_z_local_space_fall = 0.0
                            if target_obj.bound_box:
                                local_bbox_corners_rot_scaled_fall = [matrix_world_no_loc_fall @ Vector(corner) for corner in target_obj.bound_box]
                                if local_bbox_corners_rot_scaled_fall:
                                    min_z_local_space_fall = min(c.z for c in local_bbox_corners_rot_scaled_fall)

                            target_obj_pivot_z_on_surface = loc_collision.z - min_z_local_space_fall

                            final_pivot_location_fall = loc_collision.copy()
                            final_pivot_location_fall.z = target_obj_pivot_z_on_surface + settings.landing_z_correction

                            if settings.use_scatter_on_scatter and settings.snap_to_center_on_stack and \
                               hit_obj_for_collision and hit_obj_for_collision.name in bpy.data.objects and \
                               ((hasattr(hit_obj_for_collision, 'rigid_body') and hit_obj_for_collision.rigid_body and hit_obj_for_collision.rigid_body.type == 'ACTIVE') or \
                                (self._session_source_collection and self._session_source_collection.name in bpy.data.collections and hit_obj_for_collision.name.startswith(self._session_source_collection.name))):
                                target_obj.location.xy = hit_obj_for_collision.matrix_world.translation.xy
                                target_obj.location.z = final_pivot_location_fall.z
                            else:
                                target_obj.location = final_pivot_location_fall

                            has_landed_this_frame = True
                    else:
                        target_obj.location.z -= settings.drop_anim_speed_step

                if has_landed_this_frame:
                    f_obj_wrapper.landed = True
                    if target_obj.animation_data: target_obj.animation_data_clear()

                f_obj_wrapper.current_step +=1

            except ReferenceError as e_ref_fall:
                log_scatter_exception(e_ref_fall, f"Falling object '{f_obj_wrapper.name}' became invalid", self)
                self.report({'WARNING'}, f"A falling object ({f_obj_wrapper.name}) became invalid. Removing.");
                self._falling_objects_data.pop(i); continue
            except Exception as e_fall:
                log_scatter_exception(e_fall, f"Unexpected error updating falling object '{f_obj_wrapper.name}'", self)
                self.report({'ERROR'}, f"Unexpected error in _update_falling_objects for {f_obj_wrapper.name}: {e_fall}");
                self._falling_objects_data.pop(i); continue

    def _calculate_downhill_direction(self, surface_normal: Vector) -> Vector: # Unverändert
        world_down = Vector((0, 0, -1))
        downhill_on_plane = world_down - world_down.dot(surface_normal) * surface_normal
        if downhill_on_plane.length > 0.0001:
            return downhill_on_plane.normalized()
        if abs(surface_normal.z) > 0.9999:
            return Vector((random.uniform(-1,1), random.uniform(-1,1), 0.0)).normalized() if random.random() > 0.1 else Vector((0,0,0))
        return Vector((0,0,0))

    def _trigger_post_land_spawn(self, context, settings, main_landed_obj_ref): # Unverändert
        if not main_landed_obj_ref or main_landed_obj_ref.name not in bpy.data.objects:
            self.report({'WARNING'}, "Main landed object for post-spawn is invalid or gone.")
            return

        source_obj_for_spawn = self._current_scatter_source_obj
        if not source_obj_for_spawn or source_obj_for_spawn.name not in bpy.data.objects:
            source_obj_for_spawn = self.get_random_scatter_object(settings)
            if not source_obj_for_spawn or source_obj_for_spawn.name not in bpy.data.objects:
                self.report({'WARNING'}, "No source object available for Post-Landing Spawn.")
                return
        if not source_obj_for_spawn.data:
            self.report({'WARNING'}, f"Source for spawn '{source_obj_for_spawn.name}' has no mesh data.")
            return

        actual_spawn_count = random.randint(settings.post_land_spawn_count_min, settings.post_land_spawn_count_max)
        if actual_spawn_count == 0: return
        duration = settings.post_land_spawn_duration_frames
        land_pos = main_landed_obj_ref.location.copy()

        try:
            ray_origin_main = land_pos + Vector((0,0,0.1))
            hit_main, _, main_land_norm, _ = self.mouse_raycast(context, settings, 0, 0,
                                                                 use_custom_ray=True, custom_origin=ray_origin_main,
                                                                 custom_direction=Vector((0,0,-1)), max_distance_override=0.2,
                                                                 ignore_object_for_raycast=main_landed_obj_ref)
            main_obj_surface_normal = main_land_norm.normalized() if hit_main and main_land_norm and main_land_norm.length > 0.001 else Vector((0,0,1))

            if abs(main_obj_surface_normal.dot(Vector((0,0,1)))) > 0.99:
                plane_x_axis = Vector((1,0,0)); plane_y_axis = Vector((0,1,0))
            else:
                plane_x_axis = main_obj_surface_normal.cross(Vector((0,0,1))).normalized()
                if plane_x_axis.length < 0.01: plane_x_axis = Vector((1,0,0))
                plane_y_axis = plane_x_axis.cross(main_obj_surface_normal).normalized()
                if plane_y_axis.length < 0.01 : plane_y_axis = Vector((0,1,0)) if abs(plane_x_axis.dot(Vector((1,0,0)))) > 0.9 else plane_x_axis.cross(Vector((0,0,1))).normalized()

            min_spawn_dist_base = settings.post_land_spawn_distance_min
            max_spawn_dist_base = settings.post_land_spawn_distance_max

            if settings.post_land_spawn_scale_distance_by_mesh_size:
                depsgraph = context.evaluated_depsgraph_get()
                eval_main_landed_obj = main_landed_obj_ref.evaluated_get(depsgraph)
                main_dims = eval_main_landed_obj.dimensions
                mesh_size_metric = max(0.01, (main_dims.x + main_dims.y) / 2.0)
                distance_multiplier = mesh_size_metric * settings.post_land_spawn_mesh_size_influence
                min_spawn_dist_actual = min_spawn_dist_base * distance_multiplier
                max_spawn_dist_actual = max_spawn_dist_base * distance_multiplier
                if max_spawn_dist_actual < min_spawn_dist_actual: max_spawn_dist_actual = min_spawn_dist_actual + 0.01
            else:
                min_spawn_dist_actual = min_spawn_dist_base
                max_spawn_dist_actual = max_spawn_dist_base

            for i in range(actual_spawn_count):
                new_spawned_obj_marker = None
                try:
                    new_spawned_obj_marker = source_obj_for_spawn.copy()
                    if new_spawned_obj_marker.data == source_obj_for_spawn.data and source_obj_for_spawn.data:
                        new_spawned_obj_marker.data = source_obj_for_spawn.data.copy()

                    sub_count = 1; new_name_candidate = f"{main_landed_obj_ref.name}_SpawnMarker{i}"
                    while new_name_candidate in bpy.data.objects:
                        new_name_candidate = f"{main_landed_obj_ref.name}_SpawnMarker{i}.{sub_count:03d}"; sub_count += 1
                    new_spawned_obj_marker.name = new_name_candidate

                    for col_other in list(new_spawned_obj_marker.users_collection):
                        col_other.objects.unlink(new_spawned_obj_marker)
                    context.scene.collection.objects.link(new_spawned_obj_marker)

                    initial_obj_rotation_quat = Quaternion()
                    initial_scale_vec = Vector((1,1,1))
                    if settings.post_land_spawn_copy_main_obj_transform:
                        new_spawned_obj_marker.scale = main_landed_obj_ref.scale.copy()
                        initial_scale_vec = main_landed_obj_ref.scale.copy()
                        initial_obj_rotation_quat = main_landed_obj_ref.rotation_quaternion if main_landed_obj_ref.rotation_mode == 'QUATERNION' else main_landed_obj_ref.rotation_euler.to_quaternion()
                    else:
                        new_spawned_obj_marker.scale = source_obj_for_spawn.scale.copy()
                        initial_scale_vec = new_spawned_obj_marker.scale.copy()
                        initial_obj_rotation_quat = Euler((0,0,random.uniform(0, 2 * math.pi)), 'XYZ').to_quaternion()
                    new_spawned_obj_marker.rotation_mode = 'QUATERNION'
                    new_spawned_obj_marker.rotation_quaternion = initial_obj_rotation_quat

                    current_spread_distance = random.uniform(min_spawn_dist_actual, max_spawn_dist_actual)
                    angle = (2 * math.pi / actual_spawn_count) * i + random.uniform(-0.1, 0.1)
                    local_offset_on_plane = Vector((math.cos(angle) * current_spread_distance, math.sin(angle) * current_spread_distance, 0))

                    world_offset_on_plane = plane_x_axis * local_offset_on_plane.x + plane_y_axis * local_offset_on_plane.y
                    initial_target_pos_on_main_plane = land_pos + world_offset_on_plane

                    ray_origin_for_spawn_z = initial_target_pos_on_main_plane + main_obj_surface_normal * 1.0
                    hit_spawn_z, hit_loc_spawn_z, hit_norm_spawn_z, _ = self.mouse_raycast(
                        context, settings, 0, 0, use_custom_ray=True,
                        custom_origin=ray_origin_for_spawn_z, custom_direction=-main_obj_surface_normal,
                        max_distance_override=2.0, ignore_object_for_raycast=new_spawned_obj_marker
                    )

                    actual_spread_pos_on_surface = initial_target_pos_on_main_plane
                    surface_normal_at_spread_point = main_obj_surface_normal

                    if hit_spawn_z and hit_loc_spawn_z:
                        actual_spread_pos_on_surface = hit_loc_spawn_z
                        if hit_norm_spawn_z and hit_norm_spawn_z.length > 0.1:
                            surface_normal_at_spread_point = hit_norm_spawn_z.normalized()

                    actual_spread_pos_on_surface += surface_normal_at_spread_point * settings.post_land_spawn_offset_from_surface
                    final_end_pos_world = actual_spread_pos_on_surface

                    if settings.post_land_spawn_use_virtual_gravity:
                        downhill_dir = self._calculate_downhill_direction(surface_normal_at_spread_point)
                        if downhill_dir.length > 0.01:
                            gravity_roll_distance_factor = random.uniform(0.5, 1.5)
                            gravity_roll_distance = current_spread_distance * gravity_roll_distance_factor

                            tentative_gravity_end_pos = actual_spread_pos_on_surface + downhill_dir * gravity_roll_distance

                            ray_origin_for_gravity_z = tentative_gravity_end_pos + surface_normal_at_spread_point * 1.0
                            hit_gravity_z, hit_loc_gravity_z, hit_norm_gravity_z, _ = self.mouse_raycast(
                                context, settings, 0, 0, use_custom_ray=True,
                                custom_origin=ray_origin_for_gravity_z, custom_direction=-surface_normal_at_spread_point,
                                max_distance_override=2.0, ignore_object_for_raycast=new_spawned_obj_marker
                            )
                            if hit_gravity_z and hit_loc_gravity_z:
                                final_end_pos_world = hit_loc_gravity_z + ((hit_norm_gravity_z.normalized() * settings.post_land_spawn_offset_from_surface) if hit_norm_gravity_z and hit_norm_gravity_z.length > 0.001 else Vector())
                            else:
                                final_end_pos_world = tentative_gravity_end_pos

                    source_z_dim = source_obj_for_spawn.dimensions.z if source_obj_for_spawn.dimensions and source_obj_for_spawn.dimensions.z > 0.001 else 0.1
                    effective_z_dim_for_pop = source_z_dim * initial_scale_vec.z
                    spawn_pop_height = effective_z_dim_for_pop * 0.25 + settings.post_land_spawn_offset_from_surface
                    anim_start_pos_world = land_pos + main_obj_surface_normal * spawn_pop_height

                    spawn_wrapper = PostLandSpawnObject(
                        obj_ref=new_spawned_obj_marker,
                        start_pos_world=anim_start_pos_world,
                        end_pos_world=final_end_pos_world, duration_frames=duration,
                        settings_ref=settings, initial_orientation_quat = initial_obj_rotation_quat,
                        surface_normal_at_spawn = surface_normal_at_spread_point,
                        initial_scale_vector = initial_scale_vec,
                        source_mesh_name_for_processing=source_obj_for_spawn.data.name
                    )
                    self._post_land_spawn_objects.append(spawn_wrapper)
                except ReferenceError as e_ref_spawn_item:
                    log_scatter_exception(e_ref_spawn_item, f"Source object for spawn item {i} became invalid", self)
                    self.report({'WARNING'}, "Source object for spawn became invalid during copy.")
                    if new_spawned_obj_marker and new_spawned_obj_marker.name in bpy.data.objects: bpy.data.objects.remove(new_spawned_obj_marker, do_unlink=True)
                    continue
                except Exception as e_spawn_item:
                    log_scatter_exception(e_spawn_item, f"Creating spawn object item {i}", self)
                    self.report({'ERROR'}, f"Error creating a spawn object: {e_spawn_item}")
                    if new_spawned_obj_marker and new_spawned_obj_marker.name in bpy.data.objects: bpy.data.objects.remove(new_spawned_obj_marker, do_unlink=True)
                    continue
            if actual_spawn_count > 0: context.view_layer.update()
        except Exception as e_trigger_spawn_outer:
            log_scatter_exception(e_trigger_spawn_outer, "Outer _trigger_post_land_spawn logic", self)
            self.report({'ERROR'}, f"General error in _trigger_post_land_spawn: {e_trigger_spawn_outer}")

    def _update_post_land_spawn_animations(self, context, settings): # Unverändert
        if not self._post_land_spawn_objects: return False
        needs_redraw_for_spawn_anim = False
        for i in range(len(self._post_land_spawn_objects) - 1, -1, -1):
            spawn_wrapper = self._post_land_spawn_objects[i]
            try:
                marker_obj_spawn = spawn_wrapper.obj
                if not marker_obj_spawn or marker_obj_spawn.name not in bpy.data.objects:
                    self._post_land_spawn_objects.pop(i); continue

                if spawn_wrapper.update():
                    cpp_processing_settings_spawn = self._get_processing_settings_for_cpp(context)
                    if cpp_processing_settings_spawn and NATIVE_MODULE_AVAILABLE and scatter_accel:
                        if not spawn_wrapper.source_mesh_name_for_processing:
                            self.report({'WARNING'}, f"Missing source_mesh_name_for_processing for spawned object {marker_obj_spawn.name}.")
                            if marker_obj_spawn.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_spawn, do_unlink=True)
                            self._post_land_spawn_objects.pop(i); continue

                        single_object_data_spawn_cpp = {
                            "original_marker_name": marker_obj_spawn.name,
                            "source_mesh_name": spawn_wrapper.source_mesh_name_for_processing,
                            "matrix_world": [list(row) for row in marker_obj_spawn.matrix_world],
                        }
                        try:
                            instruction_spawn = scatter_accel.analyze_single_object_for_processing(single_object_data_spawn_cpp, cpp_processing_settings_spawn)
                            action_spawn = instruction_spawn.get("action")

                            if action_spawn == "CREATE_INSTANCE_FROM_SOURCE":
                                mesh_name_inst_spawn = instruction_spawn.get("mesh_to_instance")
                                mesh_data_inst_spawn = bpy.data.meshes.get(mesh_name_inst_spawn)
                                if not mesh_data_inst_spawn:
                                    self.report({'WARNING'}, f"Mesh '{mesh_name_inst_spawn}' for spawn instance not found.")
                                    if marker_obj_spawn.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_spawn, do_unlink=True)
                                    self._post_land_spawn_objects.pop(i); continue

                                inst_base_name_s = instruction_spawn.get("new_instance_name_base", f"{marker_obj_spawn.name}_spawn_inst")
                                final_inst_name_s = inst_base_name_s; i_inst_s = 0
                                while final_inst_name_s in bpy.data.objects:
                                    i_inst_s +=1; final_inst_name_s = f"{inst_base_name_s}.{i_inst_s:03d}"

                                new_inst_spawn = bpy.data.objects.new(name=final_inst_name_s, object_data=mesh_data_inst_spawn)
                                new_inst_spawn.matrix_world = Matrix(instruction_spawn.get("matrix_world"))

                                target_col_name_s = instruction_spawn.get("target_collection_name")
                                target_col_s = get_or_create_scatter_target_collection(target_col_name_s, context)
                                if target_col_s: target_col_s.objects.link(new_inst_spawn)
                                else: context.scene.collection.objects.link(new_inst_spawn)

                                if marker_obj_spawn.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_spawn, do_unlink=True)

                            elif action_spawn == "CONVERT_MARKER_TO_STATIC_RIGID" or action_spawn == "CONVERT_MARKER_TO_STATIC":
                                target_col_name_st = instruction_spawn.get("target_collection_name")
                                target_col_st = get_or_create_scatter_target_collection(target_col_name_st, context)

                                if marker_obj_spawn.name in context.scene.collection.objects:
                                    context.scene.collection.objects.unlink(marker_obj_spawn)
                                if target_col_st: target_col_st.objects.link(marker_obj_spawn)
                                else: context.scene.collection.objects.link(marker_obj_spawn)

                                if instruction_spawn.get("add_rigidbody", False):
                                    self._apply_rigid_body_to_object(context, marker_obj_spawn)
                            else:
                                if marker_obj_spawn.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_spawn, do_unlink=True)

                        except Exception as e_proc_spawn:
                             log_scatter_exception(e_proc_spawn, f"C++ processing for spawned object {marker_obj_spawn.name}", self)
                             if marker_obj_spawn.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_spawn, do_unlink=True)

                    else:
                        im_settings_spawn = getattr(context.scene, 'instance_manager_settings', None)
                        use_legacy_marking_spawn = True
                        if im_settings_spawn: use_legacy_marking_spawn = im_settings_spawn.use_instancing

                        if use_legacy_marking_spawn:
                            marker_obj_spawn["is_scatter_instance"] = True

                        if marker_obj_spawn.name in context.scene.collection.objects:
                            context.scene.collection.objects.unlink(marker_obj_spawn)
                        if self._session_source_collection and self._session_source_collection.name in bpy.data.collections:
                            self._session_source_collection.objects.link(marker_obj_spawn)
                        else: context.scene.collection.objects.link(marker_obj_spawn)

                    self._post_land_spawn_objects.pop(i)
                else:
                    needs_redraw_for_spawn_anim = True
            except ReferenceError as e_ref_update_spawn:
                log_scatter_exception(e_ref_update_spawn, f"Spawn wrapper object '{spawn_wrapper.obj.name if spawn_wrapper.obj else 'Unknown'}' became invalid during update", self)
                self._post_land_spawn_objects.pop(i)
                continue
            except Exception as e_update_spawn:
                log_scatter_exception(e_update_spawn, f"Updating spawn animation for '{spawn_wrapper.obj.name if spawn_wrapper.obj else 'Unknown'}'", self)
                self.report({'ERROR'}, f"Error updating spawn animation: {e_update_spawn}")
                self._post_land_spawn_objects.pop(i)
                continue
        return needs_redraw_for_spawn_anim

    def invoke(self, context, event): # Task 3 angepasst
        settings = context.scene.mouse_scatter_settings
        self._mouse_x = event.mouse_region_x; self._mouse_y = event.mouse_region_y
        self._is_dragging = False; self._last_placed_loc = None; self._last_action_time = 0.0
        self._last_overlap_report_time = 0.0
        self._falling_objects_data.clear(); self._post_land_spawn_objects.clear()
        self._cleanup_scatter_debug_objects(context)
        # self.ghost_name_cached = "" # Entfernt

        # Task 3: Drawer-Initialisierung
        self._drop_marker_drawer = None
        self._ghost_drawer = None

        try:
            if settings.apply_transforms_to_sources_on_invoke:
                self.report({'INFO'}, "Applying transforms to source objects as per settings...")
                bpy.ops.scatter_list.apply_transforms('EXEC_DEFAULT')
        except Exception as e_apply_invoke:
            log_scatter_exception(e_apply_invoke, "Applying transforms to sources on invoke", self)
            self.report({'ERROR'}, "Error applying transforms to source objects on start.")

        im_settings = getattr(context.scene, 'instance_manager_settings', None)
        base_col_name_from_im = "SCATTER_SESSION"
        if im_settings and hasattr(im_settings, 'source_collection_basename') and im_settings.source_collection_basename:
            base_col_name_from_im = im_settings.source_collection_basename

        base_col_name_for_session = base_col_name_from_im
        if not base_col_name_for_session.endswith("_"): base_col_name_for_session += "_"

        i = 1; session_col_name = f"{base_col_name_for_session}{i:03d}"
        while session_col_name in bpy.data.collections: i += 1; session_col_name = f"{base_col_name_for_session}{i:03d}"

        parent_for_session_col = context.scene.collection
        if hasattr(context.view_layer, 'layer_collection') and hasattr(context.view_layer.layer_collection, 'collection'):
             if context.view_layer.layer_collection.collection:
                parent_for_session_col = context.view_layer.layer_collection.collection

        self._session_source_collection = get_or_create_scatter_target_collection(session_col_name, context, parent_collection_obj=parent_for_session_col)
        if not self._session_source_collection:
            self.report({'ERROR'}, f"Could not create Session Source Collection '{session_col_name}' (for fallback)."); return {'CANCELLED'}

        if not settings.scatter_objects_list or not any(entry.obj for entry in settings.scatter_objects_list):
            self.report({'ERROR'}, "No scatter objects defined in the list."); return {'CANCELLED'}

        try:
            self._current_scatter_source_obj = self.get_random_scatter_object(settings)
            if not self._current_scatter_source_obj or self._current_scatter_source_obj.name not in bpy.data.objects:
                self.report({'ERROR'}, "No valid scatter object selected/found from list."); return {'CANCELLED'}
        except ReferenceError as e_ref_src:
            log_scatter_exception(e_ref_src, "Getting initial scatter source object", self)
            self.report({'ERROR'}, "Selected scatter object is invalid."); return {'CANCELLED'}
        except Exception as e_gen_src_invoke:
            log_scatter_exception(e_gen_src_invoke, "Unexpected error getting initial scatter source object", self)
            self.report({'ERROR'}, "Unexpected error getting initial scatter object."); return {'CANCELLED'}

        if settings.raycast_mode == 'OBJECT':
            try:
                if not settings.ground_object or settings.ground_object.name not in bpy.data.objects:
                    self.report({'ERROR'}, "Ground object missing or invalid for 'OBJECT' raycast mode."); return {'CANCELLED'}
            except ReferenceError as e_ref_ground:
                log_scatter_exception(e_ref_ground, "Checking ground object", self)
                self.report({'ERROR'}, "Ground object reference is invalid."); return {'CANCELLED'}
            except Exception as e_gen_ground:
                log_scatter_exception(e_gen_ground, "Unexpected error checking ground object", self)
                self.report({'ERROR'}, "Unexpected error checking ground object."); return {'CANCELLED'}

        # Task 3: Drawer-Instanziierung basierend auf placement_mode
        if settings.placement_mode == 'GHOST_IMMEDIATE':
            if self._current_scatter_source_obj:
                self._ghost_drawer = GPUMeshGhostPreview(
                    color=tuple(settings.ghost_color),
                    initial_obj_name_for_mesh_data=self._current_scatter_source_obj.name
                )
                self._ghost_drawer.enable_drawing()
                self._ghost_drawer.set_visible(False) # Wird erst bei Mouse-Over sichtbar
            else:
                self.report({'WARNING'}, "No current scatter source object for GPU Ghost on invoke.")
        elif settings.placement_mode == 'ANIMATED_DROP_DIRECT':
            self._drop_marker_drawer = CircleWireframeDrawer(
                color=tuple(settings.marker_color),
                radius=settings.marker_radius,
                segments=settings.marker_segments,
                line_width=settings.marker_line_width
            )
            self._drop_marker_drawer.enable_drawing()
            self._drop_marker_drawer.set_visible(False)

        try:
            wm = context.window_manager
            self._timer = wm.event_timer_add(0.05, window=context.window) # Timer-Intervall ggf. anpassen
            wm.modal_handler_add(self)
            context.window.cursor_modal_set('CROSSHAIR')
        except Exception as e_modal_setup:
            log_scatter_exception(e_modal_setup, "Setting up modal handler/timer", self)
            self.report({'ERROR'}, "Error initializing modal operator.")
            self._cleanup_and_finish_for_error(context); return {'CANCELLED'}

        processing_mode_report = "On-the-fly processing" if NATIVE_MODULE_AVAILABLE and scatter_accel else "Fallback (marker) processing"
        self.report({'INFO'}, f"Mouse Scatter '{settings.placement_mode}' mode started. ({processing_mode_report})")
        self.report({'INFO'}, "Left-click to place/drop. ESC/RMB to exit.")
        return {'RUNNING_MODAL'}

    def modal(self, context, event): # Task 5 & 6 & 7 angepasst
        settings = context.scene.mouse_scatter_settings
        try: # State checks
            if self._session_source_collection and self._session_source_collection.name not in bpy.data.collections:
                self.report({'WARNING'}, "Session collection (fallback) became invalid. Exiting operator.")
                self._cleanup_and_finish_for_error(context); return {'CANCELLED'}

            self._falling_objects_data = [f for f in self._falling_objects_data if f.obj and f.obj.name in bpy.data.objects]
            self._post_land_spawn_objects = [s for s in self._post_land_spawn_objects if s.obj and s.obj.name in bpy.data.objects]
        except ReferenceError as e_ref_modal_check:
            log_scatter_exception(e_ref_modal_check, "Checking critical object references in modal", self)
            self.report({'WARNING'}, "A critical object reference became invalid. Exiting operator.");
            self._cleanup_and_finish_for_error(context); return {'CANCELLED'}
        except Exception as e_modal_check:
            log_scatter_exception(e_modal_check, "Unexpected error during state check in modal", self)
            self.report({'ERROR'}, f"Unexpected error during state check: {e_modal_check}. Exiting.");
            self._cleanup_and_finish_for_error(context); return {'CANCELLED'}

        redraw_needed_this_event = False
        if context.area:
            try: context.area.tag_redraw(); redraw_needed_this_event = True
            except ReferenceError: self._cleanup_and_finish_for_error(context); return {'CANCELLED'}
            except Exception as e_redraw_modal: log_scatter_exception(e_redraw_modal, "Tagging area for redraw in modal", self, level="WARNING")

        if event.type == 'ESC' or (event.type == 'RIGHTMOUSE' and event.value == 'PRESS'):
            self.finish(context); return {'CANCELLED'}
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'PAGE_UP', 'PAGE_DOWN', 'HOME', 'END', 'INSERT'}:
            return {'PASS_THROUGH'}

        current_time = time.time()
        try:
            # Task 5: MOUSEMOVE Event Handling
            if event.type == 'MOUSEMOVE':
                self._mouse_x = event.mouse_region_x
                self._mouse_y = event.mouse_region_y
                redraw_needed_this_event = True # Mouse move always needs redraw for preview

                # Raycast once for both modes
                hit, location, normal, hit_object = self.mouse_raycast(context, settings, self._mouse_x, self._mouse_y)

                if settings.placement_mode == 'GHOST_IMMEDIATE':
                    if self._ghost_drawer:
                        if not self._current_scatter_source_obj or self._current_scatter_source_obj.name not in bpy.data.objects:
                            self._current_scatter_source_obj = self.get_random_scatter_object(settings) # Finde neues Quellobjekt

                        if self._current_scatter_source_obj:
                            self._ghost_drawer.update_mesh_from_object(self._current_scatter_source_obj)
                            self._ghost_drawer.update_appearance(color=tuple(settings.ghost_color))

                            if hit and self._ghost_drawer._batch: # Nur wenn Raycast trifft UND Mesh-Daten für Ghost geladen sind
                                # Berechnung der Ghost-Transformationsmatrix
                                rand_rot_euler_rad = None
                                rand_scale_uniform = 1.0
                                if NATIVE_MODULE_AVAILABLE and scatter_accel:
                                    try:
                                        transform_data = scatter_accel.calculate_random_transforms_cpp(self._get_random_transform_settings_dict(settings))
                                        rot_values = transform_data["rotation_euler_rad"]
                                        rand_rot_euler_rad = Euler(rot_values, 'XYZ') if isinstance(rot_values, tuple) and len(rot_values) == 3 else None
                                        rand_scale_uniform = float(transform_data["scale_uniform"])
                                    except Exception: rand_rot_euler_rad = None
                                if not rand_rot_euler_rad: # Python Fallback
                                    rot_x_rad_py = math.radians(random.uniform(settings.rot_x_min, settings.rot_x_max))
                                    rot_y_rad_py = math.radians(random.uniform(settings.rot_y_min, settings.rot_y_max))
                                    rot_z_rad_py = math.radians(random.uniform(settings.rot_z_min, settings.rot_z_max))
                                    rand_rot_euler_rad = Euler((rot_x_rad_py, rot_y_rad_py, rot_z_rad_py), 'XYZ')
                                    rand_scale_uniform = random.uniform(settings.scale_min, settings.scale_max)

                                scale_matrix = Matrix.Scale(rand_scale_uniform, 4)
                                placement_normal_vec = (normal.normalized() if normal and normal.length > 0.001 else Vector((0.0, 0.0, 1.0)))
                                align_rot_quat = placement_normal_vec.to_track_quat('Z', 'Y')
                                random_rot_quat = rand_rot_euler_rad.to_quaternion()
                                final_rot_matrix = (align_rot_quat @ random_rot_quat).to_matrix().to_4x4()

                                # Pivot-Anpassung (vereinfacht, da wir keine Blender Objekt-Bounds direkt haben)
                                # Für GPU-Ghost ist der Pivot meist der Ursprung des Meshes.
                                # Man könnte die Bounding Box des *Quellobjekts* nehmen und transformieren.
                                final_pivot_location = location.copy()
                                height_offset_val = random.uniform(settings.height_min, settings.height_max)
                                if settings.offset_application_mode == 'WORLD_Z':
                                    final_pivot_location.z += height_offset_val
                                else:
                                    offset_vector_along_normal = placement_normal_vec * height_offset_val
                                    final_pivot_location += offset_vector_along_normal
                                
                                # Snap-to-Center-Logik
                                if settings.use_scatter_on_scatter and hit_object and hit_object.name in bpy.data.objects:
                                    is_scatter_target = (hasattr(hit_object, "rigid_body") and hit_object.rigid_body and hit_object.rigid_body.type == 'ACTIVE') or \
                                                        (self._session_source_collection and self._session_source_collection.name in bpy.data.collections and \
                                                        hasattr(hit_object, 'name') and hit_object.name.startswith(self._session_source_collection.name))
                                    if is_scatter_target and settings.snap_to_center_on_stack:
                                        final_pivot_location.xy = hit_object.matrix_world.translation.xy


                                loc_matrix = Matrix.Translation(final_pivot_location)
                                ghost_world_matrix = loc_matrix @ final_rot_matrix @ scale_matrix
                                self._ghost_drawer.set_transform(ghost_world_matrix)
                                self._ghost_drawer.set_visible(True)
                            else: # Kein Hit oder kein Batch
                                self._ghost_drawer.set_visible(False)
                        else: # Kein _current_scatter_source_obj
                            self._ghost_drawer.set_visible(False)


                elif settings.placement_mode == 'ANIMATED_DROP_DIRECT':
                    if self._drop_marker_drawer:
                        if hit:
                            self._drop_marker_drawer.set_transform(location, normal)
                            self._drop_marker_drawer.update_appearance(color=tuple(settings.marker_color), radius=settings.marker_radius, segments=settings.marker_segments, line_width=settings.marker_line_width)
                            self._drop_marker_drawer.set_visible(True)
                        else:
                            self._drop_marker_drawer.set_visible(False)

                # Brush Mode Logic innerhalb MOUSEMOVE
                if settings.use_brush_mode and self._is_dragging:
                    spacing_ok = True; current_brush_potential_loc = None

                    if hit: current_brush_potential_loc = location
                    else: spacing_ok = False

                    if not current_brush_potential_loc: spacing_ok = False

                    if spacing_ok and self._last_placed_loc:
                        if (current_brush_potential_loc - self._last_placed_loc).length < settings.brush_spacing:
                            spacing_ok = False

                    if spacing_ok:
                        action_taken_in_brush_drag = False
                        if settings.placement_mode == 'GHOST_IMMEDIATE' and self._ghost_drawer and self._ghost_drawer.get_is_visible():
                            new_loc = self.place_object(context, settings, self._mouse_x, self._mouse_y)
                            if new_loc: self._last_placed_loc = new_loc; action_taken_in_brush_drag = True
                        elif settings.placement_mode == 'ANIMATED_DROP_DIRECT' and self._drop_marker_drawer and self._drop_marker_drawer.get_is_visible():
                            new_dropped_obj_marker = self._start_animated_drop_object(context, settings, self._mouse_x, self._mouse_y)
                            if new_dropped_obj_marker: self._last_placed_loc = new_dropped_obj_marker.location.copy(); action_taken_in_brush_drag = True

                        if action_taken_in_brush_drag:
                            self._last_action_time = current_time
                            if settings.placement_mode == 'GHOST_IMMEDIATE':
                                self._current_scatter_source_obj = self.get_random_scatter_object(settings)
                                # Ghost-Mesh wird oben im MOUSEMOVE-Block aktualisiert
                        redraw_needed_this_event = True

                return {'RUNNING_MODAL'}


            # Task 6: LEFTMOUSE Event Handling
            if event.type == 'LEFTMOUSE':
                if event.value == 'PRESS':
                    if context.area and context.area.type == 'VIEW_3D':
                        action_taken_this_click = False
                        if settings.placement_mode == 'GHOST_IMMEDIATE':
                            if settings.use_brush_mode: self._is_dragging = True
                            # place_object nutzt den Zustand des _ghost_drawer
                            if self._ghost_drawer and self._ghost_drawer.get_is_visible():
                                new_loc = self.place_object(context, settings, self._mouse_x, self._mouse_y)
                                if new_loc: self._last_placed_loc = new_loc; action_taken_this_click = True
                            if action_taken_this_click or not settings.use_brush_mode :
                                self._current_scatter_source_obj = self.get_random_scatter_object(settings)
                                # Ghost-Mesh wird im MOUSEMOVE-Block aktualisiert

                        elif settings.placement_mode == 'ANIMATED_DROP_DIRECT':
                            if settings.use_brush_mode: self._is_dragging = True; self._last_action_time = 0
                            if self._drop_marker_drawer and self._drop_marker_drawer.get_is_visible(): # Nur wenn Marker sichtbar
                                new_dropped_obj_marker = self._start_animated_drop_object(context, settings, self._mouse_x, self._mouse_y)
                                if new_dropped_obj_marker:
                                    self._last_placed_loc = new_dropped_obj_marker.location.copy()
                                    action_taken_this_click = True; self._last_action_time = current_time

                        redraw_needed_this_event = True
                        return {'RUNNING_MODAL'}
                    else:
                        return {'PASS_THROUGH'}
                elif event.value == 'RELEASE':
                    if settings.use_brush_mode: self._is_dragging = False
                    return {'RUNNING_MODAL'}


            # Task 7: TIMER Event Handling
            if event.type == 'TIMER':
                timer_did_something = False
                if self._falling_objects_data:
                    self._update_falling_objects(context, settings); timer_did_something = True
                if self._post_land_spawn_objects:
                    if self._update_post_land_spawn_animations(context, settings): timer_did_something = True

                # Entfernt: self.update_preview(context, settings)
                # Die GPU-Drawer werden in MOUSEMOVE aktualisiert.

                if timer_did_something and context.area:
                    try: context.area.tag_redraw()
                    except ReferenceError: pass
                return {'RUNNING_MODAL'}

        except Exception as e_modal_main:
            log_scatter_exception(e_modal_main, "Main modal event handling loop", self)
            self.report({'ERROR'}, f"An unexpected error occurred in the modal operator: {e_modal_main}")
            self._cleanup_and_finish_for_error(context)
            return {'CANCELLED'}

        if redraw_needed_this_event and context.area:
            try: context.area.tag_redraw()
            except ReferenceError: pass
        return {'PASS_THROUGH'}


    def finish(self, context): # Task 4 angepasst
        scatter_settings = context.scene.mouse_scatter_settings
        session_col_name_at_finish = self._session_source_collection.name if self._session_source_collection and self._session_source_collection.name in bpy.data.collections else None

        try:
            # Finalize any falling objects
            for f_obj_wrapper in list(self._falling_objects_data):
                marker_obj_falling = f_obj_wrapper.obj
                if not marker_obj_falling or marker_obj_falling.name not in bpy.data.objects:
                    continue

                if not f_obj_wrapper.landed:
                    f_obj_wrapper.landed = True
                    if marker_obj_falling.animation_data:
                        marker_obj_falling.animation_data_clear()

                if not f_obj_wrapper.processed_on_land:
                    cpp_proc_settings_finish = self._get_processing_settings_for_cpp(context)
                    if cpp_proc_settings_finish and NATIVE_MODULE_AVAILABLE and scatter_accel:
                        if not f_obj_wrapper.source_mesh_name_for_processing:
                            self.report({'WARNING'}, f"Missing source_mesh_name for falling obj '{marker_obj_falling.name}' in finish. Removing.")
                            if marker_obj_falling.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_falling, do_unlink=True)
                            continue

                        data_for_cpp_finish = {
                            "original_marker_name": marker_obj_falling.name,
                            "source_mesh_name": f_obj_wrapper.source_mesh_name_for_processing,
                            "matrix_world": [list(row) for row in marker_obj_falling.matrix_world],
                        }
                        try:
                            instruction_finish = scatter_accel.analyze_single_object_for_processing(data_for_cpp_finish, cpp_proc_settings_finish)
                            action_finish = instruction_finish.get("action")
                            original_marker_name_cpp = instruction_finish.get("original_marker_name")
                            marker_to_process_finish = bpy.data.objects.get(original_marker_name_cpp)

                            if not marker_to_process_finish:
                                self.report({'WARNING'}, f"Marker '{original_marker_name_cpp}' for action '{action_finish}' (falling obj finish) not found. Item lost.")
                                continue

                            if action_finish == "CREATE_INSTANCE_FROM_SOURCE":
                                mesh_name_inst_f = instruction_finish.get("mesh_to_instance")
                                mesh_data_inst_f = bpy.data.meshes.get(mesh_name_inst_f)
                                if not mesh_data_inst_f:
                                    self.report({'WARNING'}, f"Mesh '{mesh_name_inst_f}' for instance (falling obj finish) not found.")
                                    if marker_to_process_finish.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process_finish, do_unlink=True)
                                    continue

                                inst_base_f = instruction_finish.get("new_instance_name_base", f"{marker_to_process_finish.name}_finish_inst")
                                final_inst_name_f = inst_base_f; idx_f = 0
                                while final_inst_name_f in bpy.data.objects:
                                    idx_f += 1; final_inst_name_f = f"{inst_base_f}.{idx_f:03d}"

                                new_inst_f = bpy.data.objects.new(name=final_inst_name_f, object_data=mesh_data_inst_f)
                                new_inst_f.matrix_world = Matrix(instruction_finish.get("matrix_world"))
                                target_col_name_f = instruction_finish.get("target_collection_name")
                                target_col_f = get_or_create_scatter_target_collection(target_col_name_f, context)
                                if target_col_f: target_col_f.objects.link(new_inst_f)
                                else: context.scene.collection.objects.link(new_inst_f)
                                if marker_to_process_finish.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process_finish, do_unlink=True)
                                marker_obj_falling = new_inst_f # Update ref for potential post-spawn

                            elif action_finish == "CONVERT_MARKER_TO_STATIC_RIGID" or action_finish == "CONVERT_MARKER_TO_STATIC":
                                target_col_name_f_s = instruction_finish.get("target_collection_name")
                                target_col_f_s = get_or_create_scatter_target_collection(target_col_name_f_s, context)
                                if marker_to_process_finish.name in context.scene.collection.objects:
                                     context.scene.collection.objects.unlink(marker_to_process_finish)
                                if target_col_f_s: target_col_f_s.objects.link(marker_to_process_finish)
                                else:
                                    if marker_to_process_finish.name not in context.scene.collection.objects:
                                        context.scene.collection.objects.link(marker_to_process_finish)
                                if instruction_finish.get("add_rigidbody", False):
                                    self._apply_rigid_body_to_object(context, marker_to_process_finish)

                            else: # SKIP
                                if marker_to_process_finish.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process_finish, do_unlink=True)

                        except Exception as e_finish_proc:
                            log_scatter_exception(e_finish_proc, f"Processing falling obj '{marker_obj_falling.name}' in finish (C++)", self)
                            if marker_obj_falling and marker_obj_falling.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_falling, do_unlink=True)
                    else:
                        im_settings_finish_f = getattr(context.scene, 'instance_manager_settings', None)
                        use_legacy_mark_f = True
                        if im_settings_finish_f: use_legacy_mark_f = im_settings_finish_f.use_instancing
                        if use_legacy_mark_f: marker_obj_falling["is_scatter_instance"] = True
                        if marker_obj_falling.name in context.scene.collection.objects:
                            context.scene.collection.objects.unlink(marker_obj_falling)
                        if self._session_source_collection: self._session_source_collection.objects.link(marker_obj_falling)
                        else: context.scene.collection.objects.link(marker_obj_falling)
                    f_obj_wrapper.processed_on_land = True

                if marker_obj_falling and marker_obj_falling.name in bpy.data.objects: # Check if object still exists
                    if scatter_settings.use_post_land_spawn and not f_obj_wrapper.spawn_triggered:
                        self._trigger_post_land_spawn(context, scatter_settings, marker_obj_falling)
                        f_obj_wrapper.spawn_triggered = True
            self._falling_objects_data.clear()

            # Finalize any post-land spawn animations
            for spawn_wrapper in list(self._post_land_spawn_objects):
                marker_obj_spawn = spawn_wrapper.obj
                if not marker_obj_spawn or marker_obj_spawn.name not in bpy.data.objects:
                    continue
                if not spawn_wrapper.animation_done:
                    marker_obj_spawn.location = spawn_wrapper.end_pos_world
                    if spawn_wrapper.total_roll_radians > 0.001 and spawn_wrapper.roll_axis_world.length > 0.5:
                        final_roll_quat = Quaternion(spawn_wrapper.roll_axis_world, spawn_wrapper.total_roll_radians)
                        marker_obj_spawn.rotation_quaternion = final_roll_quat @ spawn_wrapper.initial_orientation_quat
                    if marker_obj_spawn.animation_data:
                        marker_obj_spawn.animation_data_clear()

                cpp_proc_settings_spawn_finish = self._get_processing_settings_for_cpp(context)
                if cpp_proc_settings_spawn_finish and NATIVE_MODULE_AVAILABLE and scatter_accel:
                    if not spawn_wrapper.source_mesh_name_for_processing:
                        self.report({'WARNING'}, f"Missing source_mesh_name for spawned obj '{marker_obj_spawn.name}' in finish. Removing.")
                        if marker_obj_spawn.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_spawn, do_unlink=True)
                        continue

                    data_for_cpp_spawn_finish = {
                        "original_marker_name": marker_obj_spawn.name,
                        "source_mesh_name": spawn_wrapper.source_mesh_name_for_processing,
                        "matrix_world": [list(row) for row in marker_obj_spawn.matrix_world],
                    }
                    try:
                        instruction_spawn_f = scatter_accel.analyze_single_object_for_processing(data_for_cpp_spawn_finish, cpp_proc_settings_spawn_finish)
                        action_spawn_f = instruction_spawn_f.get("action")
                        original_marker_name_spawn_cpp = instruction_spawn_f.get("original_marker_name")
                        marker_to_process_spawn_finish = bpy.data.objects.get(original_marker_name_spawn_cpp)

                        if not marker_to_process_spawn_finish:
                            self.report({'WARNING'}, f"Marker '{original_marker_name_spawn_cpp}' for action '{action_spawn_f}' (spawned obj finish) not found. Item lost.")
                            continue

                        if action_spawn_f == "CREATE_INSTANCE_FROM_SOURCE":
                            mesh_name_inst_sf = instruction_spawn_f.get("mesh_to_instance")
                            mesh_data_inst_sf = bpy.data.meshes.get(mesh_name_inst_sf)
                            if not mesh_data_inst_sf:
                                self.report({'WARNING'}, f"Mesh '{mesh_name_inst_sf}' for instance (spawned obj finish) not found.")
                                if marker_to_process_spawn_finish.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process_spawn_finish, do_unlink=True)
                                continue

                            inst_base_sf = instruction_spawn_f.get("new_instance_name_base", f"{marker_to_process_spawn_finish.name}_finish_inst")
                            final_inst_name_sf = inst_base_sf; idx_sf = 0
                            while final_inst_name_sf in bpy.data.objects:
                                idx_sf += 1; final_inst_name_sf = f"{inst_base_sf}.{idx_sf:03d}"

                            new_inst_sf = bpy.data.objects.new(name=final_inst_name_sf, object_data=mesh_data_inst_sf)
                            new_inst_sf.matrix_world = Matrix(instruction_spawn_f.get("matrix_world"))
                            target_col_name_sf = instruction_spawn_f.get("target_collection_name")
                            target_col_sf = get_or_create_scatter_target_collection(target_col_name_sf, context)
                            if target_col_sf: target_col_sf.objects.link(new_inst_sf)
                            else: context.scene.collection.objects.link(new_inst_sf)
                            if marker_to_process_spawn_finish.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process_spawn_finish, do_unlink=True)

                        elif action_spawn_f == "CONVERT_MARKER_TO_STATIC_RIGID" or action_spawn_f == "CONVERT_MARKER_TO_STATIC":
                            target_col_name_sf_s = instruction_spawn_f.get("target_collection_name")
                            target_col_sf_s = get_or_create_scatter_target_collection(target_col_name_sf_s, context)
                            if marker_to_process_spawn_finish.name in context.scene.collection.objects:
                                context.scene.collection.objects.unlink(marker_to_process_spawn_finish)
                            if target_col_sf_s: target_col_sf_s.objects.link(marker_to_process_spawn_finish)
                            else:
                                if marker_to_process_spawn_finish.name not in context.scene.collection.objects:
                                    context.scene.collection.objects.link(marker_to_process_spawn_finish)
                            if instruction_spawn_f.get("add_rigidbody", False):
                                self._apply_rigid_body_to_object(context, marker_to_process_spawn_finish)

                        else: # SKIP
                            if marker_to_process_spawn_finish.name in bpy.data.objects: bpy.data.objects.remove(marker_to_process_spawn_finish, do_unlink=True)

                    except Exception as e_finish_spawn_proc:
                        log_scatter_exception(e_finish_spawn_proc, f"Processing spawned obj '{marker_obj_spawn.name}' in finish (C++)", self)
                        if marker_obj_spawn and marker_obj_spawn.name in bpy.data.objects: bpy.data.objects.remove(marker_obj_spawn, do_unlink=True)
                else:
                    im_settings_finish_s = getattr(context.scene, 'instance_manager_settings', None)
                    use_legacy_mark_s = True
                    if im_settings_finish_s: use_legacy_mark_s = im_settings_finish_s.use_instancing
                    if use_legacy_mark_s: marker_obj_spawn["is_scatter_instance"] = True
                    if marker_obj_spawn.name in context.scene.collection.objects:
                        context.scene.collection.objects.unlink(marker_obj_spawn)
                    if self._session_source_collection: self._session_source_collection.objects.link(marker_obj_spawn)
                    else: context.scene.collection.objects.link(marker_obj_spawn)
            self._post_land_spawn_objects.clear()

            self._cleanup_and_finish_for_error(context) # Task 4: Cleanup Drawer auch hier

            im_settings = getattr(context.scene, 'instance_manager_settings', None)
            if im_settings and im_settings.enable_instancing_on_scatter_finish:
                if session_col_name_at_finish and session_col_name_at_finish in bpy.data.collections:
                    fallback_collection = bpy.data.collections.get(session_col_name_at_finish)
                    if fallback_collection and fallback_collection.all_objects:
                        if hasattr(bpy.ops.object, 'process_source_for_instancing_modal'):
                            try:
                                bpy.ops.object.process_source_for_instancing_modal('INVOKE_DEFAULT', source_collection_to_process=session_col_name_at_finish)
                                self.report({'INFO'}, f"Triggered modal instancing for fallback objects in '{session_col_name_at_finish}'.")
                            except Exception as e_op_call_finish:
                                log_scatter_exception(e_op_call_finish, f"Calling modal instancing for fallback in '{session_col_name_at_finish}'", self)
                                self.report({'ERROR'}, f"Error calling modal instancing for fallback: {e_op_call_finish}")
                        else: self.report({'WARNING'}, "Instance Manager operator 'process_source_for_instancing_modal' not found for fallback objects.")
                    elif fallback_collection:
                        self.report({'INFO'}, f"Fallback collection '{session_col_name_at_finish}' is empty. No batch processing needed.")
                        try:
                            if not fallback_collection.all_objects :
                                parent_found = False
                                if fallback_collection.name in context.scene.collection.children:
                                    context.scene.collection.children.unlink(fallback_collection); parent_found = True
                                else:
                                    for coll_iter in bpy.data.collections:
                                        if fallback_collection.name in coll_iter.children:
                                            coll_iter.children.unlink(fallback_collection); parent_found = True; break
                                bpy.data.collections.remove(fallback_collection)
                                self.report({'DEBUG'}, f"Removed empty session collection '{session_col_name_at_finish}'.")
                        except Exception as e_rem_empty_sess:
                             log_scatter_exception(e_rem_empty_sess, f"Removing empty session collection '{session_col_name_at_finish}'", self, level="DEBUG")
                elif session_col_name_at_finish:
                     self.report({'INFO'}, f"Session Collection (fallback) '{session_col_name_at_finish}' no longer exists.")
            self.report({'INFO'}, "Mouse Scatter finished.")
        except Exception as e_finish_main:
            log_scatter_exception(e_finish_main, "Main finish logic", self)
            self.report({'ERROR'}, f"An error occurred while finishing the operator: {e_finish_main}")
        return {'FINISHED'}

# --- UI Panel ---
class VIEW3D_PT_mouse_scatter(bpy.types.Panel):
    bl_label = "Mouse Scatter Tool"
    bl_idname = "VIEW3D_PT_mouse_scatter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'PhysicalTool'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.mouse_scatter_settings
        if not settings:
            layout.label(text="Scatter Settings not available!", icon='ERROR')
            return

        try:
            box_main_setup = layout.box()
            box_main_setup.label(text="Basic Setup:")
            col_main_setup = box_main_setup.column(align=True)
            col_main_setup.prop(settings, "raycast_mode")
            if settings.raycast_mode == 'OBJECT': col_main_setup.prop(settings, "ground_object")
            col_main_setup.prop(settings, "placement_mode")

            # Task 2: UI für neue Drawer-Settings
            if settings.placement_mode == 'GHOST_IMMEDIATE':
                box_ghost_vis = layout.box()
                box_ghost_vis.label(text="GPU Ghost Preview:")
                col_ghost_vis = box_ghost_vis.column(align=True)
                col_ghost_vis.prop(settings, "ghost_color")
            elif settings.placement_mode == 'ANIMATED_DROP_DIRECT':
                box_marker_vis = layout.box()
                box_marker_vis.label(text="GPU Drop Marker:")
                col_marker_vis = box_marker_vis.column(align=True)
                col_marker_vis.prop(settings, "marker_color")
                col_marker_vis.prop(settings, "marker_radius")
                col_marker_vis.prop(settings, "marker_segments")
                col_marker_vis.prop(settings, "marker_line_width")

            layout.separator()

            im_settings_ui = getattr(context.scene, 'instance_manager_settings', None)
            if im_settings_ui:
                box_info = layout.box()
                col_info = box_info.column()
                col_info.label(text="Object Handling (via Instance Manager):", icon='INFO')

                if im_settings_ui.use_instancing:
                    col_info.label(text="-> Output Mode: INSTANCES", icon='OUTLINER_OB_LIGHTPROBE')
                    col_info.label(text=f"   (Target: '{im_settings_ui.instance_collection_name}')")
                else:
                    col_info.label(text="-> Output Mode: STATIC Objects", icon='OBJECT_DATAMODE')
                    col_info.label(text=f"   (Target: '{im_settings_ui.static_collection_name}')")
                    if im_settings_ui.use_rigid_for_non_instances:
                        col_info.label(text="   (Rigid Bodies will be added)", icon='PHYSICS')
                    else:
                        col_info.label(text="   (No Rigid Bodies by default)", icon='CANCEL')

                if im_settings_ui.enable_instancing_on_scatter_finish:
                    col_info.label(text="Batch Processing on Finish: ACTIVE", icon='CHECKMARK')
                    col_info.label(text=" (For fallback objects if C++ fails)")
                else:
                    col_info.label(text="Batch Processing on Finish: INACTIVE", icon='CANCEL')
                col_info.label(text="Settings in 'Instance Manager' panel.")
            else:
                layout.label(text="Instance Manager settings not found.", icon='ERROR')
                layout.label(text="On-the-fly processing relies on these settings.")
            layout.separator()

            box_placement_options = layout.box()
            box_placement_options.label(text="Placement Options (General):")
            col_placement_options = box_placement_options.column(align=True)
            col_placement_options.prop(settings, "use_brush_mode")
            if settings.use_brush_mode:
                sub_col_brush = col_placement_options.column(align=True); sub_col_brush.alignment = 'RIGHT'
                sub_col_brush.prop(settings, "brush_spacing")
            col_placement_options.prop(settings, "use_scatter_on_scatter")
            if settings.use_scatter_on_scatter:
                sub_col_stack = col_placement_options.column(align=True); sub_col_stack.alignment = 'RIGHT'
                sub_col_stack.prop(settings, "snap_to_center_on_stack")
            col_placement_options.prop(settings, "prevent_overlap")
            if settings.prevent_overlap:
                sub_col_overlap = col_placement_options.column(align=True); sub_col_overlap.alignment = 'RIGHT'
                sub_col_overlap.prop(settings, "overlap_check_distance")

            col_placement_options.prop(settings, "apply_transforms_to_sources_on_invoke")
            if hasattr(bpy.ops.object, 'prepare_managed_instances_modal'):
                col_placement_options.operator("scatter_list.prepare_instances", icon='MOD_INSTANCE', text="Prepare Managed Instances")
            layout.separator()

            box_random = layout.box()
            box_random.label(text="Initial Randomization (Ghost & Drop Start):")
            col_random = box_random.column(align=True)
            col_random.prop(settings, "offset_application_mode", text="Offset Application")
            row_h = col_random.row(align=True); row_h.prop(settings, "height_min"); row_h.prop(settings, "height_max")
            row_rx = col_random.row(align=True); row_rx.prop(settings, "rot_x_min"); row_rx.prop(settings, "rot_x_max")
            row_ry = col_random.row(align=True); row_ry.prop(settings, "rot_y_min"); row_ry.prop(settings, "rot_y_max")
            row_rz = col_random.row(align=True); row_rz.prop(settings, "rot_z_min"); row_rz.prop(settings, "rot_z_max")
            row_s = col_random.row(align=True); row_s.prop(settings, "scale_min"); row_s.prop(settings, "scale_max")
            layout.separator()

            is_animated_mode_for_drop_settings = settings.placement_mode == 'ANIMATED_DROP_DIRECT'
            if is_animated_mode_for_drop_settings:
                box_animated_drop = layout.box()
                box_animated_drop.label(text="Animated Drop Settings:")
                col_animated_drop = box_animated_drop.column(align=True)
                col_animated_drop.prop(settings, "drop_anim_steps")
                col_animated_drop.prop(settings, "drop_anim_speed_step")
                col_animated_drop.label(text="Start Height: Uses 'Initial Randomization' above.")
                col_animated_drop.prop(settings, "landing_z_correction")
                col_animated_drop.separator()
                col_animated_drop.label(text="Tumble Effect During Drop:")
                col_animated_drop.prop(settings, "enable_tumble_during_drop", text="Enable")
                sub_box_tumble = col_animated_drop.box(); sub_box_tumble.enabled = settings.enable_tumble_during_drop
                col_tumble_params = sub_box_tumble.column(align=True)
                col_tumble_params.prop(settings, "tumble_rotation_intensity_factor")
                col_tumble_params.prop(settings, "tumble_offset_xy_max_step")
                col_tumble_params.prop(settings, "tumble_frequency_during_drop")
                col_animated_drop.separator()
                col_animated_drop.prop(settings, "create_debug_empties_on_land")
                col_animated_drop.separator()
                col_animated_drop.label(text="Post-Landing Spawn (Multiball):")
                col_animated_drop.prop(settings, "use_post_land_spawn")
                box_post_spawn = col_animated_drop.box()
                box_post_spawn.enabled = settings.use_post_land_spawn
                col_post_spawn = box_post_spawn.column(align=True)
                row_count = col_post_spawn.row(align=True)
                row_count.prop(settings, "post_land_spawn_count_min", text="Min Count")
                row_count.prop(settings, "post_land_spawn_count_max", text="Max Count")
                row_dist = col_post_spawn.row(align=True)
                row_dist.prop(settings, "post_land_spawn_distance_min", text="Min Dist.")
                row_dist.prop(settings, "post_land_spawn_distance_max", text="Max Dist.")
                col_post_spawn.prop(settings, "post_land_spawn_scale_distance_by_mesh_size")
                box_dist_scale = col_post_spawn.box()
                box_dist_scale.enabled = settings.use_post_land_spawn and settings.post_land_spawn_scale_distance_by_mesh_size
                col_dist_scale_params = box_dist_scale.column(align=True)
                col_dist_scale_params.prop(settings, "post_land_spawn_mesh_size_influence")
                col_post_spawn.prop(settings, "post_land_spawn_duration_frames")
                col_post_spawn.prop(settings, "post_land_spawn_offset_from_surface")
                col_post_spawn.prop(settings, "post_land_spawn_roll_revolutions")
                col_post_spawn.prop(settings, "post_land_spawn_copy_main_obj_transform")
                col_post_spawn.prop(settings, "post_land_spawn_use_virtual_gravity")
            layout.separator()

            box_objects = layout.box()
            box_objects.label(text="Objects to Scatter:")
            if any(entry.obj for entry in settings.scatter_objects_list if entry.obj and entry.obj.type == 'MESH'):
                box_objects.operator("scatter_list.apply_transforms", icon='OBJECT_ORIGIN', text="Apply Transforms to Source List")
            row_obj_btns_top = box_objects.row(align=True)
            row_obj_btns_top.operator(OBJECT_OT_add_selected_to_scatter_list.bl_idname, icon='SELECT_SET', text="Add Selected")
            row_obj_btns_top.operator(OBJECT_OT_clear_scatter_list.bl_idname, icon='TRASH', text="Clear List")
            row_list_ui = box_objects.row()
            row_list_ui.template_list("SCATTER_UL_objects_list", "scatter_objects_list_ul",
                                      settings, "scatter_objects_list",
                                      settings, "active_scatter_object_index", rows=3)
            col_list_btns_side = row_list_ui.column(align=True)
            col_list_btns_side.operator(OBJECT_OT_add_scatter_object_entry.bl_idname, icon='ADD', text="")
            col_list_btns_side.operator(OBJECT_OT_remove_scatter_object_entry.bl_idname, icon='REMOVE', text="")
            col_list_btns_side.separator()
            op_up = col_list_btns_side.operator(OBJECT_OT_move_scatter_object_entry.bl_idname, icon='TRIA_UP', text=""); op_up.direction = 'UP'
            op_down = col_list_btns_side.operator(OBJECT_OT_move_scatter_object_entry.bl_idname, icon='TRIA_DOWN', text=""); op_down.direction = 'DOWN'
            if 0 <= settings.active_scatter_object_index < len(settings.scatter_objects_list):
                active_entry = settings.scatter_objects_list[settings.active_scatter_object_index]
                box_objects.prop(active_entry, "obj", text="Selected")
            layout.separator()

            if NATIVE_MODULE_AVAILABLE and scatter_accel:
                 layout.operator(SCATTER_OT_test_native_module.bl_idname, text="Test Native Module (Scatter)", icon='CONSOLE')
            else:
                 layout.label(text="Native module (Scatter) not available for testing.", icon='ERROR')
            layout.separator()

            if context.mode == 'OBJECT':
                layout.operator("object.mouse_scatter", text="Start Scatter / Drop", icon='BRUSH_DATA')
            else: layout.label(text="Switch to Object Mode to use", icon='INFO')
        except Exception as e_draw:
            log_scatter_exception(e_draw, "Drawing Scatter UI Panel", operator_instance=self, level="CRITICAL")
            layout.label(text="Error drawing panel!", icon='ERROR')

# --- UIList Class ---
class SCATTER_UL_objects_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        obj_entry = item
        try:
            if self.layout_type in {'DEFAULT', 'COMPACT'}:
                if obj_entry.obj:
                    layout.prop(obj_entry, "obj", text="", emboss=False, icon_value=layout.icon(obj_entry.obj))
                else:
                    layout.label(text="Empty Slot", icon='QUESTION')
            elif self.layout_type == 'GRID':
                layout.alignment = 'CENTER'
                layout.label(text="", icon_value=layout.icon(obj_entry.obj) if obj_entry.obj else 'QUESTION')
        except Exception as e:
            log_scatter_exception(e, f"Drawing UIList item for '{obj_entry.name if obj_entry else 'UnknownItem'}'", level="WARNING")
            layout.label(text="UI Error", icon='ERROR')

# --- Testoperator for Native C++ Module ---
class SCATTER_OT_test_native_module(bpy.types.Operator):
    bl_idname = "scatter.test_native_call"
    bl_label = "Native C++ Test Call (Scatter-Modul)"
    bl_options = {'REGISTER', 'UNDO'}

    def _get_test_transform_settings_dict(self, settings: bpy.types.PropertyGroup) -> dict:
        return {
            "rot_x_min_deg": settings.rot_x_min, "rot_x_max_deg": settings.rot_x_max,
            "rot_y_min_deg": settings.rot_y_min, "rot_y_max_deg": settings.rot_y_max,
            "rot_z_min_deg": settings.rot_z_min, "rot_z_max_deg": settings.rot_z_max,
            "scale_min": settings.scale_min, "scale_max": settings.scale_max,
        }

    def execute(self, context):
        self.report({'INFO'}, "Executing native C++ test (from Scatter module)...")
        print("--- Native C++ Test (Scatter Module) ---")

        if NATIVE_MODULE_AVAILABLE and scatter_accel:
            print("Native module IS AVAILABLE to Scatter module.")

            print("\nTesting 'calculate_random_transforms_cpp':")
            settings_mock = context.scene.mouse_scatter_settings
            transform_settings_dict = self._get_test_transform_settings_dict(settings_mock)
            print(f"Sending transform settings to C++: {transform_settings_dict}")
            try:
                result_transforms = scatter_accel.calculate_random_transforms_cpp(transform_settings_dict)
                print(f"Received from C++ (calculate_random_transforms_cpp): {result_transforms}")

                print("\nTesting 'analyze_single_object_for_processing':")
                cpp_proc_settings_test = self._get_processing_settings_for_cpp(context)
                if cpp_proc_settings_test:
                    print(f"Processing settings for C++: {cpp_proc_settings_test}")

                    mock_marker_data = {
                        "original_marker_name": "TestMarker_001",
                        "source_mesh_name": "Cube",
                        "matrix_world": [
                            [1.0, 0.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0, 0.0],
                            [0.0, 0.0, 1.0, 0.0],
                            [0.0, 0.0, 0.0, 1.0]
                        ]
                    }
                    print(f"Sending single object data to C++: {mock_marker_data}")
                    instruction_single = scatter_accel.analyze_single_object_for_processing(mock_marker_data, cpp_proc_settings_test)
                    print(f"Received from C++ (analyze_single_object_for_processing): {instruction_single}")
                else:
                    print("Could not get processing settings for C++ test (Instance Manager settings missing?).")

            except Exception as e_cpp_call:
                self.report({'ERROR'}, f"Error calling C++ function: {e_cpp_call}. See console.")
                log_scatter_exception(e_cpp_call, "calling scatter_accel function", self)
        else:
            self.report({'ERROR'}, "Native C++ module is NOT available to Scatter module.")
            print("Native module is NOT available to Scatter module.")

        print("--- End Native C++ Test (Scatter Module) ---")
        return {'FINISHED'}

    def _get_processing_settings_for_cpp(self, context) -> dict:
        im_settings = getattr(context.scene, 'instance_manager_settings', None)
        if not im_settings:
            self.report({'WARNING'}, "Instance Manager Settings not found for C++ processing test.")
            return None
        return {
            "mode_is_instancing": im_settings.use_instancing,
            "apply_rigidbody_static": im_settings.use_rigid_for_non_instances,
            "instance_collection_name": im_settings.instance_collection_name,
            "static_collection_name": im_settings.static_collection_name,
            "instance_name_base_suffix": "_inst"
        }

# --- Registration ---
classes_to_register_scatter = (
    ScatterObjectEntry, MouseScatterSettings, # PropertyGroups first
    OBJECT_OT_add_scatter_object_entry, OBJECT_OT_remove_scatter_object_entry,
    OBJECT_OT_move_scatter_object_entry, OBJECT_OT_add_selected_to_scatter_list,
    OBJECT_OT_clear_scatter_list, OBJECT_OT_apply_transforms_to_scatter_objects,
    OBJECT_OT_prepare_scatter_instances, OBJECT_OT_mouse_scatter,
    SCATTER_UL_objects_list, VIEW3D_PT_mouse_scatter, SCATTER_OT_test_native_module
)
_registered_classes_scatter = set()

def register():
    global _registered_classes_scatter
    _registered_classes_scatter.clear()
    print(f"SCATTER_REG: --- Starting Scatter Registration (Module: {__name__}) ---")
    print(f"SCATTER_REG: Native module available status: {NATIVE_MODULE_AVAILABLE}")

    # Unregister any existing classes from this addon module to prevent conflicts on re-registration
    for cls in reversed(classes_to_register_scatter): # Check in reverse order of typical registration
        if hasattr(bpy.types, cls.__name__):
            try:
                # Check if the class in bpy.types is indeed from this module before unregistering
                current_bpy_type_class = getattr(bpy.types, cls.__name__)
                if hasattr(current_bpy_type_class, 'bl_rna') and current_bpy_type_class.__module__.startswith(__name__.split('.')[0]):
                    bpy.utils.unregister_class(current_bpy_type_class)
                    print(f"SCATTER_REG: Pre-unregistered existing class: {cls.__name__}")
            except RuntimeError:
                print(f"SCATTER_REG: Could not pre-unregister {cls.__name__} (likely already gone or not from this module).")
            except Exception as e_pre_unreg:
                log_scatter_exception(e_pre_unreg, f"Pre-unregistering {cls.__name__}", level="WARNING")

    # Register PropertyGroups first
    property_groups_to_register = [ScatterObjectEntry, MouseScatterSettings]
    for cls in property_groups_to_register:
        try:
            bpy.utils.register_class(cls)
            _registered_classes_scatter.add(cls)
            print(f"SCATTER_REG: Registered PG: {cls.__name__}")
        except Exception as e:
            log_scatter_exception(e, f"Registering PG {cls.__name__}", level="CRITICAL")
            # If a critical PG fails, it might be better to stop registration
            raise  # Re-raise the exception to halt addon loading if PG registration fails

    # Add PointerProperty to Scene for MouseScatterSettings
    try:
        # Defensive deletion if it somehow exists but from a wrong type or old registration
        if hasattr(bpy.types.Scene, 'mouse_scatter_settings'):
            prop_info = bpy.types.Scene.bl_rna.properties.get('mouse_scatter_settings')
            # Only delete if it's a PointerProperty AND its type is our MouseScatterSettings
            # OR if it's something else entirely (which would be an error from a previous load)
            if not (isinstance(prop_info.fixed_type, PointerProperty) and prop_info.fixed_type.type == MouseScatterSettings):
                 print(f"SCATTER_REG: WARN - 'mouse_scatter_settings' exists on Scene but is not the correct type. Attempting to delete.")
            try:
                del bpy.types.Scene.mouse_scatter_settings
            except Exception as e_del_prop:
                 log_scatter_exception(e_del_prop, "Deleting existing 'mouse_scatter_settings' property from Scene", level="WARNING")

        bpy.types.Scene.mouse_scatter_settings = PointerProperty(type=MouseScatterSettings)
        print("SCATTER_REG: Set scene property 'mouse_scatter_settings'.")
    except Exception as e:
        log_scatter_exception(e, "Setting scene property 'mouse_scatter_settings'", level="CRITICAL")
        raise # Critical for the addon to function

    # Register other classes (Operators, Panels, UILists)
    other_classes_to_register = [cls for cls in classes_to_register_scatter if cls not in property_groups_to_register]
    for cls in other_classes_to_register:
        try:
            bpy.utils.register_class(cls)
            _registered_classes_scatter.add(cls)
            print(f"SCATTER_REG: Registered: {cls.__name__}")
        except Exception as e:
            log_scatter_exception(e, f"Registering {cls.__name__}", level="CRITICAL")
            # For UI elements or operators, failing to register might not be fatal for the whole addon
            # but it will mean parts of it won't work. Decide if to raise or just warn.
            if not issubclass(cls, (bpy.types.UIList, bpy.types.Panel, bpy.types.Operator)):
                 raise # If it's not one of these, it might be more critical
            else:
                 print(f"SCATTER_REG: WARNING - Failed to register UI/Operator class {cls.__name__}, addon might be partially non-functional.")

    print(f"SCATTER_REG: --- Scatter Registration Complete ({len(_registered_classes_scatter)} classes actually registered by this module) ---")


def unregister():
    global _registered_classes_scatter
    print(f"SCATTER_UNREG: --- Starting Scatter Unregistration ({len(_registered_classes_scatter)} classes to check from this module) ---")

    # Remove the PointerProperty from Scene first
    if hasattr(bpy.types.Scene, 'mouse_scatter_settings'):
        try:
            # Check if the property is of the correct type before deleting
            # This helps prevent errors if another addon modified it or if it was already removed
            prop_info = bpy.types.Scene.bl_rna.properties.get('mouse_scatter_settings')
            if prop_info and isinstance(prop_info.fixed_type, PointerProperty) and prop_info.fixed_type.type == MouseScatterSettings:
                del bpy.types.Scene.mouse_scatter_settings
                print("SCATTER_UNREG: Removed scene property 'mouse_scatter_settings'.")
            elif prop_info:
                print(f"SCATTER_UNREG: Scene property 'mouse_scatter_settings' was not of expected type '{MouseScatterSettings.__name__}'. Skipping deletion by this module.")
            else:
                print("SCATTER_UNREG: Scene property 'mouse_scatter_settings' not found (already removed or never set by this module).")
        except Exception as e:
            log_scatter_exception(e, "Deleting scene property 'mouse_scatter_settings'", level="WARNING")

    # Unregister classes in reverse order of registration (approximately)
    # It's safer to iterate over a copy of the set if items might be removed during iteration (though here we clear it at the end)
    # Using reversed(list(_registered_classes_scatter)) is a good practice.

    # Correct unregistration order: Operators/Panels/UILists, then PropertyGroups
    property_groups_registered = {cls for cls in _registered_classes_scatter if issubclass(cls, PropertyGroup)}
    other_classes_registered = _registered_classes_scatter - property_groups_registered

    for cls in reversed(list(other_classes_registered)): # Unregister Operators, Panels, UILists
        if hasattr(bpy.types, cls.__name__): # Check if Blender still knows about this class type name
            try:
                # Double check if the class registered under bpy.types is actually our class
                current_class_ref = getattr(bpy.types, cls.__name__)
                if current_class_ref == cls: # Ensure we are unregistering the correct class object
                     bpy.utils.unregister_class(cls)
                     print(f"SCATTER_UNREG: Unregistered: {cls.__name__}")
                else:
                     print(f"SCATTER_UNREG: Mismatch - bpy.types.{cls.__name__} is not the class from this module. Skipping unregistration for {cls.__name__}.")
            except RuntimeError:
                print(f"SCATTER_UNREG: {cls.__name__} already unregistered or not found (RuntimeError).")
            except Exception as e_gen:
                log_scatter_exception(e_gen, f"Unregistering {cls.__name__}", level="WARNING")

    for cls in reversed(list(property_groups_registered)): # Unregister PropertyGroups
        if hasattr(bpy.types, cls.__name__):
            try:
                current_class_ref = getattr(bpy.types, cls.__name__)
                if current_class_ref == cls:
                     bpy.utils.unregister_class(cls)
                     print(f"SCATTER_UNREG: Unregistered PG: {cls.__name__}")
                else:
                     print(f"SCATTER_UNREG: Mismatch - bpy.types.{cls.__name__} is not the PG from this module. Skipping unregistration for {cls.__name__}.")
            except RuntimeError:
                print(f"SCATTER_UNREG: PG {cls.__name__} already unregistered or not found (RuntimeError).")
            except Exception as e_gen:
                log_scatter_exception(e_gen, f"Unregistering PG {cls.__name__}", level="WARNING")

    _registered_classes_scatter.clear()
    print("SCATTER_UNREG: --- Scatter Unregistration Complete ---")

# --- END OF FILE physics_cursor_scatter.py ---
