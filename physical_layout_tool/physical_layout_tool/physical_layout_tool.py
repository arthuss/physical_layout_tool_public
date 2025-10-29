# coding: utf-8
# physical_layout_tool.py
bl_info = {
    "name": "Physical Tool",
    "blender": (4, 4, 0),
    "category": "Object",
    "author": "EXEGET",
    "version": (1, 7, 0, 0), # Version erhöht für C++ Integration
    "location": "View3D > Sidebar > PhysicalTool Tab",
    "description": "Advanced mouse-based object scattering with physics and post-landing animations. C++ accelerated parts.",
}
import bpy
import traceback
from bpy.props import FloatProperty, EnumProperty, PointerProperty, BoolProperty, StringProperty, IntProperty

# --- Globale Variablen für C++ Modul und Flag (werden durch Import aus __init__.py gefüllt) ---
# Diese werden am Anfang des Moduls definiert, damit sie immer existieren,
# auch wenn der Import aus dem Paket fehlschlägt oder die __init__.py nicht korrekt arbeitet.
# Die tatsächlichen Werte kommen dann aus dem Import.
scatter_accel = None
NATIVE_MODULE_AVAILABLE = False
# ---

_pt_module_name = __name__ # physical_tool module name (dieser Name ist modul-spezifisch und ok)

# Import für das C++ Modul und das Verfügbarkeits-Flag aus dem Hauptpaket
# Angepasst an den Stil des ursprünglichen instance_operator.py für Konsistenz
try:
    # Diese Zeilen versuchen, die Variablen zu importieren, die in __init__.py des Pakets
    # (also im Ordner darüber, repräsentiert durch '..') definiert und initialisiert wurden.
    # Die Alias-Namen sind exakt wie im ursprünglichen instance_operator.py Vorbild.
    from . import scatter_accel as pkg_scatter_accel
    from . import NATIVE_MODULE_AVAILABLE as pkg_NATIVE_MODULE_AVAILABLE

    # Weise die importierten Werte den modulglobalen Variablen zu.
    # Dies ist der "alte" Stil, den wir hier für Konsistenz replizieren.
    pkg_scatter_accel = pkg_scatter_accel
    NATIVE_MODULE_AVAILABLE = pkg_NATIVE_MODULE_AVAILABLE

    # Die nachfolgenden Prüfungen basieren nun auf den globalen Variablen,
    # die gerade oben zugewiesen wurden.
    if NATIVE_MODULE_AVAILABLE and pkg_scatter_accel:
        print(f"INFO [{_pt_module_name}]: Native C++ Modul 'pkg_scatter_accel' und Flag NATIVE_MODULE_AVAILABLE für PhysicalTool erfolgreich bezogen.")
    elif NATIVE_MODULE_AVAILABLE and not pkg_scatter_accel:
         print(f"WARNUNG [{_pt_module_name}]: NATIVE_MODULE_AVAILABLE ist True, aber pkg_scatter_accel ist None. Problem in __init__.py? Setze NATIVE_MODULE_AVAILABLE lokal auf False.")
         NATIVE_MODULE_AVAILABLE = False
         # pkg_scatter_accel ist durch die Zuweisung oben bereits None.
    elif not NATIVE_MODULE_AVAILABLE:
        print(f"INFO [{_pt_module_name}]: Native C++ Modul für PhysicalTool NICHT verfügbar (NATIVE_MODULE_AVAILABLE ist False).")
        if pkg_scatter_accel is not None:
            print(f"WARNUNG [{_pt_module_name}]: NATIVE_MODULE_AVAILABLE False, aber pkg_scatter_accel ist nicht None. Setze pkg_scatter_accel auf None.")
            pkg_scatter_accel = None

except ImportError as e_imp_pt:
    print(f"KRITISCH [{_pt_module_name}]: ImportError beim Versuch, C++ Modul/Flag für PhysicalTool aus Paket zu importieren: {e_imp_pt}")
    print(f"  [{_pt_module_name}]: C++ Beschleunigung wird für dieses Modul DEAKTIVIERT.")
    pkg_scatter_accel = None # Sicherstellen
    NATIVE_MODULE_AVAILABLE = False # Sicherstellen
except Exception as e_gen_imp_pt:
    print(f"KRITISCH [{_pt_module_name}]: Allgemeiner Fehler (Typ: {type(e_gen_imp_pt).__name__}) beim Import von C++ Modul/Flag für PhysicalTool: {e_gen_imp_pt}")
    print(f"  [{_pt_module_name}]: C++ Beschleunigung wird für dieses Modul DEAKTIVIERT.")
    pkg_scatter_accel = None # Sicherstellen
    NATIVE_MODULE_AVAILABLE = False # Sicherstellen

# --- (Rest der Datei physical_layout_tool.py bleibt unverändert) ---

# Helper function to get or create collection
def get_or_create_collection_phy(collection_name, context, parent_collection_obj=None): 
    if not collection_name:
        return None
    if collection_name in bpy.data.collections:
        return bpy.data.collections[collection_name]
    else:
        active_scene = context.scene 
        
        parent_to_use = parent_collection_obj if parent_collection_obj else active_scene.collection
        
        if not parent_to_use:
             print(f"PT_UTIL Error: No valid parent collection for '{collection_name}' in scene '{active_scene.name}'")
             return None
        try:
            new_collection = bpy.data.collections.new(name=collection_name)
            parent_to_use.children.link(new_collection)
            return new_collection
        except Exception as e:
            print(f"PT_UTIL Error: Could not create collection '{collection_name}': {e}")
            traceback.print_exc()
            return None

# --- PropertyGroup for Rigid Body Settings ---
class PhysicalToolSettings(bpy.types.PropertyGroup):
    """Stores settings for the Rigid Body utility functions."""
    mass: bpy.props.FloatProperty(
        name="Mass", 
        default=1.0, 
        min=0.001,
        description="Mass to apply when setting Active Rigid Body"
        )
    collision_shape: bpy.props.EnumProperty(
        items=[
            ('CONVEX_HULL', "Convex Hull", "Best performance, approximates shape"),
            ('MESH', "Mesh", "Most accurate, slowest, requires manifold mesh"),
            ('BOX', "Box", "Bounding box shape"),
            ('SPHERE', "Sphere", "Bounding sphere shape"),
        ],
        name="Collision Shape",
        default='CONVEX_HULL',
        description="Collision shape to use when setting Rigid Body"
    )
    collision_margin: bpy.props.FloatProperty(
        name="Margin", 
        default=0.001, 
        min=0.0, 
        subtype='DISTANCE', 
        unit='LENGTH',
        description="Collision margin around the object"
        )
    
    batch_size: bpy.props.IntProperty(
        name="Batch Size",
        description="Number of objects to process per step in modal operations",
        default=5, 
        min=1
    )
    timer_interval: bpy.props.FloatProperty(
        name="Timer Interval",
        description="Delay between processing batches in modal operations (seconds)",
        default=0.01, 
        min=0.001,
        subtype='TIME',
        unit='TIME'
    )

