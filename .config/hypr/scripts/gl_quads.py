"""Минимальный OpenGL через libepoxy (тот же, что у GTK3) — без PyOpenGL.
Картинки cairo → текстуры, рисование прямоугольниками с прозрачностью.
Нужен для перехода обзора Super+G (ws_grid.py) на видеокарте (03.11.2026)."""
import ctypes as C
_e = C.CDLL("libepoxy.so.0")
u, i, f, p, sz = C.c_uint, C.c_int, C.c_float, C.c_void_p, C.c_ssize_t
def _fn(name, res, *args):
    ptr = C.c_void_p.in_dll(_e, "epoxy_" + name)
    return C.CFUNCTYPE(res, *args)(ptr.value)
glGenTextures = _fn("glGenTextures", None, i, C.POINTER(u))
glDeleteTextures = _fn("glDeleteTextures", None, i, C.POINTER(u))
glBindTexture = _fn("glBindTexture", None, u, u)
glTexImage2D = _fn("glTexImage2D", None, u, i, i, i, i, i, u, u, p)
glTexParameteri = _fn("glTexParameteri", None, u, u, i)
glPixelStorei = _fn("glPixelStorei", None, u, i)
glCreateShader = _fn("glCreateShader", u, u)
glShaderSource = _fn("glShaderSource", None, u, i, C.POINTER(C.c_char_p), p)
glCompileShader = _fn("glCompileShader", None, u)
glGetShaderiv = _fn("glGetShaderiv", None, u, u, C.POINTER(i))
glGetShaderInfoLog = _fn("glGetShaderInfoLog", None, u, i, p, C.c_char_p)
glCreateProgram = _fn("glCreateProgram", u)
glAttachShader = _fn("glAttachShader", None, u, u)
glLinkProgram = _fn("glLinkProgram", None, u)
glUseProgram = _fn("glUseProgram", None, u)
glGetUniformLocation = _fn("glGetUniformLocation", i, u, C.c_char_p)
glUniform1f = _fn("glUniform1f", None, i, f)
glUniform1i = _fn("glUniform1i", None, i, i)
glUniform2f = _fn("glUniform2f", None, i, f, f)
glUniform4f = _fn("glUniform4f", None, i, f, f, f, f)
glGenVertexArrays = _fn("glGenVertexArrays", None, i, C.POINTER(u))
glBindVertexArray = _fn("glBindVertexArray", None, u)
glDrawArrays = _fn("glDrawArrays", None, u, i, i)
glClearColor = _fn("glClearColor", None, f, f, f, f)
glClear = _fn("glClear", None, u)
glEnable = _fn("glEnable", None, u)
glDisable = _fn("glDisable", None, u)
glBlendFunc = _fn("glBlendFunc", None, u, u)
glViewport = _fn("glViewport", None, i, i, i, i)
glActiveTexture = _fn("glActiveTexture", None, u)
glFlush = _fn("glFlush", None)
glGetError = _fn("glGetError", u)

TEXTURE_2D, RGBA, BGRA, UBYTE = 0x0DE1, 0x1908, 0x80E1, 0x1401
LINEAR, NEAREST, MIN_F, MAG_F, WRAP_S, WRAP_T, CLAMP = 0x2601, 0x2600, 0x2801, 0x2800, 0x2802, 0x2803, 0x812F
VS, FS, COMPILE_STATUS = 0x8B31, 0x8B30, 0x8B81
TRI_STRIP, COLOR_BIT, BLEND, ONE, ONE_MINUS_SRC_ALPHA, TEXTURE0 = 5, 0x4000, 0x0BE2, 1, 0x0303, 0x84C0
UNPACK_ROW_LENGTH = 0x0CF2

VERT = b"""#version 150
uniform vec4 rect; uniform vec2 screen;
out vec2 uv;
void main() {
  vec2 c = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
  uv = c;
  vec2 px = rect.xy + c * rect.zw;
  gl_Position = vec4(px.x / screen.x * 2.0 - 1.0, 1.0 - px.y / screen.y * 2.0, 0.0, 1.0);
}"""
FRAG = b"""#version 150
uniform sampler2D tex; uniform float alpha; uniform vec4 color; uniform int solid; uniform int opaque;
in vec2 uv; out vec4 o;
void main() {
  vec4 c = solid == 1 ? color : texture(tex, uv);
  if (opaque == 1) c.a = 1.0;
  o = c * alpha;
}"""


