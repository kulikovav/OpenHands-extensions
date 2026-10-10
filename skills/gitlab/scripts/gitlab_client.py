"""Shared GitLab transport and project operations for GitLab automations."""

import argparse
import json
import os
import re
import subprocess
from functools import cached_property
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
from urllib.request import Request, urlopen


# The secret name of the GitLab token an OpenHands Cloud or Enterprise user's
# connected GitLab integration provides: how this run's sandbox serves it, and
# how a conversation sees it in its environment.
CLOUD_GITLAB_TOKEN_SECRET = "gitlab_token"
CLOUD_GITLAB_TOKEN_ENV = "GITLAB_TOKEN"

DEFAULT_GITLAB_API_URL = "https://gitlab.com/api/v4"


def is_cloud_run() -> bool:
    """Whether this run is on OpenHands Cloud or Enterprise.

    The automation service hands a run the Agent Server URL only on a local
    Agent Canvas; elsewhere the run talks to the OpenHands API instead.
    """
    return bool(os.environ.get("OPENHANDS_CLOUD_API_URL")) and not os.environ.get(
        "AGENT_SERVER_URL"
    )


def _load_cloud_secret(name: str) -> str | None:
    """Read one named secret of this run's sandbox from the OpenHands API."""
    api = os.environ["OPENHANDS_CLOUD_API_URL"].rstrip("/")
    request = Request(
        f"{api}/api/v1/sandboxes/{os.environ['SANDBOX_ID']}/settings/secrets/{name}",
        headers={"X-Session-API-Key": os.environ["SESSION_API_KEY"]},
    )
    try:
        with urlopen(request, timeout=90) as response:
            return response.read().decode().strip()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _load_secret(name: str) -> str:
    """Read one named secret from the environment, or from the configured Agent
    Server on a local run and the OpenHands API on a cloud one."""
    value = os.environ.get(name)
    if value:
        return value

    if is_cloud_run():
        value = _load_cloud_secret(name)
    else:
        from openhands.sdk.workspace import RemoteWorkspace

        workspace = RemoteWorkspace(
            host=os.environ["AGENT_SERVER_URL"],
            api_key=os.environ["SESSION_API_KEY"],
            working_dir=os.environ.get("WORKSPACE_BASE", "/workspace"),
        )
        try:
            secret = workspace.get_secrets([name]).get(name)
            value = secret.get_value() if secret else None
        finally:
            workspace.reset_client()
    if not value:
        raise ValueError(f"The GitLab credential {name} is unavailable")
    return value


def gitlab_request(
    token: str,
    method: str,
    path: str,
    api_url: str = DEFAULT_GITLAB_API_URL,
    params: dict | None = None,
    body: dict | None = None,
) -> tuple:
    url = f"{api_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if is_cloud_run():
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers["PRIVATE-TOKEN"] = token
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=90) as r:
        raw = r.read()
        return (json.loads(raw) if raw.strip() else {}), dict(r.headers)


def gitlab_paginate(
    token: str, path: str, api_url: str = DEFAULT_GITLAB_API_URL, params: dict | None = None
) -> list:
    results = []
    page = 1
    base_params = dict(params or {})
    base_params.setdefault("per_page", 100)
    for _ in range(1, 101):
        base_params["page"] = page
        data, _ = gitlab_request(token, "GET", path, api_url=api_url, params=base_params)
        if not isinstance(data, list):
            raise TypeError("Expected a paginated GitLab list")
        results.extend(data)
        if len(data) < int(base_params["per_page"]):
            return results
        page += 1
    raise RuntimeError("GitLab pagination exceeded limit")


def project_id(project: str) -> str:
    """The URL-encoded project path GitLab accepts wherever an ID is expected.

    Every separator has to be encoded, subgroup slashes included, or the path
    segments become routes of their own.
    """
    return quote(project, safe="")


