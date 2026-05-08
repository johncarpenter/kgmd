"""Configuration loading and defaults."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import yaml

DEFAULT_CONFIG = {
    "corpus": {
        "include": None,  # list of paths relative to corpus root, or None for all
    },
    "embedding": {
        "backend": "fastembed",
        "model": "BAAI/bge-small-en-v1.5",
    },
    "llm": {
        "model": "openrouter/anthropic/claude-sonnet-4-5",
        "temperature": 0.0,
        "max_tokens": 16384,
        "timeout_seconds": 120,
        "concurrency": 4,
    },
    "chunking": {
        "max_chars": 4000,
        "overlap_chars": 200,
        "split_on": "paragraph",
    },
    "extraction": {
        "max_entities_per_chunk": 30,
        "max_relations_per_chunk": 30,
        "retry_on_parse_failure": 2,
    },
    "resolution": {
        "similarity_threshold": 0.85,
        "llm_verify_clusters": True,
        "max_cluster_size": 10,
    },
    "induction": {
        "include_attribute_summary": True,
        "hierarchy_depth": 3,
    },
}


def global_config_dir() -> Path:
    return Path(platformdirs.user_config_dir("kgmd"))


def global_config_path() -> Path:
    return global_config_dir() / "config.yaml"


def load_config(corpus_dir: Path) -> dict:
    """Load config by merging global → corpus-level defaults."""
    cfg = _deep_copy_dict(DEFAULT_CONFIG)

    # Global config
    gpath = global_config_path()
    if gpath.exists():
        with open(gpath) as f:
            glb = yaml.safe_load(f) or {}
        _deep_merge(cfg, glb)

    # Corpus config
    cpath = corpus_dir / ".kgmd" / "config.yaml"
    if cpath.exists():
        with open(cpath) as f:
            corp = yaml.safe_load(f) or {}
        _deep_merge(cfg, corp)

    return cfg


def write_default_config(path: Path) -> None:
    """Write the default config.yaml to the given path."""
    with open(path, "w") as f:
        yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base in-place, recursing into dicts."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _deep_copy_dict(d: dict) -> dict:
    """Simple deep copy for dicts of primitives."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _deep_copy_dict(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out
