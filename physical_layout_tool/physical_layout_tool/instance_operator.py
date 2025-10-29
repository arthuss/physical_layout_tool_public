# --- START OF FILE instance_operator.py ---
bl_info = {
    "name": "Instance Operator",
    "blender": (4, 4, 0),
    "category": "Object",
    "author": "EXEGET",
    "version": (1, 6, 9, 17), # Version erhöht für diese Konsistenzanpassung
    "location": "View3D > Sidebar > PhysicalTool Tab",
    "description": "Creates instances or static/rigid objects from source collections. C++ accelerated logic.",
}

import bpy
import traceback
from bpy.props import StringProperty, PointerProperty, BoolProperty, IntProperty, FloatProperty
from mathutils import Matrix

# --- Globale Variablen für C++ Modul und Flag (werden durch Import aus __init__.py gefüllt) ---
# Diese werden am Anfang des Moduls definiert, damit sie immer existieren,
# auch wenn der Import aus dem Paket fehlschlägt oder die __init__.py nicht korrekt arbeitet.
# Die tatsächlichen Werte kommen dann aus dem Import.
# Name angepasst an die __init__.py Version (scatter_accel statt ext_scatter_accel)
scatter_accel = None
NATIVE_MODULE_AVAILABLE = False
# ---

# Import für das C++ Modul und das Verfügbarkeits-Flag aus dem Hauptpaket
try:
    # Diese Zeilen versuchen, die Variablen zu importieren, die in __init__.py des Pakets
    # (also im Ordner darüber, repräsentiert durch '..') definiert und initialisiert wurden.
    # Name angepasst an die __init__.py Version
    from . import scatter_accel as pkg_scatter_accel
    from . import NATIVE_MODULE_AVAILABLE as pkg_NATIVE_MODULE_AVAILABLE

    # Weise die importierten Werte den modulglobalen Variablen zu.
    scatter_accel = pkg_scatter_accel # Name angepasst
    NATIVE_MODULE_AVAILABLE = pkg_NATIVE_MODULE_AVAILABLE

    _module_name = __name__
    if NATIVE_MODULE_AVAILABLE and scatter_accel: # Name angepasst
        print(f"INFO [{_module_name}]: Native C++ Modul 'scatter_accel' und Flag 'NATIVE_MODULE_AVAILABLE' erfolgreich über Paket-Namespace bezogen.")
    elif NATIVE_MODULE_AVAILABLE and not scatter_accel: # Name angepasst
        print(f"WARNUNG [{_module_name}]: 'NATIVE_MODULE_AVAILABLE' ist True aus Paket, aber 'scatter_accel' ist None. Problem in __init__.py? Setze lokal auf nicht verfügbar.")
        NATIVE_MODULE_AVAILABLE = False
        scatter_accel = None
    elif not NATIVE_MODULE_AVAILABLE:
        print(f"INFO [{_module_name}]: Native C++ Modul NICHT verfügbar (gemäß Paket-Namespace: 'NATIVE_MODULE_AVAILABLE' ist False).")
        if scatter_accel is not None: # Name angepasst
            print(f"WARNUNG [{_module_name}]: 'NATIVE_MODULE_AVAILABLE' ist False, aber 'scatter_accel' war nicht None. Wird auf None gesetzt.")
            scatter_accel = None

except ImportError as e_imp:
    _module_name = __name__
    print(f"KRITISCH [{_module_name}]: ImportError beim Versuch, 'scatter_accel' oder 'NATIVE_MODULE_AVAILABLE' aus dem Hauptpaket ('..') zu importieren: {e_imp}.") # Name angepasst
    print(f"  [{_module_name}]: Dies bedeutet wahrscheinlich, dass das Haupt-Addon (__init__.py) diese Variablen nicht korrekt im Paket-Namespace bereitstellt oder ein Strukturproblem vorliegt.")
    print(f"  [{_module_name}]: C++ Beschleunigung wird für dieses Modul DEAKTIVIERT.")
    scatter_accel = None # Name angepasst
    NATIVE_MODULE_AVAILABLE = False
except Exception as e_gen_imp:
    _module_name = __name__
    print(f"KRITISCH [{_module_name}]: Allgemeiner Fehler (Typ: {type(e_gen_imp).__name__}) beim Import von 'scatter_accel' oder 'NATIVE_MODULE_AVAILABLE' aus dem Hauptpaket: {e_gen_imp}.") # Name angepasst
    print(f"  [{_module_name}]: C++ Beschleunigung wird für dieses Modul DEAKTIVIERT.")
    scatter_accel = None # Name angepasst
    NATIVE_MODULE_AVAILABLE = False

