SaverBot Railway FFmpeg fix

1) Copy nixpacks.toml into the same directory Railway uses as the service's Root Directory.
2) If Railway uses Nixpacks, this file asks it to install ffmpeg.
3) If Railway uses Railpack instead, add this service variable:
   RAILPACK_DEPLOY_APT_PACKAGES=ffmpeg
4) Redeploy and check Build Logs for package installation.
5) FFmpeg is a system executable, not a pip package. yt-dlp needs it for MP3 extraction.

If this is a monorepo or Railway Root Directory is a subfolder, put nixpacks.toml in that service root.
