// Pybind11-Includes, die für die Implementierung und Moduldefinition benötigt werden.
// Einige davon könnten bereits durch scatter_accel_impl.hpp transitiv inkludiert sein,
// aber explizite Includes hier können die Klarheit und Wartbarkeit verbessern.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <pybind11/operators.h> // Für Operatoren, falls später benötigt

// Standard C++ Bibliotheken für die Implementierungen
#include <vector>
#include <string>
#include <random>
#include <cmath>   // Für std::cos, std::sin, M_PI
#include <chrono>  // Für den Zufallszahlengenerator-Seed
#include <map>
#include <algorithm> // Für std::find, std::swap, std::max
#include <stdexcept> // Für std::runtime_error
#include <cstring>   // Für std::memcpy

// Blender Core Headers (nur was wirklich gebraucht wird)
#include "blenlib/BLI_utildefines.h"
#include "guardedalloc/MEM_guardedalloc.h"

// NOTE: GPU headers disabled due to linking complexity
// We'll implement GPU functionality through Python API when running in Blender
// #include "GPU_batch.hh"
// #include "GPU_shader.hh"
// #include "GPU_texture.hh"
// #include "GPU_vertex_buffer.hh"
// #include "GPU_index_buffer.hh"
// #include "GPU_vertex_format.hh"
// #include "GPU_state.hh"
// #include "GPU_context.hh"
// #include "GPU_common_types.hh"

// Blender GPU Services (kritisch für GPU-Funktionen!)
// services_gpu.h ist für Cycles OSL, nicht für die allgemeine GPU-API
// #include "services_gpu.h"

// Blender Python GPU Bindings  
// #include "python/gpu/gpu_py_texture.hh"
// Sicherstellen, dass M_PI definiert ist (doppelt hält besser, falls Header nicht alles abdeckt oder allein kompiliert wird)
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// Eigenen Header einbinden, der GpuVertexData und Funktionsdeklarationen enthält
#include "scatter_accel_impl.hpp" 

// Alias für den pybind11 Namespace
namespace py = pybind11;