# --- Helper function to get or create collection (Updated for Robustness) ---
def get_or_create_collection(collection_name, context, parent_collection_obj=None):
    if not collection_name:
        print(f"IM_UTIL Error: Collection name is empty.")
        return None
    if collection_name in bpy.data.collections:
        return bpy.data.collections[collection_name]
    else:
        if not context or not hasattr(context, 'scene') or not context.scene:
            print(f"IM_UTIL Error: Context hat keine Szene für Collection '{collection_name}'.")
            active_scene = bpy.context.scene if bpy.context and bpy.context.scene else None
            if not active_scene:
                 print(f"IM_UTIL Error: bpy.context hat auch keine Szene für '{collection_name}'")
                 return None
        else:
            active_scene = context.scene

        parent_to_use = parent_collection_obj if parent_collection_obj else active_scene.collection

        if not parent_to_use:
            print(f"IM_UTIL Error: Keine gültige Parent-Collection für '{collection_name}'.")
            return None
        try:
            new_collection = bpy.data.collections.new(name=collection_name)
            parent_to_use.children.link(new_collection)
            print(f"IM_UTIL: Collection '{collection_name}' erstellt.")
            return new_collection
        except Exception as e:
            print(f"IM_UTIL Error: Konnte Collection '{collection_name}' nicht erstellen: {e}")
            traceback.print_exc()
            return None

# --- Callback für Property Update ---
def instancing_toggle_callback(self, context):
    settings = getattr(context.scene, 'instance_manager_settings', None)
    if not settings: return

    if self.use_instancing:
        created = get_or_create_collection(settings.instance_collection_name, context)
        if created:
            print(f"[InstanceManager] Instanz-Collection '{created.name}' sichergestellt.")
        else:
            print("[InstanceManager] ⚠️ Instanz-Collection konnte nicht erstellt werden.")

# --- Settings for the Instancing Manager ---
class InstanceManagerSettings(bpy.types.PropertyGroup):
    source_collection_basename: StringProperty(
        name="Source Collection Basename",
        description="Base name for dynamically created source collections per scatter session",
        default="SCATTER_SESSION"
    )
    instance_collection_name: StringProperty(
        name="Instance Collection",
        description="Lightweight instances will be placed here",
        default="COL_MANAGED_INSTANCES"
    )
    static_collection_name: StringProperty(
        name="Static Collection",
        description="Collection for non-instanced objects (potentially with rigid bodies)",
        default="COL_BAKED_STATIC"
    )
    use_instancing: BoolProperty(
        name="Enable Instancing",
        description="Enable instance-based object handling. If unchecked, objects become static/rigid.",
        default=False,
        update=instancing_toggle_callback
    )
    enable_instancing_on_scatter_finish: BoolProperty(
        name="Enable Instancing on Scatter Finish",
        description="If enabled, processes the session's Source Collection when scatter mode is finished",
        default=True
    )
    use_rigid_for_non_instances: BoolProperty(
        name="Rigid für Nicht-Instanzen",
        description="Wenn Instancing DEAKTIVIERT ist: Nicht instanzierte Objekte erhalten Rigid Body (ACTIVE), konfiguriert durch 'Physical Layout Tool Settings'",
        default=True
    )
    batch_size: IntProperty(
        name="Batch Size (Instancing)",
        description="Number of objects/instructions to process per step",
        default=10,
        min=1
    )
    timer_interval: FloatProperty(
        name="Timer Interval (Instancing)",
        description="Delay between processing batches (seconds)",
        default=0.01,
        min=0.001,
        subtype='TIME',
        unit='TIME'
    )

# --- Base Modal Operator for Instance Operations ---
class OBJECT_OT_instance_modal_base(bpy.types.Operator):
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _current_instruction_index = 0
    _instructions_from_cpp: list = []

    _initial_selected_names = set()
    _initial_active_name = None
    _im_settings_ref = None

    def process_single_object(self, context, obj_identifier):
        raise NotImplementedError("Subclasses must implement specific processing logic.")

    def gather_objects_to_process(self, context):
        raise NotImplementedError("Subclasses must implement gather_objects_to_process.")

    def invoke(self, context, event):
        self._im_settings_ref = getattr(context.scene, 'instance_manager_settings', None)
        if not self._im_settings_ref:
            self.report({'ERROR'}, "InstanceManagerSettings nicht gefunden.")
            return {'CANCELLED'}

        self._initial_selected_names = {obj.name for obj in context.selected_objects if obj}
        self._initial_active_name = context.view_layer.objects.active.name if context.view_layer.objects.active else None
        self._current_instruction_index = 0

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.report({'INFO'}, f"{self.bl_label} cancelled by user.")
            return self._finish_modal(context, cancelled=True)

        if event.type == 'TIMER':
            pass

        return {'RUNNING_MODAL'}

    def _finish_modal(self, context, cancelled=False):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

        context.window.cursor_modal_restore()

        original_active_obj = bpy.data.objects.get(self._initial_active_name) if self._initial_active_name else None
        original_selected_objs = [bpy.data.objects.get(name) for name in self._initial_selected_names]
        original_selected_objs = [obj for obj in original_selected_objs if obj and obj.name in context.view_layer.objects]

        bpy.ops.object.select_all(action='DESELECT')
        for obj_to_reselect in original_selected_objs:
            try: obj_to_reselect.select_set(True)
            except ReferenceError: pass

        if original_active_obj and original_active_obj.name in context.view_layer.objects:
            try: context.view_layer.objects.active = original_active_obj
            except ReferenceError: pass
        elif original_selected_objs:
            try: context.view_layer.objects.active = original_selected_objs[0]
            except (IndexError, ReferenceError): pass


        if context.area:
            try: context.area.tag_redraw()
            except ReferenceError: pass

        if cancelled:
            self.report({'INFO'}, f"{self.bl_label} cancelled.")
        else:
            self.report({'INFO'}, f"{self.bl_label} complete.")
        return {'FINISHED'} if not cancelled else {'CANCELLED'}

