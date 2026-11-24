"""Build learn.json: official Microsoft Learn certification courses with their unit videos.

Usage: python3 learn.py           # once a week: does nothing if learn.json was built less than 6 days ago
       python3 learn.py --force   # rebuild now, and accept a learn.json that lost more than 10% of its videos

Learn is read gently (a few requests at a time, waiting and retrying when it asks to slow down). A module
whose pages can't be read keeps what the last learn.json had for it, so a bad run never drops a course;
if most of them can't be read, nothing is written and the next run tries again.

learn_courses.json lists the courses. For each one, the Learn catalog API gives its learning paths and
modules; every module page lists its units, and a unit page embeds its video (hosted by Microsoft, not
on YouTube). The video API gives each video's length, its MP4 and its English captions. Every unit is
a step: units with a video play in Nerdvana, the rest (reading, exercises, knowledge checks) open on
Learn, where a signed-in Microsoft account tracks progress.

learn.json:
  built    the date it was built (YYYY-MM-DD)
  modules  [module title]
  videos   [[id, unit title, seconds, module index, unit, mp4, captions]]   id = "ml-" + Learn video id. To keep the
           file small, unit is the unit's url after UNIT_BASE, and mp4/captions the file name after
           MEDIA_BASE + "public-<Learn video id>/" (a full url when a video is stored somewhere else)
  units    [[unit, title, module index]]   units without a video (unit as in videos); their step id is "lu-" + unit
  courses  same shape as courses.json, plus "ml": 1, "code", "cert", "url" (the course on Learn), "certUrl"
           (the certification's page) and "guide" (the exam's study guide). Sections are modules ("path": the
           learning path it belongs to, "url": the module on Learn); steps {"k": "v", "id"} point at a video
           above (or at a YouTube video in videos.json, in the last "Exam prep" section), {"k": "u", "id"} at a unit.

Video metadata never changes for an id, so it's cached in .cache/learn_videos.json.
"""
import collections, datetime, html, json, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "learn_videos.json"
PLAYLISTS = ROOT / "raw" / "_playlists"
CATALOG = "https://learn.microsoft.com/api/catalog/?locale=en-us&type=courses,learningPaths,modules,certifications"
GUIDE = "https://learn.microsoft.com/en-us/credentials/certifications/resources/study-guides/"
VIDEO_API = "https://learn.microsoft.com/api/video/public/v1/entries/"
VID = re.compile(r'learn-video\.azurefd\.net/vod/player\?id=([0-9a-f-]{36})')
UNIT = re.compile(r'<a class="unit-title[^"]*" href="(\d+-[a-z0-9-]+)"[^>]*>([^<]+)</a>')
UA = {"User-Agent": "Mozilla/5.0 (compatible; nerdvana-learn/1.1)"}
WORKERS = 3          # requests in flight at once
MAX_AGE_DAYS = 6
errors = collections.Counter()   # why requests failed, printed at the end
UNIT_BASE = "https://learn.microsoft.com/en-us/training/modules/"
MEDIA_BASE = "https://videoencodingpublic-hgeaeyeba8gycee3.b01.azurefd.net/"


def short(url, base):
    """url without base in front, to keep learn.json small; a url stored somewhere else stays whole."""
    return url[len(base):] if url.startswith(base) else url


def get(url, tries=5):
    """The page, or None. Waits and retries on errors, longer when Learn asks to slow down (429/503)."""
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read().decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            errors[f"HTTP {e.code}"] += 1
            if e.code == 404:
                return None
            wait = e.headers.get("Retry-After", "")
            time.sleep(min(int(wait), 120) if wait.isdigit() else 2 ** (k + 1))
        except Exception as e:
            errors[type(e).__name__] += 1
            time.sleep(2 ** (k + 1))
    return None


def scan_module(m):
    """[(unit title, unit url, [video ids])] for a module, or None if any of its pages couldn't be read."""
    base = m["url"].split("?")[0]
    page = get(base)
    if page is None:
        return m["uid"], None
    units = []
    for slug, title in dict.fromkeys(UNIT.findall(page)):
        body = get(base + slug)
        if body is None:
            return m["uid"], None
        units.append((html.unescape(title).strip(), base + slug, list(dict.fromkeys(VID.findall(body)))))
    return m["uid"], units or None


