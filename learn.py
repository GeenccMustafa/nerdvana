"""Build learn.json: official Microsoft Learn certification courses with their unit videos.

Usage: python3 learn.py           # keeps the current learn.json if the new one lost more than 10% of its videos
       python3 learn.py --force

learn_courses.json lists the courses. For each one, the Learn catalog API gives its learning paths and
modules; every module page lists its units, and a unit page embeds its video (hosted by Microsoft, not
on YouTube). The video API gives each video's length, its MP4 and its English captions.

learn.json:
  modules  [module title]
  videos   [[id, unit title, seconds, module index, unit, mp4, captions]]   id = "ml-" + Learn video id. To keep the
           file small, unit is the unit's url after UNIT_BASE, and mp4/captions the file name after
           MEDIA_BASE + "public-<Learn video id>/" (a full url when a video is stored somewhere else)
  courses  same shape as courses.json, plus "ml": 1, "code", "cert" and "url" (the course on Learn).
           Sections are modules ("path": the learning path it belongs to); steps {"k": "v", "id"} point
           at a video above, or at a YouTube video in videos.json for the last "Exam prep" section.

Video metadata never changes for an id, so it's cached in .cache/learn_videos.json.
"""
import json, re, sys, html, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "learn_videos.json"
PLAYLISTS = ROOT / "raw" / "_playlists"
CATALOG = "https://learn.microsoft.com/api/catalog/?locale=en-us&type=courses,learningPaths,modules"
VIDEO_API = "https://learn.microsoft.com/api/video/public/v1/entries/"
VID = re.compile(r'learn-video\.azurefd\.net/vod/player\?id=([0-9a-f-]{36})')
UNIT = re.compile(r'<a class="unit-title[^"]*" href="(\d+-[a-z0-9-]+)"[^>]*>([^<]+)</a>')
UA = {"User-Agent": "nerdvana-learn/1.0"}
UNIT_BASE = "https://learn.microsoft.com/en-us/training/modules/"
MEDIA_BASE = "https://videoencodingpublic-hgeaeyeba8gycee3.b01.azurefd.net/"


def short(url, base):
    return url[len(base):] if url.startswith(base) else url


def get(url, tries=3):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read().decode("utf8", "replace")
        except Exception:
            pass
    return None


def scan_module(m):
    """[(unit title, unit url, [video ids])] for a module, or None if its page couldn't be read."""
    base = m["url"].split("?")[0]
    page = get(base)
    if page is None:
        return m["uid"], None
    units = []
    for slug, title in dict.fromkeys(UNIT.findall(page)):
        body = get(base + slug) or ""
        units.append((html.unescape(title).strip(), base + slug, list(dict.fromkeys(VID.findall(body)))))
    return m["uid"], units


def video_meta(vid):
    try:
        d = json.loads(get(VIDEO_API + vid) or "")
    except ValueError:
        return vid, None
    pv = d.get("publicVideo") or {}
    mp4 = pv.get("mediumQualityVideoUrl") or pv.get("highQualityVideoUrl") or pv.get("lowQualityVideoUrl")
    if not mp4:
        return vid, None
    cc = next((c["url"] for c in pv.get("captions") or [] if c.get("language", "").startswith("en")), "")
    return vid, {"dur": round((pv.get("durationInMillisecond") or 0) / 1000), "mp4": mp4, "cc": cc}


def exam_ids(pid):
    f = PLAYLISTS / f"{pid}.json"
    if not pid or not f.exists():
        return []
    return [e["id"] for e in json.loads(f.read_text()).get("entries") or [] if e.get("id")]


