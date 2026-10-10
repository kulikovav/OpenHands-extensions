"""Unit tests for gitlab-mr-reviewer main.py and worker.py.

Run from the skill root:
    python -m pytest tests/
or with the standard library runner:
    python -m unittest discover tests

The focus is the logic that owns files and state: preparing a checkout from an
untrusted archive, removing it again, keeping one project's state apart from
another's, binding a review to its exact head through the note marker, deciding
the head pipeline gate, and reading a GitLab webhook as a request or a
completion.
"""

import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Allow importing the scripts from the sibling scripts/ directory, including
# the packed-bundle flat layout the catalog ships.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import main  # noqa: E402
import worker  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────

ARCHIVE_ROOT = "group-project-abc123"


def _tarball(members) -> bytes:
    """Build a .tar.gz from (name, kind, payload) triples.

    kind is "file", "dir", or "symlink"; payload is the file body or, for a
    symlink, its target.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, kind, payload in members:
            info = tarfile.TarInfo(name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = payload
                tar.addfile(info)
            else:
                data = payload.encode()
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _CheckoutTestCase(unittest.TestCase):
    """Base case that points WORKSPACE_BASE at a scratch directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self._env = patch.dict(os.environ, {"WORKSPACE_BASE": str(self.workspace)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()


# ── Checkout paths ─────────────────────────────────────────────────────────────


class TestCheckoutPaths(_CheckoutTestCase):
    def test_slug_replaces_the_separator(self):
        self.assertEqual(main._project_slug("group/project"), "group__project")

    def test_slug_keeps_subgroups_flat(self):
        self.assertEqual(main._project_slug("group/sub/project"), "group__sub__project")

    def test_checkout_path_is_per_project_and_per_commit(self):
        a = main._checkout_path("group/project", 7, "0123456789abcdef")
        b = main._checkout_path("other/project", 7, "0123456789abcdef")
        c = main._checkout_path("group/project", 7, "fedcba9876543210")
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(a.name, "mr-7-0123456789ab")
        self.assertTrue(a.is_relative_to(main._checkouts_root()))


# ── Preparing a checkout from an archive ───────────────────────────────────────


class TestPrepareRepository(_CheckoutTestCase):
    def _prepare(self, members):
        payload = _tarball(members)
        with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
            return main._prepare_repository(
                "token", "group/project", 7, "0123456789abcdef"
            )

    def test_extracts_files_under_the_checkout(self):
        checkout = self._prepare([
            (f"{ARCHIVE_ROOT}/README.md", "file", "hello"),
            (f"{ARCHIVE_ROOT}/src", "dir", None),
            (f"{ARCHIVE_ROOT}/src/app.py", "file", "print(1)\n"),
        ])
        self.assertEqual((checkout / "README.md").read_text(), "hello")
        self.assertEqual((checkout / "src" / "app.py").read_text(), "print(1)\n")
        self.assertEqual(checkout.parent.name, "group__project")

    def test_skips_symlinks_instead_of_materialising_them(self):
        checkout = self._prepare([
            (f"{ARCHIVE_ROOT}/README.md", "file", "hello"),
            (f"{ARCHIVE_ROOT}/escape", "symlink", "/etc/passwd"),
        ])
        self.assertFalse((checkout / "escape").exists())
        self.assertTrue((checkout / "README.md").exists())

    def test_rejects_path_traversal(self):
        payload = _tarball([(f"{ARCHIVE_ROOT}/../outside", "file", "no")])
        with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
            with self.assertRaises(RuntimeError):
                main._prepare_repository(
                    "token", "group/project", 7, "0123456789abcdef"
                )

    def test_rejects_an_archive_with_no_single_root(self):
        payload = _tarball([
            ("a/one", "file", "1"),
            ("b/two", "file", "2"),
        ])
        with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
            with self.assertRaises(RuntimeError):
                main._prepare_repository(
                    "token", "group/project", 7, "0123456789abcdef"
                )


# ── Releasing a checkout ───────────────────────────────────────────────────────


class TestReleaseCheckout(_CheckoutTestCase):
    def _record(self, conversation_id=None):
        checkout = main._checkouts_root() / "group__project" / "mr-1-abc"
        checkout.mkdir(parents=True)
        return {
            "mr_iid": 1,
            "conversation_id": conversation_id,
            "workspace_dir": str(checkout),
        }

    def test_removed_in_one_step_when_no_conversation_is_recorded(self):
        rec = self._record()
        checkout = rec["workspace_dir"]
        self.assertTrue(main._release_checkout(rec, "", ""))
        self.assertFalse(Path(checkout).exists())
        self.assertNotIn("workspace_dir", rec)

    def test_kept_while_the_conversation_status_cannot_be_confirmed(self):
        rec = self._record(conversation_id="c1")
        with patch(
            "main.conversation_status", side_effect=RuntimeError("down")
        ):
            self.assertFalse(main._release_checkout(rec, "http://agent", "key"))
        self.assertTrue(Path(rec["workspace_dir"]).exists())

    def test_refuses_to_remove_anything_outside_the_checkout_root(self):
        outside = self.workspace / "elsewhere"
        outside.mkdir()
        rec = {
            "mr_iid": 1,
            "conversation_id": None,
            "workspace_dir": str(outside),
        }
        self.assertTrue(main._release_checkout(rec, "", ""))
        self.assertTrue(outside.exists())
        self.assertNotIn("workspace_dir", rec)


# ── State isolation ───────────────────────────────────────────────────────────


class TestStateIsolation(_CheckoutTestCase):
    def test_states_are_keyed_per_project(self):
        a = main._default_state("group/project")
        b = main._default_state("other/project")
        self.assertNotEqual(a, b)
        a["reviews"]["1:label:9"] = {"mr_iid": 1}
        self.assertEqual(b["reviews"], {})

    def test_review_key_binds_the_label_event(self):
        self.assertEqual(main._review_key(7, 9), "7:label:9")


# ── Review identity through the note marker ───────────────────────────────────


class TestReviewIdentity(unittest.TestCase):
    def setUp(self):
        self._auth = patch.object(main, "_AUTH_USERNAME", "openhands-bot")
        self._auth.start()

    def tearDown(self):
        self._auth.stop()

    def _note(self, username, body, iid=1):
        return {
            "id": iid,
            "author": {"username": username},
            "body": body,
            "created_at": f"2026-01-0{max(iid % 9, 1)}T00:00:00Z",
        }

    def test_review_marker_binds_the_head_sha(self):
        marker = main._review_marker("0123456789abcdef")
        self.assertEqual(marker, "openhands-mr-review 0123456789abcdef")

    def test_only_the_token_owner_is_mine(self):
        self.assertTrue(main._mine(self._note("OpenHands-Bot", "hi")))
        self.assertFalse(main._mine(self._note("someone-else", "hi")))
        self.assertFalse(main._mine(self._note("", "hi")))

    def test_review_notes_on_matches_only_that_head(self):
        sha = "0123456789abcdef"
        mine = self._note(
            "openhands-bot",
            f"<!-- {main._review_marker(sha)} -->\n\nreview\n\n✅ APPROVED",
        )
        other_head = self._note(
            "openhands-bot",
            f"<!-- {main._review_marker('fedcba')} -->\n\nolder\n\n✅ APPROVED",
            iid=2,
        )
        other_author = self._note(
            "someone",
            f"<!-- {main._review_marker(sha)} -->\n\nforged\n\n✅ APPROVED",
            iid=3,
        )
        matched = main._review_notes_on([mine, other_head, other_author], sha)
        self.assertEqual([note["id"] for note in matched], [1])

    def test_verdict_detection_accepts_the_three_verdicts(self):
        for verdict in (
            main.APPROVED_VERDICT,
            main.CHANGES_REQUESTED_VERDICT,
            main.MAINTAINER_DECISION_VERDICT,
        ):
            self.assertEqual(main._verdict_of(f"text\n{verdict}"), verdict.rstrip())
        self.assertIsNone(main._verdict_of("no verdict here"))

    def test_verdict_must_be_the_last_line(self):
        body = f"✅ APPROVED\n\n_This note was posted by an AI agent (OpenHands)._"
        self.assertIsNone(main._verdict_of(body))


# ── The head pipeline gate ─────────────────────────────────────────────────────


class TestPipelineGate(unittest.TestCase):
    def test_no_pipeline_is_green(self):
        self.assertEqual(worker._classify_pipelines([]), ("green", []))

    def test_failed_pipeline_blocks_by_name(self):
        state, names = worker._classify_pipelines(
            [{"id": 1, "status": "failed", "ref": "f", "source": "push", "name": "ci"}]
        )
        self.assertEqual(state, "blocked")
        self.assertEqual(names, ["ci"])

    def test_canceled_pipeline_blocks(self):
        self.assertEqual(
            worker._classify_pipelines(
                [{"id": 1, "status": "canceled", "ref": "f", "source": "push", "name": "ci"}]
            )[0],
            "blocked",
        )

    def test_a_newer_success_supersedes_an_older_failure(self):
        state, _ = worker._classify_pipelines([
            {"id": 1, "status": "failed", "ref": "f", "source": "push", "name": "ci"},
            {"id": 2, "status": "success", "ref": "f", "source": "push", "name": "ci"},
        ])
        self.assertEqual(state, "green")

    def test_a_newer_running_supersedes_an_older_success(self):
        state, names = worker._classify_pipelines([
            {"id": 5, "status": "success", "ref": "f", "source": "push", "name": "ci"},
            {"id": 6, "status": "running", "ref": "f", "source": "push", "name": "ci"},
        ])
        self.assertEqual(state, "waiting")
        self.assertEqual(names, ["ci"])

    def test_a_failed_pipeline_on_the_same_head_decides_against_another_green_one(self):
        # Every pipeline this gate reads was queried by the exact head SHA, so a
        # failure under another ref/source pair is still a failure of this head
        # and a wrong head can never be approved.
        state, names = worker._classify_pipelines([
            {"id": 1, "status": "failed", "ref": "mr", "source": "merge_request", "name": "ci"},
            {"id": 2, "status": "success", "ref": "main", "source": "push", "name": "ci"},
        ])
        self.assertEqual(state, "blocked")
        self.assertEqual(sorted(names), ["ci"])

    def test_an_unknown_status_fails_closed(self):
        self.assertEqual(
            worker._classify_pipelines(
                [{"id": 9, "status": "mystery", "ref": "f", "source": "push", "name": "x"}]
            )[0],
            "blocked",
        )

    def test_skipped_is_non_blocking(self):
        self.assertEqual(
            worker._classify_pipelines(
                [{"id": 4, "status": "skipped", "ref": "f", "source": "push", "name": "ci"}]
            ),
            ("green", []),
        )


# ── Reading a GitLab webhook ───────────────────────────────────────────────────


REVIEWER = worker.MergeRequestReviewer


def _reviewer_stub():
    stub = REVIEWER.__new__(REVIEWER)
    stub.project = "grp/proj"
    stub.trigger_reviewer = "all-hands-bot"
    return stub


class TestEventSignals(unittest.TestCase):
    def setUp(self):
        self.r = _reviewer_stub()

    def _payload(self, action="update", changes=None, user=None, updated="t0"):
        payload = {
            "project": {"path_with_namespace": "grp/proj"},
            "object_attributes": {
                "action": action,
                "iid": 4,
                "updated_at": updated,
            },
        }
        if changes is not None:
            payload["changes"] = changes
        if user is not None:
            payload["user"] = user
        return payload

    def _reviewers_change(self, previous, current):
        return {"reviewers": [previous, current]}

    def test_a_newly_added_reviewer_is_a_request(self):
        payload = self._payload(
            changes=self._reviewers_change(
                [{"username": "someone"}],
                [{"username": "all-hands-bot", "state": "unreviewed", "re_requested": False}],
            )
        )
        self.assertTrue(REVIEWER._request_signal(self.r, payload))
        self.assertEqual(REVIEWER._event_candidate(self.r, payload), {
            "action": "update", "iid": 4, "updated_at": "t0",
        })

    def test_a_re_requested_reviewer_is_a_request(self):
        payload = self._payload(
            changes=self._reviewers_change(
                [{"username": "all-hands-bot", "state": "approved", "re_requested": False}],
                [{"username": "all-hands-bot", "state": "unreviewed", "re_requested": True}],
            )
        )
        self.assertTrue(REVIEWER._request_signal(self.r, payload))

    def test_the_reviewer_starting_a_review_is_not_a_request(self):
        payload = self._payload(
            changes=self._reviewers_change(
                [{"username": "all-hands-bot", "state": "unreviewed"}],
                [{"username": "all-hands-bot", "state": "review_started", "re_requested": False}],
            )
        )
        self.assertFalse(REVIEWER._request_signal(self.r, payload))
        self.assertIsNone(REVIEWER._event_candidate(self.r, payload))

    def test_a_decided_state_is_a_completion_not_a_request(self):
        payload = self._payload(
            changes=self._reviewers_change(
                [{"username": "all-hands-bot", "state": "review_started"}],
                [{"username": "all-hands-bot", "state": "approved", "re_requested": False}],
            )
        )
        self.assertFalse(REVIEWER._request_signal(self.r, payload))
        self.assertEqual(
            REVIEWER._event_completion(self.r, payload),
            {"state": "approved", "created_at": "t0"},
        )

    def test_a_re_requested_state_is_never_reported_as_a_completion(self):
        payload = self._payload(
            changes=self._reviewers_change(
                [{"username": "all-hands-bot", "state": "approved", "re_requested": False}],
                [{"username": "all-hands-bot", "state": "unreviewed", "re_requested": True}],
            )
        )
        self.assertIsNone(REVIEWER._event_completion(self.r, payload))

    def test_the_reviewer_own_approval_is_a_completion(self):
        payload = self._payload(action="approval", user={"username": "all-hands-bot"}, updated="t1")
        self.assertEqual(
            REVIEWER._event_completion(self.r, payload),
            {"state": "approval", "created_at": "t1"},
        )

    def test_someone_elses_approval_is_not_a_completion(self):
        payload = self._payload(action="approval", user={"username": "human"}, updated="t1")
        self.assertIsNone(REVIEWER._event_completion(self.r, payload))

    def test_events_for_other_projects_are_ignored(self):
        payload = self._payload(
            changes=self._reviewers_change(
                [], [{"username": "all-hands-bot", "state": "unreviewed", "re_requested": False}]
            )
        )
        payload["project"]["path_with_namespace"] = "other/project"
        # The request signal reads the reviewer change; project scoping is the
        # candidate's job, and the candidate refuses a foreign project.
        self.assertIsNone(REVIEWER._event_candidate(self.r, payload))

    def test_an_open_event_is_neither_request_nor_completion(self):
        self.assertIsNone(REVIEWER._event_candidate(self.r, self._payload(action="open")))


# ── Scan candidates and the intake ─────────────────────────────────────────────


class TestScanCandidates(unittest.TestCase):
    def setUp(self):
        self.r = _reviewer_stub()

    def _mr(self, draft=False, labels=(), reviewers=()):
        # The REST merge-request payload carries labels as plain strings; the
        # webhook payload carries objects. Discovery reads the REST shape.
        return {
            "iid": 1,
            "draft": draft,
            "labels": list(labels),
            "reviewers": [{"username": name} for name in reviewers],
        }

    def test_a_draft_without_label_or_request_is_skipped(self):
        mrs = self.r._scan_candidates([self._mr(draft=True)], "openhands-review")
        self.assertEqual(mrs, [])

    def test_a_labeled_draft_is_a_candidate(self):
        mrs = self.r._scan_candidates(
            [self._mr(draft=True, labels=("openhands-review",))], "openhands-review"
        )
        self.assertEqual(len(mrs), 1)

    def test_a_requested_draft_is_a_candidate(self):
        mrs = self.r._scan_candidates(
            [self._mr(draft=True, reviewers=("all-hands-bot",))], "openhands-review"
        )
        self.assertEqual(len(mrs), 1)

    def test_an_open_labeled_mr_is_a_candidate(self):
        mrs = self.r._scan_candidates(
            [self._mr(labels=("openhands-review",))], "openhands-review"
        )
        self.assertEqual(len(mrs), 1)


class TestReviewIntake(unittest.TestCase):
    def _record(self, number=1, priority=0, created=""):
        return {
            "project": "grp/proj",
            "number": number,
            "priority": priority,
            "created_at": created,
            "config": {"max_new_per_run": 2},
            "start": lambda: {"disposition": "created", "conversation_id": "c"},
        }

    def test_the_bound_starts_at_most_two(self):
        intake = worker.ReviewIntake()
        started = []
        for number in range(4):
            record = self._record(number=number, created=f"2026-01-0{number + 1}")
            record["start"] = lambda number=number, started=started: (
                started.append(number),
                {"disposition": "created", "conversation_id": f"c{number}"},
            )[1]
            intake.register(record)
        intake.drain()
        # The oldest two started; the remaining two wait for a later scan.
        self.assertEqual(started, [0, 1])
        self.assertEqual(intake._started, 2)

    def test_explicit_requests_drain_before_unrequested_candidates(self):
        intake = worker.ReviewIntake()
        order = []
        for number, priority in ((10, 1), (11, 0)):
            def start(number=number):
                order.append(number)
                return {"disposition": "created", "conversation_id": f"c{number}"}
            record = self._record(number=number, priority=priority, created="2026-01-01")
            record["start"] = start
            intake.register(record)
        intake.drain()
        self.assertEqual(order, [11, 10])

    def test_a_failed_dispatch_does_not_consume_a_slot(self):
        intake = worker.ReviewIntake()
        started = []

        def failing():
            raise RuntimeError("down")

        record = self._record(number=1, created="2026-01-01")
        record["start"] = failing
        intake.register(record)
        good = self._record(number=2, created="2026-01-02")
        good["start"] = lambda: (
            started.append(2),
            {"disposition": "created", "conversation_id": "c2"},
        )[1]
        intake.register(good)
        # The failure is reported after the drain, so the candidate behind it
        # still started and consumed the slot it earned.
        with self.assertRaises(RuntimeError):
            intake.drain()
        self.assertEqual(started, [2])


# ── Config loading ─────────────────────────────────────────────────────────────


class TestConfig(unittest.TestCase):
    def test_rejects_a_max_new_per_run_below_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"projects": ["g/p"], "max_new_per_run": 0}))
            with self.assertRaises(SystemExit):
                main.load_config(Path(tmp))

    def test_rejects_a_string_typed_as_a_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"projects": ["g/p"], "max_new_per_run": "2"}))
            with self.assertRaises(SystemExit):
                main.load_config(Path(tmp))

    def test_accepts_a_valid_rendered_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({
                "projects": ["g/p"],
                "max_new_per_run": 2,
                "gitlab_api_url": "https://gitlab.example.com/api/v4",
            }))
            config = main.load_config(Path(tmp))
            self.assertEqual(config["projects"], ["g/p"])
            self.assertEqual(config["max_new_per_run"], 2)
            self.assertEqual(
                config["gitlab_api_url"], "https://gitlab.example.com/api/v4"
            )


