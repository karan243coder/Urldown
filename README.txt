URLBIM3 TERABOX UPDATE

Replace these files in your urlbim3 repository, keeping the same paths:

1. plugins/terabox_engine.py
2. plugins/youtube_dl_button.py

Also copy TERABOX_COOKIELESS_SETUP.md into the repository root.

Then redeploy/restart your bot.

No cookie/session is required by the new engine. For resolver configuration,
read TERABOX_COOKIELESS_SETUP.md.

Alternatively, apply terabox_cookieless_update.patch from the root of the
urlbim3 repository:
    git apply terabox_cookieless_update.patch
