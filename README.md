# Nerdvana

~50,000 nerdy videos from 185 tech YouTube channels and ~10,000 of the best articles from 150 tech blogs — programming, AI and agents, cloud and Azure, hardware, security, science and engineering — in one fast, searchable page. Plus a **TV mode** for laid-back watching.

**Live:** https://geenccmustafa.github.io/nerdvana/

Inspired by Andrej Karpathy's [TristanTube](https://karpathy.ai/tristan-tube/).

## Features

**Find something to watch**
- **Sidebar**: Home, Top picks, New this week, Code craft, Discovered, Learning paths, I have X minutes, the Focus sections (AI agents, LangChain, Azure, Azure certifications), Watch later and History, plus every channel (with its avatar) grouped by tier: Essential, Great, Worth a look
- **Focus sections**: **AI agents** (`#agents`), **LangChain** (`#langchain`) and **Azure** (`#azure`) each gather everything on their subject in one place: their courses on top, then every matching video (or article) from the tech channels and blogs, the channels that are all about it (LangChain, CrewAI, LlamaIndex, Arize; Microsoft Azure, Azure Developers, Adam Marczak) and what their own keyword searches find. Chips narrow a section down, with counts:
  - AI agents: Basics, Patterns, Frameworks, Multi-agent, Tools & MCP, RAG & memory, Chatbots & voice, Evals & production, No-code, Coding agents
  - LangChain: LangGraph, LangChain, LangSmith & evals, Agents, Multi-agent, RAG & memory, Deep agents, Deploy, JavaScript
  - Azure: Basics, Certifications, AI & agents, Compute & apps, Data & storage, Networking, Identity & security, DevOps & IaC, Architecture & cost

  A chip has its own link, e.g. `#agents&f=mcp`, and a section's videos play in TV mode. The sections are defined in `HUBS` in `index.html`, and a course joins one with `"hubs"` in `playlist_paths.json`
