# Nerdvana

~30,000 nerdy videos from 100 popular tech YouTube channels and ~10,000 of the best articles from 122 tech blogs — programming, AI, hardware, security, science and engineering — in one fast, searchable page. Plus a **TV mode** for laid-back watching.

**Live:** https://geenccmustafa.github.io/nerdvana/

Inspired by Andrej Karpathy's [TristanTube](https://karpathy.ai/tristan-tube/).

## Features

**Find something to watch**
- **Sidebar**: Home, Top picks, New this week, Learning paths, I have X minutes, Watch later and History, plus every channel (with its avatar) grouped by tier: Essential, Great, Worth a look
- **Search titles and transcripts**: matches in what is *said* in a video show up with a timestamp and jump straight to that moment (Essential channels)
- **Curated paths**: hand-picked courses that mix videos and articles, in sections, with a note on why each step is there and your progress (Neural networks to LLMs, Docker to Kubernetes, How the internet works). Step through them from the watch page with *Next step*
- **Learning paths**: shorter, automatically picked playlists for the topics that don't have a curated path yet
- **I have X minutes**: pick 5–60 minutes and get unwatched videos that fit, ready to play back to back
- **New this week**: the latest uploads from all channels
- **Mix** sort (default): a channel-balanced shuffle, so no single channel floods the feed

**Watch**
- **Watch page** with **More like this** (videos on the same topic from other channels) and an Up next list with autoplay
- **Continue watching**: picks up where you left off
- **Watch later** list, **Surprise me** button, and **TV mode** (full screen, auto-advancing; `→` next, `←` previous, `C` subtitles, `Esc` exit)
- **Shareable links** for every video (optionally at a timestamp), channel, path and view, e.g. `#v=VIDEO_ID&t=90`, `#c=veritasium`, `#path=kubernetes`

**Read** (the Articles tab)
- Articles from 122 personal and engineering blogs (Paul Graham, Dan Luu, Julia Evans, Simon Willison, Cloudflare, Netflix…), each source's **most-upvoted posts on Hacker News plus its newest**
- Every card shows a short description, reading time, HN points and a link to the HN discussion; the article itself opens on its own site
- **Reading paths**: ordered reading lists (distributed systems, how LLMs work, performance, security, the web, engineering career)
- **More like this**, **Read later**, **I have X minutes** (by reading time), **New this week**, and search across titles and descriptions
- Videos and articles are linked: the watch page shows **Read more about this**, and an article's "More like this" page shows **Watch on this topic**

**Follow along**: [`feed.xml`](https://geenccmustafa.github.io/nerdvana/feed.xml) is an Atom feed of the week's 10 most-viewed new videos and 10 most-upvoted new articles, rebuilt every night. Add it to any feed reader.

Watched, read, saved and in-progress items are stored only in your browser. Light and dark themes.

## How it works

| File | What it is |
|---|---|
| `channels.json` | The channel list: handle, tier and topic. This is the part to edit. |
| `fetch.py` | Pulls every channel's uploads with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (no API key) and writes `videos.json`. |
| `enrich.py` | Embeds every title with [bge-small](https://huggingface.co/BAAI/bge-small-en-v1.5) and writes `similar.json` (More like this) and `paths.json` (learning paths from `paths_def.json`); with articles it also writes `similar_articles.json` and `links.json` (videos ↔ articles on the same topic). |
| `transcripts.py` | Downloads English subtitles for the Essential channels and writes `search.json`, a compact word index with timestamps. |
| `sources.json` | The blog list: name, URL, tier and topic (optionally the feed URL). |
| `articles.py` | Collects each blog's posts from [Hacker News](https://hn.algolia.com/api) (all-time popular, with points) and its RSS/Atom feed (newest), fetches each new page once for its description, cover image and length, and writes `articles.json`. |
| `curated_paths.json` | The curated paths: sections and hand-picked steps (a video or article id, its title and a one-line note). If a step's item disappears, the nightly job swaps in the closest match and newer, better-fitting items are listed in `path_candidates.json` for review. |
| `reading_paths_def.json` | The reading paths: a title and steps per path (a search phrase, or `title:` to pin a specific post). |
| `feed.py` | Writes `feed.xml`, the weekly top-20 Atom feed. |
| `index.html` | The whole site: one file, no build step, no dependencies. |

### Balancing rules

So that prolific channels (daily uploaders, conference archives) can't drown out the rest:

- only channels with **≥ 250K subscribers**, at most **100** of them (picked by tier, then subscribers)
- each channel keeps at most its **300 most-viewed + 100 newest** videos
- Shorts (≤ 60 s) are dropped
- articles: at most **150** sources, each keeping its **100 most-upvoted + 30 newest** posts

Only an article's title, a short description (the author's own summary or opening line) and its cover image link are stored. The full text stays on the author's site.

## Update the data

A GitHub Action ([`refresh.yml`](.github/workflows/refresh.yml)) runs nightly at 03:17 UTC: it re-fetches every channel and every blog (new posts and fresh HN points), rebuilds the similarity files, and commits the result, which redeploys the site. If a dataset comes back much smaller than the live one (e.g. YouTube blocks the runner), it keeps the live version of that file. You can also start it by hand from the Actions tab.

Transcripts are refreshed every morning on a local machine rather than in an Action, because YouTube blocks subtitle downloads from CI runners: `python3 transcripts.py` fetches subtitles for any new videos from the Essential channels and rebuilds `search.json`, which is then committed. The transcripts themselves (~40 MB) are never committed; only the compact word index is published.

Locally you need Python 3 and [uv](https://docs.astral.sh/uv/):

```bash
python3 fetch.py           # fetch new channels, rebuild videos.json
python3 fetch.py --force   # re-fetch every channel (picks up new uploads)
uv run --python 3.12 --with fastembed --with numpy python enrich.py   # similarity, paths, video/article links
python3 feed.py            # feed.xml
python3 transcripts.py     # download missing transcripts, rebuild search.json
python3 articles.py        # refresh every blog, fetch new pages, rebuild articles.json
```

Run locally:

```bash
python3 -m http.server 8000   # then open http://localhost:8000
```

## Suggest a channel or blog

Know a great channel or blog that's missing? Suggest a [channel](https://github.com/GeenccMustafa/nerdvana/issues/new?template=suggest-channel.yml) or a [blog](https://github.com/GeenccMustafa/nerdvana/issues/new?template=suggest-blog.yml).

Tiers are one person's opinion. Fork it and make your own.