# --- Base Modal Operator for Rigid Body Operations ---
class OBJECT_OT_rigidbody_modal_base(bpy.types.Operator):
    bl_options = {'REGISTER', 'UNDO'} 

    _timer = None
    _objects_to_process_names = []
    _current_object_index = 0
    _processed_in_batch = 0 
    
    _initial_selected_names = set()
    _initial_active_name = None
    
    _phys_settings_ref = None 
    _im_settings_ref = None   

    def process_single_object(self, context, obj):
        raise NotImplementedError("Subclasses must implement process_single_object.")

    @classmethod
    def poll(cls, context):
        return any(obj and obj.type == 'MESH' for obj in context.selected_objects)

    def invoke(self, context, event):
        self._objects_to_process_names = [obj.name for obj in context.selected_objects if obj and obj.type == 'MESH']
        if not self._objects_to_process_names:
            self.report({'WARNING'}, "No mesh objects selected.")
            return {'CANCELLED'}

        self._initial_selected_names = {obj.name for obj in context.selected_objects if obj}
        self._initial_active_name = context.view_layer.objects.active.name if context.view_layer.objects.active else None
        
        self._current_object_index = 0
        self._processed_in_batch = 0

        active_scene = context.scene
        self._phys_settings_ref = getattr(active_scene, 'physical_tool_settings', None)
        self._im_settings_ref = getattr(active_scene, 'instance_manager_settings', None)

        if not self._phys_settings_ref: 
            self.report({'ERROR'}, "PhysicalToolSettings nicht gefunden.")
            return {'CANCELLED'}

        wm = context.window_manager
        self._timer = wm.event_timer_add(self._phys_settings_ref.timer_interval, window=context.window)
        wm.modal_handler_add(self)
        context.window.cursor_modal_set('WAIT')
        self.report({'INFO'}, f"Starting: {self.bl_label} for {len(self._objects_to_process_names)} objects.")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.report({'INFO'}, f"{self.bl_label} cancelled by user.")
            return self._finish_modal(context, cancelled=True)

        if event.type == 'TIMER':
            if self._current_object_index >= len(self._objects_to_process_names):
                return self._finish_modal(context)

            self._processed_in_batch = 0
            batch_size = self._phys_settings_ref.batch_size if self._phys_settings_ref else 1

            for _ in range(batch_size):
                if self._current_object_index >= len(self._objects_to_process_names):
                    break 

                obj_name = self._objects_to_process_names[self._current_object_index]
                obj = bpy.data.objects.get(obj_name)

                if obj and obj.name in context.view_layer.objects: 
                    loop_original_active = context.view_layer.objects.active
                    loop_original_selected_names = {o.name for o in context.selected_objects if o}
                    
                    bpy.ops.object.select_all(action='DESELECT')
                    try:
                        obj.select_set(True)
                        context.view_layer.objects.active = obj
                        self.process_single_object(context, obj)
                    except ReferenceError:
                        self.report({'WARNING'}, f"Objekt '{obj_name}' wurde während der Verarbeitung ungültig.")
                    except RuntimeError as e:
                        self.report({'WARNING'}, f"Laufzeitfehler bei der Verarbeitung von '{obj_name}': {e}")
                        traceback.print_exc()
                    except Exception as e_gen:
                        self.report({'ERROR'}, f"Unerwarteter Fehler bei Verarbeitung von '{obj_name}': {e_gen}")
                        traceback.print_exc()
                    finally:
                        bpy.ops.object.select_all(action='DESELECT')
                        for name_sel in loop_original_selected_names:
                            obj_sel_loop = bpy.data.objects.get(name_sel)
                            if obj_sel_loop and obj_sel_loop.name in context.view_layer.objects:
                                try: obj_sel_loop.select_set(True)
                                except ReferenceError: pass
                        if loop_original_active and loop_original_active.name in context.view_layer.objects:
                            try: context.view_layer.objects.active = loop_original_active
                            except ReferenceError: pass
                        elif loop_original_selected_names: # Fallback if original active is gone
                            first_sel_name = next(iter(loop_original_selected_names), None)
                            if first_sel_name:
                                first_sel_obj = bpy.data.objects.get(first_sel_name)
                                if first_sel_obj and first_sel_obj.name in context.view_layer.objects:
                                    try: context.view_layer.objects.active = first_sel_obj
                                    except ReferenceError: pass

                else:
                    self.report({'WARNING'}, f"Object '{obj_name}' not found or invalid, skipping.")
                
                self._current_object_index += 1
                self._processed_in_batch += 1
            
            if self._processed_in_batch > 0:
                 self.report({'INFO'}, f"Processed {self._current_object_index}/{len(self._objects_to_process_names)}...")
        return {'RUNNING_MODAL'}

    def _finish_modal(self, context, cancelled=False):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window.cursor_modal_restore()
        bpy.ops.object.select_all(action='DESELECT')
        for name in self._initial_selected_names:
            obj_to_reselect = bpy.data.objects.get(name)
            if obj_to_reselect and obj_to_reselect.name in context.view_layer.objects:
                try: obj_to_reselect.select_set(True)
                except ReferenceError: pass
        initial_active_obj = bpy.data.objects.get(self._initial_active_name) if self._initial_active_name else None
        if initial_active_obj and initial_active_obj.name in context.view_layer.objects:
            try: context.view_layer.objects.active = initial_active_obj
            except ReferenceError: pass
        elif self._initial_selected_names: 
            first_selected_name = next(iter(self._initial_selected_names), None)
            if first_selected_name:
                first_selected_obj = bpy.data.objects.get(first_selected_name)
                if first_selected_obj and first_selected_obj.name in context.view_layer.objects:
                    try: context.view_layer.objects.active = first_selected_obj
                    except ReferenceError: pass
        if context.area: 
            try: context.area.tag_redraw()
            except ReferenceError: pass 
        if cancelled: self.report({'INFO'}, f"{self.bl_label} cancelled.")
        else: self.report({'INFO'}, f"{self.bl_label} complete for {len(self._objects_to_process_names)} objects.")
        return {'FINISHED'} if not cancelled else {'CANCELLED'}


# --- Modal Operator to Set ACTIVE Rigid Body ---
class OBJECT_OT_set_active_rigid_body_modal(OBJECT_OT_rigidbody_modal_base):
    bl_idname = "object.set_active_rigid_body_modal"
    bl_label = "Set Active Rigid Body (Modal)"

    def process_single_object(self, context, obj):
        is_unprepared_managed_instance = False
        obj_data_users = 0
        if obj.data:
            obj_data_users = obj.data.users
        
        if self._im_settings_ref and self._im_settings_ref.instance_collection_name:
            instance_collection = bpy.data.collections.get(self._im_settings_ref.instance_collection_name)
            if instance_collection and obj.name in instance_collection.objects:
                if obj.data and obj_data_users > 1:
                    is_unprepared_managed_instance = True
        
        if is_unprepared_managed_instance:
            self.report({'DEBUG'}, f"Instanz '{obj.name}' wird für Physik vorbereitet (Make Single User)...")
            try:
                current_matrix = obj.matrix_world.copy() 
                bpy.ops.object.make_single_user(object=True, obdata=True, animation=False, obdata_animation=False)
                obj.matrix_world = current_matrix 
                context.view_layer.update() 
                obj_data_users_after = obj.data.users if obj.data else -1 
                if obj_data_users_after > 1: 
                     self.report({'WARNING'}, f"Vorbereitung (Make Single User) von '{obj.name}' fehlgeschlagen, Daten immer noch geteilt.")
                     return 
                else:
                    self.report({'DEBUG'}, f"'{obj.name}' erfolgreich zu Single User gemacht.")
            except RuntimeError as e_prep:
                self.report({'WARNING'}, f"Konnte Instanz '{obj.name}' nicht zu Single User machen: {e_prep}.")
                traceback.print_exc()
                return 
            except Exception as e_generic_prep: 
                self.report({'ERROR'}, f"Generischer Fehler bei Vorbereitung von '{obj.name}': {e_generic_prep}")
                traceback.print_exc()
                return

        if not obj.rigid_body: 
            try: 
                bpy.ops.rigidbody.object_add()
            except RuntimeError as e_add_rb:
                self.report({'WARNING'}, f"Konnte Rigid Body zu '{obj.name}' nicht hinzufügen: {e_add_rb}")
                traceback.print_exc()
                return 
        
        if obj.rigid_body: 
            rb = obj.rigid_body
            rb.type = 'ACTIVE'
            rb.mass = self._phys_settings_ref.mass
            rb.collision_shape = self._phys_settings_ref.collision_shape
            rb.use_margin = True
            rb.collision_margin = self._phys_settings_ref.collision_margin
            rb.linear_damping = 0.04
            rb.angular_damping = 0.1
            rb.use_deactivation = True
            rb.use_start_deactivated = False
            context.view_layer.update()
            self.report({'DEBUG'}, f"Rigid Body für '{obj.name}' als ACTIVE konfiguriert.")

