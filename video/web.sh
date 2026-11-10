#!/usr/bin/env bash
# Web copies of the intro, made from out/luciazero-intro.mp4 (run `npm run render` first):
#   site/intro.mp4                        720p video for the website, under GitHub's 10 MB upload limit
#   site/intro-poster.jpg                 its poster, frame 23.6 s without grain
#   docs/assets/intro-cover.jpg           the README image that links to the video (cover.html)
#   docs/assets/intro-false-green.gif     1.2-6.4 s, the false green and the shatter, under 5 MB
set -euo pipefail
cd "$(dirname "$0")"
SITE=../site
ASSETS=../docs/assets
MASTER=out/luciazero-intro.mp4
for f in "$MASTER" out/music.wav; do [ -f "$f" ] || { echo "$f is missing; run npm run render first" >&2; exit 1; }; done
TAGS=(-colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv)

node render.mjs --grain 0 --stills 23.6
node render.mjs --cover
node render.mjs --grain 0 --from 1.2 --to 6.4 --fps 15 --out out/gif-src.mp4

# The score peaks at -1.0 dBFS and AAC at 128k overshoots it to +0.2, so the
# audio comes from the WAV, not the master's AAC, 1.5 dB lower.
ffmpeg -v error -y -i "$MASTER" -i out/music.wav -map 0:v -map 1:a -vf scale=1280:-2 \
  -c:v libx264 -preset slow -crf 26 -maxrate 3M -bufsize 6M -pix_fmt yuv420p "${TAGS[@]}" \
  -af volume=-1.5dB -c:a aac -b:a 128k -movflags +faststart "$SITE/intro.mp4"
ffmpeg -v error -y -i out/stills/t-23.60.png -vf scale=1280:-2:flags=lanczos -q:v 3 "$SITE/intro-poster.jpg"
ffmpeg -v error -y -i out/cover.png -vf scale=1280:-2:flags=lanczos -q:v 3 "$ASSETS/intro-cover.jpg"
# A global palette over the whole clip (stats_mode=full) bands less than per-change
# stats; ordered dither keeps the file smaller than error diffusion.
ffmpeg -v error -y -i out/gif-src.mp4 -vf "scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
  "$ASSETS/intro-false-green.gif"

.venv/bin/python verify.py "$SITE/intro.mp4" 1280x720 | grep -v "^PASS"
for f in "$SITE/intro.mp4" "$SITE/intro-poster.jpg" "$ASSETS/intro-cover.jpg" "$ASSETS/intro-false-green.gif"; do
  printf '%9d bytes  %s\n' "$(wc -c < "$f")" "$f"
done
[ "$(wc -c < "$SITE/intro.mp4")" -lt 10000000 ] || { echo "site/intro.mp4 is over 10 MB" >&2; exit 1; }
[ "$(wc -c < "$ASSETS/intro-false-green.gif")" -lt 5000000 ] || { echo "the GIF is over 5 MB" >&2; exit 1; }
