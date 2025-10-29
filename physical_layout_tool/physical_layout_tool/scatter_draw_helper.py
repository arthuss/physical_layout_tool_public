# scatter_draw_helper.py
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
import numpy as np
from mathutils import Matrix, Vector, Quaternion
import math
import traceback # Für detailliertere Fehlermeldungen, falls nötig

# --- Globale Variablen für C++ Modul und Flag (werden durch Import aus __init__.py gefüllt) ---
scatter_accel = None
NATIVE_MODULE_AVAILABLE = False
# ---

_helper_module_name = __name__

try:
    from . import scatter_accel as pkg_level_scatter_accel
    from . import NATIVE_MODULE_AVAILABLE as pkg_level_native_flag
    scatter_accel = pkg_level_scatter_accel
    NATIVE_MODULE_AVAILABLE = pkg_level_native_flag

    if NATIVE_MODULE_AVAILABLE and scatter_accel:
        print(f"INFO [{_helper_module_name}]: C++ Modul 'scatter_accel' und Flag 'NATIVE_MODULE_AVAILABLE' erfolgreich vom Paket-Scope bezogen.")
    elif NATIVE_MODULE_AVAILABLE and not scatter_accel:
        print(f"WARNUNG [{_helper_module_name}]: Paket-Flag 'NATIVE_MODULE_AVAILABLE' ist True, aber 'scatter_accel' Modulreferenz ist None. C++-Modul wird als nicht verfügbar behandelt.")
        NATIVE_MODULE_AVAILABLE = False
    elif not NATIVE_MODULE_AVAILABLE:
        print(f"INFO [{_helper_module_name}]: C++ Modul nicht verfügbar (gemäß Paket-Flag).")
        if scatter_accel is not None:
            print(f"WARNUNG [{_helper_module_name}]: Inkonsistenz: Paket-Flag 'NATIVE_MODULE_AVAILABLE' ist False, aber 'scatter_accel' Referenz ist nicht None. Wird lokal auf None gesetzt.")
            scatter_accel = None
except ImportError as e_imp:
    print(f"KRITISCH [{_helper_module_name}]: ImportError beim Versuch, C++ Modul/Flag aus dem Paket ('..') zu importieren: {e_imp}.")
    print(f"  [{_helper_module_name}]: C++ Beschleunigung wird für dieses Modul DEAKTIVIERT.")
    scatter_accel = None
    NATIVE_MODULE_AVAILABLE = False
except Exception as e_gen_imp:
    print(f"KRITISCH [{_helper_module_name}]: Allgemeiner Fehler beim Import von C++ Modul/Flag aus Paket: {e_gen_imp}.")
    scatter_accel = None
    NATIVE_MODULE_AVAILABLE = False

# Definiere MockGpuVertexData auf Modulebene, falls es doch mal extern geprüft werden müsste,
# oder um die Definition nicht bei jedem Funktionsaufruf neu zu erstellen.
# Für den Moment ist es hauptsächlich für den Fallback-Pfad innerhalb von safe_prepare_mesh_data_for_cpp.
class _MockGpuVertexData: # Unterstrich, da es primär intern genutzt wird
    def __init__(self, pos, idx):
        self.positions = pos
        self.indices = idx

