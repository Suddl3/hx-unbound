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
        pulls = self.pages(f"/repos/{repo}/pulls?state=closed&sort=updated&direction=desc", cutoff)
        return select_events(repo, releases, pulls, checkpoint["since"])


def select_events(repo, releases, pulls, since):
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


def publish_pending(store, send):
    sent = 0
    for key, record in store.state["events"].items():
        if record["status"] != "queued":
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
            store.state["repos"][repo] = {"since": started, "checked_at": started}
            counts["baselined"] += 1
            continue
        try:
            events = github.events(repo, checkpoint)
        except MonitorError as exc:
            failures.append(f"{repo}: {exc}")
            continue
        for event in events:
            if event["key"] not in store.state["events"]:
                store.state["events"][event["key"]] = {"status": "queued", "event": event}
                counts["queued"] += 1
        checkpoint["checked_at"] = started
    if announce_setup and not failures and "setup:v1" not in store.state["events"]:
        store.state["events"]["setup:v1"] = {"status": "queued", "event": {
            "key": "setup:v1", "repo": HUB, "kind": "Monitoring enabled",
            "title": f"{len(repos)} projects • releases and merged pull requests • checked hourly",
            "url": f"https://github.com/{HUB}/blob/main/monitor/repos.json", "at": started}}
        counts["queued"] += 1
    if not dry_run:
        store.save()
        counts["posted"] = publish_pending(store, send)
    print(json.dumps({"dry_run": dry_run, **counts, "errors": failures}))
    if failures:
        raise MonitorError("One or more repositories could not be checked; their checkpoints were preserved")
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--announce-setup", action="store_true")
    args = parser.parse_args()
    repos = json.loads((ROOT / "repos.json").read_text())
    if len(set(repos)) != len(repos) or not all(re.fullmatch(r"[\w.-]+/[\w.-]+", r) for r in repos):
        raise MonitorError("Invalid or duplicate repository names")
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
