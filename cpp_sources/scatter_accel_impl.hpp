#ifndef SCATTER_ACCEL_IMPL_HPP
#define SCATTER_ACCEL_IMPL_HPP

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <vector>
#include <string>
#include <stdexcept> // Für std::runtime_error

// Forward declarations für Blender GPU Typen
struct GPUShader;
struct GPUVertBuf;
struct GPUIndexBuf;
struct GPUBatch;
struct GPUTexture;


#ifndef M_PI
    #define M_PI 3.14159265358979323846
#endif

namespace py = pybind11;

namespace ScatterAccelImpl {

// --- BESTEHENDE STRUKTUREN ---
struct GpuVertexData { // Deine bestehende Struktur
    py::array_t<float> positions;
    py::array_t<unsigned int> indices;
};

// --- NEUE STRUKTUR für Master Mesh Daten (inkl. UVs) ---
struct MasterMeshData {
    py::array_t<float> positions; // Nx3 (x,y,z)
    py::array_t<float> uvs;       // Nx2 (u,v)
    py::array_t<unsigned int> indices; // Mx3 (Dreiecks-Indizes)
};

// --- GPU HANDLES STRUKTUR für interne GPU Objekte (Modernisiert) ---
// Note: Disabled due to linking complexity. GPU functionality will be implemented
// through Python API when running in Blender.
struct GpuHandles {
    void* shader_ptr = nullptr;    // GPUShader *shader_ptr = nullptr;
    void* vbo_master_mesh_data = nullptr; // blender::gpu::VertBuf *vbo_master_mesh_data = nullptr;
    void* vbo_instance_data = nullptr; // blender::gpu::VertBuf *vbo_instance_data = nullptr;
    void* ibo_master_mesh = nullptr; // blender::gpu::IndexBuf *ibo_master_mesh = nullptr;
    void* batch = nullptr; // blender::gpu::Batch *batch = nullptr;

    int loc_viewMatrix = -1;
    int loc_projectionMatrix = -1;
    int loc_time = -1;
    int loc_sampler_albedo = -1;
    int loc_sampler_emissive = -1;
    
    unsigned int num_master_vertices = 0;
    unsigned int num_master_indices = 0;
    bool uses_indices = false;
};

// --- BESTEHENDE FUNKTIONSDEKLARATIONEN ---
std::vector<std::string> analyze_objects(const std::vector<py::dict>& objects, bool enable_rigidbody);
py::dict calculate_random_transforms_cpp(const py::dict& settings);
py::list analyze_scatter_objects_for_processing(
    const py::list& python_objects_data,
    const py::dict& python_processing_settings);
py::dict analyze_single_object_for_processing(
    const py::dict& python_single_object_data,
    const py::dict& python_processing_settings);
py::list analyze_objects_for_static_bake(
    const py::list& python_object_names,
    const std::string& target_static_collection_name);
void mark_for_deletion_cpp(const std::string& marker_name);
py::list get_marked_garbage_cpp();
void clear_garbage_cpp();
void flush_marked_objects_cpp(py::object bpy_data_objects_param);
py::list analyze_objects_for_rb_setup_cpp(const py::list& object_names_py);
bool configure_batch_rigidbody_properties_cpp(
    const py::list& object_names_py,
    const py::dict& target_rb_settings_py);
GpuVertexData generate_circle_marker_gpu_data_cpp(float radius, int segments);
GpuVertexData prepare_mesh_gpu_data_from_flat_arrays_cpp( // Deine bestehende Funktion
    py::array_t<float, py::array::c_style | py::array::forcecast> flat_vertex_cos_py,
    py::array_t<int, py::array::c_style | py::array::forcecast> flat_loop_triangle_indices_py,
    size_t num_actual_vertices,
    size_t num_loop_triangles);

// --- NEUE FUNKTIONSDEKLARATION für MasterMeshData ---
MasterMeshData prepare_master_mesh_data_from_py_arrays_cpp( // Für GpuInstancer
    py::array_t<float, py::array::c_style | py::array::forcecast> flat_vertex_cos_py,
    py::array_t<float, py::array::c_style | py::array::forcecast> flat_vertex_uvs_py,
    py::array_t<int, py::array::c_style | py::array::forcecast> flat_loop_triangle_indices_py,
    size_t num_actual_vertices,
    size_t num_loop_triangles);


// --- NEUE GPU INSTANCER KLASSE DEKLARATION ---
class GpuInstancer {
public:
    GpuInstancer(const std::string& shader_name_py);
    ~GpuInstancer();

    GpuInstancer(const GpuInstancer&) = delete;
    GpuInstancer& operator=(const GpuInstancer&) = delete;
    GpuInstancer(GpuInstancer&&) = delete;
    GpuInstancer& operator=(GpuInstancer&&) = delete;

    void setup_master_mesh(const MasterMeshData& master_mesh_data, int initial_max_instances);
    
    void update_instance_transforms(
        py::array_t<float, py::array::c_style | py::array::forcecast> instance_matrices_flat,
        int num_instances
    );

    void draw(
        int num_instances_to_render,
        py::array_t<float, py::array::c_style | py::array::forcecast> view_matrix_flat,
        py::array_t<float, py::array::c_style | py::array::forcecast> projection_matrix_flat,
        float current_time,
        PyObject *py_texture_albedo_obj, 
        PyObject *py_texture_emissive_obj 
    );
    
    void cleanup();

    // --- PHASE 1.1 ERWEITERUNGEN: Neue Instance Management Methoden ---
    int add_instance(py::array_t<float, py::array::c_style | py::array::forcecast> transform_matrix_flat);
    void update_instance(int instance_index, py::array_t<float, py::array::c_style | py::array::forcecast> transform_matrix_flat);
    py::array_t<float> get_all_instance_matrices() const;
    void clear_instances();
    void upload_transforms_to_gpu();
    void set_ghost_mode(bool enabled, int ghost_instance_index = -1);
    
    // Getter für aktuellen Zustand
    int get_instance_count() const { return static_cast<int>(instance_matrices_cpu_.size()); }
    bool is_ghost_mode_enabled() const { return ghost_mode_enabled_; }
    int get_ghost_instance_index() const { return ghost_instance_index_; }

private:
    std::string shader_name_;
    GpuHandles handles_; // Interne GPU Objekte und Locations
    
    // --- PHASE 1.1 ERWEITERUNGEN: Neue Datenstrukturen ---
    std::vector<std::vector<float>> instance_matrices_cpu_; // CPU-Kopie aller Instance-Matrices (16 floats pro Matrix)
    bool ghost_mode_enabled_ = false;
    int ghost_instance_index_ = -1; // Index der Ghost-Instance (-1 = keine Ghost-Instance)
};

} // namespace ScatterAccelImpl

#endif // SCATTER_ACCEL_IMPL_HPP