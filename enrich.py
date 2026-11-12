"""Build similar.json ("More like this") and paths.json (learning paths) from videos.json.

Run after fetch.py, with Python 3.10-3.13 (onnxruntime has no wheels for newer versions yet):
  uv run --python 3.12 --with fastembed --with numpy enrich.py

Video titles are embedded with BAAI/bge-small-en-v1.5. Embeddings are cached in .cache/ by video id,
so re-runs only embed new videos.

similar.json  {"n": video count, "first": first video id, "sim": [[video index, ...] x 8 per video]}
              aligned with the order of videos.json; the page checks n/first before using it
paths.json    [{id, title, blurb, videos: [video id, ...]}] resolved from paths_def.json

If articles.json exists, articles (title + description) are embedded the same way, for links, courses
and reading paths. "More like this" for articles uses a larger model (ART_MODEL) on title + description +
the start of the text (kept in .cache/pages.json by articles.py), and only lists matches above ART_MIN_SIM:
similar_articles.json  {"n", "first", "sim": [[article index, ...] x up to 8]}  aligned with articles.json
courses.json           curated paths from curated_paths.json: [{id, title, level, blurb, sections: [{title, steps: [{k, id, note}]}]}]
path_candidates.json   newer items that may fit a curated step better (for the monthly review)
reading_paths.json     [{id, title, blurb, articles: [article id, ...]}] resolved from reading_paths_def.json
links.json             videos <-> articles on the same topic:
                       {"vn", "vfirst", "an", "afirst", "v2a": [[article index, ...]], "a2v": [[video index, ...]]}
"""
import hashlib, json, math, time
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "emb.npz"
MODEL = "BAAI/bge-small-en-v1.5"
SIMILAR = 8
MAX_SAME_CHANNEL = 3
LINK_THRESHOLD = 0.8
ART_MODEL = "BAAI/bge-base-en-v1.5"
ART_TEXT_LEN = 1800     # characters of article text embedded (the model reads ~512 tokens)
ART_MIN_SIM = 0.66      # below this, bge-base matches on this data are mostly unrelated
ART_REEMBED_PER_RUN = 1500  # articles whose text changed (body text arrived) re-embedded per run; the rest next run


def embed(texts, model, cache_file, by_text=False, max_changed=None):
    """texts: {id: text}. Returns normalized vectors in the order of texts; caches by id
    (by_text: by id + text hash, so an item is re-embedded when its text changes).
    max_changed: at most this many items that already have a vector for an older text are
    re-embedded; the others keep their old vector until a later run (keeps each run short)."""
    cached = {}
    if cache_file.exists():
        z = np.load(cache_file)
        cached = dict(zip(z["ids"].tolist(), z["vecs"]))
    if by_text:
        texts = {f"{i}:{hashlib.sha1(t.encode()).hexdigest()[:10]}": t for i, t in texts.items()}
    todo = [i for i in texts if i not in cached]
    if by_text and max_changed is not None:
        old = {k.split(":")[0]: k for k in cached}
        changed = [k for k in todo if k.split(":")[0] in old]
        if len(changed) > max_changed:
            later = set(changed[max_changed:])
            print(f"re-embedding {max_changed} changed texts now, {len(later)} on later runs", flush=True)
            texts = {(old[k.split(":")[0]] if k in later else k): t for k, t in texts.items()}
            todo = [k for k in todo if k not in later]
    if todo:
        print(f"embedding {len(todo)} new texts…", flush=True)
        for i, vec in zip(todo, model.embed([texts[i] for i in todo], batch_size=64 if by_text else 256)):
            cached[i] = vec.astype(np.float32)
    cache_file.parent.mkdir(exist_ok=True)
    ids = list(texts)
    E = np.stack([cached[i] for i in ids])
    np.savez(cache_file, ids=np.array(ids), vecs=E)
    return E / np.linalg.norm(E, axis=1, keepdims=True)


def embed_titles(videos, channels, model):
    return embed({v[0]: f"{v[1]} ({channels[v[2]]['topic']})" for v in videos}, model, CACHE)


def cross_links(A, B, k, threshold, allowed=None):
    """For each row of A, up to k rows of B that are about the same thing (cosine >= threshold)."""
    out = []
    for start in range(0, len(A), 2048):
        S = A[start:start + 2048] @ B.T
        if allowed is not None:
            S[:, ~allowed] = -1
        top = np.argpartition(-S, k, axis=1)[:, :k]
        for r in range(S.shape[0]):
            cand = top[r][np.argsort(-S[r, top[r]])]
            out.append([int(j) for j in cand if S[r, j] >= threshold])
    return out


