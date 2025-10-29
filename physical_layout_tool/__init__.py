# SPDX-License-Identifier: GPL-3.0-or-later

"""
Physics Layout Tool - Blender Extension

GPU-accelerated physics-based object scattering with C++ instancing support.
"""

import bpy

# Import the main addon functionality from the physical_layout_tool package
from .physical_layout_tool import (
    instance_operator,
    physical_layout_tool,
    physics_cursor_scatter,
    scatter_draw_helper,
    loader
)

# Blender extension registration
def register():
    """Register all Blender classes and operators."""
    # Register operators and UI classes
    instance_operator.register()
    physical_layout_tool.register()
    physics_cursor_scatter.register()
    # scatter_draw_helper and loader are helper modules without register() functions

def unregister():
    """Unregister all Blender classes and operators."""
    # Unregister in reverse order
    physics_cursor_scatter.unregister()
    physical_layout_tool.unregister()
    instance_operator.unregister()
    # scatter_draw_helper and loader are helper modules without unregister() functions

# Required for Blender to recognize this as an add-on
if __name__ == "__main__":
    register()