# --- MODAL Operator to Process Source Collection and Create Instances ---
class OBJECT_OT_process_source_for_instancing_modal(OBJECT_OT_instance_modal_base):
    bl_idname = "object.process_source_for_instancing_modal"
    bl_label = "Process Source for Instancing/Static (Modal)"
    bl_description = "Scans a Source Collection, creates instances OR static/rigid objects based on settings. C++ accelerated."

    source_collection_to_process: StringProperty(
        name="Source Collection to Process",
        description="The specific source collection to process"
    )
    _instance_collection_ref = None
    _static_collection_ref = None

    def _apply_rigid_body_active(self, context, obj):
        if not obj or obj.rigid_body:
            return

        phys_settings = getattr(context.scene, 'physical_tool_settings', None)
        if not phys_settings:
            self.report({'WARNING'}, f"PhysicalToolSettings nicht gefunden für RB auf '{obj.name}'. Standardwerte verwendet.")
            default_mass, default_shape, default_margin = 1.0, 'CONVEX_HULL', 0.001
        else:
            default_mass = phys_settings.mass
            default_shape = phys_settings.collision_shape
            default_margin = phys_settings.collision_margin

        current_active = context.view_layer.objects.active
        current_selected_names = {o.name for o in context.selected_objects if o}

        original_hide_viewport = obj.hide_get(view_layer=context.view_layer)
        original_hide_select = obj.hide_select

        if original_hide_viewport: obj.hide_set(False, view_layer=context.view_layer)
        if original_hide_select: obj.hide_select = False

        bpy.ops.object.select_all(action='DESELECT')
        try:
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.rigidbody.object_add()

            if obj.rigid_body:
                obj.rigid_body.type = 'ACTIVE'
                obj.rigid_body.mass = default_mass
                obj.rigid_body.collision_shape = default_shape
                obj.rigid_body.use_margin = True
                obj.rigid_body.collision_margin = default_margin
                obj.rigid_body.linear_damping = 0.04
                obj.rigid_body.angular_damping = 0.1
                obj.rigid_body.use_deactivation = True
                obj.rigid_body.use_start_deactivated = False
                context.view_layer.update()
            else:
                self.report({'WARNING'}, f"RB konnte nicht zu '{obj.name}' hinzugefügt werden (nach ops.call).")
        except Exception as e:
            self.report({'WARNING'}, f"Konnte RB nicht zu '{obj.name}' hinzufügen/konfigurieren: {e}")
            traceback.print_exc()
        finally:
            bpy.ops.object.select_all(action='DESELECT')
            for name in current_selected_names:
                sel_obj = bpy.data.objects.get(name)
                if sel_obj and sel_obj.name in context.view_layer.objects:
                    try:
                        sel_obj.select_set(True)
                    except ReferenceError:
                        pass

            # --- START MODIFIED BLOCK (endgültige Korrektur) ---
            active_obj_restored = bpy.data.objects.get(current_active.name) if current_active else None
            if active_obj_restored and active_obj_restored.name in context.view_layer.objects:
                try:
                    context.view_layer.objects.active = active_obj_restored
                except ReferenceError:
                    pass
            elif current_selected_names:
                first_selected_name = next(iter(current_selected_names), None)
                if first_selected_name:
                    first_sel_obj_restored = bpy.data.objects.get(first_selected_name)
                    if first_sel_obj_restored and first_sel_obj_restored.name in context.view_layer.objects:
                        try:
                            context.view_layer.objects.active = first_sel_obj_restored
                        except ReferenceError:
                            pass
            # --- END MODIFIED BLOCK ---

            if obj and obj.name in bpy.data.objects:
                if original_hide_viewport:
                    obj.hide_set(True, view_layer=context.view_layer)
                if original_hide_select:
                    obj.hide_select = True


    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, 'instance_manager_settings')

    def invoke(self, context, event):
        super().invoke(context, event)
        if not self._im_settings_ref: return {'CANCELLED'}

        self._instance_collection_ref = get_or_create_collection(self._im_settings_ref.instance_collection_name, context)
        self._static_collection_ref = get_or_create_collection(self._im_settings_ref.static_collection_name, context)

        if self._im_settings_ref.use_instancing and not self._instance_collection_ref:
            self.report({'ERROR'}, f"Instancing AN, aber Collection '{self._im_settings_ref.instance_collection_name}' nicht erstellbar.")
            return {'CANCELLED'}
        if not self._im_settings_ref.use_instancing and not self._static_collection_ref:
            self.report({'ERROR'}, f"Static-Modus, aber Collection '{self._im_settings_ref.static_collection_name}' nicht erstellbar.")
            return {'CANCELLED'}

        object_names_from_source = self.gather_objects_to_process(context)
        if not object_names_from_source:
            self.report({'INFO'}, "Keine Objekte zum Verarbeiten in Quell-Collection gefunden.")
            return {'FINISHED'}


        objects_data_for_cpp, settings_for_cpp = self._prepare_data_for_cpp(context, object_names_from_source)

        if not objects_data_for_cpp:
            self.report({'INFO'}, "Keine validen Objekte für C++-Verarbeitung vorbereitet.")
            return {'FINISHED'}

        # Verwende die modulglobalen Variablen NATIVE_MODULE_AVAILABLE und scatter_accel
        if NATIVE_MODULE_AVAILABLE and scatter_accel:
            try:
                print(f"IM_INFO: Sende {len(objects_data_for_cpp)} Objekte an C++ zur Analyse...")
                self._instructions_from_cpp = scatter_accel.analyze_scatter_objects_for_processing(objects_data_for_cpp, settings_for_cpp) # Name angepasst
                self.report({'INFO'}, f"C++ Analyse abgeschlossen. {len(self._instructions_from_cpp)} Anweisungen erhalten.")
            except Exception as e:
                self.report({'ERROR'}, f"Fehler bei C++ Analyse: {e}. Siehe Konsole.")
                traceback.print_exc()
                self._instructions_from_cpp = []
                return {'CANCELLED'}
        else:
            self.report({'ERROR'}, "Natives C++ Modul nicht verfügbar. Operation kann nicht fortgesetzt werden.")
            return {'CANCELLED'}

        if not self._instructions_from_cpp:
             self.report({'INFO'}, "Keine Anweisungen von C++ erhalten (oder Fehler). Abbruch.")
             return {'CANCELLED'}


        self._current_instruction_index = 0
        wm = context.window_manager
        self._timer = wm.event_timer_add(self._im_settings_ref.timer_interval, window=context.window)
        wm.modal_handler_add(self)
        context.window.cursor_modal_set('WAIT')
        self.report({'INFO'}, f"Starting: {self.bl_label} für {len(self._instructions_from_cpp)} Anweisungen.")
        return {'RUNNING_MODAL'}

    def gather_objects_to_process(self, context):
        if not self.source_collection_to_process:
            self.report({'INFO'}, "Keine spezifische Quell-Collection zum Verarbeiten angegeben.")
            return []
        source_collection = bpy.data.collections.get(self.source_collection_to_process)
        if not source_collection:
            self.report({'INFO'}, f"Spezifische Quell-Collection '{self.source_collection_to_process}' nicht gefunden.")
            return []

        collected_names = []
        for obj in source_collection.objects:
            if obj and obj.type == 'MESH' and obj.data and len(obj.data.vertices) > 0:
                collected_names.append(obj.name)
            elif obj:
                print(f"IM_INFO: Objekt '{obj.name}' in '{source_collection.name}' ignoriert (kein Mesh/Vertices oder ungültig).")
        return collected_names

    def _prepare_data_for_cpp(self, context, object_names_to_process):
        objects_to_analyze_cpp = []
        for obj_name in object_names_to_process:
            obj = bpy.data.objects.get(obj_name)
            if obj and obj.data:
                 objects_to_analyze_cpp.append({
                    "name": obj.name,
                    "mesh_name": obj.data.name,
                    "matrix_world": [list(row) for row in obj.matrix_world],
                    "has_rigidbody": (obj.rigid_body is not None)
                })
            else:
                print(f"IM_WARN: Objekt '{obj_name}' nicht gefunden oder hat keine Mesh-Daten beim Vorbereiten für C++ (nach gather).")

        settings = self._im_settings_ref
        processing_settings_cpp = {
            "mode_is_instancing": settings.use_instancing,
            "apply_rigidbody_static": settings.use_rigid_for_non_instances,
            "instance_collection_name": self._instance_collection_ref.name if self._instance_collection_ref else "",
            "static_collection_name": self._static_collection_ref.name if self._static_collection_ref else "",
            "instance_name_base_suffix": "_inst"
        }
        return objects_to_analyze_cpp, processing_settings_cpp

    def modal(self, context, event):
        if event.type == 'ESC':
            self.report({'INFO'}, f"{self.bl_label} cancelled by user.")
            return self._finish_modal(context, cancelled=True)

        if event.type == 'TIMER':
            if self._current_instruction_index >= len(self._instructions_from_cpp):
                self.report({'INFO'}, f"Alle {len(self._instructions_from_cpp)} Anweisungen verarbeitet.")
                return self._finish_modal(context)

            processed_in_batch = 0
            batch_size = self._im_settings_ref.batch_size

            for _ in range(batch_size):
                if self._current_instruction_index >= len(self._instructions_from_cpp):
                    break

                instruction = self._instructions_from_cpp[self._current_instruction_index]
                self.execute_instruction(context, instruction)
                self._current_instruction_index += 1
                processed_in_batch +=1

            if processed_in_batch > 0:
                self.report({'INFO'}, f"Processed {self._current_instruction_index}/{len(self._instructions_from_cpp)} instructions...")

        return {'RUNNING_MODAL'}

    def execute_instruction(self, context, instruction_dict):
        action = instruction_dict.get("action")
        original_name = instruction_dict.get("original_name")
        obj_marker = bpy.data.objects.get(original_name)

        if not obj_marker:
            if action != "SKIP" and action != "ERROR_OBJECT_NOT_FOUND":
                 self.report({'WARNING'}, f"Originalobjekt '{original_name}' für Aktion '{action}' nicht mehr vorhanden. Übersprungen.")
            return

        source_collection = bpy.data.collections.get(self.source_collection_to_process)

        if action == "CREATE_INSTANCE_AND_DELETE_ORIGINAL":
            mesh_to_instance_name = instruction_dict.get("mesh_to_instance")
            mesh_data = bpy.data.meshes.get(mesh_to_instance_name)
            if not mesh_data:
                self.report({'WARNING'}, f"Mesh '{mesh_to_instance_name}' für Instanz von '{original_name}' nicht gefunden. Übersprungen.")
                return
            if not self._instance_collection_ref:
                self.report({'ERROR'}, "Instanz-Collection Referenz ist None in CREATE_INSTANCE. Breche für dieses Objekt ab.")
                return

            py_instance_name_base = instruction_dict.get("new_instance_name_base", f"{original_name}_inst")
            final_py_instance_name = py_instance_name_base
            i = 0
            while final_py_instance_name in bpy.data.objects:
                i += 1; final_py_instance_name = f"{py_instance_name_base}.{i:03d}"

            new_instance = bpy.data.objects.new(name=final_py_instance_name, object_data=mesh_data)
            matrix_data = instruction_dict.get("matrix_world")
            if matrix_data: new_instance.matrix_world = Matrix(matrix_data)
            else: new_instance.matrix_world = obj_marker.matrix_world.copy()

            try:
                for col in list(new_instance.users_collection): col.objects.unlink(new_instance)
                self._instance_collection_ref.objects.link(new_instance)
            except Exception as e:
                self.report({'WARNING'}, f"Fehler Verlinken Instanz '{new_instance.name}' in '{self._instance_collection_ref.name}': {e}")
                if new_instance.name in bpy.data.objects: bpy.data.objects.remove(new_instance, do_unlink=True)
                return

            if source_collection and obj_marker.name in source_collection.objects:
                try: source_collection.objects.unlink(obj_marker)
                except Exception as e_unlink: self.report({'WARNING'}, f"Konnte '{obj_marker.name}' nicht aus Quell-Col '{source_collection.name}' entlinken: {e_unlink}")

            for vl in context.scene.view_layers:
                if obj_marker.name in vl.objects:
                    try:
                        pass
                    except Exception:
                        pass
            try:
                bpy.data.objects.remove(obj_marker, do_unlink=True)
            except Exception as e_remove: self.report({'WARNING'}, f"Fehler Entfernen Originalobjekt '{original_name}': {e_remove}")


        elif action == "MOVE_TO_STATIC_COLLECTION":
            if not self._static_collection_ref:
                self.report({'ERROR'}, "Static-Collection Referenz ist None in MOVE_TO_STATIC. Breche für dieses Objekt ab.")
                return

            if instruction_dict.get("add_rigidbody", False):
                self._apply_rigid_body_active(context, obj_marker)

            try:
                if source_collection and obj_marker.name in source_collection.objects:
                    source_collection.objects.unlink(obj_marker)

                if obj_marker.name not in self._static_collection_ref.objects:
                    self._static_collection_ref.objects.link(obj_marker)

            except Exception as e: self.report({'WARNING'}, f"Fehler Verschieben '{obj_marker.name}' nach Static Collection '{self._static_collection_ref.name}': {e}")

        elif action == "SKIP":
            reason = instruction_dict.get('reason', 'Kein Grund angegeben')
            pass
        elif action == "ERROR_OBJECT_NOT_FOUND":
            self.report({'WARNING'}, f"C++ meldet: Objekt '{original_name}' nicht gefunden/ungültig.")
        else:
            self.report({'WARNING'}, f"Unbekannte C++ Aktion '{action}' für Objekt '{original_name}'.")

    def _finish_modal(self, context, cancelled=False):
        base_result = super()._finish_modal(context, cancelled)

        settings = self._im_settings_ref
        if not cancelled and settings and self.source_collection_to_process:
            source_collection = bpy.data.collections.get(self.source_collection_to_process)
            if source_collection and \
               source_collection.name.startswith(settings.source_collection_basename) and \
               not source_collection.all_objects:
                try:
                    parent_found = False
                    if source_collection.name in context.scene.collection.children:
                        context.scene.collection.children.unlink(source_collection)
                        parent_found = True
                    else:
                        for coll_iter in bpy.data.collections:
                            if source_collection.name in coll_iter.children:
                                coll_iter.children.unlink(source_collection)
                                parent_found = True
                                break

                    if not parent_found:
                         print(f"IM_WARN: Konnte Parent-Collection von '{source_collection.name}' nicht zum Unlinken finden. Versuche direktes Entfernen.")

                    bpy.data.collections.remove(source_collection)
                    self.report({'INFO'}, f"Leere Quell-Collection '{self.source_collection_to_process}' entfernt.")
                except Exception as e:
                    self.report({'WARNING'}, f"Konnte leere Quell-Collection '{self.source_collection_to_process}' nicht entfernen: {e}")
                    traceback.print_exc()

        self._instance_collection_ref = None
        self._static_collection_ref = None
        return base_result

