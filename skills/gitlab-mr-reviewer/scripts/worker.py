"""Select requested merge-request heads and delegate each review to an agent."""

import json
import os
import sys
from functools import cached_property
from urllib.parse import urlsplit

import main as workflow
from agent_conversation import AgentConversationDispatcher
from gitlab_client import GitLabProject, run_projects
from maintainer_handoff import (
    HandoffConfigurationError,
    parse_maintainers,
    request_maintainer_review,
)

# The head-eligibility gate. Scheduled discovery classifies only the pipelines
# GitLab reports for the exact head SHA, because a merge request's head pipeline
# is the same merge-policy signal a GitLab review gate uses. An explicit
# reviewer request is the intake-policy exception and bypasses the gate
# entirely. A failed pipeline blocks, a pipeline that has not concluded means
# waiting never approval, and an unrecognized status fails closed rather than
# approving silently. A project with no CI configured treats an absent pipeline
# as green: there is no signal to wait for, and demanding one would pin every
# CI-less project out of the unrequested backlog review for good.
CHECK_GATE_MARKER = "<!-- openhands-review-gate:"
NON_BLOCKING_PIPELINES = frozenset({"success", "skipped"})
BLOCKING_PIPELINES = frozenset({"failed", "canceled"})
PENDING_PIPELINES = frozenset(
    {
        "created",
        "waiting_for_resource",
        "preparing",
        "pending",
        "running",
        "scheduled",
        "manual",
    }
)
# The gate is deterministic; this disclosure is what tells a reader no model ran.
WORKFLOW_DISCLOSURE = "no AI was used to generate this comment"


def _classify_pipelines(pipelines):
    """Split the head's pipelines into blocking, pending, and green names.

    Only the latest attempt per ref/source pair decides, so a re-run that a new
    push superseded cannot contribute its stale failure. Within a pair the
    higher pipeline id wins - pipeline ids are GitLab's monotonic per-project
    creation sequence, so the id orders reliably even when timestamps tie.
    """
    latest = {}
    for pipeline in pipelines:
        key = (pipeline.get("ref") or "", pipeline.get("source") or "")
        current = latest.get(key)
        if current is None or int(pipeline.get("id") or 0) > int(current.get("id") or 0):
            latest[key] = pipeline
    blocking, pending = [], []
    for pipeline in latest.values():
        name = pipeline.get("name") or f"pipeline {pipeline.get('id') or '?'}"
        status = (pipeline.get("status") or "").lower()
        if status in NON_BLOCKING_PIPELINES:
            continue
        if status in BLOCKING_PIPELINES:
            blocking.append(name)
        elif status in PENDING_PIPELINES:
            pending.append(name)
        else:
            # An unknown status fails closed rather than approving silently.
            blocking.append(name)
    if blocking:
        return "blocked", sorted(set(blocking))
    if pending:
        return "waiting", sorted(set(pending))
    return "green", []


