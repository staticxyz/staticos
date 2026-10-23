# PxPlus TTF → BDF нужного кегля (Xwayland не умеет масштабируемые X-шрифты, только растровые)
import sys
from PIL import Image, ImageDraw, ImageFont
ttf, px, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
f = ImageFont.truetype(ttf, px)
asc, desc = f.getmetrics()
cps = [c for r in [(0x20, 0x7f), (0xa0, 0x100), (0x400, 0x460), (0x2010, 0x2027), (0x2116, 0x2117)] for c in range(*r)]
glyphs = []
for cp in cps:
    ch = chr(cp)
    if f.getmask(ch).getbbox() is None and cp != 0x20: continue
    adv = round(f.getlength(ch))
    im = Image.new("1", (adv, asc + desc), 0); d = ImageDraw.Draw(im); d.fontmode = "1"
    d.text((0, 0), ch, font=f, fill=1)
    rows = ["".join("%02X" % sum(im.getpixel((x8 * 8 + b, y)) << (7 - b) for b in range(8) if x8 * 8 + b < adv)
                    for x8 in range((adv + 7) // 8)) for y in range(asc + desc)]
    glyphs.append((cp, adv, rows))
w = glyphs[0][1]
name = "-jarvis-pxplus-medium-r-normal--%d-%d-75-75-c-%d-iso10646-1" % (px, px * 10, w * 10)
L = ["STARTFONT 2.1", "FONT " + name, "SIZE %d 75 75" % px, "FONTBOUNDINGBOX %d %d 0 %d" % (w, asc + desc, -desc),
     "STARTPROPERTIES 4", "FONT_ASCENT %d" % asc, "FONT_DESCENT %d" % desc, "DEFAULT_CHAR 32", 'SPACING "C"', "ENDPROPERTIES",
     "CHARS %d" % len(glyphs)]
for cp, adv, rows in glyphs:
    L += ["STARTCHAR U+%04X" % cp, "ENCODING %d" % cp, "SWIDTH %d 0" % (adv * 1000 // px), "DWIDTH %d 0" % adv,
          "BBX %d %d 0 %d" % (adv, asc + desc, -desc), "BITMAP"] + rows + ["ENDCHAR"]
L.append("ENDFONT")
open(out, "w").write("\n".join(L) + "\n"); print(name, len(glyphs))
