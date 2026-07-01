"""
CORDIS Config Loader
====================
Loads the extraction configuration from ``config.json``.

The config file holds the CORDIS query string, the list of summary fields,
and the default output path prefix.  Edit ``config.json`` directly — no code
changes required between runs.
"""

import json
from pathlib import Path


# Default location: <project_root>/config.json
_CONFIG_FILE = Path(__file__).parent.parent / "config.json"


def load_config(path: str | Path | None = None) -> dict:
    """
    Load and validate the extraction config from a JSON file.

    Parameters
    ----------
    path : str or Path, optional
        Path to the config file.  Defaults to ``config.json`` in the project root.

    Returns
    -------
    dict
        Parsed config with at minimum a non-empty ``"query"`` key.

    Raises
    ------
    FileNotFoundError
        If the config file does not exist.
    ValueError
        If the file exists but ``"query"`` is missing or empty.
    """
    cfg_path = Path(path) if path else _CONFIG_FILE

    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {cfg_path}\n"
            "Create config.json and set the 'query' field to your CORDIS query string."
        )

    cfg: dict = json.loads(cfg_path.read_text(encoding="utf-8"))

    query = cfg.get("query", "").strip()
    if not query:
        raise ValueError(
            f"'query' is empty in {cfg_path}\n"
            "Paste your CORDIS query string into the 'query' field and try again."
        )

    cfg["query"] = query   # store stripped version
    return cfg