# --- Modal Operator to Set PASSIVE Rigid Body ---
class OBJECT_OT_set_passive_rigid_body_modal(OBJECT_OT_rigidbody_modal_base):
    bl_idname = "object.set_passive_rigid_body_modal"
    bl_label = "Set Passive Rigid Body (Modal)"

    def process_single_object(self, context, obj):
        is_unprepared_managed_instance = False
        if self._im_settings_ref and self._im_settings_ref.instance_collection_name:
            instance_collection = bpy.data.collections.get(self._im_settings_ref.instance_collection_name)
            if instance_collection and obj.name in instance_collection.objects and \
               obj.data and obj.data.users > 1:
                is_unprepared_managed_instance = True
        
        if is_unprepared_managed_instance:
            self.report({'DEBUG'}, f"Instanz '{obj.name}' wird für Physik vorbereitet (Make Single User)...")
            try:
                current_matrix = obj.matrix_world.copy()
                bpy.ops.object.make_single_user(object=True, obdata=True, animation=False, obdata_animation=False)
                obj.matrix_world = current_matrix
                context.view_layer.update()
                if obj.data.users > 1:
                     self.report({'WARNING'}, f"Vorbereitung (Make Single User) von '{obj.name}' fehlgeschlagen.")
                     return 
                else:
                    self.report({'DEBUG'}, f"'{obj.name}' erfolgreich zu Single User gemacht.")
            except RuntimeError as e_prep:
                self.report({'WARNING'}, f"Konnte Instanz '{obj.name}' nicht zu Single User machen: {e_prep}.")
                traceback.print_exc()
                return
            except Exception as e_generic_prep:
                self.report({'ERROR'}, f"Generischer Fehler bei Vorbereitung von '{obj.name}': {e_generic_prep}")
                traceback.print_exc()
                return

        if not obj.rigid_body:
            try: bpy.ops.rigidbody.object_add()
            except RuntimeError as e_add_rb:
                self.report({'WARNING'}, f"Konnte RB zu '{obj.name}' nicht hinzufügen: {e_add_rb}")
                traceback.print_exc()
                return
        
        if obj.rigid_body:
            rb = obj.rigid_body
            rb.type = 'PASSIVE'
            rb.collision_shape = self._phys_settings_ref.collision_shape
            rb.use_margin = True
            rb.collision_margin = self._phys_settings_ref.collision_margin
            context.view_layer.update()
            self.report({'DEBUG'}, f"Rigid Body für '{obj.name}' als PASSIVE konfiguriert.")

# --- Modal Operator to REMOVE Rigid Body ---
class OBJECT_OT_remove_rigid_body_modal(OBJECT_OT_rigidbody_modal_base):
    bl_idname = "object.remove_rigid_body_modal"
    bl_label = "Remove Rigid Body (Modal)"

    def process_single_object(self, context, obj):
        if obj.rigid_body:
            try:
                bpy.ops.rigidbody.object_remove()
                context.view_layer.update()
                self.report({'DEBUG'}, f"Rigid Body von '{obj.name}' entfernt.")
            except RuntimeError as e_rem_rb:
                self.report({'WARNING'}, f"Konnte Rigid Body von '{obj.name}' nicht entfernen: {e_rem_rb}")
                traceback.print_exc()

# --- Utility Operators ---
class OBJECT_OT_bake_visual_transform(bpy.types.Operator):
    bl_idname = "object.physical_tool_bake_visual_transform" 
    bl_label = "Bake Visual Transform"
    bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        if not context.selected_objects: return False
        im_settings = getattr(context.scene, 'instance_manager_settings', None)
        instance_collection = None
        if im_settings and hasattr(im_settings, 'instance_collection_name') and im_settings.instance_collection_name:
            instance_collection = bpy.data.collections.get(im_settings.instance_collection_name)
        for obj in context.selected_objects:
            if obj and obj.type == 'MESH':
                is_unprepared_instance = False
                if instance_collection and obj.name in instance_collection.objects and \
                   obj.data and obj.data.users > 1: 
                    is_unprepared_instance = True
                if not is_unprepared_instance: return True
        return False
    def execute(self, context):
        original_active = context.view_layer.objects.active
        original_selected_names = {obj.name for obj in context.selected_objects if obj}
        im_settings = getattr(context.scene, 'instance_manager_settings', None)
        instance_collection = None
        if im_settings and hasattr(im_settings, 'instance_collection_name') and im_settings.instance_collection_name:
            instance_collection = bpy.data.collections.get(im_settings.instance_collection_name)
        processed_count = 0
        for obj_name in original_selected_names:
            obj = bpy.data.objects.get(obj_name)
            if not obj or obj.type != 'MESH': continue
            is_unprepared_instance = False
            if instance_collection and obj.name in instance_collection.objects and \
               obj.data and obj.data.users > 1: is_unprepared_instance = True
            if is_unprepared_instance: self.report({'INFO'}, f"'{obj.name}' ist eine unvorbereitete Instanz. Bake Visual Transform übersprungen."); continue
            
            current_loop_active = context.view_layer.objects.active 
            current_loop_selected_names = {o.name for o in context.selected_objects if o}
            bpy.ops.object.select_all(action='DESELECT')
            try:
                obj.select_set(True); context.view_layer.objects.active = obj
                bpy.ops.object.visual_transform_apply(); processed_count += 1
            except ReferenceError: self.report({'WARNING'}, f"Objekt '{obj_name}' wurde während Bake Visual Transform ungültig.")
            except Exception as e: 
                self.report({'WARNING'}, f"Fehler beim Anwenden des visuellen Transforms auf '{obj.name}': {e}")
                traceback.print_exc()
            finally:
                bpy.ops.object.select_all(action='DESELECT')
                for name_sel in current_loop_selected_names:
                    obj_sel_loop = bpy.data.objects.get(name_sel)
                    if obj_sel_loop and obj_sel_loop.name in context.view_layer.objects:
                        try: obj_sel_loop.select_set(True)
                        except ReferenceError: pass
                if current_loop_active and current_loop_active.name in context.view_layer.objects:
                    try: context.view_layer.objects.active = current_loop_active
                    except ReferenceError: pass
                elif current_loop_selected_names:
                    first_sel_name = next(iter(current_loop_selected_names), None)
                    if first_sel_name:
                        first_sel_obj = bpy.data.objects.get(first_sel_name)
                        if first_sel_obj and first_sel_obj.name in context.view_layer.objects:
                            try: context.view_layer.objects.active = first_sel_obj
                            except ReferenceError: pass
                            
        bpy.ops.object.select_all(action='DESELECT')
        for name in original_selected_names:
            obj_to_reselect = bpy.data.objects.get(name)
            if obj_to_reselect and obj_to_reselect.name in context.view_layer.objects:
                try: obj_to_reselect.select_set(True)
                except ReferenceError: pass
        if original_active and original_active.name in context.view_layer.objects:
            try: context.view_layer.objects.active = original_active
            except ReferenceError: pass
        elif context.selected_objects:
            try: context.view_layer.objects.active = context.selected_objects[0]
            except (IndexError, ReferenceError) : pass

        if processed_count == 0 and any(bpy.data.objects.get(name) for name in original_selected_names):
            self.report({'INFO'}, "Keine geeigneten Objekte für Bake Visual Transform ausgewählt oder Fehler bei allen.")
        elif processed_count > 0:
            self.report({'INFO'}, f"Visueller Transform auf {processed_count} Objekt(e) angewendet.")
        return {'FINISHED'}

