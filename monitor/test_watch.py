import copy
import unittest
from unittest.mock import patch
import watch

REPO = "owner/project"
OLD = "2026-11-01T00:00:00Z"
NEW = "2026-11-10T00:00:00Z"
EVENT = {"key": REPO + ":pr:1", "repo": REPO, "kind": "Merged pull request",
         "title": "#1 A useful feature", "url": f"https://github.com/{REPO}/pull/1", "at": NEW}


class MemoryStore:
    def __init__(self, initialized=True):
        self.state = {"version": 1, "repos": {REPO: {"since": OLD, "checked_at": OLD}} if initialized else {}, "events": {}}
        self.saved = []

    def save(self):
        self.saved.append(copy.deepcopy(self.state))


class FakeGitHub:
    def api(self, path):
        return {"private": False}

    def events(self, repo, checkpoint):
        return [EVENT]


class MonitorTests(unittest.TestCase):
    def test_directory_addition_and_reference_exclusion(self):
        directory = '''Prose https://github.com/ignored/prose
<!-- monitored-projects:start -->
| Project | Owner | Scope |
| --- | --- | --- |
| [First](https://github.com/owner/first/tree/main) | owner | Text [ref](https://github.com/ignored/ref) |
| [Again](https://github.com/OWNER/FIRST.git) | owner | Duplicate |
<!-- monitored-projects:end -->
| [Reference](https://github.com/ignored/reference) | owner | Reference |
'''
        self.assertEqual(["owner/first"], watch.directory_repos(directory))
        directory = directory.replace("<!-- monitored-projects:end -->", "| [New](https://github.com/owner/new) | owner | Added |\n<!-- monitored-projects:end -->")
        self.assertEqual(["owner/first", "owner/new"], watch.directory_repos(directory))

    def test_malformed_directory_fails_instead_of_silently_dropping_projects(self):
        for source in ["no markers", "<!-- monitored-projects:start --><!-- monitored-projects:end -->",
                       "<!-- monitored-projects:start -->\n| [Bad](https://example.com/repo) | x |\n<!-- monitored-projects:end -->"]:
            with self.subTest(source=source), self.assertRaises(watch.MonitorError):
                watch.directory_repos(source)

    def test_new_directory_repo_is_baselined_without_backlog(self):
        store, sent = MemoryStore(), []
        with patch.object(FakeGitHub, "events", return_value=[]):
            result = watch.run(FakeGitHub(), store, [REPO, "another/new"], sent.append)
        self.assertEqual(1, result["baselined"])
        self.assertEqual([], sent)
        self.assertIn("another/new", store.state["repos"])

    def test_existing_install_gets_new_pr_baseline(self):
        store = MemoryStore()
        checkpoints = []
        def events(repo, checkpoint):
            checkpoints.append(checkpoint)
            return []
        with patch.object(FakeGitHub, "events", side_effect=events):
            watch.run(FakeGitHub(), store, [REPO], lambda _: None)
        self.assertNotEqual(OLD, checkpoints[0]["opened_since"])
        self.assertEqual(OLD, checkpoints[0]["since"])
        self.assertEqual(checkpoints[0]["opened_since"], store.state["repos"][REPO]["opened_since"])

    def test_open_and_merge_have_independent_event_ids(self):
        pull = {"number": 4, "title": "Feature", "created_at": NEW, "merged_at": None,
                "html_url": f"https://github.com/{REPO}/pull/4", "draft": False}
        events = watch.select_events(REPO, [], [pull], OLD, OLD)
        self.assertEqual([REPO + ":pr-opened:4"], [e["key"] for e in events])
        pull["merged_at"] = "2026-11-10T01:00:00Z"
        events = watch.select_events(REPO, [], [pull], OLD, OLD)
        self.assertEqual({REPO + ":pr-opened:4", REPO + ":pr:4"}, {e["key"] for e in events})
        self.assertEqual(1, len(watch.select_events(REPO, [], [pull], OLD, NEW)))

    def test_drafts_are_clearly_labelled(self):
        pull = {"number": 1, "title": "Work in progress", "created_at": NEW, "merged_at": None,
                "html_url": f"https://github.com/{REPO}/pull/1", "draft": True}
        self.assertEqual("Draft pull request opened", watch.select_events(REPO, [], [pull], OLD, OLD)[0]["kind"])

    def test_removed_repo_does_not_publish_queued_updates(self):
        store, sent = MemoryStore(), []
        store.state["events"][EVENT["key"]] = {"status": "queued", "event": EVENT}
        watch.publish_pending(store, sent.append, set())
        self.assertEqual([], sent)

    def test_first_run_and_new_repo_skip_history(self):
        store = MemoryStore(False)
        sent = []
        watch.run(FakeGitHub(), store, [REPO], sent.append)
        self.assertEqual([], sent)
        self.assertEqual({}, store.state["events"])
        self.assertIn(REPO, store.state["repos"])

    def test_repeat_poll_posts_once(self):
        store, sent = MemoryStore(), []
        def send(payload):
            self.assertEqual("sending", store.saved[-1]["events"][EVENT["key"]]["status"])
            sent.append(payload)
            return {"id": "123"}
        watch.run(FakeGitHub(), store, [REPO], send)
        watch.run(FakeGitHub(), store, [REPO], send)
        self.assertEqual(1, len(sent))
        self.assertEqual({"parse": []}, sent[0]["allowed_mentions"])

    def test_setup_notice_sent_once_without_historical_updates(self):
        store, sent = MemoryStore(False), []
        def send(payload):
            sent.append(payload)
            return {"id": "123"}
        with patch.object(FakeGitHub, "events", return_value=[]):
            watch.run(FakeGitHub(), store, [REPO], send, announce_setup=True)
            watch.run(FakeGitHub(), store, [REPO], send, announce_setup=True)
        self.assertEqual(1, len(sent))
        self.assertIn("Monitoring enabled", sent[0]["embeds"][0]["title"])

    def test_ambiguous_delivery_is_not_retried(self):
        store = MemoryStore()
        def fail(payload):
            raise watch.MonitorError("connection lost")
        with self.assertRaises(watch.MonitorError):
            watch.run(FakeGitHub(), store, [REPO], fail)
        sent = []
        with self.assertRaises(watch.MonitorError):
            watch.run(FakeGitHub(), store, [REPO], sent.append)
        self.assertEqual([], sent)
        self.assertEqual("sending", store.state["events"][EVENT["key"]]["status"])

    def test_read_failure_preserves_checkpoint(self):
        store = MemoryStore()
        with patch.object(FakeGitHub, "events", side_effect=watch.MonitorError("unavailable")):
            with self.assertRaises(watch.MonitorError):
                watch.run(FakeGitHub(), store, [REPO], lambda _: None)
        self.assertEqual(OLD, store.state["repos"][REPO]["checked_at"])

    def test_dry_run_does_not_save_or_post(self):
        store, sent = MemoryStore(), []
        counts = watch.run(FakeGitHub(), store, [REPO], sent.append, True)
        self.assertEqual(1, counts["queued"])
        self.assertEqual([], sent)
        self.assertEqual([], store.saved)

    def test_only_published_releases_and_merged_prs_after_baseline(self):
        releases = [{"id": 1, "draft": False, "published_at": NEW, "tag_name": "v1", "html_url": f"https://github.com/{REPO}/releases/tag/v1"},
                    {"id": 2, "draft": True, "published_at": NEW},
                    {"id": 3, "draft": False, "published_at": OLD}]
        pulls = [{"number": 4, "title": "Old PR merged today", "created_at": OLD, "merged_at": NEW, "html_url": f"https://github.com/{REPO}/pull/4"},
                 {"number": 5, "merged_at": None}, {"number": 6, "merged_at": OLD}]
        events = watch.select_events(REPO, releases, pulls, OLD)
        self.assertEqual({REPO + ":release:1", REPO + ":pr:4"}, {e["key"] for e in events})

    def test_pagination_includes_later_pages(self):
        github = watch.GitHub("unused")
        first = [{"updated_at": NEW}] * 100
        with patch.object(github, "api", side_effect=[first, [{"updated_at": OLD}]]):
            self.assertEqual(101, len(github.pages("/example", watch.timestamp(OLD))))

    def test_unexpected_event_link_rejected(self):
        event = dict(EVENT, url="https://example.com")
        with self.assertRaises(watch.MonitorError):
            watch.message(event)


if __name__ == "__main__":
    unittest.main()