def article_texts(arts, cache_file):
    """Title, description and the start of the article text (when articles.py has fetched it)."""
    pages = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    out = {}
    for a in arts:
        body = (pages.get(a[6]) or {}).get("body") or ""
        out[a[0]] = f"{a[1]}. {a[7]} {body}"[:ART_TEXT_LEN]
    return out


def build_similar(E, videos, min_sim=None):
    n, ch = len(videos), np.array([v[2] for v in videos])
    titles = [v[1].lower() for v in videos]
    out = []
    for start in range(0, n, 2048):
        S = E[start:start + 2048] @ E.T
        top = np.argpartition(-S, 60, axis=1)[:, :60]
        for r in range(S.shape[0]):
            i = start + r
            cand = top[r][np.argsort(-S[r, top[r]])]
            picked, per = [], {}
            for j in cand:
                j = int(j)
                if min_sim is not None and S[r, j] < min_sim:
                    break   # sorted: nothing after this is close enough either
                if j == i or titles[j] == titles[i]:
                    continue
                if per.get(ch[j], 0) >= MAX_SAME_CHANNEL:
                    continue
                per[ch[j]] = per.get(ch[j], 0) + 1
                picked.append(j)
                if len(picked) == SIMILAR:
                    break
            out.append(picked)
    return {"n": n, "first": videos[0][0], "sim": out}


def resolve_paths(defs, E, rows, src_col, ok, boost, model, key):
    """Each step of each path: the best-matching row (by meaning, plus a popularity boost),
    never reusing a row and nudging away from sources already in the path."""
    out = []
    for p in defs:
        Q = np.stack(list(model.embed([f"Represent this sentence for searching relevant passages: {s.removeprefix('title:')}" for s in p["steps"]])))
        Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        used, per_src, picked = set(), {}, []
        for step, q in zip(p["steps"], Q):
            # "title:Some Title" pins a specific item (case-insensitive title prefix, most popular match)
            if step.startswith("title:"):
                t = step[6:].strip().lower()
                hits = sorted((j for j, r in enumerate(rows) if r[1].lower().startswith(t) and j not in used), key=lambda j: -rows[j][4])
                if hits:
                    j = hits[0]; used.add(j); per_src[rows[j][src_col]] = per_src.get(rows[j][src_col], 0) + 1
                    picked.append(j); continue
                print(f"  ! no item titled {step[6:]!r}, searching by meaning instead")
            score = E @ q + boost - np.array([0.04 * per_src.get(r[src_col], 0) for r in rows])
            score[~ok] = -9
            for j in np.argsort(-score)[:50]:
                j = int(j)
                if j not in used:
                    used.add(j); per_src[rows[j][src_col]] = per_src.get(rows[j][src_col], 0) + 1
                    picked.append(j); break
        out.append({"id": p["id"], "title": p["title"], "blurb": p["blurb"], key: [rows[j][0] for j in picked]})
        print(f"  path {p['title']}: " + " | ".join(rows[j][1][:40] for j in picked))
    return out


def build_paths(E, videos, channels, model):
    defs = json.loads((ROOT / "paths_def.json").read_text())
    ok = np.array([channels[v[2]]["t"] in ("S", "A") and v[4] >= 50_000 and 120 <= v[3] <= 10800 for v in videos])
    boost = np.array([0.025 * math.log10(max(v[4], 1)) for v in videos])
    return resolve_paths(defs, E, videos, 2, ok, boost, model, "videos")


def build_reading_paths(A, arts, srcs, model):
    """Reading paths from reading_paths_def.json: well-received posts from Essential/Great sources."""
    defs = json.loads((ROOT / "reading_paths_def.json").read_text())
    ok = np.array([srcs[a[2]]["t"] in ("S", "A") and a[4] >= 30 and (a[3] == 0 or 300 <= a[3] <= 15000) for a in arts])
    boost = np.array([0.025 * math.log10(max(a[4], 1)) for a in arts])
    return resolve_paths(defs, A, arts, 2, ok, boost, model, "articles")