def previous_units(old):
    """{module title: units} and {video id: metadata} from the last learn.json, to fill in modules that
    couldn't be read this time."""
    by_mod, meta = collections.defaultdict(dict), {}
    for unit, title, mi in old.get("units", []):
        by_mod[old["modules"][mi]][UNIT_BASE + unit] = (title, [])
    for sid, title, dur, mi, unit, mp4, cc in old.get("videos", []):
        vid, media = sid[3:], f"{MEDIA_BASE}public-{sid[3:]}/"
        full = lambda u, base: u if not u or u.startswith("https://") else base + u
        url = full(unit, UNIT_BASE)
        t, vs = by_mod[old["modules"][mi]].setdefault(url, (re.sub(r" \(\d+\)$", "", title), []))
        vs.append(vid)
        meta[vid] = {"dur": dur, "mp4": full(mp4, media), "cc": full(cc, media)}
    # back in Learn's order: units are numbered (1-introduction, 2-…)
    order = lambda u: int(re.match(r"(\d+)", u.rsplit("/", 1)[1]).group(1))
    return {m: [(t, u, vs) for u, (t, vs) in sorted(us.items(), key=lambda x: order(x[0]))] for m, us in by_mod.items()}, meta


def video_meta(vid):
    """(video id, {"dur", "mp4", "cc"}) from Learn's video API, or (video id, None) when there's no MP4 to play.

    dur is in seconds, mp4 the medium-quality file (or the closest there is), cc the English captions or ""."""
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
    """The video ids of an exam-prep playlist, as fetch.py saved it; [] if there is none (yet)."""
    f = PLAYLISTS / f"{pid}.json"
    if not pid or not f.exists():
        return []
    return [e["id"] for e in json.loads(f.read_text()).get("entries") or [] if e.get("id")]


