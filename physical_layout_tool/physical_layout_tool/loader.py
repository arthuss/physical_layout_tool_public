# loader.py
import platform
import importlib.util
import os
import sys
import traceback

def load_native_module(module_name, addon_root_path):
    """
    Lädt ein natives Modul (.pyd/.so) aus dem Addon-Verzeichnis.
    Versucht zuerst, einen 'native' Unterordner zu finden, dann das Addon-Root.

    Args:
        module_name (str): Der Name des Moduls ohne Dateiendung (z.B. "scatter_accel").
        addon_root_path (str): Der Pfad zum Hauptverzeichnis des Addons.
    """
    system = platform.system()
    # machine_arch = platform.machine() # z.B. 'AMD64', 'x86_64', 'arm64'

    filename = ""
    possible_filenames = None # Initialisierung hinzugefügt!

    # Priorisiere den 'native' Unterordner
    native_subfolder_path = os.path.join(addon_root_path, "native")
    # Fallback: Direkt im Addon-Root
    search_paths = [native_subfolder_path, addon_root_path]

    if system == "Windows":
        filename = f"{module_name}.pyd"
        # Für Windows wird possible_filenames nicht direkt verwendet,
        # aber wir prüfen später darauf.
        possible_filenames = [filename] # Sicherstellen, dass es eine Liste ist für die spätere Logik
    elif system == "Linux":
        python_version_suffix = f"cpython-{sys.version_info.major}{sys.version_info.minor}-{platform.machine().lower().replace('_', '')}-linux-gnu.so"
        possible_filenames = [
            f"{module_name}.so",
            f"{module_name}_{platform.machine().lower()}.so",
            f"{module_name}.{python_version_suffix}"
        ]
    elif system == "Darwin": # macOS
        machine = platform.machine().lower()
        possible_filenames = [
            f"{module_name}.so", 
            f"{module_name}.dylib",
            f"{module_name}_{machine}.so",
            f"{module_name}_{machine}.dylib"
        ]
    else:
        raise ImportError(f"Unsupported operating system: {system}")

    module_path = None
    found_module_file = None

    # Durchsuche die Pfade nach den möglichen Dateinamen
    for search_dir in search_paths:
        for fname_candidate in possible_filenames: # Jetzt ist possible_filenames immer definiert
            current_path_candidate = os.path.join(search_dir, fname_candidate)
            if os.path.exists(current_path_candidate):
                module_path = current_path_candidate
                found_module_file = fname_candidate
                break
        if module_path:
            break
            
    if not module_path:
        searched_names_str = ", ".join(possible_filenames)
        raise ImportError(f"Native module '{module_name}' (gesuchte Dateien: '{searched_names_str}') nicht gefunden in Pfaden: {search_paths}")

    print(f"  [Loader] Versuche Modul zu laden von: {module_path}")

    module_dir = os.path.dirname(module_path)
    path_added_to_sys = False
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
        path_added_to_sys = True
        print(f"  [Loader] Temporär zum sys.path hinzugefügt: {module_dir}")

    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None:
            raise ImportError(f"Konnte keine Modul-Spezifikation für '{module_name}' von Pfad '{module_path}' erstellen.")
        
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod 
        spec.loader.exec_module(mod)
        print(f"  [Loader] Modul '{module_name}' erfolgreich geladen.")
        return mod
    except ImportError as e:
        print(f"  [Loader] ImportError beim Laden von '{module_name}': {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"  [Loader] Allgemeiner Fehler beim Laden von '{module_name}': {e}")
        traceback.print_exc()
        raise
    finally:
        if path_added_to_sys:
            if sys.path and sys.path[0] == module_dir:
                sys.path.pop(0)
                print(f"  [Loader] Temporärer Pfad entfernt: {module_dir}")