def safe_prepare_mesh_data_for_cpp(flat_positions_array_np: np.ndarray, flat_triangle_indices_array_np: np.ndarray):
    """
    Wrapper to safely prepare and call the C++ mesh data preparation function.
    Ensures that num_actual_vertices and num_loop_triangles are non-negative
    and correctly derived from the flat input arrays.

    Args:
        flat_positions_array_np (np.ndarray): Flat float32 NumPy array of vertex coordinates (x,y,z,x,y,z,...).
        flat_triangle_indices_array_np (np.ndarray): Flat int32 NumPy array of triangle vertex indices (i0,i1,i2, i0,i1,i2,...).

    Returns:
        scatter_accel.GpuVertexData or _MockGpuVertexData: Object containing 'positions' (Nx3 float32) and 'indices' (Mx3 uint32) NumPy arrays.
                                       Returns _MockGpuVertexData with (0,3) shaped arrays if inputs are empty or C++ fails / is unavailable.
    """
    if not isinstance(flat_positions_array_np, np.ndarray) or flat_positions_array_np.dtype != np.float32:
        # print(f"WARNUNG [{_helper_module_name}]: flat_positions_array_np ist kein float32 ndarray. Shape: {getattr(flat_positions_array_np, 'shape', 'N/A')}")
        pass # C++ wird ggf. forcecasten oder fehlschlagen

    if not isinstance(flat_triangle_indices_array_np, np.ndarray) or flat_triangle_indices_array_np.dtype != np.int32:
        # print(f"WARNUNG [{_helper_module_name}]: flat_triangle_indices_array_np ist kein int32 ndarray. Shape: {getattr(flat_triangle_indices_array_np, 'shape', 'N/A')}")
        pass

    num_actual_vertices = 0
    if flat_positions_array_np.size > 0:
        if flat_positions_array_np.size % 3 != 0:
            raise ValueError(f"Positions array (flat) length {flat_positions_array_np.size} must be divisible by 3.")
        num_actual_vertices = flat_positions_array_np.size // 3

    num_loop_triangles = 0
    if flat_triangle_indices_array_np.size > 0:
        if flat_triangle_indices_array_np.size % 3 != 0:
            raise ValueError(f"Triangle indices array (flat) length {flat_triangle_indices_array_np.size} must be divisible by 3.")
        num_loop_triangles = flat_triangle_indices_array_np.size // 3

    num_actual_vertices = max(0, num_actual_vertices)
    num_loop_triangles = max(0, num_loop_triangles)

    if NATIVE_MODULE_AVAILABLE and scatter_accel:
        try:
            gpu_data = scatter_accel.prepare_mesh_gpu_data_from_flat_arrays_cpp(
                flat_positions_array_np,
                flat_triangle_indices_array_np,
                num_actual_vertices,
                num_loop_triangles
            )
            return gpu_data
        except RuntimeError as e_cpp:
            print(f"FEHLER [{_helper_module_name}]: C++ RuntimeError in prepare_mesh_gpu_data_from_flat_arrays_cpp: {e_cpp}")
            # Details für Debugging
            # print(f"  Aufrufparameter waren: V:{num_actual_vertices}, T:{num_loop_triangles}")
            # print(f"  Pos-Array (flat) Shape: {flat_positions_array_np.shape}, dtype: {flat_positions_array_np.dtype}")
            # print(f"  Idx-Array (flat) Shape: {flat_triangle_indices_array_np.shape}, dtype: {flat_triangle_indices_array_np.dtype}")
            empty_pos_fallback = np.empty((0, 3), dtype=np.float32)
            empty_idx_fallback = np.empty((0, 3), dtype=np.uint32)
            return _MockGpuVertexData(empty_pos_fallback, empty_idx_fallback)
        except Exception as e_gen: # Andere unerwartete Fehler vom C++ Modul
            print(f"FEHLER [{_helper_module_name}]: Allgemeiner Fehler beim Aufruf von C++ prepare_mesh_gpu_data_from_flat_arrays_cpp: {e_gen}")
            # traceback.print_exc()
            return _MockGpuVertexData(np.empty((0,3), dtype=np.float32), np.empty((0,3), dtype=np.uint32))
    else: # Python-Fallback
        # print(f"INFO [{_helper_module_name}]: C++ Modul nicht verfügbar oder deaktiviert. Python-Fallback für prepare_mesh_gpu_data.")
        if num_actual_vertices > 0:
            py_positions = flat_positions_array_np.reshape((num_actual_vertices, 3)).astype(np.float32)
        else:
            py_positions = np.empty((0, 3), dtype=np.float32)

        if num_loop_triangles > 0:
            py_indices_temp = flat_triangle_indices_array_np.reshape((num_loop_triangles, 3))
            if np.any(py_indices_temp < 0):
                raise ValueError("Negative vertex index found in Python fallback.")
            if num_actual_vertices > 0 and np.any(py_indices_temp >= num_actual_vertices):
                max_idx = py_indices_temp.max()
                raise ValueError(f"Vertex index {max_idx} out of bounds for {num_actual_vertices} vertices in Python fallback.")
            elif num_actual_vertices == 0 and num_loop_triangles > 0:
                 raise ValueError("Cannot have triangles with 0 vertices in Python fallback.")
            py_indices = py_indices_temp.astype(np.uint32)
        else:
            py_indices = np.empty((0, 3), dtype=np.uint32)
        
        # Im Python-Fallback verwenden wir _MockGpuVertexData, um unabhängig von der
        # C++ GpuVertexData-Konstruktor-Signatur zu sein.
        return _MockGpuVertexData(py_positions, py_indices)