# --- MODAL Operator to Prepare Instances for Simulation ---
class OBJECT_OT_prepare_managed_instances_modal(OBJECT_OT_instance_modal_base):
    bl_idname = "object.prepare_managed_instances_modal"
    bl_label = "Make Instances Editable (Modal)"
    bl_description = "Converts selected instances from the Instance Collection to have their own mesh data (modal)"

    _instance_collection_name_cache = None
    _objects_to_process_names: list = []
    _current_object_index: int = 0

    @classmethod
    def poll(cls, context):
        active_scene = context.scene
        if not hasattr(active_scene, 'instance_manager_settings'): return False
        settings = active_scene.instance_manager_settings
        if not settings.instance_collection_name: return False
        instance_col = bpy.data.collections.get(settings.instance_collection_name)
        if not instance_col: return False

        return any(obj and obj.data and obj.data.users > 1 and obj.name in instance_col.objects
                   for obj in context.selected_objects if obj.type == 'MESH')

    def invoke(self, context, event):
        base_invoke_result = super().invoke(context, event)
        if base_invoke_result == {'CANCELLED'} or not self._im_settings_ref:
             return {'CANCELLED'}

        self._objects_to_process_names = self.gather_objects_to_process(context)
        if not self._objects_to_process_names:
            self.report({'INFO'}, "Keine zu bearbeitenden Instanzen ausgewählt oder gefunden.")
            return {'FINISHED'}

        self._current_object_index = 0
        wm = context.window_manager
        self._timer = wm.event_timer_add(self._im_settings_ref.timer_interval, window=context.window)
        wm.modal_handler_add(self)
        context.window.cursor_modal_set('WAIT')
        self.report({'INFO'}, f"Starting: {self.bl_label} für {len(self._objects_to_process_names)} Instanzen.")
        return {'RUNNING_MODAL'}


    def gather_objects_to_process(self, context):
        if not self._im_settings_ref:
            self.report({'ERROR'}, "Instance Manager Settings nicht verfügbar in gather_objects.")
            return []

        settings = self._im_settings_ref
        self._instance_collection_name_cache = settings.instance_collection_name
        instance_collection = bpy.data.collections.get(self._instance_collection_name_cache)

        if not instance_collection:
            self.report({'ERROR'}, f"Instance Collection '{self._instance_collection_name_cache}' nicht gefunden.")
            return []

        return [obj.name for obj in context.selected_objects
                if obj and obj.type == 'MESH' and obj.data and obj.data.users > 1 and obj.name in instance_collection.objects]

    def modal(self, context, event):
        if event.type == 'ESC':
            self.report({'INFO'}, f"{self.bl_label} cancelled by user.")
            return self._finish_modal(context, cancelled=True)

        if event.type == 'TIMER':
            if self._current_object_index >= len(self._objects_to_process_names):
                self.report({'INFO'}, f"Alle {len(self._objects_to_process_names)} Instanzen bearbeitet.")
                return self._finish_modal(context)

            processed_in_batch = 0
            batch_size = self._im_settings_ref.batch_size if self._im_settings_ref else 1

            for _ in range(batch_size):
                if self._current_object_index >= len(self._objects_to_process_names):
                    break

                obj_name = self._objects_to_process_names[self._current_object_index]
                self.process_single_object(context, obj_name)
                self._current_object_index += 1
                processed_in_batch +=1

            if processed_in_batch > 0:
                self.report({'INFO'}, f"Prepared {self._current_object_index}/{len(self._objects_to_process_names)} instances...")

        return {'RUNNING_MODAL'}

    def process_single_object(self, context, obj_name):
        obj = bpy.data.objects.get(obj_name)
        if not obj or obj.type != 'MESH' or not obj.data or obj.data.users <= 1:
            return

        if self._instance_collection_name_cache:
            instance_collection = bpy.data.collections.get(self._instance_collection_name_cache)
            if not instance_collection or obj.name not in instance_collection.objects:
                self.report({'WARNING'}, f"Objekt '{obj.name}' nicht (mehr) in Instanz-Collection '{self._instance_collection_name_cache}'. Übersprungen.")
                return
        else:
            self.report({'WARNING'}, f"Instanz-Collection-Name nicht gecached für '{obj.name}'. Übersprungen.")
            return


        current_matrix = obj.matrix_world.copy()
        original_active_in_loop = context.view_layer.objects.active

        original_hide_viewport = obj.hide_get(view_layer=context.view_layer)
        original_hide_select = obj.hide_select

        if original_hide_viewport: obj.hide_set(False, view_layer=context.view_layer)
        if original_hide_select: obj.hide_select = False

        bpy.ops.object.select_all(action='DESELECT')
        try:
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.make_single_user(object=False, obdata=True, animation=False, obdata_animation=False)
            obj.matrix_world = current_matrix
        except RuntimeError as e:
            self.report({'WARNING'}, f"Konnte '{obj.name}' nicht zu Single User machen (RuntimeError): {e}")
        except Exception as e_gen:
            self.report({'ERROR'}, f"Generischer Fehler bei Make Single User für '{obj.name}': {e_gen}")
            traceback.print_exc()
        finally:
            # --- START MODIFIED BLOCK ---
            original_active_name_in_loop = original_active_in_loop.name if original_active_in_loop else None
            if original_active_name_in_loop:
                obj_to_restore_as_active = bpy.data.objects.get(original_active_name_in_loop)
                if obj_to_restore_as_active and obj_to_restore_as_active.name in context.view_layer.objects and \
                   context.view_layer.objects.active != obj_to_restore_as_active: # Nur ändern, wenn nötig
                    try:
                        context.view_layer.objects.active = obj_to_restore_as_active
                    except ReferenceError:
                        pass
            elif obj and obj.name in context.view_layer.objects: # Fallback: das gerade bearbeitete Objekt aktiv lassen, wenn nichts anderes da war
                if context.view_layer.objects.active != obj:
                    try:
                        context.view_layer.objects.active = obj
                    except ReferenceError:
                        pass
            # --- END MODIFIED BLOCK ---

            if obj and obj.name in bpy.data.objects:
                if original_hide_viewport: obj.hide_set(True, view_layer=context.view_layer)
                if original_hide_select: obj.hide_select = True

            if obj and obj.select_get():
                try: obj.select_set(False)
                except ReferenceError: pass


