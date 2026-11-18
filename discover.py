"""Find videos and articles by keyword (discover.json), beyond the fixed channel and blog lists.

Usage:
  python3 discover.py        # search every query, write raw/_discovered.json and raw_articles/discovered.json

For every query in discover.json:
  * YouTube search (yt-dlp, no API key): the top results, kept if they have >= min_views views,
    last 3 min to 3 h, and have a mostly-Latin title (English content).
  * Hacker News search (Algolia, no key): stories with >= min_points points, linking to a page.
A result is kept only if its title contains every non-generic word of the query, so "itertools"
needs "itertools" in the title. Each query keeps its per_query best results (by views or points).
Queries in the "python" group are searched as "python <query>", and a result must be about Python:
"python" in the title (or the URL, or a video from a channel in channels.json) and no other language named.
Queries in the "general" group and in each of the "hubs" (the site's focus sections: AI agents, LangChain,
Azure) are searched as they are, and the words must be in the title as a phrase. Hub queries use
hub_min_views and hub_per_query. Every result records the groups whose queries found it ("python",
"general" or a hub name), so the site can put it in Code craft or in a hub's section.

fetch.py and articles.py pick these files up when they build, as the "D" (Discovered) tier:
videos keep their real channel, articles go into one "Discovered" source.
"""
import json, re, subprocess, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
YTDLP = ["uvx", "--from", "yt-dlp@latest", "yt-dlp"]
UA = "Mozilla/5.0 (compatible; NerdvanaBot/1.0; +https://github.com/GeenccMustafa/nerdvana)"
SEARCH_N = 30   # YouTube results read per query
GENERIC = {"python", "tutorial", "tutorials", "explained", "module", "modules", "library", "libraries", "guide",
           "beginners", "beginner", "how", "to", "the", "in", "for", "with", "and", "a", "an", "of", "crash", "course"}
# small words a phrase may skip over: "agents in production" matches "Agents in Production"
FILLER = r"(?:(?:in|to|the|for|with|and|a|an|of|on|your|my)\W+){0,2}"
# endings a phrase word may take: "code review" matches "code reviews", "autogen" doesn't match "autogenic"
SUFFIX = r"(?:s|es|ed|ing|er|ers)?"
CRAFT_GROUPS = ("python", "general")


def must_words(q):
    return [w for w in re.findall(r"[a-z0-9_+]+", q.lower()) if w not in GENERIC]


def title_ok(title, words, phrase=False):
    if phrase:   # general and hub queries: the words in this order, next to each other ("code review", "code reviews")
        return bool(re.search(r"(?<![a-z0-9])" + (SUFFIX + r"\W+" + FILLER).join(map(re.escape, words)) + SUFFIX + r"(?![a-z0-9])",
                              (title or "").lower()))
    t = re.findall(r"[a-z0-9_+]+", (title or "").lower())
    # "type hints" also matches "type hinting", "decorators" matches "decorator"
    return all(any(x.startswith(w) or w.startswith(x) and len(w) - len(x) <= 1 and len(x) >= 4 for x in t) for w in words)


OTHER_LANG = re.compile(r"(?<![a-z])(c\+\+|c#|java|javascript|typescript|rust|golang|php|ruby|kotlin|swift|"
                        r"lua|julia|clojure|haskell|elixir|hindi|urdu)(?![a-z])", re.I)


def is_python(text, also=False):
    return ("python" in text.lower() or also) and not OTHER_LANG.search(text)


NOT_TALKS = re.compile(r"chillstep|lo-?fi|beats|ambient|music|playlist|asmr|sleep|relax|meditation|hypnos|entspann", re.I)


def watchable(e):
    """Not members-only, Premium-only or login-only, and not an upcoming premiere."""
    return e.get("availability") not in ("subscriber_only", "premium_only", "needs_auth") and e.get("live_status") != "is_upcoming"


def latin(title):
    letters = [c for c in title if c.isalpha()]
    return not letters or sum(c.isascii() for c in letters) / len(letters) >= 0.9


def queries(cfg):
    """(query, group) pairs: the python and general groups, then every hub's queries."""
    out = [(q, "python") for q in cfg["python"]] + [(q, "general") for q in cfg["general"]]
    for hub, h in cfg.get("hubs", {}).items():
        out += [(q, hub) for q in h["queries"]]
    return out


def limits(group, cfg):
    """(min views, results kept per query) for a group: hubs have their own."""
    if group in CRAFT_GROUPS:
        return cfg["min_views"], cfg["per_query"]
    return cfg.get("hub_min_views", cfg["min_views"]), cfg.get("hub_per_query", cfg["per_query"])


def label(q, group):
    return {"python": "py ", "general": ""}.get(group, group + " ") + q