# === MODIFIED: OBJECT_OT_bake_to_static ===
class OBJECT_OT_bake_to_static(bpy.types.Operator): 
    bl_idname = "object.physical_tool_bake_to_static"
    bl_label = "Bake Selected to Static"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(obj and obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        active_scene = context.scene
        im_settings = getattr(active_scene, 'instance_manager_settings', None)
        
        if not im_settings or not hasattr(im_settings, 'static_collection_name') or not im_settings.static_collection_name:
            self.report({'ERROR'}, "Instance Manager Settings oder Static Collection Name nicht definiert.")
            return {'CANCELLED'}

        static_collection_target_name = im_settings.static_collection_name
        static_collection_obj = get_or_create_collection_phy(static_collection_target_name, context, parent_collection_obj=active_scene.collection) 
        
        if not static_collection_obj:
            self.report({'ERROR'}, f"Static Collection '{static_collection_target_name}' konnte nicht gefunden oder erstellt werden.")
            return {'CANCELLED'}

        original_active = context.view_layer.objects.active
        selected_mesh_objects = [obj for obj in context.selected_objects if obj and obj.type == 'MESH']
        
        if not selected_mesh_objects:
            self.report({'INFO'}, "Keine Mesh-Objekte zum Baken ausgewählt.")
            return {'FINISHED'}

        original_selected_names = {obj.name for obj in selected_mesh_objects}

        processed_count = 0
        failed_count = 0
        
        if NATIVE_MODULE_AVAILABLE and pkg_scatter_accel and hasattr(pkg_scatter_accel, 'analyze_objects_for_static_bake'):
            self.report({'INFO'}, "Verwende C++ Analyse für Bake to Static...")
            object_names_for_cpp = [obj.name for obj in selected_mesh_objects]

            try:
                instructions_from_cpp = pkg_scatter_accel.analyze_objects_for_static_bake(object_names_for_cpp, static_collection_target_name)
            except Exception as e_cpp_analyze:
                self.report({'ERROR'}, f"Fehler bei C++ Analyse für Bake to Static: {e_cpp_analyze}. Fallback auf Python.")
                traceback.print_exc()
                instructions_from_cpp = None 
            
            if instructions_from_cpp is not None:
                for instruction in instructions_from_cpp:
                    obj_name = instruction.get("name")
                    obj = bpy.data.objects.get(obj_name)

                    if not obj:
                        self.report({'WARNING'}, f"Objekt '{obj_name}' aus C++ Instruktion nicht gefunden. Übersprungen.")
                        failed_count += 1
                        continue
                    
                    loop_original_active = context.view_layer.objects.active
                    loop_original_selected_names = {o.name for o in context.selected_objects if o}
                    
                    bpy.ops.object.select_all(action='DESELECT')
                    try:
                        obj.select_set(True)
                        context.view_layer.objects.active = obj

                        bpy.ops.object.visual_transform_apply()

                        if instruction.get("has_rigidbody", False) and obj.rigid_body:
                            bpy.ops.rigidbody.object_remove()
                        
                        if instruction.get("needs_make_single_user", False) and obj.data and obj.data.users > 1:
                            current_matrix_for_sud = obj.matrix_world.copy()
                            bpy.ops.object.make_single_user(object=True, obdata=True, animation=False, obdata_animation=False)
                            obj.matrix_world = current_matrix_for_sud
                        
                        # Collection Management
                        current_collections_on_obj_names_cpp = instruction.get("current_collections", [])
                        for col_name_from_cpp in current_collections_on_obj_names_cpp:
                            if col_name_from_cpp == static_collection_target_name:
                                continue # Nicht von der Zielcollection entfernen
                            col_to_unlink = bpy.data.collections.get(col_name_from_cpp)
                            if col_to_unlink and obj.name in col_to_unlink.objects:
                                try:
                                    col_to_unlink.objects.unlink(obj)
                                except RuntimeError as e_unlink_cpp:
                                    self.report({'DEBUG'}, f"Fehler beim Unlinken (C++ path) von '{obj_name}' aus '{col_name_from_cpp}': {e_unlink_cpp} (ggf. schon weg)")
                        
                        # Fallback, falls C++ keine Collections lieferte oder als zusätzliche Sicherheit
                        if not current_collections_on_obj_names_cpp:
                             for col_obj_iter_py_fallback in list(obj.users_collection):
                                if col_obj_iter_py_fallback.name != static_collection_target_name:
                                    try: col_obj_iter_py_fallback.objects.unlink(obj)
                                    except RuntimeError: pass


                        if obj.name not in static_collection_obj.objects:
                            try:
                                static_collection_obj.objects.link(obj)
                            except RuntimeError as e_link_cpp:
                                 self.report({'WARNING'}, f"Konnte '{obj.name}' nicht mit Collection '{static_collection_obj.name}' verlinken (C++ path): {e_link_cpp}")
                                 traceback.print_exc()
                                 failed_count += 1
                                 continue 
                        
                        processed_count += 1

                    except ReferenceError:
                        self.report({'WARNING'}, f"Objekt '{obj_name}' wurde während Bake to Static (C++ path) ungültig.")
                        failed_count += 1
                    except RuntimeError as e_rt_ops_cpp:
                        self.report({'WARNING'}, f"Laufzeitfehler bei bpy.ops für '{obj_name}' (C++ path): {e_rt_ops_cpp}")
                        traceback.print_exc()
                        failed_count +=1
                    except Exception as e_cpp_loop:
                        self.report({'WARNING'}, f"Allgemeiner Fehler bei Bake to Static für '{obj_name}' (C++ path): {e_cpp_loop}")
                        traceback.print_exc()
                        failed_count += 1
                    finally:
                        bpy.ops.object.select_all(action='DESELECT')
                        for name_sel_loop_cpp in loop_original_selected_names:
                            obj_sel_loop_restore_cpp = bpy.data.objects.get(name_sel_loop_cpp)
                            if obj_sel_loop_restore_cpp and obj_sel_loop_restore_cpp.name in context.view_layer.objects:
                                try: obj_sel_loop_restore_cpp.select_set(True)
                                except ReferenceError: pass
                        if loop_original_active and loop_original_active.name in context.view_layer.objects:
                            try: context.view_layer.objects.active = loop_original_active
                            except ReferenceError: pass
                        elif loop_original_selected_names:
                            first_sel_name = next(iter(loop_original_selected_names), None)
                            if first_sel_name:
                                first_sel_obj = bpy.data.objects.get(first_sel_name)
                                if first_sel_obj and first_sel_obj.name in context.view_layer.objects:
                                    try: context.view_layer.objects.active = first_sel_obj
                                    except ReferenceError: pass
                
                # Selektion am Ende des C++ Pfades wiederherstellen
                bpy.ops.object.select_all(action='DESELECT')
                for name in original_selected_names:
                    obj_to_reselect = bpy.data.objects.get(name)
                    if obj_to_reselect and obj_to_reselect.name in context.view_layer.objects:
                        try: obj_to_reselect.select_set(True)
                        except ReferenceError: pass
                if original_active and original_active.name in context.view_layer.objects:
                    try: context.view_layer.objects.active = original_active
                    except ReferenceError: pass
                elif context.selected_objects:
                     try: context.view_layer.objects.active = context.selected_objects[0]
                     except (IndexError, ReferenceError): pass

                if processed_count > 0: self.report({'INFO'}, f"{processed_count} Objekt(e) zu Static gebacken (C++-Pfad).")
                if failed_count > 0: self.report({'WARNING'}, f"{failed_count} Objekt(e) nicht gebacken (C++-Pfad).")
                if processed_count == 0 and failed_count == 0 and original_selected_names: self.report({'INFO'}, "Keine Objekte gebacken (C++-Pfad, ggf. waren alle konform).")
                return {'FINISHED'}

        # === PYTHON FALLBACK PATH ===
        self.report({'INFO'}, "Verwende reine Python-Logik für Bake to Static (Fallback).")
        for obj_name in original_selected_names: 
            obj = bpy.data.objects.get(obj_name)
            if not obj: continue 

            loop_original_active = context.view_layer.objects.active
            loop_original_selected_names = {o.name for o in context.selected_objects if o}
            original_obj_collections_py_path = [] # Für Rollback im Fehlerfall
            
            bpy.ops.object.select_all(action='DESELECT')
            try:
                obj.select_set(True); context.view_layer.objects.active = obj
                original_obj_collections_py_path = [col for col in obj.users_collection] 
                
                bpy.ops.object.visual_transform_apply()
                if obj.rigid_body: bpy.ops.rigidbody.object_remove()
                if obj.data and obj.data.users > 1: 
                    current_matrix_for_sud = obj.matrix_world.copy()
                    bpy.ops.object.make_single_user(object=True, obdata=True, animation=False, obdata_animation=False)
                    obj.matrix_world = current_matrix_for_sud
                
                for col_obj_iter_py in list(obj.users_collection): 
                    if col_obj_iter_py.name != static_collection_target_name:
                        try: col_obj_iter_py.objects.unlink(obj)
                        except RuntimeError: pass 
                
                if obj.name not in static_collection_obj.objects: 
                    try: static_collection_obj.objects.link(obj)
                    except RuntimeError as e_link_py:
                        self.report({'WARNING'}, f"Konnte '{obj.name}' nicht mit Collection '{static_collection_obj.name}' verlinken (Python path): {e_link_py}")
                        traceback.print_exc()
                        failed_count += 1
                        continue
                
                processed_count += 1
            except ReferenceError:
                self.report({'WARNING'}, f"Objekt '{obj_name}' wurde während Bake to Static (Python path) ungültig.")
                failed_count += 1
                if obj and obj.name in bpy.data.objects and obj.name not in static_collection_obj.objects:
                    for col_orig in original_obj_collections_py_path:
                        if col_orig.name != static_collection_target_name and obj.name not in col_orig.objects:
                           try: col_orig.objects.link(obj)
                           except: pass
            except RuntimeError as e_rt_ops_py:
                self.report({'WARNING'}, f"Laufzeitfehler bei bpy.ops für '{obj_name}' (Python path): {e_rt_ops_py}")
                traceback.print_exc()
                failed_count +=1
            except Exception as e_py:
                self.report({'WARNING'}, f"Fehler bei Bake to Static für '{obj.name}' (Python path): {e_py}")
                traceback.print_exc()
                failed_count += 1
                if obj and obj.name in bpy.data.objects and obj.name not in static_collection_obj.objects: 
                    for col_orig in original_obj_collections_py_path:
                        if col_orig.name != static_collection_target_name and obj.name not in col_orig.objects:
                           try: col_orig.objects.link(obj)
                           except: pass
            finally:
                bpy.ops.object.select_all(action='DESELECT')
                for name_sel_loop_py in loop_original_selected_names:
                    obj_sel_loop_restore_py = bpy.data.objects.get(name_sel_loop_py)
                    if obj_sel_loop_restore_py and obj_sel_loop_restore_py.name in context.view_layer.objects:
                        try: obj_sel_loop_restore_py.select_set(True)
                        except ReferenceError: pass
                if loop_original_active and loop_original_active.name in context.view_layer.objects:
                    try: context.view_layer.objects.active = loop_original_active
                    except ReferenceError: pass
                elif loop_original_selected_names:
                    first_sel_name = next(iter(loop_original_selected_names), None)
                    if first_sel_name:
                        first_sel_obj = bpy.data.objects.get(first_sel_name)
                        if first_sel_obj and first_sel_obj.name in context.view_layer.objects:
                            try: context.view_layer.objects.active = first_sel_obj
                            except ReferenceError: pass

        # Finale Wiederherstellung der ursprünglichen Selektion und des aktiven Objekts
        bpy.ops.object.select_all(action='DESELECT')
        for name in original_selected_names:
            obj_to_reselect = bpy.data.objects.get(name)
            if obj_to_reselect and obj_to_reselect.name in context.view_layer.objects:
                try: obj_to_reselect.select_set(True)
                except ReferenceError: pass
        
        if original_active and original_active.name in context.view_layer.objects:
            try: context.view_layer.objects.active = original_active
            except ReferenceError: pass
        elif context.selected_objects: # Fallback, falls original_active nicht mehr gültig ist
            try: context.view_layer.objects.active = context.selected_objects[0]
            except (IndexError, ReferenceError): pass

        if processed_count > 0: self.report({'INFO'}, f"{processed_count} Objekt(e) zu Static gebacken und in '{static_collection_obj.name}' verschoben.")
        if failed_count > 0: self.report({'WARNING'}, f"{failed_count} Objekt(e) konnten nicht gebacken werden. Siehe Konsole für Details.")
        if processed_count == 0 and failed_count == 0 and original_selected_names:
             self.report({'INFO'}, "Keine Objekte zu Static gebacken (oder alle bereits konform/keine Mesh-Objekte).")
             
        return {'FINISHED'}


# --- Operator: Bake Rigidbody Simulation ---
class OBJECT_OT_bake_rigidbody_simulation(bpy.types.Operator):
    bl_idname = "object.physical_tool_bake_scene_simulation" 
    bl_label = "Bake Simulation (Scene)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        active_scene = context.scene
        im_settings = getattr(active_scene, 'instance_manager_settings', None)

        if im_settings and hasattr(im_settings, 'instance_collection_name') and im_settings.instance_collection_name:
            instance_collection = bpy.data.collections.get(im_settings.instance_collection_name)
            if instance_collection:
                instances_to_prepare_for_bake_names = [] # Store names
                for obj_name_iter in instance_collection.objects.keys(): 
                    obj_iter = bpy.data.objects.get(obj_name_iter)
                    if obj_iter and obj_iter.data and obj_iter.data.users > 1:
                        instances_to_prepare_for_bake_names.append(obj_iter.name)
                
                if instances_to_prepare_for_bake_names:
                    self.report({'INFO'}, f"Bereite {len(instances_to_prepare_for_bake_names)} Instanz(en) für Physik-Bake vor...")
                    original_active_before_prep = context.view_layer.objects.active
                    original_selected_names_before_prep = {o.name for o in context.selected_objects if o}
                    
                    bpy.ops.object.select_all(action='DESELECT')
                    for obj_prep_name in instances_to_prepare_for_bake_names:
                        obj_to_prep = bpy.data.objects.get(obj_prep_name)
                        if obj_to_prep and obj_to_prep.name in context.view_layer.objects: 
                           try: obj_to_prep.select_set(True)
                           except ReferenceError: pass 
                    
                    selected_for_prep_count = sum(1 for name in instances_to_prepare_for_bake_names if bpy.data.objects.get(name) and bpy.data.objects.get(name).select_get())
                    
                    prepare_op_available = hasattr(bpy.ops.object, 'prepare_managed_instances_modal') or \
                                           hasattr(bpy.ops.object, 'prepare_managed_instances')
                    
                    if selected_for_prep_count > 0 and prepare_op_available:
                        try:
                            if hasattr(bpy.ops.object, 'prepare_managed_instances_modal'):
                                bpy.ops.object.prepare_managed_instances_modal('INVOKE_DEFAULT') 
                                self.report({'INFO'}, "Instanz-Vorbereitung (modal) für Bake gestartet. Bake muss danach manuell erneut gestartet werden.")
                                # Modal operator will take over, so we return early
                                return {'CANCELLED'} # Or {'FINISHED'} if modal handles its own finish
                            elif hasattr(bpy.ops.object, 'prepare_managed_instances'):
                                bpy.ops.object.prepare_managed_instances('EXEC_DEFAULT')
                                self.report({'INFO'}, "Instanz-Vorbereitung (direkt) für Bake durchgeführt.")
                        except RuntimeError as e_prep_op: 
                            self.report({'ERROR'}, f"Laufzeitfehler beim Aufrufen von 'prepare_managed_instances': {e_prep_op}.")
                            traceback.print_exc()
                        except Exception as e_prep_generic: 
                            self.report({'ERROR'}, f"Unerwarteter Fehler bei der Instanz-Vorbereitung: {e_prep_generic}")
                            traceback.print_exc()
                        finally: # Restore selection after direct prep
                            if hasattr(bpy.ops.object, 'prepare_managed_instances'): #Only if direct op was called
                                bpy.ops.object.select_all(action='DESELECT')
                                for name in original_selected_names_before_prep:
                                    obj_sel = bpy.data.objects.get(name)
                                    if obj_sel and obj_sel.name in context.view_layer.objects:
                                        try: obj_sel.select_set(True)
                                        except ReferenceError: pass
                                if original_active_before_prep and original_active_before_prep.name in context.view_layer.objects:
                                    try: context.view_layer.objects.active = original_active_before_prep
                                    except ReferenceError: pass
                                elif original_selected_names_before_prep: 
                                    try: 
                                        first_orig_name = next(iter(original_selected_names_before_prep), None)
                                        if first_orig_name:
                                            first_orig_sel = bpy.data.objects.get(first_orig_name)
                                            if first_orig_sel and first_orig_sel.name in context.view_layer.objects: context.view_layer.objects.active = first_orig_sel
                                    except Exception: pass 
                    elif not prepare_op_available and selected_for_prep_count > 0:
                         self.report({'ERROR'}, "'prepare_managed_instances' Operator nicht gefunden! Instanzen nicht vorbereitet.")
        try:
            self.report({'INFO'}, "Starte Szene-Bake (bpy.ops.ptcache.bake_all)...")
            bpy.ops.ptcache.bake_all(bake=True)
            self.report({'INFO'}, "Szene-Bake abgeschlossen.")
        except Exception as e_bake_all: 
            self.report({'ERROR'}, f"Fehler beim Baken der Szene: {e_bake_all}"); 
            traceback.print_exc()
            return {'CANCELLED'}
        return {'FINISHED'}

# --- Operator: Clear Selected Rigid Body Cache ---
class OBJECT_OT_clear_selected_rigidbody_cache(bpy.types.Operator):
    bl_idname = "object.physical_tool_clear_cache" 
    bl_label = "Clear Selected Cache"
    bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context): 
        return any(obj and obj.type == 'MESH' and obj.rigid_body for obj in context.selected_objects)

    def execute(self, context):
        processed_count = 0
        original_active = context.view_layer.objects.active
        original_selected_names = {obj.name for obj in context.selected_objects if obj}
        
        view3d_area = context.area if context.area and context.area.type == 'VIEW_3D' else None
        if not view3d_area:
            for window in context.window_manager.windows:
                for area_iter in window.screen.areas:
                    if area_iter.type == 'VIEW_3D': view3d_area = area_iter; break
                if view3d_area: break
        
        if not view3d_area: 
            self.report({'ERROR'}, "Kein 3D-Viewport gefunden für Cache-Operation."); 
            return {'CANCELLED'}

        for obj_name in original_selected_names:
            obj = bpy.data.objects.get(obj_name)
            if not obj or obj.type != 'MESH' or not obj.rigid_body: continue
            
            loop_original_active = context.view_layer.objects.active
            loop_original_selected_names = {o.name for o in context.selected_objects if o}
            bpy.ops.object.select_all(action='DESELECT')
            try:
                obj.select_set(True)
                context.view_layer.objects.active = obj
                
                override_context = context.copy()
                override_context['area'] = view3d_area
                override_context['region'] = next((r for r in view3d_area.regions if r.type == 'WINDOW'), 
                                                  view3d_area.regions[0] if view3d_area.regions else None)
                
                if override_context['region'] is None: 
                    self.report({'WARNING'}, f"Keine passende Region für Cache-Operation bei '{obj.name}'.")
                    continue # Skip this object
                
                # This explicit override for selected/active might not always be necessary
                # if the main context selection is already correct, but can be safer.
                override_context['active_object'] = obj
                override_context['object'] = obj
                override_context['selected_objects'] = [obj]
                override_context['selected_editable_objects'] = [obj]

                try:
                    with context.temp_override(**override_context): 
                        bpy.ops.ptcache.free_bake() 
                    processed_count += 1
                    self.report({'DEBUG'}, f"Cache für '{obj.name}' gelöscht.")
                except Exception as e_cache: 
                    self.report({'WARNING'}, f"Konnte Cache für '{obj.name}' nicht löschen: {e_cache}")
                    traceback.print_exc()
            except ReferenceError: 
                self.report({'WARNING'}, f"Objekt '{obj_name}' wurde während Cache-Löschung ungültig.")
            except Exception as e_outer_loop:
                self.report({'ERROR'}, f"Unerwarteter Fehler bei Cache-Löschung für '{obj_name}': {e_outer_loop}")
                traceback.print_exc()
            finally: 
                bpy.ops.object.select_all(action='DESELECT')
                for name_sel in loop_original_selected_names:
                    obj_sel_loop = bpy.data.objects.get(name_sel)
                    if obj_sel_loop and obj_sel_loop.name in context.view_layer.objects:
                        try: obj_sel_loop.select_set(True)
                        except ReferenceError: pass
                if loop_original_active and loop_original_active.name in context.view_layer.objects:
                    try: context.view_layer.objects.active = loop_original_active
                    except ReferenceError: pass
                elif loop_original_selected_names:
                    first_sel_name = next(iter(loop_original_selected_names), None)
                    if first_sel_name:
                        first_sel_obj = bpy.data.objects.get(first_sel_name)
                        if first_sel_obj and first_sel_obj.name in context.view_layer.objects:
                            try: context.view_layer.objects.active = first_sel_obj
                            except ReferenceError: pass

        bpy.ops.object.select_all(action='DESELECT')
        for name in original_selected_names:
            obj_to_reselect = bpy.data.objects.get(name)
            if obj_to_reselect and obj_to_reselect.name in context.view_layer.objects:
                try: obj_to_reselect.select_set(True)
                except ReferenceError: pass
        if original_active and original_active.name in context.view_layer.objects:
            try: context.view_layer.objects.active = original_active
            except ReferenceError: pass
        elif context.selected_objects:
            try: context.view_layer.objects.active = context.selected_objects[0]
            except (IndexError, ReferenceError): pass

        if processed_count > 0: self.report({'INFO'}, f"Cache für {processed_count} Objekt(e) versucht zu löschen.")
        elif any(bpy.data.objects.get(name) for name in original_selected_names): self.report({'INFO'}, "Keine geeigneten Objekte zum Cache löschen ausgewählt.")
        return {'FINISHED'}