def build_courses(E, videos, A, arts, model):
    """Curated paths (curated_paths.json): every step is pinned by hand. If a pinned item disappears
    from the data, it is replaced by the closest match of the same kind and marked ("swap").
    New items that fit a step clearly better than its current pick are written to
    path_candidates.json for the monthly review; they never change a path on their own."""
    defs = json.loads((ROOT / "curated_paths.json").read_text())
    pools = {"v": (E, videos, np.array([v[4] >= 20_000 for v in videos])),
             "a": (A, arts, np.array([a[4] >= 10 for a in arts]))}
    index = {k: {r[0]: i for i, r in enumerate(rows)} for k, (_, rows, _) in pools.items()}
    now, recent = time.time(), 60 * 86400
    out, candidates = [], []
    for p in defs:
        used = {k: set() for k in pools}
        texts = [f"Represent this sentence for searching relevant passages: {st['t']}. {st['note']}"
                 for sec in p["sections"] for st in sec["steps"]]
        Q = np.stack(list(model.embed(texts))); Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        qi, sections = 0, []
        for sec in p["sections"]:
            steps = []
            for st in sec["steps"]:
                k = "v" if "v" in st else "a"
                M, rows, ok = pools[k]
                score = M @ Q[qi]; qi += 1
                j = index[k].get(st[k])
                step = {"k": k, "note": st["note"]}
                if j is None or j in used[k]:
                    s2 = score.copy(); s2[~ok] = -9
                    for u in used[k]:
                        s2[u] = -9
                    j = int(np.argmax(s2))
                    step["swap"] = st["t"]
                    print(f"  ! {p['id']}: {st['t'][:50]!r} is gone, using {rows[j][1][:50]!r}")
                used[k].add(j); step["id"] = rows[j][0]; steps.append(step)
                # newer items that fit this step better than the current pick
                ts_col = 5
                for c in np.argsort(-score)[:20]:
                    c = int(c)
                    if c != j and ok[c] and rows[c][ts_col] and now - rows[c][ts_col] <= recent and score[c] >= score[j] + 0.02:
                        candidates.append({"path": p["id"], "step": st["t"], "current": rows[j][1], "kind": k,
                                           "candidate": rows[c][0], "title": rows[c][1], "gain": round(float(score[c] - score[j]), 3)})
            sections.append({"title": sec["title"], "steps": steps})
        out.append({"id": p["id"], "title": p["title"], "level": p["level"], "blurb": p["blurb"], "sections": sections})
    return out, candidates


if __name__ == "__main__":
    data = json.loads((ROOT / "videos.json").read_text())
    videos, channels = data["videos"], data["channels"]
    model = TextEmbedding(MODEL)
    E = embed_titles(videos, channels, model)
    sim = build_similar(E, videos)
    (ROOT / "similar.json").write_text(json.dumps(sim, separators=(",", ":")))
    print(f"similar.json: {len(sim['sim'])} videos, {(ROOT / 'similar.json').stat().st_size / 1e6:.1f} MB")
    paths = build_paths(E, videos, channels, model)
    (ROOT / "paths.json").write_text(json.dumps(paths, ensure_ascii=False, indent=1))
    print(f"paths.json: {len(paths)} paths")

    if (ROOT / "articles.json").exists():
        ad = json.loads((ROOT / "articles.json").read_text())
        arts, srcs = ad["articles"], ad["sources"]
        A = embed({a[0]: f"{a[1]}. {a[7]} ({srcs[a[2]]['topic']})" for a in arts}, model, ROOT / ".cache" / "emb_articles.npz")
        art_model = TextEmbedding(ART_MODEL)
        AS = embed(article_texts(arts, ROOT / ".cache" / "pages.json"), art_model,
                   ROOT / ".cache" / "emb_articles_base.npz", by_text=True, max_changed=ART_REEMBED_PER_RUN)
        sa = build_similar(AS, arts, ART_MIN_SIM)
        (ROOT / "similar_articles.json").write_text(json.dumps(sa, separators=(",", ":")))
        counts = [len(x) for x in sa["sim"]]
        print(f"similar_articles.json: {len(counts)} articles, {sum(counts) / len(counts):.1f} matches on average, "
              f"{counts.count(0)} with none")
        # only link to videos worth a detour: Essential/Great channels with some views
        good_v = np.array([channels[v[2]]["t"] in ("S", "A") and v[4] >= 20_000 and v[3] >= 120 for v in videos])
        links = {"vn": len(videos), "vfirst": videos[0][0], "an": len(arts), "afirst": arts[0][0],
                 "v2a": cross_links(E, A, 3, LINK_THRESHOLD), "a2v": cross_links(A, E, 4, LINK_THRESHOLD, good_v)}
        courses, cands = build_courses(E, videos, A, arts, model)
        (ROOT / "courses.json").write_text(json.dumps(courses, ensure_ascii=False, indent=1))
        (ROOT / "path_candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=1))
        print(f"courses.json: {len(courses)} curated paths, {len(cands)} candidate improvements")
        rp = build_reading_paths(A, arts, srcs, model)
        (ROOT / "reading_paths.json").write_text(json.dumps(rp, ensure_ascii=False, indent=1))
        print(f"reading_paths.json: {len(rp)} paths")
        (ROOT / "links.json").write_text(json.dumps(links, separators=(",", ":")))
        print(f"links.json: {sum(map(bool, links['v2a']))} videos with articles, "
              f"{sum(map(bool, links['a2v']))} articles with videos, {(ROOT / 'links.json').stat().st_size / 1e6:.1f} MB")
