"""The bodies she can stream in (models.toml), picked with `server.py --model`.

The name is also the Godot scene the server asks the body to load; what the
actor hears about her looks comes from here."""

import tomllib
from pathlib import Path

MODELS_FILE = Path(__file__).resolve().parent / "models.toml"
DEFAULT_MODEL = "lucy"


def load_models() -> dict[str, dict]:
    """Every model by name. A missing or unknown key fails loudly."""
    with MODELS_FILE.open("rb") as f:
        models = tomllib.load(f)
    for name, model in models.items():
        if set(model) != {"looks"}:
            raise KeyError(f"models.toml: [{name}] needs exactly the key 'looks' (got {sorted(model)})")
    if DEFAULT_MODEL not in models:
        raise KeyError(f"models.toml: no [{DEFAULT_MODEL}] (the default model)")
    return models
