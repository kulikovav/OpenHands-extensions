"""Choose one code-aware, currently available maintainer for a reviewed MR."""

_DECIDED_REVIEWER_STATES = {"approved", "requested_changes"}
_MAX_PATHS = 8
_COMMITS_PER_PATH = 10


class HandoffConfigurationError(ValueError):
    """The configured roster cannot produce a GitLab review request."""


def parse_maintainers(value):
    """Normalize a comma-separated catalog value or a JSON-style list."""
    if isinstance(value, str):
        value = value.split(",")
    result = []
    seen = set()
    for item in value or []:
        username = str(item).strip().lstrip("@")
        key = username.lower()
        if username and key not in seen:
            seen.add(key)
            result.append(username)
    return result


def _reviewer_usernames(mr):
    return {
        ((item.get("username") or "")).lower() for item in mr.get("reviewers") or []
    }


def _reviewer_states(mr):
    """The standing of each current reviewer according to GitLab itself."""
    standing = {}
    for reviewer in mr.get("reviewers") or []:
        username = (reviewer.get("username") or "").lower()
        state = (reviewer.get("state") or "").lower()
        if username and state:
            standing[username] = state
    return standing


def _maintainer_email(project, username):
    """The primary email of a roster member, or None when it cannot be read.

    GitLab redacts emails for callers who are not administrators, so this is
    best-effort: a public email is the only address a non-admin token sees, and
    a candidate whose email is not readable scores zero on the changed-path
    ranking rather than failing the handoff.
    """
    users = project.api("GET", "/users", params={"username": username})
    if not users:
        return None
    email = (
        users[0].get("public_email") or users[0].get("commit_email") or users[0].get("email") or ""
    )
    return email.lower() or None


def _path_scores(project, mr_number, base_ref, emails):
    """Score one candidate per changed path by how many base-branch commits
    that candidate authored for it, exactly as the GitHub handoff does.

    GitLab commits carry an email rather than a login, so candidates are matched
    on the email their GitLab account reports. A candidate whose email is not
    readable, or who committed under another address, simply scores zero - the
    same outcome as GitHub's login-less commits.
    """
    scores = {username: 0 for username in emails}
    changed_files = project.mr_diffs(mr_number)[:_MAX_PATHS]
    for changed_file in changed_files:
        path = changed_file.get("new_path")
        if not path:
            continue
        commits = project.commits_for_path(path, base_ref, per_page=_COMMITS_PER_PATH)
        for rank, commit in enumerate(commits[:_COMMITS_PER_PATH]):
            commit_email = (commit.get("author_email") or "").lower()
            for username, email in emails.items():
                if commit_email and commit_email == email:
                    scores[username] += _COMMITS_PER_PATH - rank
    return scores


def _open_review_load(project, username):
    """How many open merge requests in this project name the user a reviewer."""
    return len(
        project.gl_pages(
            "/merge_requests",
            params={"state": "opened", "reviewer_username": username, "per_page": 100},
        )
    )


def request_maintainer_review(project, mr, maintainers):
    """Ensure one configured maintainer is reviewing *mr*.

    API failures propagate so the worker can retry on a later scan. The return
    value is the existing or newly requested username.
    """
    roster = parse_maintainers(maintainers)
    if not roster:
        return None

    by_key = {username.lower(): username for username in roster}
    current = _reviewer_usernames(mr)
    for username in roster:
        if username.lower() in current:
            return username

    standing = _reviewer_states(mr)
    # A maintainer whose current review state is decisive stays the right
    # reviewer: their approval remains useful after a later push, and someone
    # who requested changes is the one who must look at the new head. GitLab
    # reviewer state is not scoped to a head the way GitHub reviews are, so the
    # MR's live state is the whole standing, not a per-head slice of it.
    for username in roster:
        if standing.get(username.lower()) in _DECIDED_REVIEWER_STATES:
            return username

    author = ((mr.get("author") or {}).get("username") or "").lower()
    candidates = [key for key in by_key if key != author]
    if not candidates:
        raise HandoffConfigurationError(
            "No eligible maintainer remains after excluding the MR author"
        )

    base_ref = mr.get("target_branch") or "main"
    emails = {key: _maintainer_email(project, by_key[key]) for key in candidates}
    scores = _path_scores(project, mr["iid"], base_ref, emails)
    loads = {
        key: _open_review_load(project, by_key[key])
        for key in candidates
    }
    order = {key: index for index, key in enumerate(candidates)}
    selected = by_key[min(candidates, key=lambda key: (-scores[key], loads[key], order[key]))]
    project.set_reviewers(mr["iid"], [selected])
    return selected