def main():
    """Rebuild learn.json when it's due (or with --force).

    Reads the catalog, scans every module the courses need, fetches metadata for new videos, and turns
    each course into sections (one per module, then "Exam prep"). Exits without writing when Learn looks
    to be failing, so the current learn.json stays."""
    old = json.loads((ROOT / "learn.json").read_text()) if (ROOT / "learn.json").exists() else {}
    age = (datetime.date.today() - datetime.date.fromisoformat(old.get("built", "2000-01-01"))).days
    if "--force" not in sys.argv and age < MAX_AGE_DAYS:
        print(f"learn.json is {age} days old; rebuilt once a week (--force to rebuild now)"); return
    cfg = json.loads((ROOT / "learn_courses.json").read_text())["courses"]
    cat = json.loads(get(CATALOG) or "{}")
    if not cat.get("courses"):
        sys.exit("Couldn't read the Learn catalog")
    courses = {c["course_number"]: c for c in cat["courses"]}
    lps = {p["uid"]: p for p in cat["learningPaths"]}
    mods = {m["uid"]: m for m in cat["modules"]}
    certs = {c["title"].split(": ", 1)[-1]: c["url"].split("?")[0] for c in cat.get("certifications", [])}

    plan = []
    for c in cfg:
        lc = courses.get(c["course"])
        if not lc:
            print(f"  {c['course']}: not in the Learn catalog, skipped"); continue
        paths = [lps[s["uid"]] for s in lc.get("study_guide", []) if s.get("type") == "learningPath" and s["uid"] in lps]
        plan.append((c, lc, [(p, [mods[m] for m in p.get("modules", []) if m in mods]) for p in paths]))

    needed = {m["uid"]: m for _, _, paths in plan for _, ms in paths for m in ms}
    with ThreadPoolExecutor(WORKERS) as ex:
        units = dict(ex.map(scan_module, needed.values()))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    prev_units, prev_meta = previous_units(old)
    for vid, meta in prev_meta.items():
        cache.setdefault(vid, meta)
    failed = [u for u, x in units.items() if x is None]
    print(f"{len(needed)} modules: {len(needed) - len(failed)} read, {len(failed)} couldn't be read; "
          f"failed requests: {dict(errors) or 'none'}")
    # mostly unreadable: Learn is blocking or down, so try again next run instead of marking this week as done
    if len(failed) > (0.5 if old else 0.1) * len(units):
        sys.exit("Too many modules couldn't be read; keeping the current learn.json")
    for u in failed:   # as in the last build (a module missing there had no videos)
        units[u] = prev_units.get(needed[u]["title"], [])
    want = {v for us in units.values() if us for _, _, vs in us for v in vs}
    with ThreadPoolExecutor(WORKERS) as ex:
        for vid, meta in ex.map(video_meta, [v for v in want if v not in cache]):
            if meta:
                cache[vid] = meta
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache))

    last = {c["id"]: c["sections"] for c in old.get("courses", [])}
    modules, mod_ix, videos, texts, seen, out = [], {}, [], [], set(), []
    for c, lc, paths in plan:
        code = c["course"].split("T")[0]
        sections, nv = [], 0
        for p, ms in paths:
            for m in ms:
                steps = []
                if m["uid"] not in mod_ix:
                    mod_ix[m["uid"]] = len(modules); modules.append(m["title"])
                for title, url, vs in units.get(m["uid"]) or []:
                    vs = [v for v in vs if v in cache]
                    if not vs:   # a unit without a video: a link to it on Learn
                        uid = "lu-" + short(url, UNIT_BASE)
                        if uid not in seen:
                            seen.add(uid); texts.append([short(url, UNIT_BASE), title, mod_ix[m["uid"]]])
                        steps.append({"k": "u", "id": uid})
                    for k, vid in enumerate(vs):
                        sid = "ml-" + vid
                        if sid not in seen:
                            seen.add(sid)
                            meta = cache[vid]
                            media = f"{MEDIA_BASE}public-{vid}/"
                            videos.append([sid, title + (f" ({k + 1})" if k else ""), meta["dur"], mod_ix[m["uid"]],
                                           short(url, UNIT_BASE), short(meta["mp4"], media), short(meta["cc"], media)])
                        steps.append({"k": "v", "id": sid})
                if steps:
                    sections.append({"title": m["title"], "path": p["title"], "url": m["url"].split("?")[0], "steps": steps})
                    nv += sum(st["k"] == "v" for st in steps)
        # the exam playlist comes from fetch.py; if YouTube blocked it this time, keep the steps from the last build
        ids = exam_ids(c.get("exam")) or [st["id"] for sec in last.get("learn-" + code.lower(), [])
                                           if sec.get("path") == "Exam prep" for st in sec["steps"] if "note" not in st]
        prep = [{"k": "v", "id": i} for i in ids] + ([{"k": "v", "id": c["cram"], "note": "A whiteboard run through the whole exam."}] if c.get("cram") else [])
        if prep:
            sections.append({"title": f"Exam prep: {code}", "path": "Exam prep", "steps": prep})
        if not any(sec["path"] != "Exam prep" for sec in sections):
            print(f"  {c['course']}: no units, skipped"); continue
        out.append({"id": "learn-" + code.lower(), "ml": 1, "code": code, "cert": c["cert"],
                    "title": f"{code}: {lc['title']}", "level": c["level"], "blurb": c["blurb"],
                    "topic": "Azure certifications", "by": "Microsoft Learn", "hubs": c.get("hubs", []),
                    "url": lc["url"].split("?")[0], "certUrl": certs.get(c["cert"], ""), "guide": GUIDE + code.lower(),
                    "sections": sections})
        print(f"{code:7} {len(paths)} paths, {len(sections) - bool(prep)} modules, {nv} videos, "
              f"{sum(st['k'] == 'u' for sec in sections for st in sec['steps'])} other units, "
              f"{sum(cache[s['id'][3:]]['dur'] for sec in sections for s in sec['steps'] if s['id'].startswith('ml-')) / 3600:.1f} h")

    if old and "--force" not in sys.argv:
        if len(videos) < 0.9 * len(old["videos"]) or len(out) < len(old["courses"]) - 1:
            sys.exit(f"Only {len(out)} courses and {len(videos)} videos (now {len(old['courses'])} and {len(old['videos'])}); "
                     "Learn may be failing, keeping the current learn.json. Run with --force to accept it.")
    (ROOT / "learn.json").write_text(json.dumps({"built": datetime.date.today().isoformat(), "modules": modules, "videos": videos,
                                                "units": texts, "courses": out},
                                                ensure_ascii=False, separators=(",", ":")))
    print(f"learn.json: {len(out)} courses, {len(videos)} videos, {len(texts)} other units")


if __name__ == "__main__":
    main()