# --- UI Panel for Instance Manager ---
class VIEW3D_PT_instance_manager_controls(bpy.types.Panel):
    bl_label = "Instance Manager"
    bl_idname = "VIEW3D_PT_instance_manager"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'PhysicalTool'
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        settings = getattr(context.scene, 'instance_manager_settings', None)
        if not settings: self.layout.label(icon='ERROR'); return

        icon = 'NONE'
        if settings.use_instancing:
            icon = 'OUTLINER_OB_LIGHTPROBE'
        elif settings.enable_instancing_on_scatter_finish:
            icon = 'MOD_INSTANCE'
        else:
            icon = 'PHYSICS'

        self.layout.label(text="", icon=icon)


    def draw(self, context):
        layout = self.layout
        active_scene = context.scene
        settings = getattr(active_scene, 'instance_manager_settings', None)
        if not settings:
            layout.label(text="Instance Manager Settings nicht gefunden.")
            return

        get_or_create_collection(settings.instance_collection_name, context, parent_collection_obj=active_scene.collection)
        get_or_create_collection(settings.static_collection_name, context, parent_collection_obj=active_scene.collection)

        layout.label(text="Management Collections:")
        box_collections = layout.box()
        row = box_collections.row(align=True);
        row.label(text="Source Basename:")
        row.prop(settings, "source_collection_basename", text="")

        row = box_collections.row(align=True);
        row.label(text="Instances Target:")
        row.prop(settings, "instance_collection_name", text="")

        row = box_collections.row(align=True);
        row.label(text="Static Target:")
        row.prop(settings, "static_collection_name", text="")
        layout.separator()

        layout.label(text="Processing Mode & Options:")
        box_mode = layout.box()
        box_mode.prop(settings, "use_instancing", text="Output as Instances")
        box_mode.prop(settings, "enable_instancing_on_scatter_finish", text="Process on Scatter Finish")

        col_rigid = box_mode.column()
        col_rigid.enabled = not settings.use_instancing
        col_rigid.prop(settings, "use_rigid_for_non_instances", text="Add Rigid Body to Static")
        if not settings.use_instancing and settings.use_rigid_for_non_instances:
            if hasattr(bpy.types, "VIEW3D_PT_physical_layout_tool"):
                 col_rigid.label(text="(RB settings from 'Physical Layout Tool' Panel)", icon='INFO')
            else:
                 col_rigid.label(text="(Uses default RB settings if panel missing)", icon='INFO')

        layout.separator()

        col_batch_settings = layout.column(align=True)
        col_batch_settings.label(text="Modal Operator Settings:")
        row_batch = col_batch_settings.row(align=True)
        row_batch.prop(settings, "batch_size", text="Batch Size")
        row_batch.prop(settings, "timer_interval", text="Timer (s)")
        layout.separator()

        col_ops = layout.column(align=True)
        col_ops.label(text="Manual Operations (Modal):")

        op_make_editable = col_ops.operator(OBJECT_OT_prepare_managed_instances_modal.bl_idname,
                                            text="Make Selected Instances Editable",
                                            icon='OBJECT_DATAMODE')

