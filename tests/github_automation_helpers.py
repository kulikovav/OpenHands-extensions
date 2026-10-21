"""Exercise the actual shipped entrypoints with mocked GitHub/SDK boundaries."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def worker(name, tmp_path, monkeypatch, modules=None):
    """Load one automation bundle's worker in a scratch directory.

    The default `modules` set is the GitHub bundle's; pass the GitLab set for a
    GitLab bundle.
    """
    manifest = json.loads(
        (ROOT / f"automations/catalog/{name}/manifest.json").read_text()
    )
    bundle = tmp_path / name
    bundle.mkdir()
    for filename, source in manifest["setup"]["bundle"]["files"].items():
        (bundle / filename).write_text((ROOT / source).read_text())
    if modules is None:
        modules = (
            "agent_conversation",
            "main",
            "github_client",
            "maintainer_handoff",
            "qa_prompt",
            "worker",
        )
    for module in modules:
        monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.syspath_prepend(str(bundle))
    spec = importlib.util.spec_from_file_location("worker", bundle / "worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
