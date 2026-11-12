#!/usr/bin/env python3
"""Pip - cocuk kanali video uretici."""
import asyncio, json, math, pathlib, subprocess, sys, time, wave
from functools import lru_cache
import edge_tts, yaml
from PIL import Image, ImageDraw, ImageFont

AYAR = {
    "anlatici_ses": "en-GB-SoniaNeural",
    "maskot_ses": "en-GB-MaisieNeural",
    "anlatici_hiz": "-10%",
    "maskot_hiz": "-5%",
    "format": "yatay",
    "fps": 24,
    "font_dosya": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "font_adi": "DejaVu Sans",
    "altyazi_boyut": 84,
    "altyazi_alt": 240,
    "arkaplan_ust": (222, 240, 252),
    "arkaplan_alt": (186, 218, 242),
}
CIKTI = pathlib.Path("cikti")
TICK = 10000000
RATE = 48000
PALET = {"red": (233, 79, 79), "blue": (72, 140, 224), "yellow": (247, 201, 72),
         "green": (96, 190, 120), "purple": (163, 118, 214), "orange": (245, 150, 70)}

# ---------------- SES ----------------
def sesleri_sec():
    async def _f():
        return {x["ShortName"] for x in await edge_tts.list_voices()}
    try:
        mevcut = asyncio.run(_f())
    except Exception as e:
        print("Ses listesi alinamadi:", e)
        return AYAR["anlatici_ses"], AYAR["maskot_ses"]
    def sec(istenen, yedekler):
        for a in (istenen,) + yedekler:
            if a in mevcut:
                return a
        return istenen
    a = sec(AYAR["anlatici_ses"], ("en-GB-LibbyNeural", "en-GB-SoniaNeural"))
    m = sec(AYAR["maskot_ses"], ("en-GB-LibbyNeural", a))
    print("Anlatici:", a, "| Maskot:", m)
    return a, m

async def _seg(text, voice, rate, mp3):
    c = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with open(mp3, "wb") as f:
        async for ch in c.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append(ch)
    return words

def ses_uret(parts, wav_yol, words_yol, anlatici, maskot):
    tmp = CIKTI / "_ses"
    tmp.mkdir(parents=True, exist_ok=True)
    buffers, kelimeler, offset = [], [], 0.0
    for i, p in enumerate(parts):
        kim = p.get("speaker", "narrator")
        ses = maskot if kim == "mascot" else anlatici
        hiz = AYAR["maskot_hiz"] if kim == "mascot" else AYAR["anlatici_hiz"]
        mp3, wv = tmp / ("s%d.mp3" % i), tmp / ("s%d.wav" % i)
        words = []
        for deneme in range(4):
            try:
                words = asyncio.run(_seg(p["text"], ses, hiz, mp3))
                if words:
                    break
            except Exception as e:
                print("TTS deneme %d: %s" % (deneme + 1, e))
                time.sleep(2 * (deneme + 1))
                if deneme == 3:
                    raise
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ac", "1",
                        "-ar", str(RATE), "-c:a", "pcm_s16le", str(wv)], check=True)
        with wave.open(str(wv), "rb") as w:
            n = w.getnframes()
            buffers.append(w.readframes(n))
        for wd in words:
            kelimeler.append({"text": wd["text"], "speaker": kim,
                              "offset": wd["offset"] + int(offset * TICK),
                              "duration": wd["duration"]})
        offset += n / RATE
        bekle = float(p.get("pause", 0))
        if bekle > 0:
            buffers.append(b"\x00\x00" * int(bekle * RATE))
            offset += bekle
    with wave.open(str(wav_yol), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(buffers))
    words_yol.write_text(json.dumps(kelimeler, ensure_ascii=False), encoding="utf-8")
    return kelimeler, offset

# ---------------- ALTYAZI ----------------
def _cs(t):
    return int(round(t / 100000))

def _ts(cs):
    h, r = divmod(cs, 360000)
    m, r = divmod(r, 6000)
    s, c = divmod(r, 100)
    return "%d:%02d:%02d.%02d" % (h, m, s, c)

