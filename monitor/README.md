# Community repository updates

GitHub Actions reads the project tables in [PROJECTS.md](../PROJECTS.md) hourly, at minute 17. It posts new published releases (including labelled prereleases), newly opened pull requests, and merged pull requests to Discord's `#repo-updates`. Draft PRs are announced with a clear draft label. It does not post individual commits, issues, comments, PR edits/reviews, or draft releases. GitHub schedules can be delayed.

The directory is the only maintained repository list. Add a row to any project table between the `monitored-projects:start` and `monitored-projects:end` HTML comments in PROJECTS.md; the next hourly run picks it up automatically. The monitor reads the first column's GitHub project link, resolves branch/file links to their repository, and deduplicates repeated links regardless of capitalization. Links in prose or descriptions are ignored. The foundational reference tables remain outside the monitored section.

The first successful check of a newly added repository establishes its baseline without posting historical activity. Existing repositories receive a separate quiet baseline when PR-opening announcements are first enabled; existing open PRs are not announced retroactively, but future merges still are. Removing a project row stops checking that repository and stops posting its queued events; saved history remains available if it is re-added. Re-adding a previously monitored project resumes its saved checkpoint. An opened PR is a GitHub review request, not a commit or a branch push. A PR can produce one opening announcement and one later merge announcement.

## Operation

- Workflow: **Community repository updates**, on the hub's main branch.
- Credential: repository Actions secret `DISCORD_WEBHOOK_URL`, restricted to the updates channel. Never commit the URL.
- State: `state.json` on branch `repo-monitor-state`, initially `{"version":1,"repos":{},"events":{}}`. Keep this branch; deleting/resetting it can discard delivery history.
- Permissions: the workflow's temporary GitHub token reads public projects and writes state only in this hub. The script never checks out or executes monitored project code. The webhook posts with mentions disabled.
- Runs are serialized. The workflow has a five-minute timeout. Tests run before each check.
- Use **Actions → Community repository updates → Run workflow** to check manually. Select **dry_run** to inspect counts without posting or saving state.
- Select **announce_setup** for the one-time monitoring-enabled notice that verifies Discord delivery. Its saved ID prevents the setup notice from repeating. This notice does not announce historical project activity.
- Failed runs are visible in Actions; enable GitHub Actions failure notifications for the maintainer account. No separate failure-notification service is configured.
- Standard hosted runners are free for public repositories. No paid runner or external AI service is used.
- GitHub may disable a public repository's schedule after 60 days without repository activity. Check the workflow if this hub has been dormant; re-enable it if needed.

## Interrupted deliveries

Each event is saved as `queued`, then `sending` immediately before the Discord request, and `sent` after Discord confirms its message ID. If a request or state write is interrupted, the workflow fails visibly and leaves `sending` for manual review. It does not automatically repost that event, because Discord might already have received it. This favors avoiding duplicate announcements over blindly retrying uncertain delivery.

To recover, inspect `#repo-updates` for the event URL. If the message exists, set that event's status to `sent` and record its message ID in state.json. If it is absent, set status to `queued`. Commit the correction to `repo-monitor-state` while no workflow is running, then run the workflow again. Do not clear the entire state file. A failed repository fetch retains that repository's previous checkpoint for the next attempt; queued events remain durable.

This is a periodic activity feed, not an audit archive. A release deleted before a check cannot be discovered. Feed titles are supplied by each project, not independently reviewed feature summaries.

## Local checks

`python -m unittest discover -s monitor -p 'test_*.py'`

`GH_TOKEN` is required for authenticated checks. `python monitor/watch.py --dry-run` reads remote state but never posts or updates it. Live mode additionally needs the webhook secret.
