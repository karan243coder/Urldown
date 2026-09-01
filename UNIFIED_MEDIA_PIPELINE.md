# Unified Media Pipeline — xHamster + Eporner

## Problem found in the full repository review

The repository had three unrelated queue/tracker implementations plus private
xHamster/Eporner bulk workers. Profile buttons used `asyncio.create_task()` and
created a new Telegram message for every video. The core callback semaphore was
held across download **and** upload, while advanced engines bypassed it. As a
result:

- single/page/full-profile jobs did not share one progress dashboard;
- advanced jobs could bypass the advertised concurrency limit;
- queue/pending counts had no single source of truth;
- Eporner Download Page imported its downloader only inside an exception path;
- Eporner Download Page selected 8 items despite the UI being a 10-video page;
- same-title videos could be incorrectly dropped by filename de-duplication.

## New architecture

- `plugins/media_pipeline.py`
  - global fair round-robin/FIFO stage runtime;
  - exactly 2 global download slots;
  - exactly 2 global upload slots;
  - per-site xHamster safety limit (default 1, inside the global max 2);
  - waiting/active/global/per-user counters;
  - bulk remainder counters for entire profiles/channels.
- `plugins/adult_media_pipeline.py`
  - one shared xHamster/Eporner download → split → upload implementation;
  - one task/card moves through waiting, download, splitting and upload stages;
  - isolated task directories and cleanup;
  - xHamster stall watchdog and safe split-size validation;
  - user upload and optional log upload stay inside upload-stage limits.
- `helper_funcs/display_progress.py`
  - one canonical message per user;
  - premium compact mobile-first UI;
  - max four detailed active cards (2 DL + 2 UL);
  - waiting jobs summarized instead of overflowing Telegram's 4096-char limit;
  - global queue + personal queue + bulk remaining footer;
  - CPU/RAM/disk/network health and warnings.

## Covered paths

- direct xHamster and Eporner links handled by the main quality-button flow;
- xHamster profile/channel single-video quality selection;
- Eporner profile/channel single-video quality selection;
- xHamster Download Page (10);
- Eporner Download Page (10);
- xHamster entire profile/channel queue;
- Eporner entire profile/channel queue;
- generic yt-dlp quality-button downloads use the same global download/upload
  stages.

Collection/search/listing messages still exist before a queue is created. Once
media processing starts, every item uses the same canonical BIMBO LIVE message.
A short completion/error notification may be sent, but no separate per-video
processing/progress message is created.

## Interactive priority mode

Single-video links and interactive media commands use priority `100`; page/all
and entire profile/channel items use bulk priority `0`.

- Already-active downloads are never killed or paused.
- When either of the two download slots becomes free, the waiting single video
  or command gets that slot before the next bulk item.
- A lightweight interactive barrier remains until its upload completes, so a
  1000-video profile cannot immediately take the freed slot back.
- After the interactive job finishes, fair bulk processing resumes
  automatically.

Integrated commands use the same BIMBO LIVE message and two upload slots:
`/ss`, `/sample`, `/trim`, `/compress`, `/wm`, `/mp3`, `/zip`, `/unzip`, and `/rename`.
The dashboard shows Telegram download, FFmpeg processing detail, and upload.

## Recommended Koyeb settings

```text
BIMBO_MAX_CONCURRENT_DOWNLOADS=2
BIMBO_MAX_CONCURRENT_UPLOADS=2
XHAMSTER_MAX_CONCURRENT_DOWNLOADS=1
XHAMSTER_CONCURRENT_FRAGMENTS=1
XHAMSTER_STALL_TIMEOUT=600
```

The first two are global across users. Fair scheduling is round-robin by user
and FIFO inside each user's queue. The xHamster-specific limit remains 1 because
two simultaneous large xHamster streams previously froze on the shared Koyeb
IP; the second global download slot remains available to Eporner/generic media.

## Verification

- all repository Python files compile;
- `git diff --check` passes;
- 15 unit tests pass (fair FIFO, interactive next-slot priority/barrier,
  stage/site limits, backlog counters, one-message dashboard, mobile footer,
  xHamster extraction/cookies/429 handling);
- changed modules imported successfully in a Pyrogram/Motor test environment;
- mocked end-to-end Eporner pipeline completed download → dashboard updates →
  Telegram document upload → final cleanup;
- mocked `/ss` command completed priority Telegram download → processing →
  upload through one canonical dashboard;
- live xHamster extraction returned 144p/240p/480p/720p;
- live Eporner profile listing returned 53 items and a next page.