# --- CircleWireframeDrawer Klasse ---
class CircleWireframeDrawer:
    def __init__(self, color=(0.0, 0.8, 1.0, 0.7), radius=0.05, segments=16, line_width=1.0):
        self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        self.color_uniform_data = list(color)
        
        # Validierung direkt im Konstruktor
        self.radius = max(0.001, float(radius)) # Mindestradius, um Degeneration zu vermeiden
        self.segments = max(3, int(segments))
        self.line_width = max(1.0, float(line_width))

        self._batch = None
        self._draw_handler = None
        self._is_visible = False
        self.transform_matrix = Matrix.Identity(4)
        self._generate_batch()

    def _generate_batch(self):
        if self._batch is not None: self._batch = None

        use_cpp_for_circle = NATIVE_MODULE_AVAILABLE and scatter_accel is not None
        coords_np = None
        indices_np = None

        # Verwende die validierten Instanzattribute
        current_radius = self.radius
        current_segments = self.segments

        if use_cpp_for_circle:
            try:
                # print(f"DEBUG [{_helper_module_name} CircleDrawer]: C++ Batch: r={current_radius}, s={current_segments}")
                gpu_data = scatter_accel.generate_circle_marker_gpu_data_cpp(current_radius, current_segments)
                coords_np = np.asarray(gpu_data.positions, dtype=np.float32)
                indices_np = np.asarray(gpu_data.indices, dtype=np.uint32)
                if coords_np is None or indices_np is None:
                    print(f"WARNUNG [{_helper_module_name} CircleDrawer]: C++ lieferte None für Arrays. Fallback.")
                    use_cpp_for_circle = False
            except Exception as e:
                print(f"FEHLER [{_helper_module_name} CircleDrawer] C++ _generate_batch: {e}. Fallback zu Python.")
                use_cpp_for_circle = False

        if not use_cpp_for_circle:
            # print(f"DEBUG [{_helper_module_name} CircleDrawer]: Python Batch")
            coords_list_python = [(0.0, 0.0, 0.0)]
            indices_list_python = []
            center_idx = 0
            for i in range(current_segments): # Verwende validiertes self.segments (current_segments)
                angle = (i / current_segments) * (2 * math.pi)
                x = current_radius * math.cos(angle) # Verwende validiertes self.radius (current_radius)
                y = current_radius * math.sin(angle)
                coords_list_python.append((x, y, 0.0))
            for i in range(current_segments):
                current_outer_idx = center_idx + 1 + i
                next_outer_idx = center_idx + 1 + ((i + 1) % current_segments)
                indices_list_python.append((center_idx, current_outer_idx))
                indices_list_python.append((current_outer_idx, next_outer_idx))
            coords_np = np.array(coords_list_python, dtype=np.float32)
            indices_np = np.array(indices_list_python, dtype=np.uint32)

        valid_batch_data = True
        if coords_np is None or coords_np.ndim != 2 or coords_np.shape[0] < 1 or coords_np.shape[1] != 3:
            valid_batch_data = False
        if indices_np is None or indices_np.ndim != 2 or (indices_np.shape[0] > 0 and indices_np.shape[1] != 2):
            if not (indices_np.shape[0] == 0 and (indices_np.shape[1] == 0 or indices_np.shape[1] == 2)):
                valid_batch_data = False
        if valid_batch_data and indices_np.size > 0 and coords_np.size > 0 and indices_np.max() >= coords_np.shape[0]:
             valid_batch_data = False
        
        if not valid_batch_data:
            # print(f"FEHLER [{_helper_module_name} CircleDrawer]: Ungültige Batch-Daten. Coords: {getattr(coords_np, 'shape', 'N/A')}, Indices: {getattr(indices_np, 'shape', 'N/A')}")
            self._batch = None
            return

        try:
            if indices_np.size > 0:
                self._batch = batch_for_shader(self.shader, 'LINES', {"pos": coords_np}, indices=indices_np)
            elif coords_np.size > 0:
                self._batch = batch_for_shader(self.shader, 'POINTS', {"pos": coords_np})
            else: self._batch = None
        except Exception as e: self._batch = None; print(f"FEHLER [{_helper_module_name} CircleDrawer] Batch Erstellung: {e}")

    def set_transform(self, location: Vector, normal: Vector):
        if location and normal and normal.length > 0.001:
            try: rot_quat = normal.to_track_quat('Z', 'Y')
            except ValueError: rot_quat = Quaternion()
            self.transform_matrix = Matrix.Translation(location) @ rot_quat.to_matrix().to_4x4()
        elif location: self.transform_matrix = Matrix.Translation(location)
        else: self.transform_matrix = Matrix.Identity(4)

    def update_appearance(self, color=None, radius=None, segments=None, line_width=None):
        needs_regeneration = False
        if color is not None: self.color_uniform_data = list(color)

        if radius is not None:
            new_radius = max(0.001, float(radius))
            if abs(self.radius - new_radius) > 1e-6:
                self.radius = new_radius
                needs_regeneration = True
        if segments is not None:
            new_segments = max(3, int(segments))
            if self.segments != new_segments:
                self.segments = new_segments
                needs_regeneration = True
        if line_width is not None:
            new_line_width = max(1.0, float(line_width))
            if abs(self.line_width - new_line_width) > 1e-6:
                self.line_width = new_line_width
                # Keine Batch-Regeneration nötig, da line_width eine GPU-State-Einstellung ist
        if needs_regeneration: self._generate_batch()

    def set_visible(self, visible: bool): self._is_visible = visible
    def get_is_visible(self): return self._is_visible

    def _draw_callback(self):
        if not self._is_visible or not self._batch or not self.shader: return
        self.shader.bind(); self.shader.uniform_float("color", self.color_uniform_data)
        gpu.matrix.push(); gpu.matrix.multiply_matrix(self.transform_matrix)
        original_depth_test = gpu.state.depth_test_get(); original_blend = gpu.state.blend_get()
        original_line_width = gpu.state.line_width_get()
        gpu.state.depth_test_set('NONE')
        if len(self.color_uniform_data) == 4 and self.color_uniform_data[3] < 1.0: gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(self.line_width)
        try: self._batch.draw(self.shader)
        except Exception as e: print(f"ERROR [{_helper_module_name} CircleDrawer] Draw: {e}")
        gpu.state.line_width_set(original_line_width); gpu.state.blend_set(original_blend)
        gpu.state.depth_test_set(original_depth_test); gpu.matrix.pop()

    def enable_drawing(self):
        if self._draw_handler is None:
            self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(self._draw_callback, (), 'WINDOW', 'POST_VIEW')
        self.set_visible(True)
    def disable_drawing(self):
        if self._draw_handler:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, 'WINDOW'); self._draw_handler = None
        self.set_visible(False)
    def cleanup(self): self.disable_drawing(); self._batch = None

