"""Hourly public-repository news. Python standard library only; never executes upstream code."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

HUB = "Suddl3/hx-unbound"
STATE_BRANCH = "repo-monitor-state"
STATE_PATH = "state.json"
ROOT = Path(__file__).resolve().parent


class MonitorError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def directory_repos(markdown):
    """Read project links from directory table rows, excluding prose and reference tables."""
    start, end = "<!-- monitored-projects:start -->", "<!-- monitored-projects:end -->"
    if markdown.count(start) != 1 or markdown.count(end) != 1 or markdown.index(start) >= markdown.index(end):
        raise MonitorError("PROJECTS.md must contain one ordered pair of monitored-projects markers")
    section = markdown.split(start, 1)[1].split(end, 1)[0]
    repos, seen = [], set()
    for line in section.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cell = line.split("|")[1].strip()
        if cell in {"Project", "Repository"} or re.fullmatch(r":?-+:?", cell):
            continue
        match = re.fullmatch(r"\[[^\]]+\]\(<?(https://github\.com/[^\s)>]+)>?\)", cell)
        if not match:
            raise MonitorError("A monitored project row must start with a GitHub repository link")
        parts = urlsplit(match[1]).path.strip("/").split("/")
        if len(parts) < 2 or not all(re.fullmatch(r"[\w.-]+", p) for p in parts[:2]):
            raise MonitorError("Invalid project repository URL")
        repo = "/".join(parts[:2]).removesuffix(".git")
        if repo.lower() == HUB.lower():
            raise MonitorError("The hub itself cannot be monitored")
        if repo.lower() not in seen:
            repos.append(repo)
            seen.add(repo.lower())
    if not repos:
        raise MonitorError("No monitored projects found; refusing an empty directory")
    return repos


def request(url, *, token=None, method="GET", data=None):
    headers = {"User-Agent": "HX-Unbound-Repo-Monitor", "Accept": "application/json"}
    if token:
        headers.update(Authorization=f"Bearer {token}", **{"X-GitHub-Api-Version": "2022-11-28"})
    payload = None if data is None else json.dumps(data).encode()
    if payload is not None:
        headers["Content-Type"] = "application/json"
    # Retry only explicit rate limits. Network/5xx errors on a POST can mean it was delivered.
    for attempt in range(3):
        try:
            with urlopen(Request(url, data=payload, headers=headers, method=method), timeout=25) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                try:
                    delay = float(json.loads(exc.read()).get("retry_after", 5))
                except (ValueError, TypeError):
                    delay = 5
                if delay > 45:
                    raise MonitorError("Rate limited; retry on the next scheduled run") from None
                time.sleep(max(1, delay))
                continue
            # Never print an exception containing the webhook URL or an upstream response body.
            raise MonitorError(f"HTTP {exc.code} during {method} to {urlsplit(url).hostname}") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise MonitorError(f"Request failed during {method} to {urlsplit(url).hostname}") from None
    raise MonitorError("Rate limit retries exhausted")


class GitHub:
    def __init__(self, token):
        self.token = token

    def api(self, path, **kwargs):
        return request("https://api.github.com" + path, token=self.token, **kwargs)

    def pages(self, path, stop_before=None):
        rows = []
        for page in range(1, 101):
            batch = self.api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise MonitorError("Unexpected GitHub list response")
            rows.extend(batch)
            if len(batch) < 100:
                return rows
            if stop_before and timestamp(batch[-1]["updated_at"]) < stop_before:
                return rows
        raise MonitorError("Pagination limit reached; refusing to advance the checkpoint")

    def events(self, repo, checkpoint):
        releases = self.pages(f"/repos/{repo}/releases")
        # Updated order includes PRs created long ago and merged recently. Overlap tolerates indexing lag.
        cutoff = timestamp(checkpoint["checked_at"]) - timedelta(days=1)
        pulls = self.pages(f"/repos/{repo}/pulls?state=all&sort=updated&direction=desc", cutoff)
        return select_events(repo, releases, pulls, checkpoint["since"], checkpoint.get("opened_since"))


def select_events(repo, releases, pulls, since, opened_since=None):
    events = []
    for release in releases:
        published = release.get("published_at")
        if release.get("draft") or not published or timestamp(published) <= timestamp(since):
            continue
        events.append({"key": f"{repo}:release:{release['id']}", "repo": repo,
                       "kind": "Prerelease" if release.get("prerelease") else "Release",
                       "title": release.get("name") or release["tag_name"],
                       "url": release["html_url"], "at": published})
    for pull in pulls:
        created = pull.get("created_at")
        if opened_since and created and timestamp(created) > timestamp(opened_since):
            events.append({"key": f"{repo}:pr-opened:{pull['number']}", "repo": repo,
                           "kind": "Draft pull request opened" if pull.get("draft") else "Pull request opened",
                           "title": f"#{pull['number']} {pull['title']}", "url": pull["html_url"], "at": created})
        merged = pull.get("merged_at")
        if merged and timestamp(merged) > timestamp(since):
            events.append({"key": f"{repo}:pr:{pull['number']}", "repo": repo,
                           "kind": "Merged pull request", "title": f"#{pull['number']} {pull['title']}",
                           "url": pull["html_url"], "at": merged})
    return sorted(events, key=lambda event: (timestamp(event["at"]), event["key"]))


class Store:
    def __init__(self, github):
        self.github = github
        data = github.api(f"/repos/{HUB}/contents/{STATE_PATH}?ref={STATE_BRANCH}")
        self.sha = data["sha"]
        self.state = json.loads(base64.b64decode(data["content"]))
        if self.state.get("version") != 1:
            raise MonitorError("Unsupported state version")

    def save(self):
        result = self.github.api(f"/repos/{HUB}/contents/{STATE_PATH}", method="PUT", data={
            "message": "Record repository monitor progress", "branch": STATE_BRANCH,
            "sha": self.sha, "content": base64.b64encode(json.dumps(self.state, indent=2).encode()).decode()})
        self.sha = result["content"]["sha"]


def message(event):
    # Link only to the monitored repository; upstream titles are plain data, with all mentions disabled.
    if not event["url"].startswith(f"https://github.com/{event['repo']}/"):
        raise MonitorError("Unexpected event URL")
    return {"username": "HX Unbound Updates", "allowed_mentions": {"parse": []},
            "embeds": [{"author": {"name": event["repo"]},
                        "title": f"{event['kind']}: {event['title']}"[:256],
                        "url": event["url"], "color": 5793266, "timestamp": event["at"],
                        "footer": {"text": "HX Unbound • Community project updates"}}]}


def publish_pending(store, send, repos=None):
    sent = 0
    for key, record in store.state["events"].items():
        if record["status"] != "queued":
            continue
        if repos is not None and record["event"]["repo"] not in repos and key != "setup:v1":
            continue
        payload = message(record["event"])
        # Persist before sending. Interrupted/ambiguous delivery is never automatically repeated.
        record["status"] = "sending"
        store.save()
        result = send(payload)
        if not result.get("id"):
            raise MonitorError("Discord did not confirm a message ID; inspect pending delivery")
        record.update(status="sent", message_id=result["id"], sent_at=now())
        store.save()
        sent += 1
    uncertain = sum(r["status"] == "sending" for r in store.state["events"].values())
    if uncertain:
        raise MonitorError(f"{uncertain} interrupted delivery record(s) need review; not reposted")
    return sent


def run(github, store, repos, send, dry_run=False, announce_setup=False):
    started = now()
    failures = []
    counts = {"baselined": 0, "queued": 0, "posted": 0}
    for repo in repos:
        # Preserve existing checkpoints if a maintainer only changes URL capitalization.
        existing = next((key for key in store.state["repos"] if key.lower() == repo.lower()), None)
        if existing is not None:
            repo = existing
        checkpoint = store.state["repos"].get(repo)
        if checkpoint is None:
            # Validate that this is a readable public repository before establishing its baseline.
            try:
                meta = github.api(f"/repos/{repo}")
                if meta.get("private") is not False:
                    raise MonitorError("Monitor only supports public repositories")
                # Check both feeds so a disabled API fails visibly at setup, not an hour later.
                github.events(repo, {"since": started, "checked_at": started})
            except MonitorError as exc:
                failures.append(f"{repo}: {exc}")
                continue
            store.state["repos"][repo] = {"since": started, "checked_at": started, "opened_since": started}
            counts["baselined"] += 1
            continue
        try:
            # Existing installs get a separate quiet baseline for PR-opening announcements.
            events = github.events(repo, {**checkpoint, "opened_since": checkpoint.get("opened_since", started)})
        except MonitorError as exc:
            failures.append(f"{repo}: {exc}")
            continue
        for event in events:
            if event["key"] not in store.state["events"]:
                store.state["events"][event["key"]] = {"status": "queued", "event": event}
                counts["queued"] += 1
        checkpoint["checked_at"] = started
        checkpoint.setdefault("opened_since", started)
    if announce_setup and not failures and "setup:v1" not in store.state["events"]:
        store.state["events"]["setup:v1"] = {"status": "queued", "event": {
            "key": "setup:v1", "repo": HUB, "kind": "Monitoring enabled",
            "title": f"{len(repos)} projects • releases, opened and merged pull requests • checked hourly",
            "url": f"https://github.com/{HUB}/blob/main/PROJECTS.md", "at": started}}
        counts["queued"] += 1
    if not dry_run:
        store.save()
        active = {r for r in store.state["repos"] if r.lower() in {p.lower() for p in repos}}
        counts["posted"] = publish_pending(store, send, active)
    print(json.dumps({"dry_run": dry_run, "repositories": len(repos), **counts, "errors": failures}))
    if failures:
        raise MonitorError("One or more repositories could not be checked; their checkpoints were preserved")
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--announce-setup", action="store_true")
    args = parser.parse_args()
    repos = directory_repos((ROOT.parent / "PROJECTS.md").read_text(encoding="utf-8"))
    github = GitHub(os.environ["GH_TOKEN"])
    store = Store(github)
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not args.dry_run:
        if not re.fullmatch(r"https://discord\.com/api/webhooks/\d+/[\w.-]+", webhook):
            raise MonitorError("Missing or invalid DISCORD_WEBHOOK_URL secret")
    run(github, store, repos, lambda payload: request(webhook + "?wait=true", method="POST", data=payload), args.dry_run, args.announce_setup)


if __name__ == "__main__":
    try:
        main()
    except (MonitorError, KeyError) as exc:
        print(f"Monitor failed: {exc}", file=sys.stderr)
        sys.exit(1)