ASS_BAS = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Kar,{font},{fs},&H0000E8FF,&H00FFFFFF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,5,2,2,90,90,{mv}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def altyazi_yaz(words, yol, w, h):
    gruplar, cur = [], []
    for wd in words:
        t = wd["text"].strip()
        if not t:
            continue
        uzun = sum(len(x["text"]) + 1 for x in cur)
        bos = _cs(wd["offset"]) - _cs(cur[-1]["offset"] + cur[-1]["duration"]) if cur else 0
        if cur and (uzun + len(t) > 18 or bos > 60):
            gruplar.append(cur)
            cur = []
        cur.append(wd)
    if cur:
        gruplar.append(cur)
    spans = []
    for g in gruplar:
        bas = _cs(g[0]["offset"])
        parca, im = [], bas
        for i, wd in enumerate(g):
            s = _cs(wd["offset"])
            e = max(_cs(wd["offset"] + wd["duration"]), s + 1)
            on = " " if i else ""
            if s - im > 0:
                on = r"{\k%d}" % (s - im) + on
            parca.append(on + r"{\k%d}%s" % (e - s, wd["text"]))
            im = e
        spans.append((bas, im, "".join(parca)))
    ev = []
    for i, (s, e, txt) in enumerate(spans):
        bas, son = max(0, s - 8), e + 40
        if i + 1 < len(spans):
            son = min(son, spans[i + 1][0] - 9)
        ev.append("Dialogue: 0,%s,%s,Kar,,0,0,0,,%s" % (_ts(bas), _ts(max(son, bas + 1)), txt))
    yol.write_text(ASS_BAS.format(w=w, h=h, font=AYAR["font_adi"],
                                  fs=AYAR["altyazi_boyut"], mv=AYAR["altyazi_alt"])
                   + "\n".join(ev) + "\n", encoding="utf-8")

# ---------------- MASKOT ----------------
GOVDE, KOYU, GOZ, YANAK = (250, 214, 96), (226, 178, 52), (60, 58, 78), (245, 158, 158)

def maskot_ciz(d, cx, cy, r, t, konusuyor=False, selam=False):
    cy = cy + math.sin(t * 1.4) * r * 0.05
    rot = math.sin(t * 0.8) * 0.05
    aci = math.radians(-40 + (math.sin(t * 7) * 30 if selam else math.sin(t * 1.4) * 8))
    omuz = (cx + r * 0.50, cy + r * 0.12)
    el = (omuz[0] + math.cos(aci) * r * 0.55, omuz[1] + math.sin(aci) * r * 0.55)
    d.line([omuz, el], fill=KOYU, width=max(3, int(r * 0.13)))
    d.ellipse([el[0] - r * 0.14, el[1] - r * 0.14, el[0] + r * 0.14, el[1] + r * 0.14], fill=GOVDE)
    p = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5 + rot
        rr = r if i % 2 == 0 else r * 0.50
        p.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(p, fill=GOVDE)
    for sx in (-1, 1):
        d.ellipse([cx + sx * r * 0.30 - r * 0.09, cy + r * 0.08,
                   cx + sx * r * 0.30 + r * 0.09, cy + r * 0.24], fill=YANAK)
    kirp = (t % 4.2) < 0.14
    for sx in (-1, 1):
        gx = cx + sx * r * 0.17
        if kirp:
            d.line([(gx - r * 0.09, cy - r * 0.04), (gx + r * 0.09, cy - r * 0.04)],
                   fill=GOZ, width=max(2, int(r * 0.05)))
        else:
            d.ellipse([gx - r * 0.10, cy - r * 0.16, gx + r * 0.10, cy + r * 0.06], fill=(255, 255, 255))
            d.ellipse([gx - r * 0.055, cy - r * 0.10, gx + r * 0.055, cy + r * 0.02], fill=GOZ)
    if konusuyor:
        a = r * (0.09 + 0.06 * abs(math.sin(t * 11)))
        d.ellipse([cx - r * 0.11, cy + r * 0.16 - a, cx + r * 0.11, cy + r * 0.16 + a], fill=GOZ)
    else:
        d.arc([cx - r * 0.16, cy + r * 0.04, cx + r * 0.16, cy + r * 0.28],
              20, 160, fill=GOZ, width=max(2, int(r * 0.055)))

# ---------------- NESNELER ----------------
def _acik(c, k=65):
    return tuple(min(255, x + k) for x in c)

def balloon(d, cx, cy, r, c, s=1.0):
    r *= s
    if r < 2: return
    d.line([(cx, cy + r * 1.15), (cx, cy + r * 2.05)], fill=(125, 125, 135), width=max(2, int(r * 0.05)))
    d.ellipse([cx - r, cy - r * 1.15, cx + r, cy + r * 1.15], fill=c)
    d.polygon([(cx - r * 0.14, cy + r * 1.10), (cx + r * 0.14, cy + r * 1.10), (cx, cy + r * 1.34)], fill=c)
    d.ellipse([cx - r * 0.58, cy - r * 0.80, cx - r * 0.22, cy - r * 0.30], fill=_acik(c))

