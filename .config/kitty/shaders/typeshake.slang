#language slang 2026
// Отдача при печати. 28.09.2026.
//
// Экран вздрагивает при БЫСТРОМ наборе — как отдача у печатной машинки.
// В спокойной работе его нет вовсе: базовой тряски ноль, она появляется только
// когда набор разгоняется (окончательное решение пользователя, 28.09.2026).
// Работает в любом окне kitty, тренажёру jtype отдельного окна не нужно.
//
// Событий нажатия клавиши у шейдеров kitty нет. Зато есть cursor-trail-move:
// текстовый курсор смещается на КАЖДЫЙ символ, поэтому оно и служит здесь
// сигналом. Отсюда же ограничение: требуется cursor_trail в kitty.conf
// (у пользователя стоит 1).
//
// Как устроено. Сдвигаем не пиксель, а точку, из которой берём образец:
// картинка едет целиком, без искажений. Направление берётся из времени события,
// поэтому каждый удар отдаёт в свою сторону. Сила спадает по animation_progress
// (0 в начале, 1 в конце) и при этом дрожит — так вздрагивание выглядит живым,
// а не плавным съездом.

import kitty_custom_shader_types;

// ─── Ручки настройки ───
static const float AMPLITUDE = 7.5;   // размах в пикселях на пике удара.
                                      // 3.6 показалось слабым — пользователь просил жёстче
static const float WOBBLE    = 26.0;  // частота дрожи внутри одного удара
static const float VERTICAL  = 0.55;  // доля вертикали: 1 — поровну с горизонталью

static float hash21(float2 p) {
    p = frac(p * float2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return frac(p.x * p.y);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float p = t.animation_progress;
    if (p <= 0.0 || p >= 1.0) return color;

    // СТИРАНИЕ не трясёт. Забой ведёт курсор ВЛЕВО, набор — вправо; сравниваем
    // с положением до последнего хода. Прятать курсор на время отката, как
    // пробовал раньше, оказалось мало — kitty всё равно засчитывал ход.
    // Заодно это гасит удар на переносе строки: там курсор тоже уходит влево.
    float2 cur = float2((d.cursor_trail_edge.x + d.cursor_trail_edge.y) * 0.5,
                        (d.cursor_trail_edge.z + d.cursor_trail_edge.w) * 0.5);
    float2 prev = float2((d.cursor_trail_prev_edge.x + d.cursor_trail_prev_edge.y) * 0.5,
                         (d.cursor_trail_prev_edge.z + d.cursor_trail_prev_edge.w) * 0.5);
    bool prev_known = any(d.cursor_trail_prev_edge != float4(0.0));
    if (prev_known && cur.x < prev.x - 1e-6) return color;

    // Скорость набора шейдер определяет по тому, насколько след отстал от
    // курсора: при быстрой печати он не успевает, разрыв растёт. Событие
    // звонка для этого не годится — bell-in-window в kitty 0.49.1 не
    // возникает вовсе (проверено пробным шейдером 28.09.2026).
    float2 tail = float2((d.cursor_trail_corners_x.x + d.cursor_trail_corners_x.z) * 0.5,
                         (d.cursor_trail_corners_y.x + d.cursor_trail_corners_y.z) * 0.5);
    float lag = length(cur - tail);
    // БЕЗ постоянной доли: в спокойной работе тряски нет совсем, она включается
    // только на скорости. Базу 0.25 → 0.45 → 0.60 пробовали — в итоге пользователь
    // решил, что по умолчанию экран должен стоять смирно.
    float speed = smoothstep(0.0035, 0.016, lag);
    if (speed <= 0.02) return color;
    // Спад: резкий удар, затем быстрое затухание.
    float decay = (1.0 - p) * (1.0 - p);
    // Дрожь внутри удара: знак меняется несколько раз, отсюда «вздрагивание».
    float w = sin(p * WOBBLE) * decay;

    // Своё направление у каждого удара — берём из времени события.
    float seed = floor(d.cursor_trail_change_time * 1000.0);
    float ang = hash21(float2(seed, 7.13)) * 6.2831853;
    float2 dir = float2(cos(ang), sin(ang) * VERTICAL);

    float2 px = float2(d.viewport_size_pixels) * t.viewport.zw;
    float2 shift = dir * w * AMPLITUDE * speed / px;

    return t.backbuffer.Sample(t.pos - shift);
}
