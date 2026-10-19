import base64
import json
import os
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

USER = os.environ.get("GH_USER", "justpranavrs")
TOKEN = os.environ.get("GH_TOKEN")
LIMIT = int(os.environ.get("EVENT_LIMIT", 8))
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
OUT = Path(os.environ.get("OUTPUT_FILE", "activity.svg"))
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

# Layout dimensions in pixels
WIDTH, ROW_H, PAD, TEXT_X = 850, 40, 20, 84
MAX_CHARS = 74

FONT_STACK = "'JetBrains Mono'"

# Event category display labels and theme colors
STYLE = {
    "push":    ("push",    "#0969da", "#58a6ff"),
    "release": ("release", "#1a7f37", "#3fb950"),
    "repo":    ("repo",    "#0e7490", "#22d3ee"),
    "pr":      ("pr",      "#2563eb", "#60a5fa"),
    "merge":   ("merge",   "#8250df", "#a371f7"),
    "issue":   ("issue",   "#d97706", "#f59e0b"),
    "discuss": ("talk",    "#c026d3", "#e879f9"),
    "star":    ("star",    "#ca8a04", "#facc15"),
    "fork":    ("fork",    "#64748b", "#94a3b8"),
}

# Activity message templates with dynamic placeholders
MESSAGES = {
    "push_one": [
        "Pushed once to {s}. Clean getaway.",
        "One push to {s}. Tiny, tidy, done.",
    ],
    "push_few": [
        "Pushed {n} times to {s}. Steady progress.",
        "{n} pushes to {s}. Measure twice, push thrice.",
    ],
    "push_some": [
        "Pushed {n} times to {s}. Fueled by caffeine.",
        "{n} pushes to {s}. The commit button is getting warm.",
    ],
    "push_lots": [
        "Pushed {n} times to {s}. Sleep is optional.",
        "{n} pushes to {s}. Someone is in the zone.",
    ],
    "release": [
        "Shipped {s}. It works on my machine.",
        "Tagged {s}. No takebacks.",
        "{s} is out. Please be gentle in the issues.",
    ],
    "prerelease": [
        "Shipped {s} as a pre-release. Handle with care.",
        "{s} escaped early. Bugs are a feature.",
        "Pre-release {s}. Warranty void on arrival.",
    ],
    "pr_opened": [
        "Opened #{n} in {repo}: {s}. Fingers crossed.",
        "PR #{n} is up in {repo}: {s}. Review me?",
        "Asked {repo} nicely to take {s} (#{n}).",
    ],
    "pr_merged": [
        "Merged #{n} in {repo}: {s}. Ship it.",
        "{s} (#{n}) landed in {repo}. Nobody objected.",
        "Merged #{n} in {repo}: {s}. CI blinked first.",
    ],
    "pr_closed": [
        "Closed #{n} in {repo}: {s}. No sequel.",
        "Walked away from #{n} in {repo}: {s}.",
    ],
    "issue_opened": [
        "Filed #{n} in {repo}: {s}. Future me's problem.",
        "Found a bug in {repo}: {s}. Allegedly a feature.",
    ],
    "issue_closed": [
        "Closed #{n} in {repo}: {s}. Works now. Probably.",
        "Squashed #{n} in {repo}: {s}. Very satisfying.",
    ],
    "discussion": [
        "Started a chat in {repo}: {s}. Come say hi.",
        "Rang the bell in {repo}: {s}. Anyone home?",
    ],
    "repo_new": [
        "Created {s}. What could possibly go wrong?",
        "Started {s} from scratch. README coming soon.",
    ],
    "repo_public": [
        "Open-sourced {s}. Please be kind about the code.",
        "Made {s} public. Hoping the secrets were gitignored.",
    ],
    "star": [
        "Starred {s}. Great taste, honestly.",
        "Gave {s} a star. It earned it.",
    ],
    "fork": [
        "Forked {s} to tinker with it.",
        "Forked {s}. For science.",
    ],
    "empty": [
        "Nothing public lately. Touching grass, presumably.",
    ],
}


@dataclass
class Item:
    kind: str
    msg: str
    time: str
    seed: str
    subject: str
    repo: str
    n: int = 0


# Fetch recent public events from the GitHub REST API
def fetch_events():
    url = f"https://api.github.com/users/{USER}/events/public?per_page=100"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-activity"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)


# Convert a raw event payload into a structured activity item
def parse(e, dead_tags):
    t, p, full = e["type"], e["payload"], e["repo"]["name"]
    repo, act = full.split("/")[-1], p.get("action")

    def make(kind, msg, subject, n=0):
        return Item(kind, msg, e["created_at"], str(e["id"]), subject, repo, n)

    if t == "PushEvent":
        ref = p.get("ref", "").removeprefix("refs/heads/")
        return make("push", "", f"{repo}:{ref}", 1)
    if t == "ReleaseEvent" and act == "published":
        r = p["release"]
        if r["draft"] or (full, r["tag_name"]) in dead_tags:
            return None
        msg_key = "prerelease" if r["prerelease"] else "release"
        return make("release", msg_key, r["tag_name"])
    if t == "PullRequestEvent" and act in ("opened", "closed"):
        pr = p["pull_request"]
        if act == "opened":
            return make("pr", "pr_opened", pr["title"], p["number"])
        if pr.get("merged"):
            return make("merge", "pr_merged", pr["title"], p["number"])
        return make("pr", "pr_closed", pr["title"], p["number"])
    if t == "IssuesEvent" and act in ("opened", "closed"):
        i = p["issue"]
        return make("issue", f"issue_{act}", i["title"], i["number"])
    if t == "DiscussionEvent" and act == "created":
        return make("discuss", "discussion", p["discussion"]["title"])
    if t == "CreateEvent" and p.get("ref_type") == "repository":
        return make("repo", "repo_new", repo)
    if t == "PublicEvent":
        return make("repo", "repo_public", repo)
    if t == "WatchEvent":
        return make("star", "star", full)
    if t == "ForkEvent":
        return make("fork", "fork", full)
    return None


