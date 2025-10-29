# Physical Layout Tool (GPL Release)

The Physical Layout Tool is a Blender add-on that combines physics-driven scattering workflows with GPU-accelerated instancing. This repository contains the version that is ready for public release under the GNU GPLv3, including the full C++ and Python source code required to satisfy Blender licensing rules.

## Features
- Physics-aware scattering operators for quickly populating scenes.
- Optional C++/PyBind11 acceleration module (named scatter_accel) for heavy batch operations.
- Pure-Python fallback path when the compiled module is unavailable.
- Blender 4.4 ready user interface located in View3D -> Sidebar -> PhysicalTool.

## Repository Layout
- physical_layout_tool/ - Blender add-on package that is ready to be zipped and installed.
  - physical_layout_tool/native/ - placeholder directory for the compiled module. The distributed source keeps this folder empty; build outputs should not be committed.
- cpp_sources/ - C++ sources and headers for the scatter_accel extension module.
- CMakeLists.txt - cross-platform build configuration for the native module.

## Building the scatter_accel Module
1. Ensure Blender headers and Python development files are available.
2. Configure CMake with explicit paths to Python and the Blender source tree, for example:

   cmake -B build -S . \
     -DPython_EXECUTABLE="C:/Program Files/Blender Foundation/Blender 4.4/python/bin/python.exe" \
     -DPython_INCLUDE_DIRS="C:/Program Files/Blender Foundation/Blender 4.4/python/include" \
     -DPython_LIBRARIES="C:/Program Files/Blender Foundation/Blender 4.4/python/libs/python311.lib" \
     -DBLENDER_INCLUDE_DIRS="G:/blender-git/blender/build/windows_x64_vc16_Release/bin/4.4/scripts" \
     -DBLENDER_SRC_DIR="G:/blender-git"
   cmake --build build --config Release

3. Copy the resulting scatter_accel.pyd (or .so/.dylib on other platforms) into physical_layout_tool/physical_layout_tool/native/ before packaging the add-on.

The build configuration fetches PyBind11 automatically. If an offline build is required, vendor PyBind11 manually and update the CMakeLists.txt accordingly.

## Packaging for Blender
1. After building (or skipping the native module for the pure Python variant), zip the physical_layout_tool directory:

   cd physical_layout_tool_public
   zip -r PhysicalLayoutTool.zip physical_layout_tool

2. Install the zip inside Blender via Edit > Preferences > Add-ons > Install.

## Licensing
- The entire project is released under the GNU General Public License v3.0 or later. See the LICENSE file for the full text.
- Compiled binaries must always be accompanied by the matching source code when distributed.
- The Python package embeds the bl_info["license"] = "GPL-3.0-or-later" metadata so Blender surfaces the correct notice.

## Attribution
Developed by arthuss (Sascha Bay). Commercial distribution on marketplaces such as Hive or Blender Market is permitted as long as the GPL remains intact and the source code stays publicly accessible.