# --- Operator: Reset Addon Collections ---
class OBJECT_OT_reset_addon_collections(bpy.types.Operator):
    bl_idname = "object.physical_tool_reset_collections"
    bl_label = "Reset Addon Collections"
    bl_description = "Moves objects from addon-specific collections to scene root, deletes these collections, then recreates default addon collections. USE WITH CAUTION."
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=[('MOVE_OBJECTS', "Collections leeren (Objekte verschieben)", "Verschiebt Objekte in die Haupt-Szenensammlung, bevor Addon-Collections gelöscht werden.")],
        default='MOVE_OBJECTS',
        description="Wie mit Objekten in den Addon-Collections verfahren werden soll."
    )
    @classmethod
    def poll(cls, context): return True
    def invoke(self, context, event): return context.window_manager.invoke_props_dialog(self, width=400)
    def draw(self, context):
        layout = self.layout
        layout.label(text="Dieser Vorgang bereinigt die vom Addon verwalteten Collections.")
        layout.label(text="Objekte werden in die Haupt-Szenensammlung verschoben.")
        layout.prop(self, "mode", text="Aktion")
        layout.label(text="Sind Sie sicher, dass Sie fortfahren möchten?", icon='ERROR')
    def execute(self, context):
        im_settings = getattr(context.scene, 'instance_manager_settings', None)
        if not im_settings: self.report({'ERROR'}, "InstanceManagerSettings nicht gefunden. Abbruch."); return {'CANCELLED'}
        
        collections_to_delete_names = set()
        if im_settings.instance_collection_name: collections_to_delete_names.add(im_settings.instance_collection_name)
        if im_settings.static_collection_name: collections_to_delete_names.add(im_settings.static_collection_name)
        
        scatter_source_library_name = "ScatterTool_SourceLibrary" # Hardcoded for now
        collections_to_delete_names.add(scatter_source_library_name)

        session_basename_from_im = im_settings.source_collection_basename
        if session_basename_from_im and not session_basename_from_im.endswith("_"): session_basename_from_im += "_"
        
        if session_basename_from_im: # Only search if basename is defined
            for coll in bpy.data.collections:
                if coll.name.startswith(session_basename_from_im):
                    collections_to_delete_names.add(coll.name)

        self.report({'INFO'}, f"Zu löschende Collections identifiziert: {collections_to_delete_names}")
        scene_collection = context.scene.collection
        collections_actually_deleted_names = []

        for coll_name in list(collections_to_delete_names): 
            coll_to_process = bpy.data.collections.get(coll_name)
            if not coll_to_process: continue
            if self.mode == 'MOVE_OBJECTS':
                objects_in_coll_to_move_safely = list(coll_to_process.objects) 
                for obj in objects_in_coll_to_move_safely:
                    if not obj: continue
                    
                    # Sicherstellen, dass das Objekt zuerst mit der Haupt-Szenensammlung verlinkt ist
                    if obj.name not in scene_collection.objects:
                        try:
                            scene_collection.objects.link(obj)
                            self.report({'DEBUG'}, f"Objekt '{obj.name}' erfolgreich mit '{scene_collection.name}' verlinkt.")
                        except RuntimeError as e_link:
                            self.report({'WARNING'}, f"Konnte Objekt '{obj.name}' nicht mit '{scene_collection.name}' verlinken: {e_link}. Überspringe Unlink von '{coll_name}'.")
                            traceback.print_exc()
                            continue 
                    
                    # Dann von der Addon-Collection entlinken
                    if obj.name in coll_to_process.objects:
                        try: 
                            coll_to_process.objects.unlink(obj)
                            self.report({'DEBUG'}, f"Objekt '{obj.name}' von '{coll_name}' entlinkt.")
                        except RuntimeError as e_unlink: 
                            self.report({'WARNING'}, f"Konnte Objekt '{obj.name}' nicht von Addon-Collection '{coll_name}' entlinken: {e_unlink}")
                            traceback.print_exc()
            try:
                # Von allen Eltern-Collections entlinken (falls verschachtelt)
                parents_to_unlink_from = [p for p in bpy.data.collections if coll_to_process.name in p.children]
                for parent_col_iter in parents_to_unlink_from:
                    try:
                        parent_col_iter.children.unlink(coll_to_process)
                    except Exception as e_unlink_child:
                         self.report({'DEBUG'}, f"Fehler beim Unlinken von '{coll_name}' von Parent '{parent_col_iter.name}': {e_unlink_child}")


                bpy.data.collections.remove(coll_to_process)
                self.report({'INFO'}, f"Collection '{coll_name}' entfernt.")
                collections_actually_deleted_names.append(coll_name)
            except Exception as e_coll_rem: 
                self.report({'WARNING'}, f"Konnte Collection '{coll_name}' nicht entfernen: {e_coll_rem}")
                traceback.print_exc()
        
        # Standard-Collections neu erstellen (oder sicherstellen, dass sie existieren)
        if im_settings.instance_collection_name: 
            get_or_create_collection_phy(im_settings.instance_collection_name, context, parent_collection_obj=scene_collection)
            self.report({'INFO'}, f"Standard Instance Collection '{im_settings.instance_collection_name}' sichergestellt/erstellt.")
        if im_settings.static_collection_name: 
            get_or_create_collection_phy(im_settings.static_collection_name, context, parent_collection_obj=scene_collection)
            self.report({'INFO'}, f"Standard Static Collection '{im_settings.static_collection_name}' sichergestellt/erstellt.")
        get_or_create_collection_phy(scatter_source_library_name, context, parent_collection_obj=scene_collection) # Hardcoded name
        self.report({'INFO'}, f"Standard Scatter Source Library '{scatter_source_library_name}' sichergestellt/erstellt.")
        
        self.report({'INFO'}, f"Addon Collections Reset abgeschlossen. {len(collections_actually_deleted_names)} Collection(s) entfernt.")
        return {'FINISHED'}