# --- Registration ---
_classes_to_register_im = (
    InstanceManagerSettings,
    OBJECT_OT_process_source_for_instancing_modal,
    OBJECT_OT_prepare_managed_instances_modal,
    VIEW3D_PT_instance_manager_controls,
)
_im_registered_classes_module_set = set()

def register():
    global _im_registered_classes_module_set
    _im_registered_classes_module_set.clear()
    print("--- Starting Instance Manager Registration ---")

    for cls in reversed(_classes_to_register_im):
        if hasattr(bpy.types, cls.__name__):
            try:
                current_bpy_type_class = getattr(bpy.types, cls.__name__)
                if hasattr(current_bpy_type_class, 'bl_rna') and current_bpy_type_class.__module__.startswith(__name__.split('.')[0]):
                    bpy.utils.unregister_class(current_bpy_type_class)
                    print(f"IM_REG: Pre-unregistered existing class: {cls.__name__}")
            except RuntimeError as e:
                print(f"IM_REG: Info during pre-unregistration of {cls.__name__}: {e} (likely already unregistered or not a bpy type)")
            except Exception as e_gen:
                print(f"IM_REG: Error during pre-unregistration of {cls.__name__}: {e_gen}")

    if hasattr(bpy.types.Scene, 'instance_manager_settings'):
        try:
            prop_rna = bpy.types.Scene.bl_rna.properties.get('instance_manager_settings')
            if prop_rna and isinstance(prop_rna.fixed_type, bpy.types.PropertyGroup) and prop_rna.fixed_type == InstanceManagerSettings:
                 del bpy.types.Scene.instance_manager_settings
                 print("IM_REG: Pre-unregistered existing 'instance_manager_settings' PropertyGroup from Scene.")
            elif prop_rna:
                 print(f"IM_REG: 'instance_manager_settings' on Scene is of type {type(prop_rna.fixed_type).__name__}, not {InstanceManagerSettings.__name__}. Not removing.")
        except Exception as e:
            print(f"IM_REG: Error pre-unregistering 'instance_manager_settings' property: {e}")


    for cls in _classes_to_register_im:
        try:
            bpy.utils.register_class(cls)
            _im_registered_classes_module_set.add(cls)
            print(f"IM_REG: Registered: {cls.__name__}")
        except ValueError as ve:
            print(f"!! FAILED to register {cls.__name__} (ValueError): {ve}. This might be a re-registration issue.")
            traceback.print_exc()
            if not issubclass(cls, (bpy.types.Panel)): raise
        except Exception as e:
            print(f"!! FAILED to register {cls.__name__}: {e}")
            traceback.print_exc()
            if not issubclass(cls, (bpy.types.Panel)): raise

    try:
        bpy.types.Scene.instance_manager_settings = PointerProperty(type=InstanceManagerSettings)
        print("IM_REG: Added PointerProperty 'instance_manager_settings' to Scene.")
    except Exception as e:
        print(f"!! FAILED to add PointerProperty 'instance_manager_settings': {e}")
        traceback.print_exc()
        raise
    print("--- Instance Manager Registration Complete ---")

