# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {
    "name": "Physical Layout Tool Combined",
    "blender": (4, 4, 0),
    "category": "Object",
    "author": "arthuss (Sascha Bay)",
    "description": "Combines Physics Rigid Body tools with advanced Cursor Scatter and Instancing capabilities. Includes C++ accelerated parts.",
    "version": (1, 3, 4),  # Version leicht erhöht für die neue Helper-Integration
    "location": "View3D > Sidebar > PhysicalTool Tab",
    "license": "GPL-3.0-or-later",
}

import bpy
import traceback
import os 

# --- Globale Paketvariablen für C++ Modul und Verfügbarkeitsflag ---
NATIVE_MODULE_AVAILABLE = False
scatter_accel = None 
# --- Ende globale Paketvariablen ---

def _internal_load_cpp_logic():
    global NATIVE_MODULE_AVAILABLE, scatter_accel
    addon_root_path = os.path.dirname(os.path.realpath(__file__))
    module_name_to_load = "scatter_accel"
    original_bl_warning = bl_info.get("warning", "")
    try:
        from .loader import load_native_module 
        print(f"[{bl_info.get('name')} Init] Versuche, natives Modul '{module_name_to_load}' zu laden aus Addon-Pfad: {addon_root_path}")
        scatter_accel = load_native_module(module_name_to_load, addon_root_path)
        NATIVE_MODULE_AVAILABLE = True # Wird True, wenn load_native_module keinen Fehler wirft
        print(f"[{bl_info.get('name')} Init] ✅ Natives C++ Modul '{module_name_to_load}' erfolgreich geladen und global zugewiesen.")
        if bl_info.get("warning", "").startswith("Natives C++ Modul") or bl_info.get("warning", "").startswith("Fehler beim Laden"):
            bl_info["warning"] = "" 
        elif original_bl_warning :
             bl_info["warning"] = original_bl_warning
    except ImportError as e_imp:
        NATIVE_MODULE_AVAILABLE = False
        scatter_accel = None
        warning_msg = f"Natives C++ Modul '{module_name_to_load}' nicht geladen (ImportError). Addon läuft im reinen Python-Modus."
        print(f"[{bl_info.get('name')} Init] ⚠️ {warning_msg}")
        print(f"  ImportError Details: {e_imp}")
        bl_info["warning"] = warning_msg
    except Exception as e:
        NATIVE_MODULE_AVAILABLE = False
        scatter_accel = None
        warning_msg = f"Fehler beim Laden des C++ Moduls '{module_name_to_load}'. Siehe Konsole."
        print(f"[{bl_info.get('name')} Init] 💥 Ein unerwarteter Fehler (Typ: {type(e).__name__}) ist beim Laden des nativen Moduls '{module_name_to_load}' aufgetreten:")
        traceback.print_exc()
        bl_info["warning"] = warning_msg
    if not NATIVE_MODULE_AVAILABLE and original_bl_warning and not bl_info.get("warning","").startswith("Natives C++ Modul") and not bl_info.get("warning","").startswith("Fehler beim Laden"):
        bl_info["warning"] = original_bl_warning

_internal_load_cpp_logic()

print(f"[{bl_info.get('name')} Init] Importiere Submodule... (Paket-Status: NATIVE_MODULE_AVAILABLE={NATIVE_MODULE_AVAILABLE}, scatter_accel is None: {scatter_accel is None})")
from . import physical_layout_tool
from . import instance_operator
from . import physics_cursor_scatter
from . import scatter_draw_helper # <<<<<< HIER HINZUGEFÜGT

print(f"[{bl_info.get('name')} Init] Submodule importiert.")

_register_ordered = [
    physical_layout_tool,
    instance_operator,
    physics_cursor_scatter,
    # scatter_draw_helper kommt hier NICHT rein, da es keine eigene register()-Funktion hat
]

def register():
    # ... (deine register Funktion bleibt gleich) ...
    print(f"Attempting to register addon: {bl_info.get('name')} - Version {bl_info.get('version')}")
    if not NATIVE_MODULE_AVAILABLE:
        print(f"WARNUNG [{bl_info.get('name')}] Register: Natives C++ Modul ('{scatter_accel if scatter_accel else 'N/A'}') ist nicht verfügbar!")
    else:
        print(f"INFO [{bl_info.get('name')}] Register: Natives C++ Modul ist verfügbar.")
    for module in _register_ordered:
        if hasattr(module, "register"):
            try:
                module.register()
                print(f"Successfully registered module: {module.__name__}")
            except Exception as e:
                print(f"ERROR registering module {module.__name__}:")
                traceback.print_exc()
                current_index = _register_ordered.index(module)
                for i in range(current_index -1, -1, -1): 
                    prev_module = _register_ordered[i]
                    if hasattr(prev_module, "unregister"):
                        try:
                            prev_module.unregister()
                            print(f"Rolled back registration of {prev_module.__name__}")
                        except Exception as e_unreg:
                            print(f"Error during rollback unregistration of {prev_module.__name__}: {e_unreg}")
                raise 
        else:
            print(f"Module {module.__name__} has no register function.")
    print(f"{bl_info.get('name')}: Registered successfully.")


def unregister():
    # ... (deine unregister Funktion bleibt gleich) ...
    print(f"Attempting to unregister addon: {bl_info.get('name')}")
    for module in reversed(_register_ordered): 
        if hasattr(module, "unregister"):
            try:
                module.unregister()
                print(f"Successfully unregistered module: {module.__name__}")
            except Exception as e:
                print(f"ERROR unregistering module {module.__name__}:")
                traceback.print_exc()
        else:
            print(f"Module {module.__name__} has no unregister function.")
    global scatter_accel, NATIVE_MODULE_AVAILABLE
    scatter_accel = None
    NATIVE_MODULE_AVAILABLE = False
    print(f"{bl_info.get('name')}: Unregistered successfully.")

__all__ = [
    'register', 
    'unregister',
    'NATIVE_MODULE_AVAILABLE',
    'scatter_accel',
]
