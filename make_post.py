"""
Natural Vibes — cloud daily post builder.
Runs inside the CCR routine sandbox after the repo is downloaded/unzipped.

Flow:
  1. Determine today's day (Asia/Manila, UTC+8) unless overridden.
  2. Read the generated quote + caption (from quote.json, else env NV_QUOTE / NV_CAPTION).
  3. Overlay the quote into that day's template (./templates/<Day>.png) with PIL.
  4. Upload the rendered image to tmpfiles.org -> public URL.
  5. POST {caption, image_url} to the Make.com webhook -> Facebook Page.

Repo layout expected:
  ./templates/<Day>.png   (7 clean 1080x1350 PNGs)
  ./fonts/*.ttf           (7 Google Fonts)
  ./make_post.py          (this file)
"""
import os, sys, json, urllib.request
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(ROOT, "templates")
FONTS = os.path.join(ROOT, "fonts")

MAKE_WEBHOOK = "https://hook.eu1.make.com/n6w8vv6t5i22g6hm1n47dnok6kzee1n6"

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
    "Friday":    {"font": "Lato-Light.ttf", "weight": None, "color": (245, 206, 92),
                  "zone": (330, 1078, 432, 56), "align": "center", "shadow": (0, 0, 0, 140)},
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


def wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], []
    for w in words:
        test = " ".join(cur + [w])
        if draw.textlength(test, font=font) > max_w and cur:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def fit(draw, text, name, weight, zone_w, zone_h, upper=False):
    if upper:
        text = text.upper()
    for size in range(220, 9, -2):
        font = load_font(name, size, weight)
        lines = wrap(draw, text, font, zone_w)
        asc, desc = font.getmetrics()
        lh = int((asc + desc) * 1.16)
        if lh * len(lines) <= zone_h and max((draw.textlength(l, font=font) for l in lines), default=0) <= zone_w:
            return font, lines, lh
    font = load_font(name, 10, weight)
    return font, wrap(draw, text, font, zone_w), 14


def render(day, quote, out_path):
    cfg = CONFIG[day]
    base = Image.open(os.path.join(TPL, f"{day}.png")).convert("RGBA")
    scratch = ImageDraw.Draw(base)
    x, y, w, h = cfg["zone"]
    font, lines, lh = fit(scratch, quote, cfg["font"], cfg["weight"], w, h, cfg.get("upper", False))
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
        tdraw.text((lx, yy), ln, font=font, fill=cfg["color"])
        yy += lh
    if cfg.get("shadow"):
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(6))
        base = Image.alpha_composite(base, shadow_layer)
    base = Image.alpha_composite(base, txt_layer)
    base.convert("RGB").save(out_path, "JPEG", quality=88, optimize=True)


def upload_tmpfiles(path):
    with open(path, "rb") as f:
        img = f.read()
    b = "nv_boundary"
    body = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="post.jpg"\r\n'
            f'Content-Type: image/jpeg\r\n\r\n').encode() + img + f'\r\n--{b}--\r\n'.encode()
    req = urllib.request.Request("https://tmpfiles.org/api/v1/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        url = json.loads(r.read())["data"]["url"]
    return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")


def post_make(caption, image_url):
    data = json.dumps({"caption": caption, "image_url": image_url}).encode()
    req = urllib.request.Request(MAKE_WEBHOOK, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def load_input():
    qp = os.path.join(ROOT, "quote.json")
    if os.path.exists(qp):
        d = json.load(open(qp, encoding="utf-8"))
        return d.get("day"), d["quote"], d["caption"]
    return os.environ.get("NV_DAY"), os.environ.get("NV_QUOTE", ""), os.environ.get("NV_CAPTION", "")


if __name__ == "__main__":
    day, quote, caption = load_input()
    day = day or today_manila()
    if day not in CONFIG:
        sys.exit(f"Unknown day: {day}")
    if not quote.strip():
        sys.exit("No quote provided (quote.json or NV_QUOTE).")
    if not caption.strip():
        caption = f'"{quote}"\n\n#NaturalVibes'

    out = os.path.join(ROOT, "post.jpg")
    render(day, quote, out)
    print(f"Rendered {day}: {quote!r} -> {out}")
    url = upload_tmpfiles(out)
    print(f"Uploaded: {url}")
    resp = post_make(caption, url)
    print("Posted to Make.com -> Facebook")
    print("Caption:", caption[:120].replace("\n", " "))