class GitLabProject:
    name = "GitLab automation"

    def __init__(
        self,
        config_path=Path("config.json"),
        *,
        gitlab_token_secret,
        project=None,
        conversation=None,
        dispatcher=None,
    ):
        self.config = json.loads(Path(config_path).read_text())
        self.project = project or self.config["project"]
        # Subgroups are legal and common, so the path may carry them.
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", self.project):
            raise ValueError("project must be a namespace/project path")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", gitlab_token_secret):
            raise ValueError(
                "Expected the environment variable containing the GitLab token"
            )
        self.token_name = gitlab_token_secret
        self.api_url = self.config.get("gitlab_api_url") or DEFAULT_GITLAB_API_URL
        try:
            self.token = _load_secret(gitlab_token_secret)
        except ValueError:
            if not is_cloud_run():
                raise
            # No secret is saved under that name, so use the user's connected
            # GitLab integration, under the name a conversation sees it by.
            self.token = _load_cloud_secret(CLOUD_GITLAB_TOKEN_SECRET)
            if not self.token:
                raise
            self.token_name = CLOUD_GITLAB_TOKEN_ENV
        self.conversation = conversation
        self.conversation_id = str(conversation.id) if conversation else None
        self.dispatcher = dispatcher
        # A cloud run is not given a workspace base; its sandbox has /workspace.
        self.workspace = Path(os.environ.get("WORKSPACE_BASE", "/workspace"))
        self.project_dir = self.workspace
        self.evidence = self.project_dir / "evidence"
        self.evidence.mkdir(exist_ok=True)
        self._completed_dependencies = {}

    @cached_property
    def gl_username(self) -> str:
        return self.api("GET", "/user")["username"]

    @cached_property
    def project_record(self) -> dict:
        return self.gl("GET", "")

    @property
    def gitlab_instructions(self):
        # A cloud conversation runs in a sandbox of its own, so this run's
        # workspace path means nothing to it.
        where = "your working directory" if is_cloud_run() else self.project_dir
        host = self.api_url.split("/api/v4", 1)[0] or "https://gitlab.com"
        return (
            f"Call the GitLab API root `{self.api_url}` with the header "
            f"`PRIVATE-TOKEN: ${{{self.token_name}}}` (curl or plain HTTP) for "
            "GitLab requests. Never print the credential value. "
            f"Only {self.project} is in scope; the GitLab host is {host}. "
            f"Work in {where}. "
            "Do not modify the automation bundle or its configuration."
        )

    def gl(self, method, path, body=None):
        return gitlab_request(
            self.token, method, f"/projects/{project_id(self.project)}" + path,
            api_url=self.api_url, body=body,
        )[0]

    def api(self, method, path, params=None, body=None):
        """Call a GitLab endpoint that is not scoped to one project."""
        return gitlab_request(
            self.token, method, path, api_url=self.api_url, params=params, body=body
        )[0]

    def gl_pages(self, path, params=None):
        # The query travels with the path, so it has to merge with the
        # pagination params rather than follow them.
        split = urlsplit(path)
        merged = dict(parse_qsl(split.query))
        merged.update(params or {})
        return gitlab_paginate(
            self.token,
            f"/projects/{project_id(self.project)}" + split.path,
            api_url=self.api_url,
            params=merged,
        )

    def shell(self, args, cwd=None, timeout=300):
        result = subprocess.run(
            args,
            cwd=cwd or self.project_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"{args[0]} failed: {result.stdout[-4000:].replace(self.token, '[REDACTED]')}"
            )
        return result.stdout.strip()

    def comment(self, number, text):
        return self.gl(
            "POST",
            f"/merge_requests/{number}/notes",
            {
                "body": text
                + f"\n\nFactory role: `{self.name}`; conversation: `{self.conversation_id}`."
                + "\n\n_This note was posted by an AI agent (OpenHands)._"
            },
        )

    def open_merge_requests(self):
        """Every open merge request, oldest update first."""
        return self.gl_pages("/merge_requests?state=opened&order_by=updated_at&sort=asc")

    def merge_request(self, number):
        return self.gl("GET", f"/merge_requests/{number}")

    def mr_notes(self, number):
        """Every note on one merge request, oldest first."""
        return self.gl_pages(f"/merge_requests/{number}/notes", {"sort": "asc"})

    def mr_discussions(self, number):
        return self.gl_pages(f"/merge_requests/{number}/discussions")

    def pipelines(self, sha):
        """Every pipeline GitLab reported for one commit SHA."""
        return self.gl_pages("/pipelines", {"sha": sha})

    def commits_for_path(self, path, ref, per_page=10):
        return self.gl_pages(
            "/repository/commits", {"path": path, "ref_name": ref, "per_page": per_page}
        )

    def mr_diffs(self, number):
        """The changed files of one merge request."""
        return self.gl_pages(f"/merge_requests/{number}/diffs")

    def set_reviewers(self, number, usernames, keep_existing=True):
        """Set the merge request's reviewers to the named GitLab users.

        A PUT with `reviewer_ids` replaces the whole list, so requesting one
        additional reviewer would silently drop the ones already assigned. By
        default the existing reviewers are merged and kept; pass
        `keep_existing=False` to replace them deliberately.

        The merge-request entity exposes reviewers as objects, not as an id
        list, so the existing ids are read from `reviewers[]`.
        """
        user_ids = []
        for username in usernames:
            user = self.api("GET", "/users", params={"username": username})
            if not user:
                raise RuntimeError(f"No GitLab user named {username}")
            user_ids.append(user[0]["id"])
        if keep_existing:
            existing = [
                reviewer["id"]
                for reviewer in self.gl("GET", f"/merge_requests/{number}").get(
                    "reviewers", []
                )
            ]
            user_ids = list(dict.fromkeys([*user_ids, *existing]))
        return self.gl("PUT", f"/merge_requests/{number}", {"reviewer_ids": user_ids})


def run_projects(automation_type, conversation=None, dispatcher=None):
    parser = argparse.ArgumentParser(description=automation_type.__doc__)
    parser.add_argument("--gitlab-token-secret")
    args = parser.parse_args()
    config = json.loads(Path("config.json").read_text())
    token_name = args.gitlab_token_secret or config.get(
        "gitlab_token_secret", "GITLAB_TOKEN"
    )
    projects = config.get("projects") or [config["project"]]
    failures = []
    for project in projects:
        options = dict(
            gitlab_token_secret=token_name,
            project=project,
            conversation=conversation,
        )
        if dispatcher is not None:
            options["dispatcher"] = dispatcher
        automation = automation_type(**options)
        try:
            automation.run()
        except Exception as exc:  # noqa: BLE001 - one project must not block others
            failures.append(project)
            print(
                json.dumps({"project": project, "error": type(exc).__name__}),
                flush=True,
            )
    if failures:
        raise RuntimeError("Automation failed for: " + ", ".join(failures))
    return str(conversation.id) if conversation else None