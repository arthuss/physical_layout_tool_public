cmake_minimum_required(VERSION 3.25)
project(scatter_accel LANGUAGES CXX)

# --- Python 3.11 --- (Pfad wird extern via -D übergeben)
message(STATUS "CMake: Using Python executable: ${Python_EXECUTABLE}")
message(STATUS "CMake: Python include dirs: ${Python_INCLUDE_DIRS}")
message(STATUS "CMake: Python libraries: ${Python_LIBRARIES}")

# --- Pybind11 ---
include(FetchContent)
FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG        v2.13.0 # Updated to current 2025 version
)
FetchContent_MakeAvailable(pybind11)
message(STATUS "CMake: pybind11 include dirs: ${pybind11_INCLUDE_DIRS}")

# === Modul-Definition ===
# Source files from cpp_sources directory
pybind11_add_module(
  scatter_accel
  SHARED
  cpp_sources/scatter_accel.cpp
)

# === Target-Eigenschaften ===
set_target_properties(scatter_accel PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF
)

# Set suffix for Python modules explicitly for Windows
if(WIN32)
    set_target_properties(scatter_accel PROPERTIES SUFFIX ".pyd")
endif()

# === Includes ===
target_include_directories(scatter_accel PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/cpp_sources  # For local headers, e.g., scatter_accel_impl.hpp
    ${pybind11_INCLUDE_DIRS}                 # Pybind11 headers
    ${Python_INCLUDE_DIRS}                   # Python C API headers
    ${BLENDER_INCLUDE_DIRS}                  # Blender specific headers
)

# Specific Blender include directories needed for common headers
# BLENDER_SRC_DIR zeigt auf "G:/blender-git":
if(BLENDER_SRC_DIR)
    target_include_directories(scatter_accel PRIVATE
        "${BLENDER_SRC_DIR}/blender/source/blender/blenlib"  # For BLI_utildefines.h via "blenlib/BLI_utildefines.h"
        "${BLENDER_SRC_DIR}/blender/source/blender"          # Base source directory for general includes
        "${BLENDER_SRC_DIR}/blender/intern"                  # For guardedalloc/MEM_guardedalloc.h
    )
    message(STATUS "CMake: Blender source dir: ${BLENDER_SRC_DIR}")
endif()

# === Link gegen Python-Lib ===
target_link_libraries(scatter_accel PRIVATE ${Python_LIBRARIES})

# === Debug-Fix für fehlendes pythonXX_d.lib unter Windows ===
if(WIN32)
    target_compile_definitions(scatter_accel PRIVATE "PYTHON_NO_DEBUG")
endif()

# === CRT-Einstellung für MSVC (Release-kompatibel) ===
if(MSVC)
    set_target_properties(scatter_accel PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
endif()

# === Compileroptimierung und Debug-Flags ===
target_compile_options(scatter_accel PRIVATE
    $<$<CONFIG:Release>:$<$<CXX_COMPILER_ID:MSVC>:/O2 /DNDEBUG>$<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-O3 -DNDEBUG>>
    $<$<CONFIG:Debug>:$<$<CXX_COMPILER_ID:MSVC>:/Od /Zi>$<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-g>>
)

# === Debug-Ausgabe: Effektive Konfiguration für das Target ===
if(CMAKE_BUILD_TYPE)
    message(STATUS "CMake: Build type: ${CMAKE_BUILD_TYPE}")
else()
    message(STATUS "CMake: Build type: Not explicitly set (defaults often to Debug or empty for multi-config generators like VS)")
endif()

get_target_property(ACCEL_INCLUDES_PRIV scatter_accel INCLUDE_DIRECTORIES)
message(STATUS "DEBUG: Effective include directories for scatter_accel: ${ACCEL_INCLUDES_PRIV}")

get_target_property(ACCEL_LINK_LIBS scatter_accel LINK_LIBRARIES)
message(STATUS "DEBUG: Effective link libraries for scatter_accel: ${ACCEL_LINK_LIBS}")

get_target_property(ACCEL_COMPILE_DEFS scatter_accel COMPILE_DEFINITIONS)
message(STATUS "DEBUG: Effective compile definitions for scatter_accel: ${ACCEL_COMPILE_DEFS}")

get_target_property(ACCEL_COMPILE_OPTS scatter_accel COMPILE_OPTIONS)
message(STATUS "DEBUG: Effective compile options for scatter_accel: ${ACCEL_COMPILE_OPTS}")

if(MSVC)
    get_target_property(ACCEL_MSVC_RUNTIME scatter_accel MSVC_RUNTIME_LIBRARY)
    message(STATUS "DEBUG: MSVC Runtime Library for scatter_accel: ${ACCEL_MSVC_RUNTIME}")
endif()

message(STATUS "CMake configuration for scatter_accel finished.")