# --- GPUMeshGhostPreview Klasse ---
class GPUMeshGhostPreview:
    def __init__(self, color=(0.0, 1.0, 0.0, 0.3), initial_obj_name_for_mesh_data=None):
        self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        self.color_uniform_data = list(color)
        self._batch = None
        self._draw_handler = None
        self._is_visible = False
        self.transform_matrix = Matrix.Identity(4)
        self.current_mesh_source_name = None
        self.current_mesh_eval_hash = None

        # Nur wenn Blender tatsächlich läuft (nicht beim Extension-Packaging)
        if initial_obj_name_for_mesh_data and hasattr(bpy.context, 'scene'):
            try:
                obj = bpy.data.objects.get(initial_obj_name_for_mesh_data)
                if obj: self.update_mesh_from_object(obj)
            except AttributeError:
                # Blender context nicht verfügbar (z.B. beim Packaging)
                pass


    def _generate_batch_from_object(self, obj_to_ghostify_ref):
        if self._batch is not None: self._batch = None
        self.current_mesh_source_name = None
        self.current_mesh_eval_hash = None

        if not obj_to_ghostify_ref or obj_to_ghostify_ref.type != 'MESH' or not obj_to_ghostify_ref.data:
            return

        obj_name = obj_to_ghostify_ref.name
        obj_eval_for_mesh = None
        mesh_data_temp = None
        
        flat_coords_for_wrapper = np.empty(0, dtype=np.float32)
        flat_indices_for_wrapper = np.empty(0, dtype=np.int32)
        expected_num_verts = 0
        expected_num_tris = 0

        try:
            # Nur wenn Blender context verfügbar ist (nicht beim Extension-Packaging)
            if not hasattr(bpy.context, 'scene'):
                return
                
            depsgraph = bpy.context.evaluated_depsgraph_get()
            obj_eval_for_mesh = obj_to_ghostify_ref.evaluated_get(depsgraph)
            mesh_data_temp = obj_eval_for_mesh.to_mesh() # Einmaliger Aufruf von to_mesh()
        except (RuntimeError, AttributeError) as e:
            print(f"FEHLER [{_helper_module_name} GPUMeshGhost]: to_mesh() für '{obj_name}' fehlgeschlagen oder context nicht verfügbar: {e}")
            if obj_eval_for_mesh: # Wenn obj_eval_for_mesh existiert (evaluierte Version wurde geholt)
                 try: obj_eval_for_mesh.to_mesh_clear() # Versuche, die temporären Mesh-Daten freizugeben
                 except Exception as e_clear: print(f"FEHLER [{_helper_module_name} GPUMeshGhost] beim to_mesh_clear nach to_mesh()-Fehler: {e_clear}")
            return # Abbruch, da keine Mesh-Daten

        try: # Dieser try-Block ist für die Verarbeitung der Mesh-Daten und deren Freigabe
            if not mesh_data_temp or not mesh_data_temp.vertices:
                # print(f"DEBUG [{_helper_module_name} GPUMeshGhost]: Kein Mesh-Datum oder keine Vertices nach to_mesh() für '{obj_name}'")
                # expected_num_verts und expected_num_tris bleiben 0, flat_arrays bleiben leer.
                pass
            else:
                mesh_data_temp.calc_loop_triangles()
                expected_num_verts = len(mesh_data_temp.vertices)
                expected_num_tris = len(mesh_data_temp.loop_triangles)

                if expected_num_verts == 0: # Nach calc_loop_triangles, falls Modifikatoren alles entfernen
                    # expected_num_tris wird auch 0 sein oder sollte es sein.
                    expected_num_tris = 0 
                else:
                    flat_coords_for_wrapper = np.empty(expected_num_verts * 3, dtype=np.float32)
                    mesh_data_temp.vertices.foreach_get("co", flat_coords_for_wrapper)

                    if expected_num_tris > 0:
                        flat_indices_for_wrapper = np.empty(expected_num_tris * 3, dtype=np.int32)
                        mesh_data_temp.loop_triangles.foreach_get("vertices", flat_indices_for_wrapper)
                    # else: flat_indices_for_wrapper bleibt leer (0-sized)

        finally: # Stellt sicher, dass to_mesh_clear() aufgerufen wird, auch wenn Fehler bei der Datenextraktion auftreten
            if obj_eval_for_mesh and mesh_data_temp is not None: # Nur wenn mesh_data_temp erfolgreich erstellt wurde
                try:
                    obj_eval_for_mesh.to_mesh_clear()
                    # mesh_data_temp = None # Kann gesetzt werden, um Verwirrung zu vermeiden, aber mesh_data_temp ist lokal
                except Exception as e_clear:
                    print(f"FEHLER [{_helper_module_name} GPUMeshGhost] beim finalen to_mesh_clear: {e_clear}")
        
        # Datenvorbereitung und C++/Python Fallback über den Wrapper
        coords_np = None
        indices_np = None
        try:
            # print(f"DEBUG [{_helper_module_name} GPUMeshGhost]: Aufruf safe_prepare_mesh_data_for_cpp für '{obj_name}' (Erwartet V:{expected_num_verts}, T:{expected_num_tris})")
            gpu_data_obj = safe_prepare_mesh_data_for_cpp(
                flat_coords_for_wrapper, flat_indices_for_wrapper
            )
            coords_np = gpu_data_obj.positions
            indices_np = gpu_data_obj.indices

        except ValueError as e_val: 
            print(f"FEHLER [{_helper_module_name} GPUMeshGhost]: ValueError bei der Datenaufbereitung via Wrapper für '{obj_name}': {e_val}")
            self._batch = None 
            return 
        # Andere Exceptions aus safe_prepare_mesh_data_for_cpp werden dort bereits geloggt und geben _MockGpuVertexData zurück.

        # Finale Validierung der vom Wrapper zurückgegebenen Daten
        valid_batch_data = True
        if coords_np is None or not hasattr(coords_np, 'shape') or coords_np.ndim != 2 or coords_np.shape[1] != 3:
            if not (expected_num_verts == 0 and hasattr(coords_np, 'shape') and coords_np.shape == (0,3)):
                print(f"FEHLER [{_helper_module_name} GPUMeshGhost]: Ungültige Coords nach Wrapper. Shape: {getattr(coords_np, 'shape', 'N/A')}. Erwartet (~,3) oder (0,3) für leere Meshes.")
                valid_batch_data = False
        elif expected_num_verts > 0 and coords_np.shape[0] != expected_num_verts:
             print(f"FEHLER [{_helper_module_name} GPUMeshGhost]: Coords Zeilenanzahl {coords_np.shape[0]} != erwartet {expected_num_verts} nach Wrapper.")
             valid_batch_data = False

        if indices_np is None or not hasattr(indices_np, 'shape') or indices_np.ndim != 2 or indices_np.shape[1] != 3:
            if not (expected_num_tris == 0 and hasattr(indices_np, 'shape') and indices_np.shape == (0,3)):
                print(f"FEHLER [{_helper_module_name} GPUMeshGhost]: Ungültige Indices nach Wrapper. Shape: {getattr(indices_np, 'shape', 'N/A')}. Erwartet (~,3) oder (0,3) für keine Tris.")
                valid_batch_data = False
        elif expected_num_tris > 0 and indices_np.shape[0] != expected_num_tris:
            print(f"FEHLER [{_helper_module_name} GPUMeshGhost]: Indices Zeilenanzahl {indices_np.shape[0]} != erwartet {expected_num_tris} nach Wrapper.")
            valid_batch_data = False

        if valid_batch_data and expected_num_tris > 0 and hasattr(indices_np, 'max') and indices_np.size > 0 and hasattr(coords_np, 'shape') and coords_np.shape[0] > 0 :
            if indices_np.max() >= coords_np.shape[0]:
                 print(f"FEHLER [{_helper_module_name} GPUMeshGhost]: Max Index {indices_np.max()} out of bounds für {coords_np.shape[0]} Vertices nach Wrapper.")
                 valid_batch_data = False
        
        if not valid_batch_data: self._batch = None; return

        try:
            # Verwende expected_num_verts/tris für die Entscheidung, ob TRIS oder POINTS, basierend auf den ursprünglichen Mesh-Daten.
            # indices_np.size > 0 ist immer noch der primäre Indikator für 'TRIS'.
            if expected_num_tris > 0 and indices_np.size > 0 : 
                self._batch = batch_for_shader(self.shader, 'TRIS', {"pos": coords_np}, indices=indices_np)
            elif expected_num_verts > 0 and coords_np.size > 0:
                 self._batch = batch_for_shader(self.shader, 'POINTS', {"pos": coords_np})
            elif expected_num_verts == 0 and expected_num_tris == 0 and hasattr(coords_np, 'shape') and coords_np.shape == (0,3) and hasattr(indices_np, 'shape') and indices_np.shape == (0,3):
                # print(f"DEBUG [{_helper_module_name} GPUMeshGhost]: Leeres Mesh ('{obj_name}'). Kein Batch erstellt, das ist erwartet.")
                self._batch = None
            else: self._batch = None
            if self._batch: self.current_mesh_source_name = obj_name
        except Exception as e:
            print(f"FEHLER [{_helper_module_name} GPUMeshGhost] Batch Erstellung nach Wrapper: {e}"); self._batch = None
    
    def update_mesh_from_object(self, obj_to_ghostify: bpy.types.Object):
        if not obj_to_ghostify:
            if self._batch: self._batch = None; self.current_mesh_source_name = None
            return

        if self._batch is None or self.current_mesh_source_name != obj_to_ghostify.name:
            # Hier könnte man einen Hash-Vergleich einfügen, wenn performancekritisch.
            # Für den Moment ist der Namensvergleich und die Neuberechnung bei Bedarf ausreichend.
            self._generate_batch_from_object(obj_to_ghostify)
        
    def set_transform(self, matrix: Matrix):
        self.transform_matrix = matrix if matrix else Matrix.Identity(4)

    def update_appearance(self, color=None):
        if color is not None:
            self.color_uniform_data = list(color)

    def set_visible(self, visible: bool): self._is_visible = visible
    def get_is_visible(self): return self._is_visible

    def _draw_callback(self):
        if not self._is_visible or not self._batch or not self.shader: return
        self.shader.bind(); self.shader.uniform_float("color", self.color_uniform_data)
        gpu.matrix.push(); gpu.matrix.multiply_matrix(self.transform_matrix)
        original_depth_test = gpu.state.depth_test_get(); original_blend = gpu.state.blend_get()
        original_depth_mask = gpu.state.depth_mask_get()
        
        if len(self.color_uniform_data) == 4 and self.color_uniform_data[3] < 1.0:
            gpu.state.blend_set('ALPHA')
            gpu.state.depth_mask_set(False)
        else:
            gpu.state.blend_set('NONE')
            gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set('LESS_EQUAL')

        try: self._batch.draw(self.shader)
        except Exception as e: print(f"ERROR [{_helper_module_name} GPUMeshGhost] Draw: {e}")
        
        gpu.state.depth_mask_set(original_depth_mask); gpu.state.blend_set(original_blend)
        gpu.state.depth_test_set(original_depth_test); gpu.matrix.pop()

    def enable_drawing(self):
        if self._draw_handler is None:
            self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(self._draw_callback, (), 'WINDOW', 'POST_VIEW')
        self.set_visible(True)
    def disable_drawing(self):
        if self._draw_handler:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, 'WINDOW'); self._draw_handler = None
        self.set_visible(False)
    def cleanup(self): self.disable_drawing(); self._batch = None; self.current_mesh_source_name = None