# Determine the message template key based on total commit count
def push_tier(n):
    if n == 1:
        return "push_one"
    if n <= 3:
        return "push_few"
    if n <= 8:
        return "push_some"
    return "push_lots"


# Aggregate events and collapse sequential push events on the same branch
def build_items(events):
    events = sorted(events, key=lambda e: e["created_at"], reverse=True)
    dead_tags = {
        (e["repo"]["name"], e["payload"].get("ref"))
        for e in events
        if e["type"] == "DeleteEvent" and e["payload"].get("ref_type") == "tag"
    }

    items = []
    for e in events:
        item = parse(e, dead_tags)
        if item is None:
            continue
        last = items[-1] if items else None
        if last and item.kind == last.kind == "push" and item.subject == last.subject:
            last.n += 1
        else:
            items.append(item)

    for it in items:
        if it.kind == "push":
            it.msg = push_tier(it.n)
    return items[:LIMIT]


# Select a message template deterministically using the event identifier
def pick(options, seed):
    return options[zlib.crc32(seed.encode()) % len(options)]


# Extract and format message segments for an activity row
def message(it):
    before, _, after = pick(MESSAGES[it.msg], it.seed).partition("{s}")
    before = before.format(n=it.n, repo=it.repo)
    after = after.format(n=it.n, repo=it.repo)
    room = max(MAX_CHARS - len(before) - len(after), 12)
    subject = it.subject if len(it.subject) <= room else it.subject[: room - 1].rstrip() + "…"
    return before, subject, after


# Format an ISO timestamp to local timezone string
def stamp(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo(TIMEZONE))
    return dt.strftime("%b %d, %H:%M %Z")


# Base64 encode and embed local web fonts as font face rules
def font_faces():
    css_rules = []
    for weight, name in ((400, "JetBrainsMono-Regular.woff2"), (600, "JetBrainsMono-SemiBold.woff2")):
        path = FONT_DIR / name
        if path.exists():
            data = base64.b64encode(path.read_bytes()).decode()
            css_rules.append(
                f"@font-face {{"
                f"font-family: 'JetBrains Mono'; "
                f"font-weight: {weight}; "
                f"src: url(data:font/woff2;base64,{data}) format('woff2');"
                f"}}"
            )
    return "\n".join(css_rules)


# Generate style definitions for light and dark display modes
def css():
    light = "".join(f".k-{k}{{fill:{lc}}}" for k, (_, lc, _dc) in STYLE.items())
    dark = "".join(f".k-{k}{{fill:{dc}}}" for k, (_, _lc, dc) in STYLE.items())
    font_css = font_faces()
    font_prefix = f"{font_css}\n" if font_css else ""
    return (
        f"{font_prefix}"
        f"text {{ font-family: {FONT_STACK}; letter-spacing: 0.2px; }}\n"
        f".tag {{ font-size: 12px; font-weight: 600; }}\n"
        f".msg {{ font-size: 13px; fill: #424a53; }}\n"
        f".b {{ font-weight: 600; fill: #1f2328; }}\n"
        f".time {{ font-size: 12px; fill: #6e7781; }}\n"
        f".sep {{ stroke: #d8dee4; }}\n"
        f"{light}\n"
        f"@media (prefers-color-scheme: dark) {{\n"
        f"  .msg {{ fill: #9198a1; }}\n"
        f"  .b {{ fill: #c9d1d9; }}\n"
        f"  .time {{ fill: #6e7681; }}\n"
        f"  .sep {{ stroke: #21262d; }}\n"
        f"  {dark}\n"
        f"}}"
    )


# Render a single activity row as SVG elements
def row(i, it):
    y = i * ROW_H
    base = y + ROW_H // 2 + 5
    before, subject, after = message(it)
    sep = (
        f'<line class="sep" x1="{PAD}" x2="{WIDTH - PAD}" y1="{y}" y2="{y}"/>'
        if i
        else ""
    )
    return (
        f"{sep}"
        f'<text class="tag k-{it.kind}" x="{PAD}" y="{base}">{STYLE[it.kind][0]}</text>'
        f'<text class="msg" x="{TEXT_X}" y="{base}">{escape(before)}'
        f'<tspan class="b">{escape(subject)}</tspan>{escape(after)}</text>'
        f'<text class="time" x="{WIDTH - PAD}" y="{base}" text-anchor="end">{escape(stamp(it.time))}</text>'
    )


# Assemble the complete SVG document containing all activity rows
def render(items):
    if items:
        body = "\n".join(row(i, it) for i, it in enumerate(items))
        height = ROW_H * len(items)
    else:
        body = f'<text class="msg" x="{PAD}" y="25">{escape(MESSAGES["empty"][0])}</text>'
        height = ROW_H

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img">\n'
        f"<title>Recent GitHub activity</title>\n"
        f"<style>\n{css()}\n</style>\n"
        f"{body}\n"
        f"</svg>\n"
    )


if __name__ == "__main__":
    items = build_items(fetch_events())
    OUT.write_text(render(items), encoding="utf-8")
    print(f"Wrote {OUT} with {len(items)} items.")