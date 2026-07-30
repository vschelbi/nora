import os
import yaml
import copy
from pathlib import Path
from omegaconf import OmegaConf

from nora.utils.keys import MISSING_VALUES


CONFIG_YAML = "config.yaml"
USER_YAML = "user.yaml"


def load_yaml(path: str):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge overrides into base (in place)."""
    for k, v in overrides.items():
        if isinstance(base.get(k), dict) and isinstance(v, dict):
            deep_merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def get_config_path():
    config_dir = os.path.join(os.path.dirname(__file__), "..", "configs")
    config_dir = os.path.abspath(config_dir)
    return os.path.join(config_dir, CONFIG_YAML)


def get_user_config_path():
    config_dir = Path.home() / ".nora"
    config_dir.mkdir(exist_ok=True)
    return config_dir / USER_YAML


def ask(question: str, current=None):
    """Ask for a configuration value, offering to keep the one already in
    your config. An empty answer keeps it, so re-running `nora configure`
    to change one thing does not clear the others.

    The current value is never echoed back: most of what is asked here is
    a secret, and a terminal is often being shared or recorded.
    """
    known = current not in MISSING_VALUES
    answer = input(f"{question}{' [keep current]' if known else ''}: ").strip()
    if answer:
        return answer
    return current if known else ""


def current_backends(user_cfg: dict):
    """The backends a config already names, as a list. Mirrors what
    `nora.upload.resolve_backends` does when NoRA writes a paper, so that
    `nora configure` offers you back the answer you gave last time.
    """
    backend = user_cfg.get("backend") or "notion"
    if isinstance(backend, str):
        backend = backend.split(",")
    return [str(x).strip().lower() for x in backend if str(x).strip()]


def configure_user_config():
    """Interactively update ~/.nora/user.yaml with user API keys.

    Everything already in your config is kept: only the values you are
    prompted for here are replaced, so hand-edited settings - a
    `link_style`, an `on_existing`, your own `venues` - survive a re-run.
    """
    config_path = get_user_config_path()
    existing = load_yaml(config_path)
    print(f"Let's configure your NoRA keys:\n")

    # Only ask for the keys of the backends actually being used: an
    # Obsidian user has no Notion database to point at
    was = current_backends(existing)
    default = "both" if len(was) > 1 else (was[0] if was else "notion")

    backend = input(
        f"Where should NoRA write your papers? "
        f"[notion/obsidian/both] ({default}): ")
    backend = backend.strip().lower() or default
    if backend not in ("notion", "obsidian", "both"):
        print(f"⚠️ Unknown backend '{backend}', defaulting to {default}")
        backend = default

    backends = ["notion", "obsidian"] if backend == "both" else [backend]

    # A single backend is stored as a plain string, which is what every
    # config held before writing to both at once became possible
    user_cfg = {"backend": backends if len(backends) > 1 else backends[0]}

    # The keys of a backend you are not configuring right now are left in
    # place rather than dropped, so that switching back to it later does
    # not mean finding your database ids again
    notion = existing.get("notion") or {}
    obsidian = existing.get("obsidian") or {}
    zotero = existing.get("zotero") or {}

    if "notion" in backends:
        user_cfg["notion"] = {
            "token": ask(
                "Enter your Notion integration token",
                notion.get("token")),
            "papers_db_id": ask(
                "Enter your Notion Papers database ID",
                notion.get("papers_db_id")),
            "people_db_id": ask(
                "Enter your Notion People database ID",
                notion.get("people_db_id")),
            "venues_db_id": ask(
                "Enter your Notion Venues database ID",
                notion.get("venues_db_id")),
            "topics_db_id": ask(
                "Enter your Notion Topics database ID",
                notion.get("topics_db_id")),
        }

    if "obsidian" in backends:
        user_cfg["obsidian"] = {
            "vault_path": ask(
                "Enter the path to your Obsidian vault",
                obsidian.get("vault_path")),
        }

    user_cfg["zotero"] = {
        "library_id": ask(
            "Enter your Zotero library ID (optional)",
            zotero.get("library_id")),
        "api_token": ask(
            "Enter your Zotero API token (optional)",
            zotero.get("api_token")),
    }

    # What you just answered goes on top of what your config already held,
    # so nothing you had set is lost
    deep_merge(existing, user_cfg)
    with open(config_path, "w") as f:
        yaml.dump(existing, f)

    # Load the user-specific config along with static config it not
    # overwritten by the user config. Then save all into the new user
    # config file. This allows exposing explicitly in the user's config
    # all the configuration variables
    cfg_full = OmegaConf.to_container(load_config(), resolve=True)
    with open(config_path, "w") as f:
        yaml.dump(cfg_full, f)

    print(f"✅ Configuration saved to {config_path}")


def load_user_config(depth: int=0):
    """Load user keys from ~/.nora/user.yaml"""
    config_path = get_user_config_path()
    if config_path.exists():
        return load_yaml(config_path)
    elif depth < 1:
        configure_user_config()
        return load_user_config(depth=1)
    else:
        print(f"⚠️ No {USER_YAML} file found. Run `nora configure` first.")
        raise SystemExit(1)


def load_config():
    """
    Loads NoRA configuration by merging:
      1. Static defaults from src/nora/configs/config.yaml
      2. User-specific overrides from ~/.nora/user.yaml
    """
    # Find base config directory (relative to installed package).
    # Normally this call could be bypassed if configure_user_config()
    # was properly called. But this allows for making up for users
    # potentially tampering with their private config file and deleting
    # essential keys
    cfg = load_yaml(get_config_path())

    # Get config holding user keys
    user_cfg = load_user_config()
    if user_cfg:
        for k, v in user_cfg.items():
            if k in cfg and isinstance(v, dict):
                deep_merge(cfg[k], v)
            else:
                cfg[k] = v

    return OmegaConf.create(cfg)