def search_youtube(q, group, cfg, known):
    py, (min_views, keep) = group == "python", limits(group, cfg)
    query = f"python {q}" if py else q
    r = subprocess.run(YTDLP + ["--flat-playlist", "-J", f"ytsearch{SEARCH_N}:{query}"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return label(q, group), [], "FAILED: " + (r.stderr.strip().splitlines() or ["?"])[-1][-160:]
    words, out = must_words(q), []
    for e in json.loads(r.stdout).get("entries") or []:
        dur, views, title = e.get("duration") or 0, e.get("view_count") or 0, e.get("title") or ""
        if not e.get("id") or not e.get("channel_id") or "#short" in title.lower() or not watchable(e):
            continue
        if views < min_views or not 180 <= dur <= 3 * 3600 or not latin(title) or NOT_TALKS.search(title) \
                or not title_ok(title, words, phrase=not py):
            continue
        if py and not is_python(title, also=(e.get("uploader_id") or "").lower() in known):
            continue
        out.append({"id": e["id"], "title": title, "duration": dur, "view_count": views,
                    "channel": e.get("channel") or e.get("uploader") or "", "channel_id": e["channel_id"],
                    "uploader_id": e.get("uploader_id") or "", "query": q})
    out.sort(key=lambda v: -v["view_count"])
    return label(q, group), out[:keep], ""


def search_hn(q, group, cfg):
    py, keep = group == "python", limits(group, cfg)[1]
    query = " ".join(must_words(q)) or q
    params = urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": 100,
                                     "numericFilters": f"points>={cfg['min_points']}"})
    req = urllib.request.Request(f"https://hn.algolia.com/api/v1/search?{params}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            hits = json.loads(r.read()).get("hits", [])
    except Exception as e:
        return label(q, group), [], f"FAILED: {type(e).__name__}: {str(e)[:120]}"
    words, out = must_words(q), []
    for h in hits:
        u, title = h.get("url") or "", h.get("title") or ""
        host = urllib.parse.urlsplit(u).netloc.lower()
        if not u.startswith(("http://", "https://")) or any(x in host for x in ("youtube.com", "youtu.be", "github.com")):
            continue
        if title.lower().startswith(("show hn", "ask hn", "launch hn", "tell hn")) or not title_ok(title, words, phrase=not py):
            continue
        if py and not (is_python(title + " " + u) and not OTHER_LANG.search(title)):
            continue
        out.append({"url": u, "title": title, "points": h.get("points") or 0, "comments": h.get("num_comments") or 0,
                    "hn": int(h["objectID"]), "hn_ts": h.get("created_at_i"), "query": q})
    out.sort(key=lambda a: -a["points"])
    return label(q, group), out[:keep], ""


def merge(into, found, key, group, topic):
    """Add a query's results to into ({key: result}); a result found again only gains the group."""
    new = 0
    for x in found:
        if x[key] in into:
            if group not in into[x[key]]["groups"]:
                into[x[key]]["groups"].append(group)
        else:
            into[x[key]] = {**x, "groups": [group], "topic": topic}
            new += 1
    return new


def write(path, data):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.rename(path)


if __name__ == "__main__":
    cfg = json.loads((ROOT / "discover.json").read_text())
    todo = queries(cfg)
    # results from channels that aren't listed get the topic of the group that found them first
    topic = lambda g: cfg.get("hubs", {}).get(g, {}).get("topic", "Programming")
    known = {"@" + c["handle"].lower() for c in json.loads((ROOT / "channels.json").read_text())}
    videos, articles = {}, {}
    with ThreadPoolExecutor(8) as ex:
        for (_, g), (name, found, err) in zip(todo, ex.map(lambda x: search_youtube(*x, cfg, known), todo)):
            new = merge(videos, found, "id", g, topic(g))
            print(f"  yt  {name:46} {len(found):2} kept, {new:2} new {err}", flush=True)
        for (_, g), (name, found, err) in zip(todo, ex.map(lambda x: search_hn(*x, cfg), todo)):
            new = merge(articles, found, "url", g, topic(g))
            print(f"  hn  {name:46} {len(found):2} kept, {new:2} new {err}", flush=True)
    # a failed run (e.g. YouTube blocking the runner) keeps the previous results instead of emptying them
    if videos or not (ROOT / "raw" / "_discovered.json").exists():
        write(ROOT / "raw" / "_discovered.json", {"entries": list(videos.values())})
    if articles or not (ROOT / "raw_articles" / "discovered.json").exists():
        write(ROOT / "raw_articles" / "discovered.json", {"hn": list(articles.values()), "rss": [], "err": []})
    print(f"discovered: {len(videos)} videos, {len(articles)} articles")
    if not videos and not articles:
        sys.exit(1)