class ReviewIntake:
    """The per-scan bound on new review conversations, shared across projects.

    A scheduled scan drains every eligible merge request, but starting an agent
    for each one at once exhausted the OSS Agent Canvas VM, so a small maximum
    caps what a single scan may start. The maximum is per scan and shared by
    every configured project rather than reset per project, and it bounds the
    conversations a scan *starts*: a delivery that only deduplicates, or
    reports an already-running conversation, reuses a runtime and consumes no
    slot. Candidates are drained oldest first, then by project and merge-request
    iid, so a scan over more candidates than the maximum allows starts the
    oldest and a later scan reaches the remainder.
    """

    def __init__(self):
        # The budget lives on the intake so a scan that drains project by
        # project still counts its conversations against one shared maximum.
        self._pending = []
        self._maximum = None
        self._started = 0

    def register(self, record):
        """Queue one eligible candidate for this scan's bounded drain.

        `record["priority"]` is 0 for an explicit reviewer request or the
        trigger label and 1 for an unrequested merge request, so explicit
        requests drain first.
        """
        self._pending.append(record)

    def drain(self):
        """Start the oldest pending conversations, up to the per-scan maximum.

        The budget is held on the intake, so a scan that drains project by
        project still counts its conversations against one shared maximum. A
        candidate whose dispatch raises is reported and skipped without
        consuming a slot, so the candidates behind it are still considered.
        """
        pending, self._pending = self._pending, []
        if not pending:
            return
        if self._maximum is None:
            self._maximum = pending[0]["config"].get(
                "max_new_per_run", workflow.MAX_NEW_PER_RUN
            )
        failures = []
        for record in sorted(
            pending,
            key=lambda item: (
                item["priority"],
                item["created_at"],
                item["project"],
                item["number"],
            ),
        ):
            if self._started >= self._maximum:
                break
            try:
                result = record["start"]()
            except Exception as exc:  # noqa: BLE001 - one MR must not block the scan
                failures.append(record["number"])
                print(
                    f"Failed to submit {record['project']} MR "
                    f"!{record['number']}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            # A retried conversation runs again, so it uses a slot like a new one.
            if result["disposition"] in ("created", "retried"):
                self._started += 1
        if failures:
            raise RuntimeError(
                "Reviewer scan failed for MRs: "
                + ", ".join(f"!{number}" for number in failures)
            )


class MergeRequestReviewer(GitLabProject):
    name = "gitlab-mr-reviewer"
    # The shared intake the shipped entrypoint creates once per scheduled scan,
    # so the per-run maximum spans every configured project. It is None for a
    # run() invoked on its own (tests, one-off scans), which then bounds its own
    # conversations with a private intake instead.
    scan_intake = None

    @property
    def intake(self):
        """The intake this run registers eligible candidates with.

        The shipped entrypoint sets `scan_intake` once, so every project in a
        scan shares one budget and the drain happens after all projects have
        been scanned. A run() with no shared intake uses its own, created lazily
        so it exists whether or not __init__ ran.
        """
        if self.scan_intake is not None:
            return self.scan_intake
        intake = self.__dict__.get("_intake")
        if intake is None:
            intake = self.__dict__["_intake"] = ReviewIntake()
        return intake

    @cached_property
    def git_host(self):
        return urlsplit(self.api_url).netloc

    @cached_property
    def trigger_reviewer(self):
        return self.config.get("trigger_reviewer", "").lstrip("@").lower()

    @cached_property
    def require_label(self):
        """Whether the scheduled scan reviews only merge requests with the label.

        The reviewer-request paths stay open: an outstanding request or a
        reviewer-request event still starts a review. Only the unrequested
        backlog scan is off, so a deployment whose intake policy is the trigger
        label does not review every open merge request.
        """
        return bool(self.config.get("require_label", False))

    @staticmethod
    def _event_payload():
        """Return the GitLab webhook payload, or None for a scheduled run."""
        raw = os.environ.get("AUTOMATION_EVENT_PAYLOAD")
        if not raw:
            return None
        outer = json.loads(raw)
        payload = (outer.get("event") or {}).get("payload")
        return payload if isinstance(payload, dict) else None

    def _review_notes(self, iid):
        """The token owner's finished-review notes, any head."""
        return [
            note
            for note in self.mr_notes(iid)
            if workflow._mine(note)
        ]

    def _latest_trigger_label_event(self, iid):
        return workflow._latest_trigger_label_event(self.token, self.project, iid)

    def _gate_comment(self, number, marker, body, names):
        """Post one gate explanation, upserting the automation's own note.

        The marker carries the head SHA and gate category, so a later run for a
        different head updates the note it owns instead of stacking another
        one. A run that finds the same marker still compares the full body, so
        a note written for one deployment is reworded in place when the retry it
        names changes -- an event-only gate note becomes the scheduled one when
        the automation is switched to cron -- and an unchanged body is a no-op.
        Every MR note is untrusted input: only a marker this account authored
        is "managed", so a marker someone else placed can neither suppress the
        explanation nor be edited. An unmarked deterministic note an existing
        project workflow already posted is treated as the equivalent
        explanation only when it names the same reported pipelines; a note about
        some other check is left alone and the gate posts its own.
        """
        notes = self.mr_notes(number)
        managed = [
            note
            for note in notes
            if CHECK_GATE_MARKER in (note.get("body") or "")
            and workflow._mine(note)
        ]
        matching = [
            note for note in managed if marker in (note.get("body") or "")
        ]
        if matching:
            target = max(matching, key=lambda note: int(note["id"]))
            if (target.get("body") or "").strip() == body.strip():
                return None
            self.gl(
                "PUT", f"/merge_requests/{number}/notes/{target['id']}", {"body": body}
            )
            return target["id"]
        if managed:
            target = max(managed, key=lambda note: int(note["id"]))
            self.gl(
                "PUT", f"/merge_requests/{number}/notes/{target['id']}", {"body": body}
            )
            return target["id"]
        if any(
            WORKFLOW_DISCLOSURE.lower() in (note.get("body") or "").lower()
            and all(name.lower() in (note.get("body") or "").lower() for name in names)
            for note in notes
            if CHECK_GATE_MARKER not in (note.get("body") or "")
        ):
            return None
        created = self.gl("POST", f"/merge_requests/{number}/notes", {"body": body})
        return created.get("id")

    def _gate_body(self, sha, state, names, scheduled):
        """Explain a stop, naming the retry this deployment actually has.

        A scheduled run proves a scan is configured, so it may promise the next
        scan. An event run does not, so it names the one mechanism this
        deployment is guaranteed to honor: removing and re-adding the reviewer
        request, because GitLab keeps a reviewer assigned and will not re-notify
        a person it still counts as requested.
        """
        short = sha[:12]
        listed = "\n".join(f"- `{name}`" for name in names)
        if state == "blocked":
            heading = "### ⚠️ Review paused: the head pipeline did not pass"
            lead = (
                f"The current head `{short}` has a pipeline that did not pass, "
                "so no review conversation was started:"
            )
            action = (
                "Fix the pipeline above and push. The scheduled scan then starts "
                "the review on the updated head."
                if scheduled
                else "Fix the pipeline above and push. Then remove the "
                f"`{self.trigger_reviewer}` reviewer and add them again - GitLab "
                "will not re-notify a reviewer it still counts as requested. "
                "The review starts on the updated head."
            )
        else:
            heading = "### ⏳ Review waiting on the pipeline"
            lead = (
                f"The current head `{short}` still has a pipeline that has not "
                "finished, so no review conversation was started:"
            )
            action = (
                "No action is needed. The scheduled scan retries once the "
                "pipeline reports a conclusion."
                if scheduled
                else "Once the pipeline reports a conclusion, remove the "
                f"`{self.trigger_reviewer}` reviewer and add them again - GitLab "
                "will not re-notify a reviewer it still counts as requested. "
                "That starts the review."
            )
        return (
            f"{heading}\n\n{lead}\n\n{listed}\n\n{action}\n\n"
            f"{CHECK_GATE_MARKER}{state}:{sha} -->\n\n"
            f"_This is an automated check - {WORKFLOW_DISCLOSURE}._"
        )

    def _gate_head(self, mr, requested=False, scheduled=False, explain=True):
        """Return the head's eligibility, explaining any stop on the MR.

        An explicit reviewer request is the intake-policy exception: the caller
        asked for this head by name, so the pipeline gate does not apply and no
        gate note is left. Scheduled discovery still gates on the head's
        pipeline. A merge request nobody asked about that is merely red or
        pending gets no managed note - announcing it for every open MR is what
        a full-backlog scan must avoid - while a requested or labeled head
        still gets its explanation.
        """
        sha = (mr.get("sha") or "").strip()
        if requested:
            return "green", sha
        state, names = _classify_pipelines(self.pipelines(sha))
        if explain and state in ("blocked", "waiting"):
            marker = f"{CHECK_GATE_MARKER}{state}:{sha} -->"
            self._gate_comment(
                mr["iid"],
                marker,
                self._gate_body(sha, state, names, scheduled),
                names,
            )
        return state, sha

    def _outstanding_review_request(self, mr):
        """Whether one open MR, including a draft, still waits for this reviewer.

        GitLab keeps a reviewer assigned until they are removed, so the request
        itself never expires the way a GitHub review request does; what ends it
        is either the reviewer's decided state or a head review this automation
        already published, and the run() flow checks those before this branch
        alone starts a review.
        """
        return any(
            (item.get("username") or "").lower() == self.trigger_reviewer
            for item in mr.get("reviewers") or []
        )

    def _has_current_head_review(self, number, sha):
        """Whether the reviewer account already published a review on this head.

        This is the candidate filter's negative: an open, non-draft MR without a
        current-head review by the configured reviewer is eligible for a
        scheduled scan even when nobody requested the bot. The same predicate is
        what the completion handler reconciles, so a review this scan starts and
        a review it finds already present are the same set.
        """
        return sha != "" and bool(workflow._review_notes_on(self._review_notes(number), sha))

    def _latest_head_verdict_note(self, number, sha):
        """The newest of this account's verdict notes bound to one head.

        GitLab binds nothing to a commit on its own, so the hidden marker the
        review note carries is the binding. Returns the note dict, or None when
        the head has no finished review.
        """
        notes = workflow._review_notes_on(self._review_notes(number), sha)
        if not notes:
            return None
        return max(
            notes,
            key=lambda note: (note.get("created_at") or "", int(note.get("id") or 0)),
        )

    def _head_verdict_notes(self, number, sha):
        """The head-bound notes of this account that end in a recognized verdict.

        A note carrying the head marker but no verdict is not a finished review
        - it can be a fallback post of a problem report - so a verdict line is
        what makes it a completion. The verdict must be the body's last line:
        the marker sits at the start, so no reply or later edit can outrank it
        by happening to end with the verdict text.
        """
        notes = workflow._review_notes_on(self._review_notes(number), sha)
        return [
            note
            for note in notes
            if workflow._verdict_of((note.get("body") or "").rstrip())
        ]

    def _clarified_since(self, number, submitted_at):
        """Whether a human clarified the merge request after a review.

        A note by someone other than the reviewer accounts is the one thing that
        makes reviewing an unchanged head worth another conversation: the author
        answered a finding, so the earlier verdict no longer speaks to the
        current state. Any other account (an author, a maintainer, a different
        bot workflow posting a new result) counts, and the reviewer account's
        own notes are excluded so its "reviewing now" and verdict notes cannot
        re-trigger it.
        """
        if not submitted_at:
            return False
        for note in self.mr_notes(number):
            username = ((note.get("author") or {}).get("username") or "").lower()
            if username in {"", self.gl_username.lower(), self.trigger_reviewer}:
                continue
            if (note.get("created_at") or "") > submitted_at:
                return True
        return False

    def _reviewed_current_head_without_clarification(self, number, sha):
        """Whether the current head is already reviewed and nothing has changed.

        A review on this exact head, followed by no clarifying note from anyone
        else, means another conversation would publish a second review of the
        same code — the same verdict twice, spending a runtime to repeat it. The
        head advancing, or any human note arriving afterwards, makes the head
        eligible again under the normal rules.

        Returns the reviewed head's latest note time (for the log line) or None
        when the head should be reviewed.
        """
        if not sha:
            return None
        note = self._latest_head_verdict_note(number, sha)
        if note is None:
            return None
        when = note.get("created_at") or ""
        if self._clarified_since(number, when):
            return None
        return when

    def _unrequested_head(self, mr):
        """The current-head delivery key for an unrequested MR, or None.

        The key is the project/MR identity plus the head SHA, so repeated
        scheduled scans over one head reuse one conversation and one review,
        while a changed head becomes eligible again under its new SHA.
        """
        sha = (mr.get("sha") or "").strip()
        return f"scan:{self.project}:{mr['iid']}:{sha}"

    def _labels(self, mr):
        return workflow._labels(mr)

    def _scan_candidates(self, mrs, label):
        """Return every potentially reviewable MR in the scheduled backlog.

        The scan must classify the whole backlog so blocked, pending, draft, or
        already-reviewed heads cannot hide eligible heads behind an inspection
        window. The shared ReviewIntake applies the configured maximum only when
        conversations are launched.
        """
        candidates = []
        lowered = label.lower()
        for mr in mrs:
            labels = {item.lower() for item in workflow._labels(mr)}
            if (
                mr.get("draft")
                and lowered not in labels
                and not self._outstanding_review_request(mr)
            ):
                continue
            candidates.append(mr)
        return candidates

    def _request_signal(self, payload):
        """Whether the webhook reports a reviewer request for this automation.

        GitLab fires one merge-request `update` event for every reviewer state
        change, so "a reviewer was requested" and "the requested reviewer began
        or finished reviewing" arrive in the same shape. The previous reviewer
        array separates them: adding the configured reviewer makes them appear
        in the current array without being in the previous one, and a
        re-request is flagged `re_requested` on the current entry. Anything
        else - the reviewer starting their review, or a state change that is
        not an add - is the reviewer's own activity, not a request.
        """
        attributes = payload.get("object_attributes") or {}
        if attributes.get("action") != "update":
            return False
        changes = payload.get("changes") or {}
        reviewers = changes.get("reviewers") or []
        current = reviewers[-1] if reviewers else []
        # `changes.reviewers` is a [previous, current] pair per the webhook
        # reference; with a single array there is no previous to compare against
        # and the add/re-request flags decide alone.
        previous = reviewers[0] if len(reviewers) > 1 else []
        previous_usernames = {
            (item.get("username") or "").lower() for item in previous or []
        }
        for reviewer in current or []:
            if (reviewer.get("username") or "").lower() != self.trigger_reviewer:
                continue
            state = (reviewer.get("state") or "").lower()
            if state in ("approved", "requested_changes"):
                # A decided state is the reviewer's own submitted review, not a
                # request for one; _event_completion owns it.
                return False
            if reviewer.get("re_requested"):
                return True
            if (reviewer.get("username") or "").lower() not in previous_usernames:
                return True
            # The reviewer was already listed: this event is their review
            # starting, not a request to review.
            return False
        return False

    def _event_candidate(self, payload):
        """The MR a GitLab webhook names, when this automation should act.

        Either a reviewer request (_request_signal) or the configured reviewer's
        own submitted review or approval - a completion signal the run
        reconciles rather than relaunches.
        """
        project = (payload.get("project") or {}).get("path_with_namespace") or ""
        if project.lower() != self.project.lower():
            return None
        attributes = payload.get("object_attributes")
        if not isinstance(attributes, dict) or attributes.get("iid") is None:
            return None
        action = attributes.get("action")
        if action in ("approval", "unapproval"):
            # Only the configured reviewer's own approval is this automation's
            # business; anyone else's approval is someone else's review.
            return (
                attributes
                if ((payload.get("user") or {}).get("username") or "").lower()
                == self.trigger_reviewer
                else None
            )
        if self._request_signal(payload):
            return attributes
        return None

    def _event_completion(self, payload):
        """The review the webhook reports as submitted, or None.

        The configured reviewer's approval action, or their reviewer state
        having reached a decided value without a re-request flag, means the
        reviewer submitted a review. It is a completion signal: the run
        reconciles the verdict it reports rather than starting a review.
        """
        attributes = payload.get("object_attributes") or {}
        action = attributes.get("action")
        if action in ("approval", "unapproval"):
            if ((payload.get("user") or {}).get("username") or "").lower() == (
                self.trigger_reviewer
            ):
                return {"state": action, "created_at": attributes.get("updated_at") or ""}
            return None
        changes = payload.get("changes") or {}
        reviewers = changes.get("reviewers") or []
        current = reviewers[-1] if reviewers else []
        for reviewer in current or []:
            if (reviewer.get("username") or "").lower() != self.trigger_reviewer:
                continue
            if reviewer.get("re_requested"):
                return None
            if (reviewer.get("state") or "").lower() in ("approved", "requested_changes"):
                return {
                    "state": (reviewer.get("state") or "").lower(),
                    "created_at": attributes.get("updated_at") or "",
                }
        return None

    def _prompt(self, mr, trigger, label=None, delivery_key=None):
        number = mr["iid"]
        sha = (mr.get("sha") or "").strip()
        token = self.token_name
        workspace = (
            "The workspace contains an empty Git directory. Set up the shared "
            "Git credential ONCE, without touching the remote URL or printing "
            "the token: run `git config --global credential.https://"
            + self.git_host
            + ".helper '!f() { echo username=openhands; echo password=${"
            + token
            + "}; }; f'`, then `git fetch https://"
            + self.git_host
            + "/"
            + self.project
            + ".git merge-requests/"
            + str(number)
            + "/head`, then `git checkout FETCH_HEAD`, then confirm "
            "`git rev-parse HEAD` reports `"
            + sha
            + "`. Work in detached-HEAD mode. Set `GIT_TERMINAL_PROMPT=0` on "
            "Git network commands so a missing permission fails immediately "
            "instead of waiting for input."
        )
        if label:
            trigger_description = None
        elif delivery_key is not None:
            trigger_description = (
                f"scheduled scan of open, non-draft merge requests on head `{sha}`"
            )
        else:
            trigger_description = (
                f"the reviewer request for `{self.trigger_reviewer}` "
                f"(GitLab id {trigger.get('id', '?')}, updated "
                f"{trigger.get('created_at', '?')})"
            )
        prompt = workflow._build_review_prompt(
            self.project,
            mr,
            sha,
            trigger or {},
            workspace_instructions=workspace,
            gitlab_token_secret=token,
            trigger_description=trigger_description,
        )
        if label:
            moved_head_instruction = (
                f"leave `{label}` in place so the new head is reviewed"
            )
            trigger_completion = (
                f"Leave the `{label}` label in place after GitLab accepts the "
                "review. The deterministic scanner removes it"
            )
        elif delivery_key is not None:
            # A scheduled scan reviews a new head again on its own, so there is
            # no request to preserve and no label to leave behind.
            moved_head_instruction = (
                "publish no review; a later scheduled scan reviews the new head"
            )
            trigger_completion = (
                "Do not change reviewers after GitLab accepts the review. "
                "The deterministic scan records the completed review"
            )
        else:
            moved_head_instruction = (
                "publish no review; the new head requires another reviewer request"
            )
            trigger_completion = (
                "Do not change reviewers after GitLab accepts the review. "
                "The deterministic event handler completes the request"
            )
        author = ((mr.get("author") or {}).get("username") or "").lower()
        self_review_note = (
            "\n- This merge request is authored by the configured reviewer account, "
            "and approving its own merge request may be refused by project policy. "
            "Publish the clean summary note and keep the approved verdict instead "
            "of retrying the approval endpoint."
            if author == self.trigger_reviewer
            else ""
        )
        return (
            prompt + "\n\nAcceptance reporting:\n"
            "- Inspect the current pipeline results for the exact head and run "
            "the project's appropriate focused tests in the workspace. Do not "
            "modify tracked files.\n"
            "- Before publishing anything, read the MR's existing notes and "
            "threads on GitLab. If this account has already published a review "
            f"note for head `{sha}` and no one else has commented since that "
            "note, do NOT publish a second review and do NOT start another "
            "review pass: another review of identical code is a duplicate. "
            "Report the earlier verdict as still current and stop. Review the "
            "head again only when the head has moved, or when a note from "
            "someone other than this account was posted after the earlier "
            "review.\n"
            "- If a review by this account is currently underway for this head, "
            "wait for it instead of starting a second one.\n"
            f"- Re-read {self.project} MR !{number} immediately before reporting. "
            "Confirm its current description, labels, threads, reviewers, and the "
            "head's pipeline results, and re-read every linked issue's current "
            "description and labels: an issue's readiness or priority may have "
            "changed since an earlier turn. "
            f"If the head is no longer `{sha}`, {moved_head_instruction}.\n"
            f"- {trigger_completion} after completing any configured "
            "human-review handoff. Never paste JSON artifacts or full command logs "
            "into notes.\n"
            "- Once GitLab accepts the review note, stop immediately. Do not "
            "continue inspecting the repository, run more commands, or publish a "
            f"second result.{self_review_note}"
        )

    def _finish_completed_review(self, mr, label=None):
        """Complete an exact-head review, including an optional human handoff.

        `mr` is the freshly fetched merge request. There is no trigger argument:
        the head SHA is the whole key, so any finished review of this head by
        this account is the completion of work for it. That is what lets an
        unrequested review the scan started be reconciled and handed off on a
        later scan instead of being restarted. The newest head-bound verdict
        note is the standing verdict, so a newer verdict supersedes an older
        one.
        """
        head_sha = (mr.get("sha") or "").strip()
        verified = self._head_verdict_notes(mr["iid"], head_sha)
        if not verified:
            return False
        newest = max(
            verified,
            key=lambda note: (note.get("created_at") or "", int(note.get("id") or 0)),
        )
        verdict = workflow._verdict_of((newest.get("body") or "").rstrip())
        # A changes-requested verdict completes the request on its own; only an
        # approval, or a scope stop, hands off to a maintainer. A scope stop is
        # not an approval: it requests the maintainer decision the change is
        # missing, through the same handoff as an approval.
        if verdict in (workflow.APPROVED_VERDICT, workflow.MAINTAINER_DECISION_VERDICT):
            maintainers = parse_maintainers(self.config.get("maintainers"))
            if maintainers:
                try:
                    selected = request_maintainer_review(self, mr, maintainers)
                except HandoffConfigurationError as exc:
                    self.gl(
                        "POST",
                        f"/merge_requests/{mr['iid']}/notes",
                        {
                            "body": (
                                "⚠️ **Automated maintainer handoff could not be "
                                f"completed:** {exc}. Update the automation's "
                                "maintainer roster, then request another review."
                                "\n\n_This is an automated configuration check; "
                                "no AI was used to generate this note._"
                            )
                        },
                    )
                    selected = None
                print(
                    json.dumps(
                        {
                            "project": self.project,
                            "mr": mr["iid"],
                            "human_reviewer": selected,
                        }
                    ),
                    flush=True,
                )
        current = self.gl("GET", f"/merge_requests/{mr['iid']}")
        if (current.get("sha") or "").strip() != head_sha:
            # Treat this scan as handled so it cannot redeliver the stale head.
            # Scheduled mode leaves its label in place; event mode requires a
            # fresh review request for the new head.
            return True
        if label:
            self.gl("PUT", f"/merge_requests/{mr['iid']}", {"remove_labels": label})
        return True

    def run(self):
        # main.py fills this only when it runs standalone; the catalog
        # entrypoint reaches the same token identity through the client, so the
        # marker checks in workflow know which notes are this automation's own.
        workflow._AUTH_USERNAME = self.gl_username
        project_record = self.gl("GET", "")
        project_number = project_record["id"]
        label = self.config.get("trigger_label", workflow.TRIGGER_LABEL)
        payload = self._event_payload()
        event_mode = payload is not None
        if not event_mode:
            mrs = self._scan_candidates(self.open_merge_requests(), label)
        else:
            candidate = self._event_candidate(payload)
            if candidate and self.gl_username.lower() != self.trigger_reviewer:
                raise RuntimeError(
                    "The configured GitLab credential must authenticate as "
                    f"{self.trigger_reviewer} for reviewer-request mode"
                )
            mrs = [candidate] if candidate else []
        failures = []
        for mr in mrs:
            try:
                number = mr["iid"]
                submitted_event = self._event_completion(payload) if event_mode else None
                fresh_mr = self.gl("GET", f"/merge_requests/{number}")
                has_label = workflow._has_trigger_label(fresh_mr)
                requested = self._outstanding_review_request(fresh_mr)
                trigger_label = label if (not event_mode and has_label) else None
                unrequested_candidate = False
                if event_mode or has_label:
                    trigger = (
                        self._latest_trigger_label_event(number)
                        if has_label and not event_mode
                        else {
                            "id": f"reviewer-{number}",
                            "created_at": fresh_mr.get("updated_at") or "",
                        }
                    )
                    delivery_key = None
                elif requested:
                    # The outstanding request is the trigger. GitLab keeps a
                    # reviewer assigned, so neither a request id nor a request
                    # event exists to key on: the head SHA is the whole key, and
                    # a head this account already reviewed is caught by the
                    # finished-review checks below rather than re-reviewed.
                    trigger = {
                        "id": f"reviewer-{number}",
                        "created_at": fresh_mr.get("updated_at") or "",
                    }
                    delivery_key = None
                else:
                    # No label and no outstanding request: an unrequested MR the
                    # scheduled scan reviews on its own, keyed by project/MR/
                    # head. A draft is not reviewable, and a head this account
                    # already reviewed is done - reconcile that review's verdict
                    # and maintainer handoff, then skip it so no second
                    # conversation or review is created.
                    if fresh_mr.get("draft"):
                        continue
                    head_sha = (fresh_mr.get("sha") or "").strip()
                    if self._has_current_head_review(number, head_sha):
                        self._finish_completed_review(fresh_mr, None)
                        continue
                    if self.require_label:
                        # The label is this deployment's intake policy, so the
                        # scan leaves the unrequested backlog alone. A request
                        # still starts its review through the branch above.
                        continue
                    trigger = None
                    delivery_key = self._unrequested_head(fresh_mr)
                    unrequested_candidate = True
                if trigger is None and delivery_key is None:
                    # A label was applied at MR creation and carries no resource
                    # label event, or the matching event has yet to be readable.
                    # There is no request to preserve, so there is nothing to
                    # key a review on; a submitted review is its own completion
                    # signal and is reconciled further below.
                    if submitted_event is None:
                        continue
                # A head this account already reviewed, with no clarifying note
                # since, is done: another conversation would publish a second
                # review of identical code. This must come before the delivery
                # dispatch, because a fresh trigger produces a new delivery key
                # that would otherwise start a second review on an unchanged
                # head.
                already = self._reviewed_current_head_without_clarification(
                    number, (fresh_mr.get("sha") or "").strip()
                )
                if already:
                    print(
                        json.dumps(
                            {
                                "project": self.project,
                                "mr": number,
                                "head_sha": fresh_mr.get("sha"),
                                "disposition": "review-already-published",
                                "reviewed_at": already,
                            }
                        ),
                        flush=True,
                    )
                    if trigger is not None or submitted_event is not None:
                        # Reconcile the completed review (clearing the label and
                        # running the maintainer handoff). A head that carries a
                        # verdict completes normally; a head that carries only
                        # this account's review marker has no verdict to
                        # reconcile, so the label is cleared directly -
                        # otherwise the label stays and every later scan re-reads
                        # this head and re-logs with no effect.
                        if not self._finish_completed_review(fresh_mr, trigger_label) and trigger_label:
                            self.gl(
                                "PUT",
                                f"/merge_requests/{number}",
                                {"remove_labels": trigger_label},
                            )
                    continue
                if delivery_key is None and self._finish_completed_review(
                    fresh_mr, trigger_label
                ):
                    continue
                if event_mode and submitted_event is not None:
                    # A submitted review is a completion signal, never a fresh
                    # trigger. A non-decisive update, or one superseded by a new
                    # head, must wait for another reviewer request instead of
                    # dispatching a review the caller never asked for.
                    continue
                sha = (fresh_mr.get("sha") or "").strip()
                gate_state, sha = self._gate_head(
                    fresh_mr,
                    requested=event_mode,
                    scheduled=not event_mode,
                    explain=not unrequested_candidate,
                )
                if gate_state != "green":
                    # A deterministic blocker stops the run without spending a
                    # worker slot on an agent. The trigger is not consumed: the
                    # next scheduled scan or explicit request re-evaluates the
                    # head once its pipeline is non-blocking. An unrequested head
                    # that is merely red or pending gets no managed note, so a
                    # scan over a large backlog cannot storm the MRs with gate
                    # notes; the managed note answers an explicit request.
                    print(
                        json.dumps(
                            {
                                "project": self.project,
                                "mr": number,
                                "head_sha": sha,
                                "disposition": f"review-{gate_state}",
                            }
                        ),
                        flush=True,
                    )
                    continue
                record = {
                    "project": self.project,
                    "number": number,
                    # An explicit request is ordered before an unrequested
                    # candidate; within a priority the oldest candidate drains
                    # first - the request time for a requested MR, the MR's own
                    # creation time (oldest first) for an unrequested one - and
                    # project and iid break a tie so the order is
                    # deterministic.
                    "priority": 0 if (has_label or requested) else 1,
                    "created_at": (
                        trigger.get("created_at") or ""
                        if trigger
                        else fresh_mr.get("created_at") or ""
                    ),
                    "config": self.config,
                    "start": lambda mr=fresh_mr, trigger=trigger, sha=sha,
                    trigger_label=trigger_label,
                    delivery_key=delivery_key: self._start_review(
                        project_number, mr, trigger, sha, trigger_label, delivery_key
                    ),
                }
                if event_mode:
                    # An explicit request is a caller's decision to spend a
                    # conversation now, not a backlog item, so the event path
                    # dispatches immediately and is never bounded by the
                    # scheduled scan's per-run maximum.
                    self._start_review(
                        project_number,
                        fresh_mr,
                        trigger,
                        sha,
                        trigger_label,
                        delivery_key,
                    )
                else:
                    self.intake.register(record)
            except Exception as exc:  # noqa: BLE001 - one MR must not block the scan
                failures.append(mr.get("iid", "?"))
                print(
                    f"Failed to submit {self.project} MR "
                    f"!{mr.get('iid', '?')}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
        if self.scan_intake is None:
            # A run() with no shared scan intake owns its whole scan, so it
            # drains the candidates it collected, bounded by the per-run maximum.
            self.intake.drain()
        if failures:
            raise RuntimeError(
                "Reviewer scan failed for MRs: "
                + ", ".join(f"!{number}" for number in failures)
            )

    def _start_review(
        self, project_number, mr, trigger, sha, trigger_label, delivery_key=None
    ):
        result = self.dispatcher.deliver(
            subject=f"{project_number}:mr:{mr['iid']}",
            delivery=delivery_key or f"{trigger['id']}:{sha}",
            prompt=self._prompt(mr, trigger, trigger_label, delivery_key),
            head=sha,
        )
        print(
            json.dumps(
                {
                    "project": self.project,
                    "mr": mr["iid"],
                    "head_sha": sha,
                    "disposition": result["disposition"],
                    "conversation_id": result["conversation_id"],
                }
            ),
            flush=True,
        )
        return result


def run_scan(dispatcher):
    """Run one scheduled scan over every configured project, then drain.

    One shared intake spans the whole scan, so the per-run maximum is global
    rather than reset per project, and the drain happens after every project
    has been scanned so the oldest outstanding request across all of them
    starts first. One project failing must not discard another project's
    drained candidates, so the drain still runs and the first failure is what
    the scan reports.
    """
    MergeRequestReviewer.scan_intake = ReviewIntake()
    failure = None
    try:
        run_projects(MergeRequestReviewer, dispatcher=dispatcher)
    except Exception as exc:  # noqa: BLE001 - reported after the drain
        failure = exc
    try:
        MergeRequestReviewer.scan_intake.drain()
    except Exception as exc:  # noqa: BLE001 - reported after the scan failure
        failure = failure or exc
    if failure is not None:
        raise failure


if __name__ == "__main__":
    with AgentConversationDispatcher() as dispatcher:
        run_scan(dispatcher)