# --- UI Panel ---
class VIEW3D_PT_physical_layout_tool(bpy.types.Panel):
    bl_label = "Physical Layout Tool"; bl_idname = "VIEW3D_PT_physical_layout_tool"; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'PhysicalTool'; bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout; active_scene = context.scene; phys_settings = getattr(active_scene, 'physical_tool_settings', None)
        if phys_settings: 
            box_rb_settings = layout.box(); box_rb_settings.label(text="Rigid Body Settings (für Modale Operatoren):")
            col_phys_props = box_rb_settings.column(align=True); col_phys_props.prop(phys_settings, "mass"); col_phys_props.prop(phys_settings, "collision_shape"); col_phys_props.prop(phys_settings, "collision_margin")
            box_batch_settings = layout.box(); box_batch_settings.label(text="Batch Processing (für Modale Operatoren):")
            col_batch_props = box_batch_settings.column(align=True); col_batch_props.prop(phys_settings, "batch_size"); col_batch_props.prop(phys_settings, "timer_interval")
            layout.separator()
            box_apply_rb = layout.box(); box_apply_rb.label(text="Apply Rigid Body (Modal):")
            col_apply_rb = box_apply_rb.column(align=True) 
            col_apply_rb.operator(OBJECT_OT_set_active_rigid_body_modal.bl_idname, text="Set Active (Modal)", icon='PLAY')
            col_apply_rb.operator(OBJECT_OT_set_passive_rigid_body_modal.bl_idname, text="Set Passive (Modal)", icon='PAUSE')
            col_apply_rb.operator(OBJECT_OT_remove_rigid_body_modal.bl_idname, text="Remove Rigid (Modal)", icon='X')
            layout.separator()
            box_utility = layout.box(); box_utility.label(text="Utility:")
            col_util = box_utility.column(align=True) 
            col_util.operator(OBJECT_OT_bake_visual_transform.bl_idname, text="Bake Visual Transform", icon='OBJECT_DATA')
            col_util.operator(OBJECT_OT_bake_to_static.bl_idname, text="Bake Selected to Static", icon='FREEZE') 
            col_util.operator(OBJECT_OT_bake_rigidbody_simulation.bl_idname, text="Bake Simulation (Scene)", icon='REC')
            col_util.operator(OBJECT_OT_clear_selected_rigidbody_cache.bl_idname, text="Clear Selected Cache", icon='CANCEL')
        else: layout.label(text="Physical Tool Settings nicht geladen!", icon='ERROR')
        layout.separator() 
        box_maintenance = layout.box(); box_maintenance.label(text="Wartung & Reset:")
        col_maintenance = box_maintenance.column(align=True)
        col_maintenance.operator(OBJECT_OT_reset_addon_collections.bl_idname, text="Addon Collections zurücksetzen", icon='CANCEL')

