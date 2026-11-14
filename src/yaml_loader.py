"""
Carga y parseo seguro de configuración YAML/TOML sin requerir compiladores externos.
Soporta PyYAML si está instalado, o parseador robusto integrado compatible con settings.yaml.
"""

from __future__ import annotations

import re
from pathlib import Path


def _parse_yaml_basic(content: str) -> dict:
    """
    Parser elemental de estructuras anidadas YAML básicas (secciones, dicts, escalares y listas simples).
    Permite cargar settings.yaml sin depender de compiladores de C++ para PyYAML.
    """
    data: dict = {}
    current_section: str | None = None

    for raw_line in content.splitlines():
        # Limpiar comentarios y espacios finales
        line = re.sub(r"#.*$", "", raw_line).rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        # Detección de sección de primer nivel (ej. "paths:")
        if indent == 0 and stripped.endswith(":"):
            current_section = stripped[:-1].strip()
            data[current_section] = {}
            continue

        if ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()

            parsed_val: any
            if val == "":
                parsed_val = {}
            elif val.startswith("[") and val.endswith("]"):
                items = [x.strip() for x in val[1:-1].split(",") if x.strip()]
                parsed_items = []
                for it in items:
                    try:
                        parsed_items.append(int(it))
                    except ValueError:
                        try:
                            parsed_items.append(float(it))
                        except ValueError:
                            parsed_items.append(it)
                parsed_val = parsed_items
            else:
                try:
                    parsed_val = int(val)
                except ValueError:
                    try:
                        parsed_val = float(val)
                    except ValueError:
                        if val.lower() == "true":
                            parsed_val = True
                        elif val.lower() == "false":
                            parsed_val = False
                        elif val.lower() in ("null", "none"):
                            parsed_val = None
                        else:
                            parsed_val = val

            if current_section:
                data[current_section][key] = parsed_val
            else:
                data[key] = parsed_val

    return data


def load_settings(yaml_path: Path) -> dict:
    """Carga un archivo YAML utilizando PyYAML si existe; de lo contrario usa el parser integrado."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        import yaml
        return yaml.safe_load(content)
    except ImportError:
        return _parse_yaml_basic(content)