def unregister():
    global _im_registered_classes_module_set
    print("--- Starting Instance Manager Unregistration ---")

    if hasattr(bpy.types.Scene, 'instance_manager_settings'):
        try:
            prop_rna = bpy.types.Scene.bl_rna.properties.get('instance_manager_settings')
            if prop_rna and isinstance(prop_rna.fixed_type, bpy.types.PropertyGroup) and prop_rna.fixed_type == InstanceManagerSettings:
                 del bpy.types.Scene.instance_manager_settings
                 print("IM_UNREG: Removed PointerProperty 'instance_manager_settings' from Scene.")
            elif prop_rna:
                 print(f"IM_UNREG: 'instance_manager_settings' on Scene was not of type {type(prop_rna.fixed_type).__name__}, not {InstanceManagerSettings.__name__}. Not removing.")
            else:
                 print("IM_UNREG: 'instance_manager_settings' not found on Scene for removal check.")

        except Exception as e:
            print(f"!! FAILED to remove PointerProperty 'instance_manager_settings': {e}")
            traceback.print_exc()

    for cls in reversed(list(_im_registered_classes_module_set)):
        print(f"IM_UNREG: Attempting to unregister {cls.__name__}...")
        try:
            current_bpy_type_class = getattr(bpy.types, cls.__name__, None)
            if current_bpy_type_class == cls :
                bpy.utils.unregister_class(cls)
                print(f"IM_UNREG:   {cls.__name__} unregistered successfully.")
            elif current_bpy_type_class:
                 print(f"IM_UNREG:   Skipped unregistering {cls.__name__} - bpy.types.{(cls.__name__)} is a different class instance (likely from another addon or a stale registration).")
            else:
                 print(f"IM_UNREG:   {cls.__name__} not found in bpy.types (was likely already unregistered or never fully registered).")
        except RuntimeError as e_rt:
            print(f"IM_UNREG:   RuntimeError unregistering {cls.__name__}: {e_rt} (Usually means it was not registered or already gone).")
        except Exception as e:
            print(f"IM_UNREG:   GENERIC ERROR unregistering {cls.__name__}: {e}");
            traceback.print_exc()

    _im_registered_classes_module_set.clear()
    print("--- Instance Manager Unregistration Complete ---")

# --- END OF FILE instance_operator.py ---