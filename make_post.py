"""
Natural Vibes — cloud daily post builder.
Runs inside the CCR routine sandbox after the repo is downloaded/unzipped.

Flow:
  1. Determine today's day (Asia/Manila, UTC+8) unless overridden.
  2. Read the generated quote + caption (day.txt / quote.txt / caption.txt, else env).
  3. Overlay the quote into that day's template (./templates/<Day>.png) with PIL.
  4. (publish) Upload the rendered image DIRECTLY to the Facebook Page Graph API
     (/photos, multipart) using FACEBOOK_PAGE_TOKEN from the environment.
     No tmpfiles.org, no Make.com — one outbound host: graph.facebook.com.

Repo layout expected:
  ./templates/<Day>.png   (7 clean 1080x1350 PNGs)
  ./fonts/*.ttf           (7 Google Fonts)
  ./make_post.py          (this file)

Environment (set in the cloud environment's variables):
  FACEBOOK_PAGE_TOKEN  (required for publish) — Page access token
  FACEBOOK_PAGE_ID     (optional) — defaults below
"""
import os, sys, json, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(ROOT, "templates")
FONTS = os.path.join(ROOT, "fonts")

API_VERSION = "v25.0"
PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID", "1133534073170877")

# Per-day design config. Zones in the 1080x1350 pixel space.
CONFIG = {
    "Monday":    {"font": "PlayfairDisplay-Italic.ttf", "weight": 600, "color": (242, 188, 78),
                  "zone": (195, 596, 689, 263), "align": "center", "shadow": (0, 0, 0, 150)},
    "Tuesday":   {"font": "Anton-Regular.ttf", "weight": None, "color": (255, 255, 255),
                  "zone": (66, 233, 935, 448), "align": "left", "shadow": (120, 60, 10, 160), "upper": True},
    "Wednesday": {"font": "Cormorant.ttf", "weight": 600, "color": (38, 44, 50),
                  "zone": (92, 184, 894, 224), "align": "center", "shadow": (255, 255, 255, 110)},
    "Thursday":  {"font": "Cormorant-Italic.ttf", "weight": 600, "color": (233, 198, 112),
                  "zone": (191, 777, 697, 83), "align": "center", "shadow": (0, 0, 0, 150)},
    "Friday":    {"font": "Anton-Regular.ttf", "weight": None, "color": (250, 224, 150),
                  "zone": (90, 420, 900, 500), "align": "center", "upper": True,
                  "sentence_lines": True, "leading": 0.9,
                  "shadow": (0, 0, 0, 150), "stroke": (9, (26, 6, 6))},
    "Saturday":  {"font": "Lato-Regular.ttf", "weight": None, "color": (251, 243, 220),
                  "zone": (150, 252, 780, 132), "align": "center", "shadow": (35, 18, 5, 175)},
    "Sunday":    {"font": "Cormorant.ttf", "weight": 600, "color": (36, 72, 52),
                  "zone": (135, 165, 810, 200), "align": "center", "shadow": (255, 255, 246, 120)},
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def today_manila():
    return DAYS[datetime.now(timezone(timedelta(hours=8))).weekday()]


def load_font(name, size, weight):
    f = ImageFont.truetype(os.path.join(FONTS, name), size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def wrap(draw, text, font, max_w, sentence_lines=False):
    import re
    # Each chunk starts as its own line; sentence_lines splits on . ! ? so every
    # sentence gets its own line. Long chunks still word-wrap to fit max_w.
    if sentence_lines:
        chunks = [c.strip() for c in re.findall(r"[^.!?]+[.!?]*", text) if c.strip()]
    else:
        chunks = [text]
    lines = []
    for chunk in chunks:
        cur = []
        for w in chunk.split():
            test = " ".join(cur + [w])
            if draw.textlength(test, font=font) > max_w and cur:
                lines.append(" ".join(cur)); cur = [w]
            else:
                cur.append(w)
        if cur:
            lines.append(" ".join(cur))
    return lines


def fit(draw, text, name, weight, zone_w, zone_h, upper=False, sentence_lines=False, leading=1.16):
    if upper:
        text = text.upper()
    for size in range(220, 9, -2):
        font = load_font(name, size, weight)
        lines = wrap(draw, text, font, zone_w, sentence_lines)
        asc, desc = font.getmetrics()
        lh = int((asc + desc) * leading)
        if lh * len(lines) <= zone_h and max((draw.textlength(l, font=font) for l in lines), default=0) <= zone_w:
            return font, lines, lh
    font = load_font(name, 10, weight)
    return font, wrap(draw, text, font, zone_w, sentence_lines), 14


def render(day, quote, out_path):
    cfg = CONFIG[day]
    base = Image.open(os.path.join(TPL, f"{day}.png")).convert("RGBA")
    x, y, w, h = cfg["zone"]
    # optional scrim panel behind the text (legibility over busy backgrounds)
    if cfg.get("scrim"):
        pad = cfg.get("scrim_pad", 30)
        ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(ov).rounded_rectangle(
            [x - pad, y - pad, x + w + pad, y + h + pad],
            radius=cfg.get("scrim_radius", 40), fill=cfg["scrim"])
        base = Image.alpha_composite(base, ov)
    scratch = ImageDraw.Draw(base)
    font, lines, lh = fit(scratch, quote, cfg["font"], cfg["weight"], w, h, cfg.get("upper", False), cfg.get("sentence_lines", False), cfg.get("leading", 1.16))
    yy = y + (h - lh * len(lines)) // 2

    shadow_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_layer)
    txt_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(txt_layer)
    for ln in lines:
        lw = scratch.textlength(ln, font=font)
        lx = x if cfg["align"] == "left" else (x + w - lw if cfg["align"] == "right" else x + (w - lw) / 2)
        if cfg.get("shadow"):
            sdraw.text((lx + 3, yy + 3), ln, font=font, fill=cfg["shadow"])
        stroke = cfg.get("stroke")
        if stroke:
            tdraw.text((lx, yy), ln, font=font, fill=cfg["color"],
                       stroke_width=stroke[0], stroke_fill=stroke[1])
        else:
            tdraw.text((lx, yy), ln, font=font, fill=cfg["color"])
        yy += lh
    if cfg.get("shadow"):
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(6))
        base = Image.alpha_composite(base, shadow_layer)
    base = Image.alpha_composite(base, txt_layer)
    base.convert("RGB").save(out_path, "JPEG", quality=95, subsampling=0, optimize=True)