def apple(d, cx, cy, r, c, s=1.0):
    r *= s
    if r < 2: return
    d.ellipse([cx - r, cy - r * 0.95, cx + r, cy + r * 0.95], fill=c)
    d.line([(cx, cy - r * 0.85), (cx + r * 0.10, cy - r * 1.40)], fill=(122, 88, 54), width=max(3, int(r * 0.12)))
    d.ellipse([cx + r * 0.06, cy - r * 1.48, cx + r * 0.62, cy - r * 1.12], fill=(96, 190, 120))
    d.ellipse([cx - r * 0.55, cy - r * 0.55, cx - r * 0.20, cy - r * 0.15], fill=_acik(c))

def star(d, cx, cy, r, c, s=1.0):
    r *= s
    if r < 2: return
    p = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        p.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(p, fill=c)

def ball(d, cx, cy, r, c, s=1.0):
    r *= s
    if r < 2: return
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    d.line([(cx - r, cy), (cx + r, cy)], fill=(255, 255, 255), width=max(2, int(r * 0.08)))
    d.arc([cx - r, cy - r * 0.5, cx + r, cy + r * 0.5], 0, 180, fill=(255, 255, 255), width=max(2, int(r * 0.08)))

def circle(d, cx, cy, r, c, s=1.0):
    r *= s
    if r >= 2: d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)

def square(d, cx, cy, r, c, s=1.0):
    r *= s
    if r >= 2: d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=r * 0.15, fill=c)

def triangle(d, cx, cy, r, c, s=1.0):
    r *= s
    if r >= 2: d.polygon([(cx, cy - r), (cx + r * 0.95, cy + r * 0.8), (cx - r * 0.95, cy + r * 0.8)], fill=c)

NESNE = {"balloon": balloon, "apple": apple, "star": star, "ball": ball,
         "circle": circle, "square": square, "triangle": triangle}

# ---------------- ANIMASYON ----------------
def ease_back(t):
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

def gradyan(w, h, ust, alt):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(ust, alt)))
    return img

def norm(s):
    return s.lower().strip(".,!?;:\"'")

def cue_beats(words, cues):
    out, i = [], 0
    for wd in words:
        if wd.get("speaker", "narrator") != "narrator":
            continue
        if i < len(cues) and norm(wd["text"]) == cues[i]:
            out.append(wd["offset"] / TICK)
            i += 1
    if len(out) != len(cues):
        raise ValueError("Cue sirasi tutmadi: beklenen %s, eslesen %d" % (cues, len(out)))
    return out

def sure_al(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                                          "format=duration", "-of", "default=nw=1:nk=1",
                                          str(p)]).strip())

def _grid(n, w, h, r):
    cols = 5 if n > 4 else max(n, 1)
    rows = math.ceil(n / cols)
    pos = []
    for i in range(n):
        row, col = divmod(i, cols)
        bu = min(cols, n - row * cols)
        pos.append((w / 2 + (col - (bu - 1) / 2) * r * 2.7,
                    h * 0.54 + (row - (rows - 1) / 2) * r * 3.0))
    return pos

_SCRATCH = ImageDraw.Draw(Image.new("RGB", (1, 1)))

@lru_cache(maxsize=256)
def _fit_font(dosya, txt, taban, maxw):
    boy = taban
    while boy > 20:
        f = ImageFont.truetype(dosya, boy)
        bb = _SCRATCH.textbbox((0, 0), txt, font=f)
        if bb[2] - bb[0] <= maxw:
            return f
        boy -= 6
    return ImageFont.truetype(dosya, 20)

def _yazi(d, txt, font, w, h, ust):
    bb = d.textbbox((0, 0), txt, font=font)
    d.text((w / 2 - (bb[2] - bb[0]) / 2 - bb[0], h * ust), txt, font=font,
           fill=(255, 255, 255), stroke_width=max(3, int(h * 0.006)), stroke_fill=(70, 70, 100))

