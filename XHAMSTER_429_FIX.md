# xHamster HTTP 429 Fix (2026-07-28)

## Root cause found

The old engine always loaded a large browser cookie dump, flattened it into a
single name/value dictionary, and sent that header to every mirror. Cookie
`domain`, `path`, `secure`, and expiry rules were lost. On a public test video,
this changed a complete first-party page into a limited page, so the engine hit
several mirrors for one Telegram request. Under a shared Koyeb egress IP, that
request amplification makes HTTP 429 much more likely.

The HLS downloader also inherited the generic fragment concurrency (up to 10),
and an immediate yt-dlp fallback retried the same site after HTTP 429. That can
extend a server-side cooldown instead of recovering.

## Changes

- Public xHamster pages are fetched anonymously first.
- A private cookie file is tried once only when anonymous access is limited or
  rejected, and Netscape domain/path/secure/expiry scope is preserved.
- Removed hard-coded browser cookies and ignored future `cookies*.txt` files.
- Added a stable browser identity with `curl-cffi` TLS impersonation.
- Added deterministic mirror fallback and per-host HTTP 429 cooldown.
- Added a minimum interval between metadata requests.
- Disabled third-party public CORS proxies by default and never forwards
  cookies to them.
- Reduced xHamster HLS concurrency to 1 by default.
- Uses yt-dlp native HLS retry handling with exponential HTTP/fragment backoff.
- Does not immediately run the page extractor again after an HTTP 429.
- Fixed xHamster MP3 buttons: 128K/320K now use the already-extracted signed
  HLS URL instead of accidentally sending the page back through generic yt-dlp.
- Updated yt-dlp to `>=2026.7.4` and curl-cffi to `>=0.15.0`.

## Recommended Koyeb variables

```text
XHAMSTER_CONCURRENT_FRAGMENTS=1
XH_MIN_REQUEST_INTERVAL=1.25
XH_429_COOLDOWN=120
XHAMSTER_USE_COOKIES=false
```

If the Koyeb shared egress IP remains rate-limited after the cooldown, configure
an HTTP(S) proxy that you own or are authorised to use:

```text
BIMBO_HTTP_PROXY=http://user:password@host:port
```

Do not enable random public proxy rotation. `XH_ALLOW_PUBLIC_PROXIES` is false
by default.

## Cookies

Public videos should not need cookies. For a login/age-gated video only:

1. Export only current xHamster cookies to a private `cookies.txt`.
2. Do not include Google, ad-network, email, or unrelated site cookies.
3. Keep the file outside Git and set `XHAMSTER_USE_COOKIES=true`.

The old repository contained browser cookies in Git. Deleting the working-tree
files does not remove them from Git history. Revoke/rotate those sessions first,
then purge the files from repository history if the repo remains public.

## Verification performed

The supplied video path was tested without downloading the video content:

- page request: HTTP 200
- custom extraction: success on the first hostname
- qualities: 144p, 240p, 480p, 720p
- 480p media playlist: HTTP 200
- first segment HEAD request: HTTP 200
- yt-dlp 2026.07.04 simulation: exit code 0, no HTTP 429
- unit tests: 6 passed
- repository Python AST/compile checks: passed

Run tests locally with:

```bash
python -m unittest discover -s tests -v
```