def shader(kind, src):
    s = glCreateShader(kind)
    arr = (C.c_char_p * 1)(src)
    glShaderSource(s, 1, arr, None)
    glCompileShader(s)
    ok = i(0)
    glGetShaderiv(s, COMPILE_STATUS, C.byref(ok))
    if not ok.value:
        buf = C.create_string_buffer(4096)
        glGetShaderInfoLog(s, 4096, None, buf)
        raise RuntimeError(buf.value.decode())
    return s


class Painter:
    """Текстуры-прямоугольники с прозрачностью (premultiplied, как в cairo)."""
    def __init__(self):
        self.prog = glCreateProgram()
        glAttachShader(self.prog, shader(VS, VERT))
        glAttachShader(self.prog, shader(FS, FRAG))
        glLinkProgram(self.prog)
        self.loc = {n: glGetUniformLocation(self.prog, n.encode())
                    for n in ("rect", "screen", "tex", "alpha", "color", "solid", "opaque")}
        vao = u(0)
        glGenVertexArrays(1, C.byref(vao))
        self.vao = vao.value

    def begin(self, w, h, fb_w, fb_h):
        glViewport(0, 0, fb_w, fb_h)
        glClearColor(0, 0, 0, 0)
        glClear(COLOR_BIT)
        glEnable(BLEND)
        glBlendFunc(ONE, ONE_MINUS_SRC_ALPHA)
        glUseProgram(self.prog)
        glBindVertexArray(self.vao)
        glUniform2f(self.loc["screen"], w, h)
        glUniform1i(self.loc["tex"], 0)
        glActiveTexture(TEXTURE0)

    def texture(self, surf, old=0):
        """cairo.ImageSurface (ARGB32/RGB24) → текстура."""
        surf.flush()
        w, h, stride = surf.get_width(), surf.get_height(), surf.get_stride()
        t = u(old)
        if not old:
            glGenTextures(1, C.byref(t))
        glBindTexture(TEXTURE_2D, t.value)
        glPixelStorei(UNPACK_ROW_LENGTH, stride // 4)
        data = surf.get_data()
        buf = (C.c_char * len(data)).from_buffer(data)
        glTexImage2D(TEXTURE_2D, 0, RGBA, w, h, 0, BGRA, UBYTE, C.cast(buf, p))
        glPixelStorei(UNPACK_ROW_LENGTH, 0)
        glTexParameteri(TEXTURE_2D, MIN_F, LINEAR)
        glTexParameteri(TEXTURE_2D, MAG_F, LINEAR)
        glTexParameteri(TEXTURE_2D, WRAP_S, CLAMP)
        glTexParameteri(TEXTURE_2D, WRAP_T, CLAMP)
        return t.value

    def free(self, tex):
        if tex:
            glDeleteTextures(1, C.byref(u(tex)))

    def quad(self, tex, x, y, w, h, alpha=1.0, nearest=False, opaque=False):
        if alpha <= 0.002:
            return
        glUniform1i(self.loc["solid"], 0)
        glUniform1i(self.loc["opaque"], 1 if opaque else 0)
        glBindTexture(TEXTURE_2D, tex)
        flt = NEAREST if nearest else LINEAR
        glTexParameteri(TEXTURE_2D, MIN_F, flt)
        glTexParameteri(TEXTURE_2D, MAG_F, flt)
        glUniform4f(self.loc["rect"], x, y, w, h)
        glUniform1f(self.loc["alpha"], alpha)
        glDrawArrays(TRI_STRIP, 0, 4)

    def fill(self, x, y, w, h, r, g, b, a):
        glUniform1i(self.loc["solid"], 1)
        glUniform1i(self.loc["opaque"], 0)
        glUniform4f(self.loc["color"], r, g, b, 1.0)
        glUniform4f(self.loc["rect"], x, y, w, h)
        glUniform1f(self.loc["alpha"], a)
        glDrawArrays(TRI_STRIP, 0, 4)