def video_uret(ders, words, ses, ass, cikti, w, h):
    fps = AYAR["fps"]
    cues = ders["cues"]
    beats = cue_beats(words, cues)
    renk = PALET[ders["color"]]
    nesneler = [NESNE[o] for o in ders["objects"]]
    birikimli = ders.get("mode", "accumulate") == "accumulate"
    cols = 5 if len(cues) > 4 else max(len(cues), 1)
    r = min(h * 0.085, w / (2.7 * cols + 1.2)) if birikimli else min(h * 0.15, w * 0.20)
    pos = _grid(len(cues), w, h, r) if birikimli else [(w / 2, h * 0.54)]
    sure = sure_al(ses) + 1.2
    bg = gradyan(w, h, AYAR["arkaplan_ust"], AYAR["arkaplan_alt"])
    dikey = h > w
    mr = h * (0.048 if dikey else 0.085)
    mx, my = (w * 0.17, h * 0.085) if dikey else (w * 0.11, h * 0.19)
    etiket_ust = 0.20 if dikey else 0.11
    etiket_maxw = w * (0.86 if dikey else 0.60)
    konusma = [(wd["offset"] / TICK, (wd["offset"] + wd["duration"]) / TICK)
               for wd in words if wd.get("speaker") == "mascot"]
    vf = "ass=%s,format=yuv420p" % str(ass)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
           "-r", str(fps), "-i", "-", "-i", str(ses),
           "-filter_complex",
           "[1:a]loudnorm=I=-18:TP=-2:LRA=11,afade=t=out:st=%.2f:d=0.6[a]" % max(0, sure - 0.6),
           "-map", "0:v", "-map", "[a]", "-vf", vf, "-t", "%.2f" % sure,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", str(cikti)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    toplam = int(sure * fps)
    print("Toplam kare:", toplam, flush=True)
    for i in range(toplam):
        t = i / fps
        img = bg.copy()
        d = ImageDraw.Draw(img)
        idx = sum(1 for b in beats if b <= t)
        txt = None
        if idx:
            if birikimli:
                for j in range(idx):
                    g = t - beats[j]
                    s = ease_back(g / 0.45) if g < 0.45 else 1.0
                    x, y = pos[j]
                    nesneler[j % len(nesneler)](d, x, y + math.sin(t * 1.5 + j) * r * 0.05, r, renk, s)
                txt = str(idx) if ders.get("label") == "count" else ders["labels"][idx - 1]
            else:
                j = idx - 1
                g = t - beats[j]
                s = ease_back(g / 0.45) if g < 0.45 else 1.0
                x, y = pos[0]
                nesneler[j % len(nesneler)](d, x, y + math.sin(t * 1.5) * r * 0.04, r, renk, s)
                txt = ders["labels"][j]
        if txt:
            f = _fit_font(AYAR["font_dosya"], txt, int(h * 0.17), etiket_maxw)
            _yazi(d, txt, f, w, h, etiket_ust)
        konusuyor = any(a <= t <= b for a, b in konusma)
        maskot_ciz(d, mx, my, mr, t, konusuyor=konusuyor, selam=(t < 2.6 or konusuyor))
        p.stdin.write(img.tobytes())
        if i % 120 == 0:
            print("kare %d / %d" % (i, toplam), flush=True)
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg animasyon hatasi")

def kapak_uret(ders, yol, w=1280, h=720):
    img = gradyan(w, h, AYAR["arkaplan_ust"], AYAR["arkaplan_alt"])
    d = ImageDraw.Draw(img)
    renk = PALET[ders["color"]]
    nesne = NESNE[ders["objects"][0]]
    for i in range(min(len(ders["cues"]), 5)):
        nesne(d, w * 0.28 + i * w * 0.11, h * 0.66, h * 0.13, renk, 1.0)
    txt = ders.get("thumb_text") or (str(len(ders["cues"])) if ders.get("label") == "count" else ders["labels"][0])
    f = _fit_font(AYAR["font_dosya"], txt, int(h * 0.30), w * 0.85)
    bb = d.textbbox((0, 0), txt, font=f)
    d.text((w / 2 - (bb[2] - bb[0]) / 2 - bb[0], h * 0.06), txt, font=f,
           fill=(255, 255, 255), stroke_width=8, stroke_fill=(70, 70, 100))
    maskot_ciz(d, w * 0.90, h * 0.22, h * 0.13, 0.0, selam=True)
    img.save(yol)

def main():
    ders_id = sys.argv[1] if len(sys.argv) > 1 else None
    dersler = yaml.safe_load(pathlib.Path("dersler.yaml").read_text(encoding="utf-8"))
    ders = next((x for x in dersler if x["id"] == ders_id), None) if ders_id else dersler[0]
    if ders is None:
        raise SystemExit("Ders bulunamadi: %s" % ders_id)
    CIKTI.mkdir(exist_ok=True)
    dikey = AYAR["format"] == "dikey"
    w, h = (1080, 1920) if dikey else (1920, 1080)
    print("Ders:", ders["id"], flush=True)
    anlatici, maskot = sesleri_sec()
    words, sure = ses_uret(ders["parts"], CIKTI / "ses.wav", CIKTI / "kelimeler.json",
                           anlatici, maskot)
    print("Ses hazir: %.1f sn" % sure, flush=True)
    altyazi_yaz(words, CIKTI / "altyazi.ass", w, h)
    video_uret(ders, words, CIKTI / "ses.wav", CIKTI / "altyazi.ass", CIKTI / "video.mp4", w, h)
    kapak_uret(ders, CIKTI / "kapak.png")
    (CIKTI / "bilgi.json").write_text(json.dumps(
        {"title": ders["title"], "description": ders["description"]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("BITTI ->", CIKTI / "video.mp4")

if __name__ == "__main__":
    main()