// Namespace für die C++ Implementierungsdetails
namespace ScatterAccelImpl {

// Die GpuVertexData Struktur ist jetzt in "scatter_accel_impl.hpp" definiert.
// Die MasterMeshData Struktur ist jetzt in "scatter_accel_impl.hpp" definiert.

// --- Bestehende Test-Funktion ---
std::vector<std::string> analyze_objects(const std::vector<py::dict>& objects, bool enable_rigidbody) {
    std::vector<std::string> results;
    results.reserve(objects.size());
    for (const auto& obj_dict : objects) {
        std::string name = "[Name N/A]";
        if (obj_dict.contains("name") && !obj_dict["name"].is_none()) {
            try { name = obj_dict["name"].cast<std::string>(); } catch (const py::cast_error&) {}
        }
        std::string mesh_name = "[Mesh N/A]";
        if (obj_dict.contains("mesh_name") && !obj_dict["mesh_name"].is_none()) {
            try { mesh_name = obj_dict["mesh_name"].cast<std::string>(); } catch (const py::cast_error&) {}
        } else if (obj_dict.contains("mesh") && !obj_dict["mesh"].is_none()) { // Fallback für "mesh"
            try { mesh_name = obj_dict["mesh"].cast<std::string>(); } catch (const py::cast_error&) {}
        }
        
        std::string result_str = "Processed: " + name + " with mesh: " + mesh_name;
        if (enable_rigidbody) {
            result_str += " [RigidBody]";
        }
        results.push_back(result_str);
    }
    return results;
}

// --- Bestehende Funktion für zufällige Transformationen ---
py::dict calculate_random_transforms_cpp(const py::dict& settings) {
    float rot_x_min_deg = 0.0f, rot_x_max_deg = 0.0f;
    float rot_y_min_deg = 0.0f, rot_y_max_deg = 0.0f;
    float rot_z_min_deg = 0.0f, rot_z_max_deg = 0.0f;
    float scale_min = 1.0f, scale_max = 1.0f;
    try {
        if (settings.contains("rot_x_min_deg")) rot_x_min_deg = settings["rot_x_min_deg"].cast<float>();
        if (settings.contains("rot_x_max_deg")) rot_x_max_deg = settings["rot_x_max_deg"].cast<float>();
        if (settings.contains("rot_y_min_deg")) rot_y_min_deg = settings["rot_y_min_deg"].cast<float>();
        if (settings.contains("rot_y_max_deg")) rot_y_max_deg = settings["rot_y_max_deg"].cast<float>();
        if (settings.contains("rot_z_min_deg")) rot_z_min_deg = settings["rot_z_min_deg"].cast<float>();
        if (settings.contains("rot_z_max_deg")) rot_z_max_deg = settings["rot_z_max_deg"].cast<float>();
        if (settings.contains("scale_min")) scale_min = settings["scale_min"].cast<float>();
        if (settings.contains("scale_max")) scale_max = settings["scale_max"].cast<float>();
    } catch (const py::cast_error& e) {
        // py::print("Warning: Cast error while reading transform settings:", e.what());
    }

    static thread_local std::mt19937 gen(static_cast<unsigned int>(std::chrono::system_clock::now().time_since_epoch().count()));

    if (rot_x_min_deg > rot_x_max_deg) std::swap(rot_x_min_deg, rot_x_max_deg);
    if (rot_y_min_deg > rot_y_max_deg) std::swap(rot_y_min_deg, rot_y_max_deg);
    if (rot_z_min_deg > rot_z_max_deg) std::swap(rot_z_min_deg, rot_z_max_deg);
    if (scale_min > scale_max) std::swap(scale_min, scale_max);
    if (scale_min < 0.001f) scale_min = 0.001f; 
    if (scale_max < 0.001f) scale_max = 0.001f; 

    std::uniform_real_distribution<float> rot_x_dist(rot_x_min_deg, rot_x_max_deg);
    std::uniform_real_distribution<float> rot_y_dist(rot_y_min_deg, rot_y_max_deg);
    std::uniform_real_distribution<float> rot_z_dist(rot_z_min_deg, rot_z_max_deg);
    std::uniform_real_distribution<float> scale_dist(scale_min, scale_max);

    float rand_rot_x_deg = rot_x_dist(gen);
    float rand_rot_y_deg = rot_y_dist(gen);
    float rand_rot_z_deg = rot_z_dist(gen);
    float rand_scale_uniform = scale_dist(gen);

    float deg_to_rad_factor = static_cast<float>(M_PI) / 180.0f;
    float rand_rot_x_rad = rand_rot_x_deg * deg_to_rad_factor;
    float rand_rot_y_rad = rand_rot_y_deg * deg_to_rad_factor;
    float rand_rot_z_rad = rand_rot_z_deg * deg_to_rad_factor;

    py::dict result;
    result["rotation_euler_rad"] = py::make_tuple(rand_rot_x_rad, rand_rot_y_rad, rand_rot_z_rad);
    result["scale_uniform"] = rand_scale_uniform; 
    return result;
}

// --- Bestehende Funktion für die Analyse der Scatter-Objekte für den Instance Operator (Batch) ---
py::list analyze_scatter_objects_for_processing(
    const py::list& python_objects_data,
    const py::dict& python_processing_settings) {
    py::list instructions_for_python;

    bool mode_is_instancing = false;
    try {
        if (python_processing_settings.contains("mode_is_instancing")) {
            mode_is_instancing = python_processing_settings["mode_is_instancing"].cast<bool>();
        }
    } catch (const py::cast_error&) {}


    bool apply_rigidbody_static = false;
    try {
        if (python_processing_settings.contains("apply_rigidbody_static")) {
            apply_rigidbody_static = python_processing_settings["apply_rigidbody_static"].cast<bool>();
        }
    } catch (const py::cast_error&) {}

    std::string instance_collection_name = "UnknownInstanceCol";
    try {
        if (python_processing_settings.contains("instance_collection_name")) {
            instance_collection_name = python_processing_settings["instance_collection_name"].cast<std::string>();
        }
    } catch (const py::cast_error&) {}

    std::string static_collection_name = "UnknownStaticCol";
    try {
        if (python_processing_settings.contains("static_collection_name")) {
            static_collection_name = python_processing_settings["static_collection_name"].cast<std::string>();
        }
    } catch (const py::cast_error&) {}

    std::string instance_name_suffix = "_inst";
    try {
        if (python_processing_settings.contains("instance_name_base_suffix")) {
            instance_name_suffix = python_processing_settings["instance_name_base_suffix"].cast<std::string>();
        }
    } catch (const py::cast_error&) {}

    for (const auto& obj_data_handle : python_objects_data) {
        py::dict obj_data;
        try {
            obj_data = obj_data_handle.cast<py::dict>();
        } catch (const py::cast_error& e) {
            py::dict error_instruction;
            error_instruction["action"] = "SKIP";
            error_instruction["original_name"] = "[CastErrorToObjectData]";
            error_instruction["reason"] = "Failed to cast object data to dict.";
            instructions_for_python.append(error_instruction);
            continue;
        }
    
        py::dict instruction;
        std::string original_name = "[UnknownObjName]";
        try {
            if (obj_data.contains("name") && !obj_data["name"].is_none()) {
            original_name = obj_data["name"].cast<std::string>();
            }
        } catch (const py::cast_error&) {}
        instruction["original_name"] = original_name;

        if (mode_is_instancing) {
            bool has_rigidbody = false; 
            try {
                if (obj_data.contains("has_rigidbody")) {
                    has_rigidbody = obj_data["has_rigidbody"].cast<bool>();
                }
            } catch (const py::cast_error&) {}

            if (has_rigidbody) { 
                instruction["action"] = "SKIP";
                instruction["reason"] = "Original already has Rigid Body, skipping for instancing.";
            } else {
                instruction["action"] = "CREATE_INSTANCE_AND_DELETE_ORIGINAL";
                instruction["new_instance_name_base"] = original_name + instance_name_suffix;
                
                std::string mesh_to_instance_val = "[UnknownMesh]";
                try {
                    if (obj_data.contains("mesh_name") && !obj_data["mesh_name"].is_none()){
                        mesh_to_instance_val = obj_data["mesh_name"].cast<std::string>();
                    }
                } catch (const py::cast_error&) {}
                instruction["mesh_to_instance"] = mesh_to_instance_val;
                
                bool matrix_ok = false;
                if (obj_data.contains("matrix_world") && !obj_data["matrix_world"].is_none()){
                    try { 
                        instruction["matrix_world"] = obj_data["matrix_world"].cast<py::list>(); 
                        matrix_ok = true;
                    } catch (const py::cast_error&) {}
                }
                if (!matrix_ok) {
                    instruction["action"] = "SKIP";
                    instruction["reason"] = "Missing or invalid matrix_world for instancing.";
                }
                instruction["target_collection_name"] = instance_collection_name;
            }
        } else { // Static / Rigid Body Mode
            instruction["action"] = "MOVE_TO_STATIC_COLLECTION"; 
            instruction["target_collection_name"] = static_collection_name; 
            
            bool has_rigidbody = false; 
            try {
                if (obj_data.contains("has_rigidbody")) {
                    has_rigidbody = obj_data["has_rigidbody"].cast<bool>();
                }
            } catch (const py::cast_error&) {}

            instruction["add_rigidbody"] = (apply_rigidbody_static && !has_rigidbody);
        }
        instructions_for_python.append(instruction);
    }
    return instructions_for_python;
}

// --- Funktion für die "On-the-fly"-Analyse eines einzelnen Markers ---
py::dict analyze_single_object_for_processing(
    const py::dict& python_single_object_data,
    const py::dict& python_processing_settings) {
    py::dict instruction; 

    bool mode_is_instancing = false;
    try {
        if (python_processing_settings.contains("mode_is_instancing")) {
            mode_is_instancing = python_processing_settings["mode_is_instancing"].cast<bool>();
        }
    } catch (const py::cast_error&) {}

    bool apply_rigidbody_static = false;
    try {
        if (python_processing_settings.contains("apply_rigidbody_static")) {
            apply_rigidbody_static = python_processing_settings["apply_rigidbody_static"].cast<bool>();
        }
    } catch (const py::cast_error&) {}

    std::string instance_collection_name = "UnknownInstanceCol";
    try {
        if (python_processing_settings.contains("instance_collection_name")) {
            instance_collection_name = python_processing_settings["instance_collection_name"].cast<std::string>();
        }
    } catch (const py::cast_error&) {}

    std::string static_collection_name = "UnknownStaticCol";
    try {
        if (python_processing_settings.contains("static_collection_name")) {
            static_collection_name = python_processing_settings["static_collection_name"].cast<std::string>();
        }
    } catch (const py::cast_error&) {}

    std::string instance_name_suffix = "_inst";
    try {
        if (python_processing_settings.contains("instance_name_base_suffix")) {
            instance_name_suffix = python_processing_settings["instance_name_base_suffix"].cast<std::string>();
        }
    } catch (const py::cast_error&) {}

    std::string original_marker_name = "[UnknownMarkerName]";
    try {
        if (python_single_object_data.contains("original_marker_name") && !python_single_object_data["original_marker_name"].is_none()) {
        original_marker_name = python_single_object_data["original_marker_name"].cast<std::string>();
        }
    } catch (const py::cast_error&) {}
    instruction["original_marker_name"] = original_marker_name;

    std::string source_mesh_name_for_instance = "[UnknownSourceMesh]";
    try {
        if (python_single_object_data.contains("source_mesh_name") && !python_single_object_data["source_mesh_name"].is_none()) {
        source_mesh_name_for_instance = python_single_object_data["source_mesh_name"].cast<std::string>();
        }
    } catch (const py::cast_error&) {}

    if (mode_is_instancing) {
        instruction["action"] = "CREATE_INSTANCE_FROM_SOURCE"; 
        instruction["new_instance_name_base"] = original_marker_name + instance_name_suffix;
        instruction["mesh_to_instance"] = source_mesh_name_for_instance;
        
        bool matrix_ok = false;
        if (python_single_object_data.contains("matrix_world") && !python_single_object_data["matrix_world"].is_none()){
            try { 
                instruction["matrix_world"] = python_single_object_data["matrix_world"].cast<py::list>(); 
                matrix_ok = true;
            } catch (const py::cast_error&) {}
        }
        if (!matrix_ok) {
            instruction["action"] = "SKIP";
            instruction["reason"] = "Missing or invalid matrix_world for instancing.";
        }
        instruction["target_collection_name"] = instance_collection_name;

    } else { 
        if (apply_rigidbody_static) {
            instruction["action"] = "CONVERT_MARKER_TO_STATIC_RIGID";
            instruction["add_rigidbody"] = true;
        } else {
            instruction["action"] = "CONVERT_MARKER_TO_STATIC";
            instruction["add_rigidbody"] = false;
        }
        instruction["target_collection_name"] = static_collection_name;
        if (python_single_object_data.contains("matrix_world") && !python_single_object_data["matrix_world"].is_none()){
            try { instruction["matrix_world"] = python_single_object_data["matrix_world"].cast<py::list>(); } catch (const py::cast_error&) {}
        }
    }

    return instruction;
}

// === BESTEHENDE FUNKTION: ANALYZE OBJECTS FOR STATIC BAKE ===
py::list analyze_objects_for_static_bake(
    const py::list& python_object_names,
    const std::string& target_static_collection_name) {
    py::list instructions;
    py::module_ bpy_data_module; 
    py::object bpy_data_objects;

    try {
        bpy_data_module = py::module_::import("bpy.data");
        bpy_data_objects = bpy_data_module.attr("objects");
    } catch (const py::error_already_set& e) {
        if (PyErr_Occurred()) PyErr_Clear(); 
        return instructions; 
    }

    for (const auto& name_handle : python_object_names) {
        std::string obj_name;
        try {
            obj_name = name_handle.cast<std::string>();
        } catch (const py::cast_error&) {
            continue; 
        }

        py::object obj;
        try {
            obj = bpy_data_objects.attr("get")(obj_name);
        } catch (const py::error_already_set& e) {
            if (PyErr_Occurred()) PyErr_Clear();
            continue; 
        }
        
        if (obj.is_none()) continue; 

        py::dict instruction;
        instruction["name"] = obj_name;

        bool needs_single_user = false;
        try {
            py::object obj_data = obj.attr("data");
            if (!obj_data.is_none()) { 
                py::object users_attr = obj_data.attr("users"); 
                if (!users_attr.is_none() && users_attr.cast<int>() > 1) {
                    needs_single_user = true;
                }
            }
        } catch (const py::error_already_set& e) { if (PyErr_Occurred()) PyErr_Clear(); }
        catch (const std::exception&) {} 
        instruction["needs_make_single_user"] = needs_single_user;

        bool has_rigidbody = false;
        try {
            py::object rb = obj.attr("rigid_body");
            if (!rb.is_none()) {
                has_rigidbody = true;
            }
        } catch (const py::error_already_set& e) { if (PyErr_Occurred()) PyErr_Clear(); }
        catch (const std::exception&) {}
        instruction["has_rigidbody"] = has_rigidbody;

        instruction["target_collection"] = target_static_collection_name;

        py::list current_collections_py;
        try {
            py::object users_collection_attr = obj.attr("users_collection");
            if(!users_collection_attr.is_none()){
                for (const auto& col_handle : users_collection_attr) {
                    try {
                        py::object col = col_handle.cast<py::object>();
                        if (!col.is_none()) {
                            current_collections_py.append(col.attr("name").cast<std::string>());
                        }
                    } catch (const py::error_already_set& e) { if (PyErr_Occurred()) PyErr_Clear(); }
                    catch (const std::exception&) {}
                }
            }
        } catch (const py::error_already_set& e) { if (PyErr_Occurred()) PyErr_Clear(); }
        catch (const std::exception&) {}
        instruction["current_collections"] = current_collections_py;

        instructions.append(instruction);
    }

    return instructions;
}

// === START: GARBAGE COLLECTION FUNKTIONEN ===
static std::vector<std::string> cpp_marker_garbage_list; 
void mark_for_deletion_cpp(const std::string& marker_name) {
    if (std::find(cpp_marker_garbage_list.begin(), cpp_marker_garbage_list.end(), marker_name) == cpp_marker_garbage_list.end()) {
        cpp_marker_garbage_list.push_back(marker_name);
    }
}
py::list get_marked_garbage_cpp() {
    py::list result;
    for (const auto& name : cpp_marker_garbage_list) {
        result.append(name);
    }
    return result;
}
void clear_garbage_cpp() {
    cpp_marker_garbage_list.clear();
}
void flush_marked_objects_cpp(py::object bpy_data_objects_param) {
    std::vector<std::string> to_delete_list = cpp_marker_garbage_list; 
    cpp_marker_garbage_list.clear();
    for (const auto& name : to_delete_list) {
        try {
            py::object obj_to_delete = bpy_data_objects_param.attr("get")(name);
            if (!obj_to_delete.is_none()) { 
                bpy_data_objects_param.attr("remove")(obj_to_delete, py::arg("do_unlink") = true);
            }
        } catch (const py::error_already_set& e) {
            if (PyErr_Occurred()) PyErr_Clear();
        } catch (const std::exception& e_std) {
        } catch (...) {
        }
    }
}
// === ENDE: GARBAGE COLLECTION FUNKTIONEN ===

// === START: FUNKTIONEN FÜR ENHANCED PHYSICS BAKE ===
py::list analyze_objects_for_rb_setup_cpp(const py::list& object_names_py) {
    py::list analysis_results_py;
    py::module_ bpy_data;
    py::object bpy_data_objects;
    try {
        bpy_data = py::module_::import("bpy.data");
        bpy_data_objects = bpy_data.attr("objects");
    } catch (const py::error_already_set& e) {
        if (PyErr_Occurred()) PyErr_Clear();
        return analysis_results_py; 
    }

    for (const auto& name_handle : object_names_py) {
        std::string obj_name;
        try {
            obj_name = name_handle.cast<std::string>();
        } catch (const py::cast_error& e) {
            continue; 
        }

        py::object obj;
        try {
            obj = bpy_data_objects.attr("get")(obj_name);
        } catch (const py::error_already_set& e) { 
            if (PyErr_Occurred()) PyErr_Clear();
            continue; 
        }
        
        if (obj.is_none()) {
            continue; 
        }

        py::dict result_dict;
        result_dict["name"] = obj_name;

        bool needs_single_user = false;
        try {
            py::object obj_data = obj.attr("data");
            if (!obj_data.is_none()) {
                py::object users_val = obj_data.attr("users");
                if (!users_val.is_none()) { 
                    if (users_val.cast<int>() > 1) {
                        needs_single_user = true;
                    }
                }
            }
        } catch (const py::error_already_set& e) { if (PyErr_Occurred()) PyErr_Clear(); }
        catch (const std::exception& )   { }
        result_dict["needs_make_single_user"] = needs_single_user;

        py::object rb = py::none(); 
        try {
            if (py::hasattr(obj, "rigid_body")) { 
                rb = obj.attr("rigid_body"); 
            }
        } catch (const py::error_already_set& e) { if (PyErr_Occurred()) PyErr_Clear(); }
        catch (const std::exception& )   {}

        if (rb.is_none()) {
            result_dict["has_rigidbody_component"] = false;
            result_dict["original_rb_settings"] = py::none();
        } else {
            result_dict["has_rigidbody_component"] = true;
            py::dict original_settings_dict;
            try {
                auto get_attr_safe_str = [&](const py::object& o, const char* attr_name, const std::string& def_val) {
                    if (py::hasattr(o, attr_name)) {
                        py::object attr_val = o.attr(attr_name);
                        if (!attr_val.is_none()) return attr_val.cast<std::string>();
                    } return def_val; };
                auto get_attr_safe_float = [&](const py::object& o, const char* attr_name, float def_val) {
                    if (py::hasattr(o, attr_name)) {
                        py::object attr_val = o.attr(attr_name);
                        if (!attr_val.is_none()) return attr_val.cast<float>();
                    } return def_val; };
                auto get_attr_safe_bool = [&](const py::object& o, const char* attr_name, bool def_val) {
                    if (py::hasattr(o, attr_name)) {
                        py::object attr_val = o.attr(attr_name);
                        if (!attr_val.is_none()) return attr_val.cast<bool>();
                    } return def_val; };
                
                original_settings_dict["type"] = get_attr_safe_str(rb, "type", "ACTIVE");
                original_settings_dict["mass"] = get_attr_safe_float(rb, "mass", 1.0f);
                original_settings_dict["collision_shape"] = get_attr_safe_str(rb, "collision_shape", "CONVEX_HULL");
                original_settings_dict["collision_margin"] = get_attr_safe_float(rb, "collision_margin", 0.04f);
                original_settings_dict["linear_damping"] = get_attr_safe_float(rb, "linear_damping", 0.1f);
                original_settings_dict["angular_damping"] = get_attr_safe_float(rb, "angular_damping", 0.1f);
                original_settings_dict["kinematic"] = get_attr_safe_bool(rb, "kinematic", false);
                original_settings_dict["enabled"] = get_attr_safe_bool(rb, "enabled", true); 
                original_settings_dict["use_deactivation"] = get_attr_safe_bool(rb, "use_deactivation", true);
                original_settings_dict["use_start_deactivated"] = get_attr_safe_bool(rb, "use_start_deactivated", false);
                if (py::hasattr(rb, "friction")) original_settings_dict["friction"] = get_attr_safe_float(rb, "friction", 0.5f);
                if (py::hasattr(rb, "restitution")) original_settings_dict["restitution"] = get_attr_safe_float(rb, "restitution", 0.5f);

            } catch (const py::error_already_set& e) { if (PyErr_Occurred()) PyErr_Clear(); original_settings_dict.clear(); }
            catch (const std::exception& ) { original_settings_dict.clear(); }
            
            if (!original_settings_dict.empty()) { result_dict["original_rb_settings"] = original_settings_dict; }
            else { result_dict["original_rb_settings"] = py::none(); }
        }
        analysis_results_py.append(result_dict);
    }
    return analysis_results_py;
}

bool configure_batch_rigidbody_properties_cpp(
    const py::list& object_names_py,
    const py::dict& target_rb_settings_py) {
    py::module_ bpy_data;
    py::object bpy_data_objects;
    try {
        bpy_data = py::module_::import("bpy.data");
        bpy_data_objects = bpy_data.attr("objects");
    } catch (const py::error_already_set& e) {
        if (PyErr_Occurred()) PyErr_Clear();
        return false; 
    }

    bool all_successful = true;

    auto get_setting = [&](const char* key, auto default_value) {
        if (target_rb_settings_py.contains(key)) {
            try {
                py::object val = target_rb_settings_py[key];
                if (!val.is_none()) return val.cast<decltype(default_value)>();
            } catch (const py::cast_error&) { }
        } return default_value; };

    const std::string target_type     = get_setting("type", std::string("ACTIVE"));
    const bool target_kinematic       = get_setting("kinematic", false);
    const bool target_enabled         = get_setting("enabled", true);
    const bool target_use_start_deactivated = get_setting("use_start_deactivated", false);
    float mass                        = get_setting("mass", 1.0f);
    std::string shape                 = get_setting("collision_shape", std::string("CONVEX_HULL"));
    float margin                      = get_setting("collision_margin", 0.001f); 
    float lin_damp                    = get_setting("linear_damping", 0.6f); 
    float ang_damp                    = get_setting("angular_damping", 0.6f);
    bool use_deact                    = get_setting("use_deactivation", true);
    float friction                    = get_setting("friction", 0.5f);
    float restitution                 = get_setting("restitution", 0.5f);

    for (const auto& name_handle : object_names_py) {
        std::string obj_name;
        try { obj_name = name_handle.cast<std::string>(); } 
        catch (const py::cast_error& ) { all_successful = false; continue; }

        py::object obj;
        try { obj = bpy_data_objects.attr("get")(obj_name); } 
        catch (const py::error_already_set& e) { if (PyErr_Occurred()) PyErr_Clear(); all_successful = false; continue; }

        if (obj.is_none()) { all_successful = false; continue; }

        py::object rb_comp = py::none();
        if (py::hasattr(obj, "rigid_body")) {
            rb_comp = obj.attr("rigid_body");
        }

        if (rb_comp.is_none()) { all_successful = false; continue; } 

        try {
            auto set_attr_safe = [&](const char* attr_name, const auto& value) {
                if (py::hasattr(rb_comp, attr_name)) {
                    try { rb_comp.attr(attr_name) = value; } 
                    catch (const py::error_already_set& e) { 
                        if (PyErr_Occurred()) PyErr_Clear(); 
                        all_successful = false; 
                    }
                } else {
                    all_successful = false; 
                }
            };

            set_attr_safe("type", target_type);
            set_attr_safe("kinematic", target_kinematic);
            set_attr_safe("enabled", target_enabled); 
            set_attr_safe("use_start_deactivated", target_use_start_deactivated);
            set_attr_safe("mass", mass);
            set_attr_safe("collision_shape", shape);
            set_attr_safe("collision_margin", margin);
            set_attr_safe("linear_damping", lin_damp);
            set_attr_safe("angular_damping", ang_damp);
            set_attr_safe("use_deactivation", use_deact);
            set_attr_safe("friction", friction);
            set_attr_safe("restitution", restitution);

        } catch (const py::error_already_set& e ) { if (PyErr_Occurred()) PyErr_Clear(); all_successful = false; }
        catch (const std::exception& e_std) { all_successful = false; }
    }
    return all_successful;
}
// === ENDE: FUNKTIONEN FÜR ENHANCED PHYSICS BAKE ===

// === BESTEHENDE FUNKTIONEN FÜR GPU-DATENAUFBEREITUNG (GpuVertexData) ===
GpuVertexData generate_circle_marker_gpu_data_cpp(float radius, int segments) {
    segments = std::max(3, segments);
    int total_vertices = 1 + segments; 
    size_t num_lines = static_cast<size_t>(segments) * 2; 
    
    py::array_t<float> positions_py(std::vector<py::ssize_t>{static_cast<py::ssize_t>(total_vertices), static_cast<py::ssize_t>(3)});
    py::array_t<unsigned int> indices_py(std::vector<py::ssize_t>{static_cast<py::ssize_t>(num_lines), static_cast<py::ssize_t>(2)});

    auto pos_buf_info = positions_py.request(); 
    float* pos_ptr = static_cast<float*>(pos_buf_info.ptr);

    auto idx_buf_info = indices_py.request();
    unsigned int* idx_ptr = static_cast<unsigned int*>(idx_buf_info.ptr);

    pos_ptr[0] = 0.0f; 
    pos_ptr[1] = 0.0f; 
    pos_ptr[2] = 0.0f;

    for (int i = 0; i < segments; ++i) {
        float angle = static_cast<float>(i) / static_cast<float>(segments) * 2.0f * static_cast<float>(M_PI);
        size_t current_vertex_flat_offset = static_cast<size_t>(1 + i) * 3; 
        pos_ptr[current_vertex_flat_offset + 0] = radius * std::cos(angle);
        pos_ptr[current_vertex_flat_offset + 1] = radius * std::sin(angle);
        pos_ptr[current_vertex_flat_offset + 2] = 0.0f;
    }

    unsigned int center_idx_val = 0; 
    size_t current_idx_buffer_offset = 0; 
    for (int i = 0; i < segments; ++i) {
        unsigned int current_outer_idx_val = center_idx_val + 1 + i;
        unsigned int next_outer_idx_val = center_idx_val + 1 + ((i + 1) % segments); 
        
        idx_ptr[current_idx_buffer_offset++] = center_idx_val; 
        idx_ptr[current_idx_buffer_offset++] = current_outer_idx_val;

        idx_ptr[current_idx_buffer_offset++] = current_outer_idx_val; 
        idx_ptr[current_idx_buffer_offset++] = next_outer_idx_val;
    }

    return {positions_py, indices_py};
}

GpuVertexData prepare_mesh_gpu_data_from_flat_arrays_cpp(
    py::array_t<float, py::array::c_style | py::array::forcecast> flat_vertex_cos_py,
    py::array_t<int, py::array::c_style | py::array::forcecast> flat_loop_triangle_indices_py,
    size_t num_actual_vertices,
    size_t num_loop_triangles)
{
    py::buffer_info co_buf_info = flat_vertex_cos_py.request();
    py::buffer_info idx_buf_info = num_loop_triangles > 0 ? flat_loop_triangle_indices_py.request() : py::buffer_info();
    
    // Fall: Keine Vertices
    if (num_actual_vertices == 0) {
        py::array_t<float> empty_pos(std::vector<py::ssize_t>{0, static_cast<py::ssize_t>(3)}); // KORRIGIERT
        py::array_t<unsigned int> empty_idx(std::vector<py::ssize_t>{0, static_cast<py::ssize_t>(3)}); // KORRIGIERT
        return {empty_pos, empty_idx};
    }

    // Überprüfe die Größe des Koordinaten-Buffers
    if (co_buf_info.ndim != 1 || static_cast<size_t>(co_buf_info.shape[0]) != num_actual_vertices * 3) { 
        throw std::runtime_error("Mismatch: num_actual_vertices*3 (" + std::to_string(num_actual_vertices * 3) +
                                 ") != coordinate array size (" + std::to_string(co_buf_info.shape[0]) + ") or not 1D.");
    }

    // Positionen erstellen
    py::array_t<float> positions_py_shaped(std::vector<py::ssize_t>{static_cast<py::ssize_t>(num_actual_vertices), static_cast<py::ssize_t>(3)}); // KORRIGIERT
    float* pos_shaped_ptr = static_cast<float*>(positions_py_shaped.request().ptr);
    const float* co_src_ptr = static_cast<const float*>(co_buf_info.ptr);
    std::memcpy(pos_shaped_ptr, co_src_ptr, num_actual_vertices * 3 * sizeof(float));


    // Indizes erstellen
    py::array_t<unsigned int> indices_py_shaped_typed;
    if (num_loop_triangles > 0) {
        // Überprüfe die Größe des Index-Buffers (nur wenn idx_buf_info gültig ist)
        if (idx_buf_info.ndim != 1 || static_cast<size_t>(idx_buf_info.shape[0]) != num_loop_triangles * 3) { 
            throw std::runtime_error("Mismatch: num_loop_triangles*3 (" + std::to_string(num_loop_triangles * 3) +
                                     ") != index array size (" + std::to_string(idx_buf_info.shape[0]) + ") or not 1D.");
        }
        const int* idx_src_ptr = static_cast<const int*>(idx_buf_info.ptr);

        indices_py_shaped_typed = py::array_t<unsigned int>(std::vector<py::ssize_t>{static_cast<py::ssize_t>(num_loop_triangles), static_cast<py::ssize_t>(3)}); // KORRIGIERT
        unsigned int* idx_shaped_ptr = static_cast<unsigned int*>(indices_py_shaped_typed.request().ptr);

        for (size_t i = 0; i < num_loop_triangles * 3; ++i) {
            if (idx_src_ptr[i] < 0) {
                throw std::runtime_error("Negative vertex index found: " + std::to_string(idx_src_ptr[i]));
            }
            if (static_cast<size_t>(idx_src_ptr[i]) >= num_actual_vertices) {
                 throw std::runtime_error("Vertex index " + std::to_string(idx_src_ptr[i]) +
                                         " is out of bounds for " + std::to_string(num_actual_vertices) + " vertices.");
            }
            idx_shaped_ptr[i] = static_cast<unsigned int>(idx_src_ptr[i]);
        }
    } else { 
        indices_py_shaped_typed = py::array_t<unsigned int>(std::vector<py::ssize_t>{0, static_cast<py::ssize_t>(3)}); // KORRIGIERT
    }

    return {positions_py_shaped, indices_py_shaped_typed};
}

// === NEUE FUNKTION FÜR GPU-DATENAUFBEREITUNG (MasterMeshData) ===
MasterMeshData prepare_master_mesh_data_from_py_arrays_cpp(
    py::array_t<float, py::array::c_style | py::array::forcecast> flat_vertex_cos_py,
    py::array_t<float, py::array::c_style | py::array::forcecast> flat_vertex_uvs_py,
    py::array_t<int, py::array::c_style | py::array::forcecast> flat_loop_triangle_indices_py,
    size_t num_actual_vertices,
    size_t num_loop_triangles)
{
    MasterMeshData data;

    // Positions
    py::buffer_info co_buf_info = flat_vertex_cos_py.request();
    if (num_actual_vertices > 0) {
        if (co_buf_info.ndim != 1 || static_cast<size_t>(co_buf_info.shape[0]) != num_actual_vertices * 3) {
            throw std::runtime_error("Position data size mismatch. Expected " + 
                                     std::to_string(num_actual_vertices * 3) + " floats, got " + 
                                     std::to_string(co_buf_info.shape[0]));
        }
        data.positions = py::array_t<float>(std::vector<py::ssize_t>{static_cast<py::ssize_t>(num_actual_vertices), 3});
        std::memcpy(data.positions.mutable_data(), co_buf_info.ptr, num_actual_vertices * 3 * sizeof(float));
    } else {
        data.positions = py::array_t<float>(std::vector<py::ssize_t>{0, 3});
    }

    // UVs
    if (num_actual_vertices > 0) {
        py::buffer_info uv_buf_info = flat_vertex_uvs_py.request();
        // Check if the UV array contains valid data or is empty/invalid
        if (uv_buf_info.ptr != nullptr && uv_buf_info.ndim == 1 && 
            static_cast<size_t>(uv_buf_info.shape[0]) == num_actual_vertices * 2) {
            data.uvs = py::array_t<float>(std::vector<py::ssize_t>{static_cast<py::ssize_t>(num_actual_vertices), 2});
            std::memcpy(data.uvs.mutable_data(), uv_buf_info.ptr, num_actual_vertices * 2 * sizeof(float));
        } else { 
            // py::print("ScatterAccel Warning: UV data is missing or has incorrect dimensions for master mesh. Using default (0,0) UVs.");
            data.uvs = py::array_t<float>(std::vector<py::ssize_t>{static_cast<py::ssize_t>(num_actual_vertices), 2});
            std::memset(data.uvs.mutable_data(), 0, num_actual_vertices * 2 * sizeof(float));
        }
    } else { 
        data.uvs = py::array_t<float>(std::vector<py::ssize_t>{0, 2});
    }

    // Indices
    py::buffer_info idx_buf_info = flat_loop_triangle_indices_py.request();
    if (num_loop_triangles > 0) {
        if (idx_buf_info.ndim != 1 || static_cast<size_t>(idx_buf_info.shape[0]) != num_loop_triangles * 3) {
            throw std::runtime_error("Index data size mismatch. Expected " + 
                                     std::to_string(num_loop_triangles * 3) + " ints, got " + 
                                     std::to_string(idx_buf_info.shape[0]));
        }
        data.indices = py::array_t<unsigned int>(std::vector<py::ssize_t>{static_cast<py::ssize_t>(num_loop_triangles), 3});
        unsigned int* out_idx_ptr = data.indices.mutable_data();
        const int* in_idx_ptr = static_cast<const int*>(idx_buf_info.ptr);
        for (size_t i = 0; i < num_loop_triangles * 3; ++i) {
            if (in_idx_ptr[i] < 0 || (num_actual_vertices > 0 && static_cast<size_t>(in_idx_ptr[i]) >= num_actual_vertices) ) {
                 throw std::runtime_error("Invalid vertex index " + std::to_string(in_idx_ptr[i]) + 
                                         " for " + std::to_string(num_actual_vertices) + " vertices.");
            }
            out_idx_ptr[i] = static_cast<unsigned int>(in_idx_ptr[i]);
        }
    } else {
        data.indices = py::array_t<unsigned int>(std::vector<py::ssize_t>{0, 3});
    }
    return data;
}


// --- Implementierung der GpuInstancer Klasse ---
GpuInstancer::GpuInstancer(const std::string& shader_name_py) : shader_name_(shader_name_py) {
    handles_.shader_ptr = nullptr;
    handles_.vbo_master_mesh_data = nullptr; // Updated
    handles_.vbo_instance_data = nullptr;
    handles_.ibo_master_mesh = nullptr;
    handles_.batch = nullptr;
    handles_.loc_viewMatrix = -1;
    handles_.loc_projectionMatrix = -1;
    handles_.loc_time = -1;
    handles_.loc_sampler_albedo = -1;
    handles_.loc_sampler_emissive = -1;
    handles_.num_master_indices = 0;
    handles_.num_master_vertices = 0;
    handles_.uses_indices = false;
}

GpuInstancer::~GpuInstancer() {
    // Note: GPU cleanup disabled due to linking complexity
    // GPU resources will be managed through Python API when running in Blender
    cleanup();
}

void GpuInstancer::setup_master_mesh(const MasterMeshData& master_mesh_data, int initial_max_instances) {
    // Store master mesh data for later use
    py::buffer_info pos_info = master_mesh_data.positions.request();
    py::buffer_info uv_info = master_mesh_data.uvs.request(); 
    
    handles_.num_master_vertices = master_mesh_data.positions.shape(0);
    if (handles_.num_master_vertices == 0 && master_mesh_data.positions.size() > 0) {
         handles_.num_master_vertices = master_mesh_data.positions.shape(0);
    }
    if (handles_.num_master_vertices == 0) throw std::runtime_error("Master mesh has no vertices.");

    // Process indices if available
    py::buffer_info idx_info = master_mesh_data.indices.request();
    if (master_mesh_data.indices.size() > 0 && idx_info.ndim > 0 && idx_info.shape[0] > 0) {
        handles_.num_master_indices = master_mesh_data.indices.shape(0) * master_mesh_data.indices.shape(1); // num_tris * 3
        handles_.uses_indices = true;
    } else {
        handles_.num_master_indices = 0;
        handles_.uses_indices = false;
    }

    // Initialize instance data storage
    instance_matrices_cpu_.clear();
    instance_matrices_cpu_.reserve(initial_max_instances > 0 ? initial_max_instances : 1);
}

void GpuInstancer::update_instance_transforms(
    py::array_t<float, py::array::c_style | py::array::forcecast> instance_matrices_flat,
    int num_instances)
{
    if (num_instances < 0) return;
    py::buffer_info matrices_buf = instance_matrices_flat.request();
    if (matrices_buf.ndim != 1 || (num_instances > 0 && static_cast<size_t>(matrices_buf.shape[0]) != static_cast<size_t>(num_instances * 16))) {
        throw std::runtime_error("GpuInstancer::update_instance_transforms: Matrix data size/shape mismatch. Expected flat array of num_instances * 16 floats.");
    }
    
    // Store instance data for CPU-side processing
    instance_matrices_cpu_.clear();
    if (num_instances > 0) {
        const float* matrix_data = static_cast<const float*>(matrices_buf.ptr);
        for (int i = 0; i < num_instances; ++i) {
            std::vector<float> instance_matrix(16);
            const float* source_matrix = matrix_data + i * 16;
            std::copy(source_matrix, source_matrix + 16, instance_matrix.begin());
            instance_matrices_cpu_.push_back(instance_matrix);
        }
    }
}

void GpuInstancer::draw(
    int num_instances_to_render,
    py::array_t<float, py::array::c_style | py::array::forcecast> view_matrix_flat,
    py::array_t<float, py::array::c_style | py::array::forcecast> projection_matrix_flat,
    float current_time,
    PyObject *py_texture_albedo_obj, 
    PyObject *py_texture_emissive_obj)
{
    if (num_instances_to_render <= 0) return;
    
    // Note: GPU drawing is disabled due to linking complexity
    // Actual drawing will be implemented through Python API when running in Blender
    // For now, this function validates inputs and maintains state
    
    py::buffer_info view_info = view_matrix_flat.request();
    py::buffer_info proj_info = projection_matrix_flat.request();
    
    // Validate matrix dimensions
    if (view_info.ndim != 1 || view_info.shape[0] != 16) {
        throw std::runtime_error("View matrix must be 16 floats (4x4 matrix)");
    }
    if (proj_info.ndim != 1 || proj_info.shape[0] != 16) {
        throw std::runtime_error("Projection matrix must be 16 floats (4x4 matrix)");
    }
    
    // Store rendering parameters for potential future use
    // This allows the system to maintain state without actual GPU calls
}

// --- PHASE 1.1 ERWEITERUNGEN: Neue Instance Management Methoden ---

int GpuInstancer::add_instance(py::array_t<float, py::array::c_style | py::array::forcecast> transform_matrix_flat) {
    // Validierung der Matrix (muss 16 floats sein)
    py::buffer_info matrix_info = transform_matrix_flat.request();
    if (matrix_info.size != 16) {
        throw std::runtime_error("GpuInstancer::add_instance: Transform matrix must be 16 floats (4x4 matrix).");
    }
    
    // Matrix als std::vector<float> kopieren und zur CPU-Liste hinzufügen
    const float* matrix_ptr = static_cast<const float*>(matrix_info.ptr);
    std::vector<float> matrix_copy(matrix_ptr, matrix_ptr + 16);
    instance_matrices_cpu_.push_back(matrix_copy);
    
    // Index der neuen Instance zurückgeben (0-basiert)
    return static_cast<int>(instance_matrices_cpu_.size() - 1);
}

void GpuInstancer::update_instance(int instance_index, py::array_t<float, py::array::c_style | py::array::forcecast> transform_matrix_flat) {
    // Validierung des Index
    if (instance_index < 0 || instance_index >= static_cast<int>(instance_matrices_cpu_.size())) {
        throw std::runtime_error("GpuInstancer::update_instance: Invalid instance index " + std::to_string(instance_index));
    }
    
    // Validierung der Matrix
    py::buffer_info matrix_info = transform_matrix_flat.request();
    if (matrix_info.size != 16) {
        throw std::runtime_error("GpuInstancer::update_instance: Transform matrix must be 16 floats (4x4 matrix).");
    }
    
    // Matrix in CPU-Liste aktualisieren
    const float* matrix_ptr = static_cast<const float*>(matrix_info.ptr);
    std::copy(matrix_ptr, matrix_ptr + 16, instance_matrices_cpu_[instance_index].begin());
}

py::array_t<float> GpuInstancer::get_all_instance_matrices() const {
    if (instance_matrices_cpu_.empty()) {
        // Leeres Array zurückgeben wenn keine Instanzen vorhanden
        return py::array_t<float>(std::vector<py::ssize_t>{0, 16});
    }
    
    // Alle Matrizen zu einem flachen Array kombinieren (N x 16)
    size_t num_instances = instance_matrices_cpu_.size();
    py::array_t<float> result = py::array_t<float>(std::vector<py::ssize_t>{static_cast<py::ssize_t>(num_instances), 16});
    py::buffer_info result_info = result.request();
    float* result_ptr = static_cast<float*>(result_info.ptr);
    
    for (size_t i = 0; i < num_instances; ++i) {
        std::copy(instance_matrices_cpu_[i].begin(), instance_matrices_cpu_[i].end(), 
                  result_ptr + (i * 16));
    }
    
    // Das Array ist bereits korrekt geformt als (num_instances, 16)
    return result;
}

void GpuInstancer::clear_instances() {
    instance_matrices_cpu_.clear();
    // Ghost-Mode wird ebenfalls zurückgesetzt
    ghost_mode_enabled_ = false;
    ghost_instance_index_ = -1;
}

void GpuInstancer::cleanup() {
    // Clear CPU-side instance data
    instance_matrices_cpu_.clear();
    
    // Reset GPU handles (no actual GPU cleanup due to linking complexity)
    handles_.shader_ptr = nullptr;
    handles_.vbo_master_mesh_data = nullptr;
    handles_.vbo_instance_data = nullptr;
    handles_.ibo_master_mesh = nullptr;
    handles_.batch = nullptr;
    handles_.loc_viewMatrix = -1;
    handles_.loc_projectionMatrix = -1;
    handles_.loc_time = -1;
    handles_.loc_sampler_albedo = -1;
    handles_.loc_sampler_emissive = -1;
    handles_.num_master_indices = 0;
    handles_.num_master_vertices = 0;
    handles_.uses_indices = false;
    
    // Reset ghost mode
    ghost_mode_enabled_ = false;
    ghost_instance_index_ = -1;
}

void GpuInstancer::upload_transforms_to_gpu() {
    if (instance_matrices_cpu_.empty()) {
        return; // Nothing to upload
    }
    
    // Note: GPU upload disabled due to linking complexity
    // Instance data is kept on CPU for now and will be uploaded through Python API
    // when running in Blender
    
    // Validate data consistency
    for (const auto& matrix : instance_matrices_cpu_) {
        if (matrix.size() != 16) {
            throw std::runtime_error("Invalid matrix size in instance data");
        }
    }
}

void GpuInstancer::set_ghost_mode(bool enabled, int ghost_instance_index) {
    ghost_mode_enabled_ = enabled;
    
    if (enabled && ghost_instance_index >= 0) {
        ghost_instance_index_ = ghost_instance_index;
    } else {
        ghost_instance_index_ = -1; // Kein gültiger Ghost-Index
    }
    
    // Hinweis: Die tatsächliche Ghost-Rendering-Logik wird in der draw() Methode 
    // implementiert (z.B. Alpha-Blending für die Ghost-Instance)
}

} // namespace ScatterAccelImpl