- **Search titles and transcripts**: matches in what is *said* in a video show up with a timestamp and jump straight to that moment (Essential channels)
- **Learning paths**: 15 hand-picked courses that mix videos and articles, in sections, with a note on why each step is there and your progress. Beginner: How a computer works, How the internet works, Python, Git, Linux, Web development, Docker to Kubernetes, Security. Intermediate: Neural networks to LLMs, AI agents (from LLM calls and tool calling to MCP, frameworks, multi-agent orchestration, evals and agents on Azure), Databases and SQL, System design. Advanced: Distributed systems, Performance. Plus Engineering career. Step through them from the watch page with *Next step*.
- **Azure certifications** (`#certs`): Microsoft Learn's official course for 16 certifications (AZ-900, AI-901, DP-900, AZ-104, AI-103, AI-200, AI-300, AZ-700, DP-300, DP-420, DP-800, SC-500, AZ-305, AZ-400, AI-500, AB-100), grouped by Fundamentals, Associate and Expert. Each course follows Learn path by path and module by module with every unit in order: 935 unit videos play in Nerdvana (hosted by Microsoft, with English captions), and the other 1,881 units (reading, exercises, knowledge checks) open on Learn. *Learn ↗* beside a video opens its unit on Learn too, and each module links to its Learn page, so anyone signed in to Learn with a Microsoft account gets their progress tracked there. Each course also links to its certification page (exam and practice assessment) and the exam's study guide, and ends with an exam-prep section: Microsoft Learn's exam-prep playlist and John Savill's study cram where there is one. The courses also show up in the Azure and AI agents sections
- **Courses by creators**: complete YouTube playlists used as learning paths, in the creator's own order, with the same progress tracking and *Next step*: 131 of them, grouped by topic. AI agents (25): IBM's agent, MCP and RAG explainers, Stanford's CS329Z Engineering AI Agents, CS329A Self-Improving AI Agents and CS193T Thinking with AI, UC Berkeley's LLM Agents and Agentic AI MOOCs, Microsoft's Python + AI and Python + Agents, Shaw Talebi, Alejandro AO, Sam Witteveen, Adam Lucek, Krish Naik, no-code agents with n8n and talks on reliable agents in production. LangChain (7): RAG from scratch, LangChain 1.0 and deep agents, LangSmith, LangGraph. Azure (12): Azure for beginners, AZ-900, AI-900, John Savill's exam crams and AZ-305, AI agents on Azure, production agents on Microsoft Foundry, RAG on Azure AI Search and MCP servers on Azure. Stanford Online (28 more): CME295 Transformers and LLMs, CS336 Language Modeling from Scratch, CS25 Transformers United, CS224N, CS229 with Andrew Ng, CS230, CS231N, CS221, deep generative models, diffusion, reinforcement learning, probability, linear algebra and convex optimization, statistical learning with Python, parallel computing, data compression, iOS with SwiftUI, and robotics and autonomy. And Karpathy's Neural Networks: Zero to Hero, 3Blue1Brown's linear algebra and calculus, StatQuest, Ben Eater's breadboard computers, KodeKloud's Docker and Kubernetes, Bro Code's language courses, Kevin Powell's CSS, Telusko, Data with Baraa and more. A channel's page links to its courses. Add one by putting its playlist id in `playlist_paths.json` The paths stay current: once a week, videos that are four or more years old are swapped for recent ones on the same topic
- **I have X minutes**: pick 5–60 minutes and get unwatched videos that fit, ready to play back to back
- **New this week**: the latest uploads from all channels
- **Code craft**: videos (and articles) about writing and reading good code: code reviews, refactoring, clean code, testing, type hints, debugging, internals and the standard library, picked from programming channels by title. It also has everything the Code craft keyword searches find. Link: `#craft`
- **Keyword search**: besides the fixed channels and blogs, every night the queries in `discover.json` (Python's standard library, popular libraries, code review, reading code…, plus about 120 for the Focus sections: AI agents, agentic RAG, multi-agent systems, MCP, tool calling, evals, CrewAI, AutoGen, LangGraph, LangSmith, AZ-104, AI-103, Azure OpenAI, Microsoft Foundry, Semantic Kernel…) are searched on YouTube and Hacker News, and the best matches from any channel or site are added under a fourth tier, **Discovered**. They have their own **Discovered** view (`#disc`) and also show up in Code craft or in their Focus section, in search and in "More like this". Their channels aren't listed in the sidebar and they stay out of the Home mix
- **Mix** sort (default): a channel-balanced shuffle, so no single channel floods the feed

**Watch**
- **Watch page** with **More like this** (videos on the same topic from other channels) and an Up next list with autoplay
- **Continue watching**: picks up where you left off
- **Watch later** list, **Surprise me** button, and **TV mode** (full screen, auto-advancing; `→` next, `←` previous, `C` subtitles, `Esc` exit)
- **Shareable links** for every video (optionally at a timestamp), channel, path and view, e.g. `#v=VIDEO_ID&t=90`, `#c=veritasium`, `#path=kubernetes`

**Read** (the Articles tab)
- Articles from 150 personal and engineering blogs (Paul Graham, Dan Luu, Julia Evans, Simon Willison, Cloudflare, Netflix…), each source's **most-upvoted posts on Hacker News plus its newest**
- Every card shows a short description, reading time, HN points and a link to the HN discussion; the article itself opens on its own site
- **More like this**, **Read later**, **I have X minutes** (by reading time), **New this week**, and search across titles and descriptions
- Videos and articles are linked: the watch page shows **Read more about this**, and an article's "More like this" page shows **Watch on this topic**

**Follow along**: [`feed.xml`](https://geenccmustafa.github.io/nerdvana/feed.xml) is an Atom feed of the week's 10 most-viewed new videos and 10 most-upvoted new articles, rebuilt every night. Add it to any feed reader.

Watched, read, saved and in-progress items are stored only in your browser. Light and dark themes.

## How it works

| File | What it is |
|---|---|
| `channels.json` | The channel list: handle, tier, topic and optionally `pin`. This is the part to edit. |
| `fetch.py` | Pulls every channel's uploads with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (no API key) and writes `videos.json`. |
| `enrich.py` | Embeds every title with [bge-small](https://huggingface.co/BAAI/bge-small-en-v1.5) and writes `similar.json` (More like this); with articles it also writes `similar_articles.json`, `links.json` (videos ↔ articles on the same topic) and `courses.json` (the learning paths, resolved from `curated_paths.json`). |
| `transcripts.py` | Downloads English subtitles for the Essential channels and writes `search.json`, a compact word index with timestamps. |
| `discover.json` | Keyword search queries for videos and articles from any channel or site, in a `python` group (searched as "python …" and filtered to Python content), a `general` group, and one group per Focus section under `hubs` (`agents`, `langchain`, `azure`), each with the topic its results get and its own thresholds (`hub_min_views`, `hub_per_query`). |
| `discover.py` | Runs those queries on YouTube (yt-dlp search) and Hacker News (Algolia), keeps well-viewed or well-upvoted results whose titles match, records which groups found each one (so `fetch.py` and `articles.py` can list them under `craft` or `hubs`), and writes `raw/_discovered.json` and `raw_articles/discovered.json`. `fetch.py` and `articles.py` merge these in as the Discovered tier. |
| `sources.json` | The blog list: name, URL, tier and topic (optionally the feed URL). |
| `articles.py` | Collects each blog's posts from [Hacker News](https://hn.algolia.com/api) (all-time popular, with points) and its RSS/Atom feed (newest), fetches each new page once for its description, cover image and length, and writes `articles.json`. |
| `learn_courses.json` | The Microsoft Learn certification courses: the Learn course number, level, certification, blurb, Focus sections, and optionally `"exam"` (an exam-prep playlist on YouTube, fetched by `fetch.py`) and `"cram"` (a study-cram video). |
| `learn.py` | Builds `learn.json` from those: the Learn catalog API gives each course's learning paths and modules, the module and unit pages give each unit (and its video, if it has one), and Learn's video API its length, MP4 and captions (cached in `.cache/learn_videos.json`). Runs once a week from the nightly refresh, reading Learn a few pages at a time; a module it can't read keeps what the last build had, and if most can't be read or the new file lost more than 10% of its videos, the current `learn.json` stays (`--force` rebuilds now and accepts it). |
| `playlist_paths.json` | Learning paths that are whole YouTube playlists: an id, title, level, topic, blurb and one or more playlist ids (each becomes a section), and optionally `"hubs"`: the Focus sections it is shown in (`["agents", "azure"]`). `"order": "number"` sorts a shuffled playlist by the lesson numbers in its titles (`#12`, `Part 12`, `Episode 12`…), `"reverse"` flips one that runs newest first, and `"skip"` leaves out videos. `fetch.py` fetches the playlists and keeps all their videos, past the per-channel limits; `enrich.py` adds them to `courses.json`. Members-only videos and Shorts are left out. |
| `curated_paths.json` | The curated paths: sections and hand-picked steps (a video or article id, its title and a one-line note). If a step's item disappears, the nightly job swaps in the closest match. Once a week the paths are also checked for age: a video step that is four or more years old is replaced by a recent video on the same topic from an Essential or Great channel, when one matches well enough (a step with `"keep": true` is never replaced; articles are left alone). Newer, better-fitting items are listed in `path_candidates.json`; once a month these are reviewed and proposed as a pull request. |
| `feed.py` | Writes `feed.xml`, the weekly top-20 Atom feed. |
| `index.html` | The whole site: one file, no build step, no dependencies. |

### Balancing rules

So that prolific channels (daily uploaders, conference archives) can't drown out the rest:

- only channels with **≥ 250K subscribers**, at most **100** of them (picked by tier, then subscribers)
- channels marked `"pin": true` in `channels.json` skip both limits and don't use up one of the 100 slots (used for smaller but valuable Python and conference channels)
- each channel keeps at most its **300 most-viewed + 100 newest** videos (plus every video of a playlist in `playlist_paths.json`)
- Shorts (≤ 60 s), members-only videos and upcoming premieres are dropped
- articles: at most **150** sources, each keeping its **100 most-upvoted + 30 newest** posts (the keyword-search source, Discovered, comes on top of the 150)

Only an article's title, a short description (the author's own summary or opening line) and its cover image link are stored. The full text stays on the author's site.

## Update the data

A GitHub Action ([`refresh.yml`](.github/workflows/refresh.yml)) runs nightly at 03:17 UTC: it re-fetches every channel and every blog (new posts and fresh HN points), rebuilds the similarity files, and commits the result, which redeploys the site. If a dataset comes back much smaller than the live one (e.g. YouTube blocks the runner), it keeps the live version of that file. You can also start it by hand from the Actions tab.

Transcripts are refreshed every morning on a local machine rather than in an Action, because YouTube blocks subtitle downloads from CI runners: `python3 transcripts.py` fetches subtitles for any new videos from the Essential channels and rebuilds `search.json`, which is then committed. The transcripts themselves (~40 MB) are never committed; only the compact word index is published.

Locally you need Python 3 and [uv](https://docs.astral.sh/uv/):

```bash
python3 discover.py        # keyword search on YouTube and Hacker News (run before fetch.py and articles.py)
python3 fetch.py           # fetch new channels, rebuild videos.json
python3 fetch.py --force   # re-fetch every channel (picks up new uploads)
python3 learn.py --force   # Microsoft Learn certification courses -> learn.json (after fetch.py)
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