def post_facebook_photo(caption, image_path, token):
    """Upload the rendered image straight to the Page's /photos endpoint as a
    multipart POST. Returns the parsed JSON response (raises on HTTP error with
    the Graph API error body)."""
    url = f"https://graph.facebook.com/{API_VERSION}/{PAGE_ID}/photos"
    b = "nv_boundary"
    with open(image_path, "rb") as f:
        img = f.read()

    def field(name, value):
        return (f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                f'{value}\r\n').encode("utf-8")

    body = field("access_token", token) + field("caption", caption)
    body += (f'--{b}\r\nContent-Disposition: form-data; name="source"; '
             f'filename="post.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode("utf-8")
    body += img + f"\r\n--{b}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def load_input():
    """Read day/quote/caption from plain text files (robust for LLM-written
    multi-line captions), falling back to env vars, then quote.json."""
    def rd(fn):
        p = os.path.join(ROOT, fn)
        return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""
    day = rd("day.txt") or os.environ.get("NV_DAY")
    quote = rd("quote.txt") or os.environ.get("NV_QUOTE", "")
    caption = rd("caption.txt") or os.environ.get("NV_CAPTION", "")
    if not quote:
        qp = os.path.join(ROOT, "quote.json")
        if os.path.exists(qp):
            d = json.load(open(qp, encoding="utf-8"))
            day = day or d.get("day"); quote = d.get("quote", ""); caption = d.get("caption", "")
    return day, quote, caption


OUT = os.path.join(ROOT, "post.jpg")

# Minimum acceptable rendered font size (px) per day. If the auto-fit shrinks
# below this, the quote is too long for that template's zone -> QA fail.
# Floors set ~30% below each design's natural sample size, so good quotes pass
# and overly-long ones get caught and retried.
QA_MIN_FONT = {"Monday": 36, "Tuesday": 70, "Wednesday": 48, "Thursday": 40,
               "Friday": 26, "Saturday": 36, "Sunday": 44}


def qa(day, quote):
    """Deterministic, offline design check. Returns a list of issue strings
    (empty list == pass). No API key needed."""
    cfg = CONFIG[day]
    x, y, w, h = cfg["zone"]
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
    font, lines, lh = fit(draw, quote, cfg["font"], cfg["weight"], w, h, cfg.get("upper", False), cfg.get("sentence_lines", False), cfg.get("leading", 1.16))
    issues = []
    floor = QA_MIN_FONT.get(day, 30)
    if font.size < floor:
        issues.append(f"quote too long for {day}: fits only at {font.size}px (need >={floor}px) - shorten it")
    if len(lines) > 4:
        issues.append(f"too many lines ({len(lines)}) - keep it tighter")
    widest = max((draw.textlength(l, font=font) for l in lines), default=0)
    if widest > w or lh * len(lines) > h:
        issues.append("text overflows the quote zone")
    return issues


def cmd_qa():
    day, quote, caption = load_input()
    day = day or today_manila()
    if day not in CONFIG:
        sys.exit(f"Unknown day: {day}")
    if not quote.strip():
        sys.exit("No quote provided.")
    issues = qa(day, quote)
    if issues:
        print(f"QA FAIL ({day}) - {quote!r}")
        for i in issues:
            print("  -", i)
        sys.exit(1)
    print(f"QA PASS ({day}) - {quote!r} fits cleanly")
    sys.exit(0)


def cmd_render():
    day, quote, caption = load_input()
    day = day or today_manila()
    if day not in CONFIG:
        sys.exit(f"Unknown day: {day}")
    if not quote.strip():
        sys.exit("No quote provided (quote.json or NV_QUOTE).")
    render(day, quote, OUT)
    print(f"Rendered {day}: {quote!r} -> {OUT}")


def cmd_publish():
    day, quote, caption = load_input()
    if not os.path.exists(OUT):
        sys.exit(f"No rendered image at {OUT}. Run 'render' first.")
    if not caption.strip():
        caption = f'"{quote}"\n\n#NaturalVibes'
    token = os.environ.get("FACEBOOK_PAGE_TOKEN", "").strip()
    if not token:
        sys.exit("ERROR: FACEBOOK_PAGE_TOKEN not set in environment.")
    result = post_facebook_photo(caption, OUT, token)
    if "error" in result:
        print("Facebook API error:", json.dumps(result["error"], indent=2))
        sys.exit(1)
    print(f"Posted to Facebook. photo_id={result.get('id')} post_id={result.get('post_id')}")
    print("Caption:", caption[:120].replace("\n", " "))


if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    if mode == "render":
        cmd_render()
    elif mode == "qa":
        cmd_qa()
    elif mode == "publish":
        cmd_publish()
    elif mode == "all":          # local/manual: render + qa + publish in one go
        cmd_render()
        _day, _quote, _ = load_input()
        _day = _day or today_manila()
        _issues = qa(_day, _quote)
        if _issues:
            print(f"QA FAIL ({_day}) - not publishing:")
            for _i in _issues:
                print("  -", _i)
            sys.exit(1)
        print(f"QA PASS ({_day})")
        cmd_publish()
    else:
        sys.exit(f"Usage: make_post.py [render|qa|publish]  (got {mode!r})")
