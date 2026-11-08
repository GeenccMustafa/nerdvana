"""Write feed.xml: an Atom feed of this week's most talked-about videos and articles.

Usage: python3 feed.py   (run after fetch.py and articles.py; the nightly job does this)

The feed holds the 10 most-viewed videos uploaded in the last 7 days and the 10 most-upvoted
(Hacker News) articles published in the last 7 days, at most 2 per channel or source.
Entry ids are stable, so a feed reader shows each item once, when it first makes the list.
"""
import json, time
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
SITE = "https://geenccmustafa.github.io/nerdvana/"
WEEK, PER_KIND, PER_SOURCE = 7 * 86400, 10, 2


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def fmt_num(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{round(n / 1e3)}K" if n >= 1e3 else str(n)


def top(rows, key, src):
    out, per = [], {}
    for r in sorted(rows, key=key):
        if per.get(r[src], 0) < PER_SOURCE:
            per[r[src]] = per.get(r[src], 0) + 1
            out.append(r)
        if len(out) == PER_KIND:
            break
    return out


def entry(eid, title, link, ts, summary):
    return f"""  <entry>
    <id>{eid}</id>
    <title>{escape(title)}</title>
    <link href="{escape(link)}"/>
    <updated>{iso(ts)}</updated>
    <summary>{escape(summary)}</summary>
  </entry>"""


def main():
    now = time.time()
    entries = []
    vd = json.loads((ROOT / "videos.json").read_text())
    chans = vd["channels"]
    for v in top([v for v in vd["videos"] if v[5] and now - v[5] <= WEEK], lambda v: -v[4], 2):
        c = chans[v[2]]
        entries.append((v[5], entry(f"tag:nerdvana,2026:video:{v[0]}", f"▶ {v[1]}", f"{SITE}#v={v[0]}", v[5],
                                     f"Video · {c['n']} · {fmt_num(v[4])} views · {round(v[3] / 60)} min")))
    if (ROOT / "articles.json").exists():
        ad = json.loads((ROOT / "articles.json").read_text())
        srcs = ad["sources"]
        recent = [a for a in ad["articles"] if a[5] and now - a[5] <= WEEK]
        for a in top(recent, lambda a: (-a[4], -a[5]), 2):
            s = srcs[a[2]]
            bits = [f"Article · {s['n']}"] + ([f"▲ {a[4]} on Hacker News"] if a[4] else []) + \
                   ([f"{max(1, round(a[3] / 230))} min read"] if a[3] else [])
            entries.append((a[5], entry(f"tag:nerdvana,2026:article:{a[0]}", a[1], a[6], a[5],
                                         " · ".join(bits) + (f"\n\n{a[7]}" if a[7] else ""))))
    entries.sort(key=lambda e: -e[0])
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>{SITE}</id>
  <title>Nerdvana: this week's top videos and articles</title>
  <subtitle>The most-viewed tech videos and most-upvoted tech articles of the last 7 days</subtitle>
  <link href="{SITE}"/>
  <link rel="self" href="{SITE}feed.xml"/>
  <updated>{iso(now)}</updated>
  <author><name>Nerdvana</name></author>
{chr(10).join(e for _, e in entries)}
</feed>
"""
    (ROOT / "feed.xml").write_text(xml)
    print(f"feed.xml: {len(entries)} entries")


if __name__ == "__main__":
    main()