# --- Registration ---
_classes_to_register_physical_tool = (
    PhysicalToolSettings,
    #OBJECT_OT_rigidbody_modal_base, # Base class needs to be registered if it's used as a type hint or base for others
    OBJECT_OT_set_active_rigid_body_modal, OBJECT_OT_set_passive_rigid_body_modal, OBJECT_OT_remove_rigid_body_modal,
    OBJECT_OT_bake_visual_transform, OBJECT_OT_bake_to_static, OBJECT_OT_bake_rigidbody_simulation, OBJECT_OT_clear_selected_rigidbody_cache,
    OBJECT_OT_reset_addon_collections,
    VIEW3D_PT_physical_layout_tool,
)

def register():
    print("PT_REG: --- Starting Registration for physical_layout_tool ---")

    for cls in reversed(_classes_to_register_physical_tool):
        if hasattr(bpy.types, cls.__name__):
            try:
                current_bpy_type_class = getattr(bpy.types, cls.__name__)
                if hasattr(current_bpy_type_class, 'bl_rna') and current_bpy_type_class.__module__.startswith(__name__.split('.')[0]):
                    bpy.utils.unregister_class(current_bpy_type_class)
                    print(f"PT_REG: Pre-unregistered existing class: {cls.__name__}")
            except RuntimeError:
                pass 
            except Exception as e_pre_unreg:
                print(f"PT_REG: Error pre-unregistering {cls.__name__}: {e_pre_unreg}")

    if hasattr(bpy.types.Scene, 'physical_tool_settings'):
        try:
            prop_info = bpy.types.Scene.bl_rna.properties.get('physical_tool_settings')
            if not (isinstance(prop_info.fixed_type, PointerProperty) and prop_info.fixed_type.type == PhysicalToolSettings):
                 print(f"PT_REG: WARN - 'physical_tool_settings' exists on Scene but is not the correct type. Attempting to delete.")
            del bpy.types.Scene.physical_tool_settings
            print("PT_REG: Removed existing PointerProperty 'physical_tool_settings'.")
        except Exception as e_del_prop:
            print(f"PT_REG: Warning - Could not remove existing PointerProperty 'physical_tool_settings': {e_del_prop}")


    property_groups_to_register_pt = [cls for cls in _classes_to_register_physical_tool if issubclass(cls, bpy.types.PropertyGroup)]
    other_classes_to_register_pt = [cls for cls in _classes_to_register_physical_tool if not issubclass(cls, bpy.types.PropertyGroup)]

    for cls in property_groups_to_register_pt:
        print(f"PT_REG: Attempting to register PG {cls.__name__}...")
        try:
            bpy.utils.register_class(cls)
            print(f"PT_REG:   PG {cls.__name__} registered successfully.")
        except Exception as e_reg_pg:
            print(f"PT_REG:   CRITICAL - Failed to register PG {cls.__name__}: {e_reg_pg}")
            traceback.print_exc(); raise

    print("PT_REG: Attempting to set Scene.physical_tool_settings...")
    try:
        bpy.types.Scene.physical_tool_settings = PointerProperty(type=PhysicalToolSettings)
        print("PT_REG:   Scene.physical_tool_settings set successfully.")
    except Exception as e_set_prop:
        print(f"PT_REG:   ERROR setting Scene.physical_tool_settings: {e_set_prop}")
        traceback.print_exc(); raise 

    for cls in other_classes_to_register_pt:
        print(f"PT_REG: Attempting to register {cls.__name__}...")
        try:
            bpy.utils.register_class(cls)
            print(f"PT_REG:   {cls.__name__} registered successfully.")
        except Exception as e_reg_other:
            print(f"PT_REG:   CRITICAL - Failed to register {cls.__name__}: {e_reg_other}")
            traceback.print_exc()
            if not issubclass(cls, (bpy.types.UIList, bpy.types.Panel, bpy.types.Operator)):
                 raise 
            else:
                 print(f"PT_REG: WARNING - Failed to register UI/Operator class {cls.__name__}, addon might be partially non-functional.")


    print(f"PT_REG: --- Registration for physical_layout_tool FINISHED ---")

