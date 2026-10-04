#language slang 2026
// Молнии от курсора при быстрой печати. 28.09.2026.
//
// Разряды бьют ОТ КУРСОРА наружу — пользователь с самого начала просил, чтобы молнии
// шли за курсором в реальном времени, а не случайными вспышками по экрану
// (первая редакция рисовала ломаные от края до края, и это выглядело шумом).
//
// Срабатывает на каждое движение текстового курсора, но силу даёт СКОРОСТЬ:
// шейдер смотрит, насколько след отстал от курсора. Спокойный набор — разрядов
// нет, быстрый — бьют на каждом ударе. Событие звонка для сигнала не годится:
// bell-in-window в kitty 0.49.1 не возникает вовсе (проверено пробным шейдером).
//
// Разряд — ломаная из нескольких колен со случайным изломом, жила почти белая,
// вокруг свечение акцентом. Вспышка резкая, затухание быстрое.

import kitty_custom_shader_types;

// ─── Ручки настройки ───
static const int   BOLTS      = 2;      // разрядов на удар
static const int   JOINTS     = 6;      // колен в каждом разряде
static const float REACH      = 0.16;   // длина разряда в долях высоты окна
static const float JAG        = 0.30;   // излом в стороны, доля длины
static const float CORE_W     = 0.0014; // толщина жилы
static const float GLOW_W     = 0.010;  // ширина свечения
static const float BURST      = 0.9;    // яркость на пике
static const float LAG_MIN    = 0.0035; // отставание следа, с которого бьют молнии
static const float LAG_MAX    = 0.016;  // отставание, на котором в полную силу
static const float TEXT_GUARD = 0.10;   // порог «это текст, сюда не светим»

// Акцент обоев. Перекрывается из speedburst.pipeline (var float3 ACCENT).
static const float3 ACCENT = float3(0.48, 0.60, 1.0);

static float hash21(float2 p) {
    p = frac(p * float2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return frac(p.x * p.y);
}

static float3 srgb2linear(float3 c) {
    float3 lo = c / 12.92;
    float3 hi = pow(max((c + 0.055) / 1.055, 0.0), float3(2.4));
    return lerp(lo, hi, step(float3(0.04045), c));
}

static float seg_d2(float2 p, float2 a, float2 b) {
    float2 ab = b - a, ap = p - a;
    float t = saturate(dot(ap, ab) / max(dot(ab, ab), 1e-9));
    float2 d = ap - ab * t;
    return dot(d, d);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float p = t.animation_progress;
    if (p <= 0.0 || p >= 1.0) return color;
    if (d.cursor_trail_color.a <= 0.0 && d.cursor_color.a <= 0.0) return color;

    // Забой молний не даёт: курсор пошёл влево — выходим (как у отдачи).
    float2 cur = float2((d.cursor_trail_edge.x + d.cursor_trail_edge.y) * 0.5,
                        (d.cursor_trail_edge.z + d.cursor_trail_edge.w) * 0.5);
    float2 prev = float2((d.cursor_trail_prev_edge.x + d.cursor_trail_prev_edge.y) * 0.5,
                         (d.cursor_trail_prev_edge.z + d.cursor_trail_prev_edge.w) * 0.5);
    if (any(d.cursor_trail_prev_edge != float4(0.0)) && cur.x < prev.x - 1e-6)
        return color;

    // Сила — от скорости набора (отставание следа от курсора).
    float2 tail = float2((d.cursor_trail_corners_x.x + d.cursor_trail_corners_x.z) * 0.5,
                         (d.cursor_trail_corners_y.x + d.cursor_trail_corners_y.z) * 0.5);
    float speed = smoothstep(LAG_MIN, LAG_MAX, length(cur - tail));
    if (speed <= 0.02) return color;

    float3 bg = d.active_window_background.rgb;
    float a = max(color.a, 1e-3);
    float clear_area = 1.0 - smoothstep(TEXT_GUARD * 0.35, TEXT_GUARD,
                                        distance(color.rgb / a, bg));

    // Экранные координаты с поправкой на соотношение сторон, иначе разряд,
    // бьющий вбок, выглядит толще бьющего вверх.
    float2 px = float2(d.viewport_size_pixels) * t.viewport.zw;
    float asp = px.x / max(px.y, 1.0);
    float2 q = float2(t.pos.x * asp, t.pos.y);
    float2 origin = float2(cur.x * asp, cur.y);

    // Быстрая отбраковка: дальше вылета разряда молний точно нет.
    if (length(q - origin) > REACH * 1.4) return color;

    float flick = 0.7 + 0.3 * sin(p * 41.0);
    float power = (1.0 - p) * (1.0 - p) * flick * speed;

    float seed = floor(d.cursor_trail_change_time * 977.0);
    float best = 1e9;
    for (int b = 0; b < BOLTS; ++b) {
        // Направление удара своё на каждый разряд и каждый удар.
        float ang = hash21(float2(seed, float(b) * 5.1)) * 6.2831853;
        float len = REACH * (0.55 + 0.45 * hash21(float2(seed, float(b) + 2.7)));
        float2 dir = float2(cos(ang), sin(ang));
        float2 nrm = float2(-dir.y, dir.x);
        float2 at = origin;
        for (int j = 1; j <= JOINTS; ++j) {
            float u = float(j) / float(JOINTS);
            float side = (hash21(float2(seed + float(b) * 17.0, float(j) * 3.7)) - 0.5);
            // К концу разряд сужает изломы — как настоящий, теряющий силу.
            float2 nxt = origin + dir * (len * u) + nrm * side * JAG * len * (1.0 - u * 0.6);
            best = min(best, seg_d2(q, at, nxt));
            at = nxt;
        }
    }
    float dist = sqrt(best);
    if (dist > GLOW_W * 2.5) return color;

    float core = 1.0 - smoothstep(CORE_W, CORE_W * 2.6, dist);
    float glow = exp(-dist / (GLOW_W * 0.5));
    float f = saturate(core + glow * 0.5) * power;

    float3 acc = srgb2linear(ACCENT);
    float3 col = lerp(acc, float3(0.95, 0.98, 1.0), core * 0.85);

    // По тексту светим слабее, но не гасим совсем: разряд у курсора неизбежно
    // проходит по буквам, и полный запрет разрезал бы его на куски.
    float add = f * BURST * (0.35 + 0.65 * clear_area);
    return float4(color.rgb + col * add, saturate(color.a + add * 0.7));
}
