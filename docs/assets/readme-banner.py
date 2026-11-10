#!/usr/bin/env python3
"""Draw the README banners, docs/assets/readme-banner-light.svg and -dark.svg.

The 3D Lucia goes in as WebP, because an SVG shown through <img> cannot load
other files. Colours come from site/style.css; fonts are system fonts for the
same reason. Redraw when the mascot, the tagline or the brand colours change,
then pin the README image URLs to the commit that adds the new files
(docs/publishing.md says why).

    cwebp -q 85 -alpha_q 100 -m 6 docs/assets/lucia-3d.png -o "$TMPDIR/lucia.webp"
    python3 docs/assets/readme-banner.py docs/assets "$TMPDIR/lucia.webp"
"""
import base64
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
LUCIA = base64.b64encode(Path(sys.argv[2]).read_bytes()).decode()
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

THEMES = {
    "light": dict(bg="#F2F5F7", border="#CBD5DD", ink="#15202B", soft="#4A5866", accent="#146B66",
                  glow="#D5E6EA", term="#0D151C", term_border="#0D151C", term_ink="#D7E2EA",
                  term_dim="#7D8D99", red="#FF6B78", green="#54D38F", halo="#7CE8E1", amber="#F2C14E"),
    "dark": dict(bg="#0E151B", border="#25343F", ink="#E4ECF1", soft="#9DB0BE", accent="#5CD6CE",
                 glow="#16313A", term="#070B0F", term_border="#25343F", term_ink="#D7E2EA",
                 term_dim="#7D8D99", red="#FF6B78", green="#54D38F", halo="#7CE8E1", amber="#F2C14E"),
}

TITLE = ("Luciazero: make coding agents prove their work. Lucia, the mascot, stands beside a terminal "
         "where an agent claims all tests pass, ./test.sh exits 1, the fix lands with a regression test, "
         "./test.sh exits 0, and /done runs full verify, then a revert probe that shows the new test fails without the fix.")


def banner(c):
    W, H = 1280, 420
    p = []
    a = p.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
      f'role="img" aria-labelledby="t"><title id="t">{TITLE}</title>')
    a('<defs>'
      f'<clipPath id="frame"><rect x="1" y="1" width="{W-2}" height="{H-2}" rx="17"/></clipPath>'
      f'<radialGradient id="glow" cx="0.5" cy="0.45" r="0.5">'
      f'<stop offset="0" stop-color="{c["glow"]}"/><stop offset="1" stop-color="{c["glow"]}" stop-opacity="0"/>'
      '</radialGradient></defs>')
    a(f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="18" fill="{c["bg"]}" stroke="{c["border"]}"/>')

    # Lucia, standing at the left edge and cut by the frame at the hips
    a('<g clip-path="url(#frame)">')
    a(f'<ellipse cx="190" cy="230" rx="190" ry="210" fill="url(#glow)"/>')
    a(f'<image x="16" y="-6" width="348" height="435" preserveAspectRatio="xMidYMin meet" '
      f'href="data:image/webp;base64,{LUCIA}"/>')
    a('</g>')

    # text column
    X = 372
    a(f'<text x="{X - 3}" y="146" font-family="{MONO}" font-size="60" font-weight="700" fill="{c["ink"]}" '
      f'letter-spacing="-1.5">Lucia<tspan fill="{c["accent"]}">zero</tspan></text>')
    lines = (f'Make coding agents <tspan fill="{c["accent"]}">prove</tspan> their work.',
             "Done is proven by a command,", "not by the agent saying so.")
    for i, line in enumerate(lines):
        weight = ' font-weight="600"' if i == 0 else ""
        fill = c["ink"] if i == 0 else c["soft"]
        a(f'<text x="{X}" y="{196 + 30 * i}" font-family="{SANS}" font-size="21"{weight} fill="{fill}">{line}</text>')
    dot = f'<tspan fill="{c["soft"]}"> · </tspan>'
    a(f'<text x="{X}" y="330" font-family="{MONO}" font-size="14.5" fill="{c["ink"]}" xml:space="preserve">'
      f'Claude Code{dot}Codex CLI{dot}any skills agent</text>')

    # terminal panel: the loop catching a false green
    TX, TY, TW, TH = 780, 52, 448, 316
    a(f'<rect x="{TX}" y="{TY}" width="{TW}" height="{TH}" rx="14" fill="{c["term"]}" stroke="{c["term_border"]}"/>')
    for i, col in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        a(f'<circle cx="{TX + 24 + 18 * i}" cy="{TY + 22}" r="5.5" fill="{col}" opacity="0.85"/>')
    a(f'<text x="{TX + TW - 20}" y="{TY + 27}" text-anchor="end" font-family="{MONO}" font-size="12" '
      f'fill="{c["term_dim"]}">plan → change → verify → fix</text>')
    rows = [
        ("agent", '"Fixed. All tests pass."', c["term_ink"], "✎ unverified", c["amber"]),
        ("$", "./test.sh", c["term_ink"], "exit 1 ✗ RED", c["red"]),
        ("", "  FAIL price() rounds 9.995 to 9.99", c["term_dim"], "", None),
        ("edit", "fix price(), add a regression test", c["term_ink"], "", None),
        ("$", "./test.sh", c["term_ink"], "exit 0 ✓ GREEN", c["green"]),
        ("/done", "full verify · revert probe · review", c["term_ink"], "", None),
    ]
    y = TY + 74
    for prompt, body, ink, status, scol in rows:
        if prompt:
            pc = c["halo"] if prompt in ("$", "/done") else c["term_dim"]
            a(f'<text x="{TX + 24}" y="{y}" font-family="{MONO}" font-size="14" fill="{pc}">{prompt}</text>')
        a(f'<text x="{TX + 86}" y="{y}" font-family="{MONO}" font-size="14" fill="{ink}" '
          f'xml:space="preserve">{body}</text>')
        if status:
            a(f'<text x="{TX + TW - 24}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="13.5" '
              f'font-weight="700" fill="{scol}">{status}</text>')
        y += 36
    a(f'<line x1="{TX + 24}" y1="{y - 20}" x2="{TX + TW - 24}" y2="{y - 20}" stroke="{c["term_border"]}"/>')
    a(f'<text x="{TX + 24}" y="{y + 8}" font-family="{MONO}" font-size="12.5" fill="{c["term_dim"]}">'
      'Scope: every item delivered or named as left out.</text>')
    a("</svg>\n")
    return "".join(p)


for name, c in THEMES.items():
    out = OUT / f"readme-banner-{name}.svg"
    out.write_text(banner(c), encoding="utf-8")
    print("wrote", out, out.stat().st_size, "bytes")