def unregister():
    print(f"PT_UNREG: --- Starting Unregistration for physical_layout_tool ---")

    if hasattr(bpy.types.Scene, 'physical_tool_settings'):
        try:
            prop_info = bpy.types.Scene.bl_rna.properties.get('physical_tool_settings')
            if prop_info and isinstance(prop_info.fixed_type, PointerProperty) and prop_info.fixed_type.type == PhysicalToolSettings:
                del bpy.types.Scene.physical_tool_settings
                print("PT_UNREG:   Scene.physical_tool_settings deleted.")
            elif prop_info:
                 print(f"PT_UNREG:   Scene.physical_tool_settings was not of expected type '{PhysicalToolSettings.__name__}'. Skipping deletion by this module.")
            else:
                 print("PT_UNREG:   Scene.physical_tool_settings not found.")
        except Exception as e:
            print(f"PT_UNREG:   ERROR deleting scene.physical_tool_settings: {e}")
            traceback.print_exc()

    property_groups_to_unregister_pt = [cls for cls in _classes_to_register_physical_tool if issubclass(cls, bpy.types.PropertyGroup)]
    other_classes_to_unregister_pt = [cls for cls in _classes_to_register_physical_tool if not issubclass(cls, bpy.types.PropertyGroup)]

    for cls in reversed(other_classes_to_unregister_pt): # Unregister non-PropertyGroups first
        if hasattr(bpy.types, cls.__name__):
            try:
                current_class_ref = getattr(bpy.types, cls.__name__)
                if current_class_ref == cls:
                     bpy.utils.unregister_class(cls)
                     print(f"PT_UNREG:   Unregistered: {cls.__name__}")
                # else: print(f"PT_UNREG: Mismatch - bpy.types.{cls.__name__} is not {cls}. Skipping.")
            except RuntimeError:
                print(f"PT_UNREG:   {cls.__name__} was not registered or already unregistered.")
            except Exception as e_unreg_other:
                print(f"PT_UNREG:   ERROR unregistering {cls.__name__}: {e_unreg_other}")
                traceback.print_exc()
    
    for cls in reversed(property_groups_to_unregister_pt): # Then unregister PropertyGroups
        if hasattr(bpy.types, cls.__name__):
            try:
                current_class_ref = getattr(bpy.types, cls.__name__)
                if current_class_ref == cls:
                     bpy.utils.unregister_class(cls)
                     print(f"PT_UNREG:   Unregistered PG: {cls.__name__}")
                # else: print(f"PT_UNREG: Mismatch - bpy.types.{cls.__name__} is not PG {cls}. Skipping.")
            except RuntimeError:
                print(f"PT_UNREG:   PG {cls.__name__} was not registered or already unregistered.")
            except Exception as e_unreg_pg:
                print(f"PT_UNREG:   ERROR unregistering PG {cls.__name__}: {e_unreg_pg}")
                traceback.print_exc()

    print("PT_UNREG: --- Unregistration for physical_layout_tool FINISHED ---")