def main():
    cfg = json.loads((ROOT / "learn_courses.json").read_text())["courses"]
    cat = json.loads(get(CATALOG) or "{}")
    if not cat.get("courses"):
        sys.exit("Couldn't read the Learn catalog")
    courses = {c["course_number"]: c for c in cat["courses"]}
    lps = {p["uid"]: p for p in cat["learningPaths"]}
    mods = {m["uid"]: m for m in cat["modules"]}

    plan = []
    for c in cfg:
        lc = courses.get(c["course"])
        if not lc:
            print(f"  {c['course']}: not in the Learn catalog, skipped"); continue
        paths = [lps[s["uid"]] for s in lc.get("study_guide", []) if s.get("type") == "learningPath" and s["uid"] in lps]
        plan.append((c, lc, [(p, [mods[m] for m in p.get("modules", []) if m in mods]) for p in paths]))

    needed = {m["uid"]: m for _, _, paths in plan for _, ms in paths for m in ms}
    with ThreadPoolExecutor(8) as ex:
        units = dict(ex.map(scan_module, needed.values()))
    failed = [u for u, x in units.items() if x is None]
    if len(failed) > 0.1 * len(units):
        sys.exit(f"{len(failed)} of {len(units)} module pages couldn't be read; keeping the current learn.json")

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    want = {v for us in units.values() if us for _, _, vs in us for v in vs}
    with ThreadPoolExecutor(8) as ex:
        for vid, meta in ex.map(video_meta, [v for v in want if v not in cache]):
            if meta:
                cache[vid] = meta
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache))

    last = {c["id"]: c["sections"] for c in json.loads((ROOT / "learn.json").read_text())["courses"]} if (ROOT / "learn.json").exists() else {}
    modules, mod_ix, videos, seen, out = [], {}, [], set(), []
    for c, lc, paths in plan:
        code = c["course"].split("T")[0]
        sections, nv = [], 0
        for p, ms in paths:
            for m in ms:
                steps = []
                for title, url, vs in units.get(m["uid"]) or []:
                    for k, vid in enumerate(v for v in vs if v in cache):
                        sid = "ml-" + vid
                        if sid not in seen:
                            seen.add(sid)
                            if m["uid"] not in mod_ix:
                                mod_ix[m["uid"]] = len(modules); modules.append(m["title"])
                            meta = cache[vid]
                            media = f"{MEDIA_BASE}public-{vid}/"
                            videos.append([sid, title + (f" ({k + 1})" if k else ""), meta["dur"], mod_ix[m["uid"]],
                                           short(url, UNIT_BASE), short(meta["mp4"], media), short(meta["cc"], media)])
                        steps.append({"k": "v", "id": sid})
                if steps:
                    sections.append({"title": m["title"], "path": p["title"], "steps": steps}); nv += len(steps)
        # the exam playlist comes from fetch.py; if YouTube blocked it this time, keep the steps from the last build
        ids = exam_ids(c.get("exam")) or [st["id"] for sec in last.get("learn-" + code.lower(), [])
                                           if sec.get("path") == "Exam prep" for st in sec["steps"] if "note" not in st]
        prep = [{"k": "v", "id": i} for i in ids] + ([{"k": "v", "id": c["cram"], "note": "A whiteboard run through the whole exam."}] if c.get("cram") else [])
        if prep:
            sections.append({"title": f"Exam prep: {code}", "path": "Exam prep", "steps": prep})
        if not nv:
            print(f"  {c['course']}: no unit videos, skipped"); continue
        out.append({"id": "learn-" + code.lower(), "ml": 1, "code": code, "cert": c["cert"],
                    "title": f"{code}: {lc['title']}", "level": c["level"], "blurb": c["blurb"],
                    "topic": "Azure certifications", "by": "Microsoft Learn", "hubs": c.get("hubs", []),
                    "url": lc["url"].split("?")[0], "sections": sections})
        print(f"{code:7} {len(paths)} paths, {len(sections) - bool(prep)} modules with video, {nv} videos, "
              f"{sum(cache[s['id'][3:]]['dur'] for sec in sections for s in sec['steps'] if s['id'].startswith('ml-')) / 3600:.1f} h")

    prev = ROOT / "learn.json"
    if prev.exists() and "--force" not in sys.argv:
        old = json.loads(prev.read_text())
        if len(videos) < 0.9 * len(old["videos"]) or len(out) < len(old["courses"]) - 1:
            sys.exit(f"Only {len(out)} courses and {len(videos)} videos (now {len(old['courses'])} and {len(old['videos'])}); "
                     "Learn may be failing, keeping the current learn.json. Run with --force to accept it.")
    (ROOT / "learn.json").write_text(json.dumps({"modules": modules, "videos": videos, "courses": out},
                                                ensure_ascii=False, separators=(",", ":")))
    print(f"learn.json: {len(out)} courses, {len(videos)} videos, {len(failed)} module pages unread")


if __name__ == "__main__":
    main()
