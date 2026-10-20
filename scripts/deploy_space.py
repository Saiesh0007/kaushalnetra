"""Publish deploy/space/build to a Hugging Face Docker Space (run scripts/build_space.py first; needs `hf auth login`).

    python scripts/deploy_space.py [--space NAME] [--private]

Copilot settings (KNETRA_LLM_*) are read from the environment or .env and stored as private Space secrets, never
uploaded as files. A random edge secret is set once, so only the Space's own edge agent can post events.
"""
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "deploy/space/build"


def dotenv() -> dict[str, str]:
    out = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return {**out, **{k: v for k, v in os.environ.items() if k.startswith("KNETRA_")}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="kaushalnetra")
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()
    if not (BUILD / "Dockerfile").exists():
        raise SystemExit("run scripts/build_space.py first")
    assert not list(BUILD.rglob(".env")), ".env must never be published"

    api = HfApi()
    repo = f"{api.whoami()['name']}/{args.space}"
    api.create_repo(repo, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
    env = dotenv()
    for k in ("KNETRA_LLM_BASE_URL", "KNETRA_LLM_API_KEY", "KNETRA_LLM_MODEL"):
        if env.get(k):
            api.add_space_secret(repo, k, env[k])
    known = {s for s in (api.get_space_variables(repo) or {})}
    if "KNETRA_EDGE_SECRET_SET" not in known:
        api.add_space_secret(repo, "KNETRA_EDGE_SECRET", secrets.token_urlsafe(24))
        api.add_space_variable(repo, "KNETRA_EDGE_SECRET_SET", "1")
    api.upload_folder(repo_id=repo, repo_type="space", folder_path=BUILD, commit_message="Deploy KaushalNetra")
    print(f"https://huggingface.co/spaces/{repo}")
    print(f"app: https://{repo.replace('/', '-').replace('_', '-').lower()}.hf.space")


if __name__ == "__main__":
    main()