# ── Project name normalization ─────────────────────────────────────────────────


class TestNormalizeProject(unittest.TestCase):
    def test_passthrough(self):
        self.assertEqual(main.normalize_project("group/project"), "group/project")

    def test_subgroups_are_kept(self):
        self.assertEqual(
            main.normalize_project("group/sub/project"), "group/sub/project"
        )

    def test_a_clone_url_becomes_the_full_path(self):
        self.assertEqual(
            main.normalize_project("https://gitlab.example.com/group/sub/project.git"),
            "group/sub/project",
        )

    def test_a_bare_host_is_rejected(self):
        with self.assertRaises(ValueError):
            main.normalize_project("https://gitlab.example.com")

    def test_a_single_segment_is_rejected(self):
        with self.assertRaises(ValueError):
            main.normalize_project("project")


# ── Reading the resource label events ─────────────────────────────────────────


class TestTriggerLabelEvent(unittest.TestCase):
    def _event(self, label="openhands-review", action="add", event_id=1, created="2026-01-01"):
        return {
            "id": event_id,
            "action": action,
            "created_at": created,
            "label": {"name": label},
        }

    def _latest(self, events):
        with patch.object(main, "_get_label_events", return_value=events):
            return main._latest_trigger_label_event("token", "group/project", 1)

    def test_the_latest_add_event_of_the_trigger_label_wins(self):
        older = self._event(event_id=1, created="2026-01-01")
        newest = self._event(event_id=2, created="2026-01-02")
        self.assertEqual(self._latest([older, newest]), newest)

    def test_label_names_match_and_other_labels_do_not(self):
        self.assertEqual(
            self._latest([self._event(label="openhands-review")]),
            self._event(label="openhands-review"),
        )
        self.assertIsNone(self._latest([self._event(label="other")]))

    def test_a_label_removal_never_queues_a_review(self):
        self.assertIsNone(self._latest([self._event(action="remove")]))

    def test_a_add_after_a_removal_is_the_fresh_request(self):
        self.assertEqual(
            self._latest([
                self._event(action="remove", event_id=1, created="2026-01-01"),
                self._event(action="add", event_id=2, created="2026-01-02"),
            ]),
            self._event(action="add", event_id=2, created="2026-01-02"),
        )


if __name__ == "__main__":
    unittest.main()