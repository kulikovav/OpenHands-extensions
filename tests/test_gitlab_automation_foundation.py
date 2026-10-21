"""Contracts for the shared GitLab automation foundation."""

import json
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/gitlab/scripts"))

import gitlab_client  # noqa: E402

from github_automation_helpers import worker as load_worker  # noqa: E402


def _configure(tmp_path, monkeypatch, projects):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker.py"])
    (tmp_path / "config.json").write_text(
        json.dumps({"projects": projects, "gitlab_token_secret": "GITLAB_TOKEN"})
    )


@pytest.mark.parametrize("status", [429, 503])
def test_run_projects_retries_a_transient_http_error(
    tmp_path, monkeypatch, status
):
    _configure(tmp_path, monkeypatch, ["infr/tools/acme-proxy"])
    delays = []
    monkeypatch.setattr(gitlab_client.time, "sleep", delays.append)
    calls = []

    class Automation:
        def __init__(self, **kwargs):
            self.project = kwargs["project"]

        def run(self):
            calls.append(self.project)
            if len(calls) == 1:
                raise HTTPError(
                    "https://git.example/api", status, "Transient", {}, None
                )

    gitlab_client.run_projects(Automation)

    assert calls == ["infr/tools/acme-proxy", "infr/tools/acme-proxy"]
    assert delays == [1]


def test_run_projects_retries_a_timeout(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, ["infr/tools/acme-proxy"])
    monkeypatch.setattr(gitlab_client.time, "sleep", lambda _: None)
    calls = []

    class Automation:
        def __init__(self, **kwargs):
            pass

        def run(self):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("timed out")

    gitlab_client.run_projects(Automation)

    assert calls == [1, 1]


def test_run_projects_reports_exhausted_retries(tmp_path, monkeypatch, capsys):
    _configure(tmp_path, monkeypatch, ["infr/tools/acme-proxy"])
    monkeypatch.setattr(gitlab_client.time, "sleep", lambda _: None)
    calls = []

    class Automation:
        def __init__(self, **kwargs):
            pass

        def run(self):
            calls.append(1)
            raise HTTPError(
                "https://git.example/api", 503, "Service Unavailable", {}, None
            )

    with pytest.raises(
        RuntimeError, match=r"HTTPError: HTTP Error 503"
    ) as excinfo:
        gitlab_client.run_projects(Automation)

    assert calls == [1, 1, 1]
    assert isinstance(excinfo.value.__cause__, HTTPError)
    output = capsys.readouterr().out
    assert '"retrying": false' in output
    assert '"detail": "HTTP Error 503: Service Unavailable"' in output


def test_run_projects_keeps_going_when_a_constructor_fails(tmp_path, monkeypatch):
    _configure(
        tmp_path, monkeypatch, ["infr/tools/failed", "infr/tools/next"]
    )
    visited = []

    class Automation:
        def __init__(self, **kwargs):
            self.project = kwargs["project"]
            if self.project == "infr/tools/failed":
                raise ValueError("bad config")

        def run(self):
            visited.append(self.project)

    with pytest.raises(RuntimeError, match="infr/tools/failed"):
        gitlab_client.run_projects(Automation)

    assert visited == ["infr/tools/next"]


def test_run_projects_reports_a_permanent_http_status(tmp_path, monkeypatch, capsys):
    _configure(tmp_path, monkeypatch, ["infr/tools/acme-proxy"])
    monkeypatch.setattr(gitlab_client.time, "sleep", lambda _: None)
    calls = []

    class Automation:
        def __init__(self, **kwargs):
            pass

        def run(self):
            calls.append(1)
            raise HTTPError("https://git.example/api", 403, "Forbidden", {}, None)

    with pytest.raises(RuntimeError, match=r"HTTPError: HTTP Error 403"):
        gitlab_client.run_projects(Automation)

    assert calls == [1]
    output = capsys.readouterr().out
    assert '"status": 403' in output
    assert '"retrying": false' in output


def test_scan_failure_reports_the_underlying_cause(tmp_path, monkeypatch):
    module = load_worker(
        "gitlab-mr-reviewer",
        tmp_path,
        monkeypatch,
        modules=(
            "agent_conversation",
            "gitlab_client",
            "main",
            "maintainer_handoff",
            "worker",
        ),
    )
    intake = module.ReviewIntake()

    def start():
        raise TimeoutError("timed out")

    intake.register(
        {
            "project": "infr/tools/meet",
            "number": 25,
            "priority": 0,
            "created_at": "",
            "config": {"max_new_per_run": 1},
            "start": start,
        }
    )

    with pytest.raises(
        RuntimeError,
        match=r"Reviewer scan failed for MRs: !25 \(TimeoutError: timed out\)",
    ) as excinfo:
        intake.drain()

    assert isinstance(excinfo.value.__cause__, TimeoutError)