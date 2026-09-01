# TeraBox — cookie-less resolver mode

This bot's TeraBox module now does **not** read, store, or require a TeraBox cookie/session. It sends a public share URL to a resolver API, receives a temporary direct URL, and downloads that URL.

## Configure resolvers

Set `BIMBO_TERABOX_RESOLVERS` in your hosting panel as a comma-separated list of endpoints. Each endpoint must accept:

```text
GET <endpoint>?url=<public-terabox-share-url>
```

and return JSON with `success: true`, a filename/size, and one of:

- `qualities` — map/list of quality → URL (the bot selects the numerically highest quality)
- `direct_download_url`
- `download_url`
- `download_link`
- `media_url`

Example:

```env
BIMBO_TERABOX_RESOLVERS=https://your-resolver.example/download,https://your-backup-resolver.example/download
```

If the variable is absent, the bot tries the legacy public default:

```text
https://terabox-api.mn-bots.workers.dev/download
```

That public service can hit quotas or go offline, so do **not** rely on it alone. A resolver outage is not a bot, API ID, or Telegram issue.

## Quality behaviour

For `qualities` such as `360p`, `720p`, and `1080p`, the largest numeric quality is selected automatically. If no quality map exists, the resolver's direct/original URL is used.

## Limits

- Only public, valid TeraBox shares can be resolved.
- Direct URLs are normally short-lived; the bot resolves again after the user taps a download button.
- HLS (`.m3u8`) URLs are downloaded via `yt-dlp`; normal direct files use streaming `requests` download.
- Third-party resolver availability, rate limits, and their terms control whether a particular share works.