// Modul-Definition
PYBIND11_MODULE(scatter_accel, m) {
    m.doc() = "Native C++ acceleration module for Physical Layout Tool (EXEGET Addon)";

    // Binding for GpuVertexData (existing)
    py::class_<ScatterAccelImpl::GpuVertexData>(m, "GpuVertexData", "Container for GPU-ready vertex and index data.")
        .def_property_readonly("positions", [](const ScatterAccelImpl::GpuVertexData &s) { return s.positions; }, 
                            "NumPy array (float32, Nx3) of vertex positions.")
        .def_property_readonly("indices", [](const ScatterAccelImpl::GpuVertexData &s) { return s.indices; },
                            "NumPy array (uint32, MxK) of vertex indices (K=2 for lines, K=3 for triangles).");

    // Existing function bindings
    m.def("analyze_objects", &ScatterAccelImpl::analyze_objects, 
        py::arg("objects"), py::arg("enable_rigidbody") = false,
        "Analyzes a list of object dictionaries and returns descriptive strings.");

    m.def("calculate_random_transforms_cpp", &ScatterAccelImpl::calculate_random_transforms_cpp, 
        py::arg("settings_dict"),
        "Calculates random rotation (Euler radians) and uniform scale based on input settings dict.");

    m.def("analyze_scatter_objects_for_processing", &ScatterAccelImpl::analyze_scatter_objects_for_processing, 
        py::arg("objects_data"), py::arg("processing_settings"),
        "Analyzes a list of scatter object data and returns a list of processing instructions for Python.");

    m.def("analyze_single_object_for_processing", &ScatterAccelImpl::analyze_single_object_for_processing, 
        py::arg("single_object_data"), py::arg("processing_settings"),
        "Analyzes a single scatter object's data for on-the-fly processing and returns an instruction dict.");

    m.def("analyze_objects_for_static_bake", &ScatterAccelImpl::analyze_objects_for_static_bake, 
        py::arg("object_names"), py::arg("target_static_collection_name"),
        "Analyzes specified Blender objects for static baking, checking data users and Rigid Body status.");

    m.def("mark_for_deletion_cpp", &ScatterAccelImpl::mark_for_deletion_cpp, 
        py::arg("marker_name"), 
        "Marks an object (by name) for future deletion by the C++ module (via flush_marked_objects_cpp).");
    m.def("get_marked_garbage_cpp", &ScatterAccelImpl::get_marked_garbage_cpp,
        "Returns a list of names of objects currently marked for deletion on the C++ side.");
    m.def("clear_garbage_cpp", &ScatterAccelImpl::clear_garbage_cpp,
        "Clears the C++ internal list of objects marked for deletion without deleting them in Blender.");
    m.def("flush_marked_objects_cpp", &ScatterAccelImpl::flush_marked_objects_cpp, 
        py::arg("bpy_data_objects"),
        "Deletes all objects in Blender that were previously marked by mark_for_deletion_cpp. Requires bpy.data.objects.");

    m.def("analyze_objects_for_rb_setup_cpp", &ScatterAccelImpl::analyze_objects_for_rb_setup_cpp, 
        py::arg("object_names_py"),
        "Analyzes specified Blender objects for Rigid Body setup, returning their current RB state and data user count.");
    m.def("configure_batch_rigidbody_properties_cpp", &ScatterAccelImpl::configure_batch_rigidbody_properties_cpp, 
        py::arg("object_names_py"), py::arg("target_rb_settings_py"),
        "Configures Rigid Body properties for a batch of specified Blender objects based on target settings.");

    m.def("generate_circle_marker_gpu_data_cpp", &ScatterAccelImpl::generate_circle_marker_gpu_data_cpp,
        py::arg("radius"), py::arg("segments"),
        "Generates vertex (float32 Nx3) and index (uint32 Mx2) data for a 2D circle wireframe (for GPU LINES drawing). Returns GpuVertexData.");

    m.def("prepare_mesh_gpu_data_from_flat_arrays_cpp", &ScatterAccelImpl::prepare_mesh_gpu_data_from_flat_arrays_cpp,
        py::arg("flat_vertex_cos_py").noconvert(), 
        py::arg("flat_loop_triangle_indices_py").noconvert(), 
        py::arg("num_actual_vertices"), 
        py::arg("num_loop_triangles"),
        "Prepares mesh data from flat Blender C-contiguous NumPy arrays into GPU-ready shaped NumPy arrays (positions Nx3, indices Mx3). Returns GpuVertexData.");

    // New binding for prepare_master_mesh_data_from_py_arrays_cpp
    m.def("prepare_master_mesh_data_from_py_arrays_cpp", &ScatterAccelImpl::prepare_master_mesh_data_from_py_arrays_cpp,
        py::arg("flat_vertex_cos_py").noconvert(),
        py::arg("flat_vertex_uvs_py").noconvert(),
        py::arg("flat_loop_triangle_indices_py").noconvert(),
        py::arg("num_actual_vertices"),
        py::arg("num_loop_triangles"),
        "Prepares master mesh data (positions, uvs, indices) from flat Python NumPy arrays for GpuInstancer. Returns MasterMeshData.");

    // New binding for MasterMeshData Struktur
    py::class_<ScatterAccelImpl::MasterMeshData>(m, "MasterMeshData")
        .def(py::init<>()) 
        .def_readwrite("positions", &ScatterAccelImpl::MasterMeshData::positions)
        .def_readwrite("uvs", &ScatterAccelImpl::MasterMeshData::uvs)
        .def_readwrite("indices", &ScatterAccelImpl::MasterMeshData::indices);

    // New binding for GpuInstancer Klasse
    py::class_<ScatterAccelImpl::GpuInstancer>(m, "GpuInstancer", "Manages GPU resources for instanced drawing.")
        .def(py::init<const std::string&>(), py::arg("shader_name_py"), "Initializes the instancer with a shader name.")
        .def("setup_master_mesh", &ScatterAccelImpl::GpuInstancer::setup_master_mesh,
             py::arg("master_mesh_data"), py::arg("initial_max_instances"),
             "Sets up the master mesh data (VBOs, IBO) and prepares for instancing.")
        .def("update_instance_transforms", &ScatterAccelImpl::GpuInstancer::update_instance_transforms,
             py::arg("instance_matrices_flat").noconvert(), py::arg("num_instances"),
             "Updates the instance transformation matrices in the GPU buffer.")
        .def("draw",
            [](ScatterAccelImpl::GpuInstancer &self,
                int num_instances_to_render,
                py::array_t<float, py::array::c_style | py::array::forcecast> view_matrix_flat,
                py::array_t<float, py::array::c_style | py::array::forcecast> projection_matrix_flat,
                float current_time,
                py::object py_tex_albedo_obj,    
                py::object py_tex_emissive_obj)  
            {
                PyObject* albedo_ptr = py_tex_albedo_obj.is_none() ? nullptr : py_tex_albedo_obj.ptr();
                PyObject* emissive_ptr = py_tex_emissive_obj.is_none() ? nullptr : py_tex_emissive_obj.ptr();

                self.draw(num_instances_to_render,
                          view_matrix_flat, projection_matrix_flat,
                          current_time,
                          albedo_ptr,     
                          emissive_ptr);  
            },
            py::arg("num_instances_to_render"),
            py::arg("view_matrix_flat").noconvert(),
            py::arg("projection_matrix_flat").noconvert(),
            py::arg("current_time"),
            py::arg("py_texture_albedo"),    
            py::arg("py_texture_emissive"),  
            "Draws the instanced meshes using the provided camera matrices, time, and textures."
        )
        .def("add_instance", &ScatterAccelImpl::GpuInstancer::add_instance,
             py::arg("transform_matrix_flat").noconvert(),
             "Adds a new instance with the given transformation matrix and returns its index.")
        .def("update_instance", &ScatterAccelImpl::GpuInstancer::update_instance,
             py::arg("instance_index"), py::arg("transform_matrix_flat").noconvert(),
             "Updates the transformation matrix of an existing instance.")
        .def("get_all_instance_matrices", &ScatterAccelImpl::GpuInstancer::get_all_instance_matrices,
             "Returns all instance transformation matrices as a flat array (N x 16).")
        .def("clear_instances", &ScatterAccelImpl::GpuInstancer::clear_instances,
             "Clears all instances and resets the instancer.")
        .def("set_ghost_mode", &ScatterAccelImpl::GpuInstancer::set_ghost_mode,
             py::arg("enabled"), py::arg("ghost_instance_index") = -1,
             "Enables or disables ghost mode for the instancer.")
        .def("cleanup", &ScatterAccelImpl::GpuInstancer::cleanup,
             "Cleans up GPU resources and clears CPU data.")
        .def("upload_transforms_to_gpu", &ScatterAccelImpl::GpuInstancer::upload_transforms_to_gpu,
             "Uploads all CPU instance matrices to the GPU buffer.")
        .def("get_instance_count", &ScatterAccelImpl::GpuInstancer::get_instance_count,
             "Returns the current number of instances.")
        .def("is_ghost_mode_enabled", &ScatterAccelImpl::GpuInstancer::is_ghost_mode_enabled,
             "Returns whether ghost mode is currently enabled.")
        .def("get_ghost_instance_index", &ScatterAccelImpl::GpuInstancer::get_ghost_instance_index,
             "Returns the index of the ghost instance (-1 if none).");
}