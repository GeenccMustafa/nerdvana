"""Fetch videos for every channel in channels.json with yt-dlp, then build videos.json.

Usage:
  python3 fetch.py          # fetch channels not yet in raw/, then build
  python3 fetch.py --build  # only rebuild videos.json from raw/
  python3 fetch.py --force  # re-fetch everything

Balancing rules (so a few prolific channels can't drown out the rest):
  - only channels with >= MIN_SUBS subscribers are kept, at most MAX_CHANNELS of them
    (picked by tier first, then subscriber count)
  - channels marked "pin": true in channels.json skip both limits and don't use up a slot

Videos found by keyword search (discover.py -> raw/_discovered.json) are added too: to their channel
if it's already listed, otherwise under a "D" (Discovered) channel of their own, which the site
keeps out of the sidebar and the Home mix.
  - each channel keeps at most TOP_BY_VIEWS most-viewed + NEWEST most-recent videos
  - clips of 60s or shorter (Shorts) are dropped, and so are members-only videos and upcoming premieres
"""
import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
YTDLP = ["uvx", "--from", "yt-dlp@latest", "yt-dlp"]
FETCH_LIMIT = 3000      # newest N uploads read per channel
MIN_SUBS = 250_000
MAX_CHANNELS = 100
TOP_BY_VIEWS = 300
NEWEST = 100
TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}
# can't be watched without a membership, YouTube Premium or a login; upcoming premieres can't be watched yet
UNWATCHABLE = {"subscriber_only", "premium_only", "needs_auth"}


def watchable(e):
    return e.get("availability") not in UNWATCHABLE and e.get("live_status") != "is_upcoming"


def fetch(ch, force=False):
    out = RAW / f"{ch['handle']}.json"
    if out.exists() and not force:
        return ch["handle"], "cached"
    cmd = YTDLP + ["--flat-playlist", "-J", "--playlist-end", str(FETCH_LIMIT),
                   "--extractor-args", "youtubetab:approximate_date",
                   ch.get("url") or f"https://www.youtube.com/@{ch['handle']}/videos"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return ch["handle"], "FAILED: " + (r.stderr.strip().splitlines() or ["?"])[-1][-200:]
    tmp = out.with_suffix(".part")
    tmp.write_text(r.stdout)
    tmp.rename(out)  # atomic: a concurrent build never sees half a file
    d = json.loads(r.stdout)
    return ch["handle"], f"{len(d.get('entries') or [])} videos, {d.get('channel_follower_count')} subs"


def pick_videos(entries):
    vids = []
    for e in entries or []:
        if not e.get("id") or e.get("title") in ("[Private video]", "[Deleted video]") or not watchable(e):
            continue
        dur = e.get("duration")
        if dur is not None and dur <= 60:
            continue
        vids.append([e["id"], e.get("title", ""), int(dur or 0),
                     int(e.get("view_count") or 0), int(e.get("timestamp") or 0)])
    keep = {v[0]: v for v in sorted(vids, key=lambda v: -v[3])[:TOP_BY_VIEWS]}
    keep.update({v[0]: v for v in sorted(vids, key=lambda v: -v[4])[:NEWEST]})
    return list(keep.values()), len(vids)


def build(channels):
    loaded, skipped = [], []
    for ch in channels:
        f = RAW / f"{ch['handle']}.json"
        if not f.exists():
            skipped.append((ch["handle"], "not fetched")); continue
        d = json.loads(f.read_text())
        subs = d.get("channel_follower_count") or 0
        if subs < MIN_SUBS and not ch.get("pin"):
            skipped.append((ch["handle"], f"{subs:,} subs")); continue
        loaded.append((ch, d, subs))
    pinned = [x for x in loaded if x[0].get("pin")]
    ranked = sorted((x for x in loaded if not x[0].get("pin")),
                    key=lambda x: (TIER_RANK.get(x[0]["tier"], 9), -x[2]))
    for ch, _, subs in ranked[MAX_CHANNELS:]:
        skipped.append((ch["handle"], f"over {MAX_CHANNELS} limit ({subs:,} subs)"))
    loaded = sorted(ranked[:MAX_CHANNELS] + pinned, key=lambda x: -x[2])

    chans, vids = [], []
    for ch, d, subs in loaded:
        picked, total = pick_videos(d.get("entries"))
        avatar = next((t["url"] for t in d.get("thumbnails") or [] if t.get("id") == "avatar_uncropped"), "")
        if avatar:
            avatar = avatar.rsplit("=", 1)[0] + "=s88-c-k-c0x00ffffff-no-rj"  # 88px square
        chans.append({"h": ch["handle"], "n": d.get("channel") or ch["handle"], "t": ch["tier"],
                      "topic": ch["topic"], "subs": subs, "total": total, "a": avatar})
        ci = len(chans) - 1
        vids += [[v[0], v[1], ci, v[2], v[3], v[4]] for v in picked]
    disc = add_discovered(chans, vids)
    data = {"channels": chans, "videos": vids, "discovered": disc,
            "fields": ["id", "title", "channel", "duration", "views", "timestamp"]}
    (ROOT / "videos.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    for h, why in skipped:
        print(f"  skipped {h:28} {why}")
    print(f"videos.json: {len(chans)} channels, {len(vids)} videos ({len(disc)} found by keyword search)")


def add_discovered(chans, vids):
    """Keyword-search results: onto their channel if listed, else a "D" channel.
    Returns the ids of every discovered video (also ones the channel lists already had), for Code craft."""
    f = RAW / "_discovered.json"
    if not f.exists():
        return []
    have = {v[0] for v in vids}
    by_handle = {c["h"].lower(): i for i, c in enumerate(chans)}
    ids = []
    for e in json.loads(f.read_text()).get("entries") or []:
        handle = (e.get("uploader_id") or "").removeprefix("@")
        if e["id"] in have:
            ids.append(e["id"]); continue
        if not handle:
            continue
        ci = by_handle.get(handle.lower())
        if ci is None:
            chans.append({"h": handle, "n": e.get("channel") or handle, "t": "D", "topic": "Programming",
                          "subs": 0, "total": 0, "a": ""})
            ci = by_handle[handle.lower()] = len(chans) - 1
        if chans[ci]["t"] == "D":
            chans[ci]["total"] += 1
        vids.append([e["id"], e.get("title") or "", ci, int(e.get("duration") or 0), int(e.get("view_count") or 0), 0])
        have.add(e["id"]); ids.append(e["id"])
    return list(dict.fromkeys(ids))


if __name__ == "__main__":
    channels = json.loads((ROOT / "channels.json").read_text())
    if "--build" not in sys.argv:
        RAW.mkdir(exist_ok=True)
        with ThreadPoolExecutor(8) as ex:
            for h, status in ex.map(lambda c: fetch(c, "--force" in sys.argv), channels):
                print(f"{h:28} {status}", flush=True)
    build(channels)
