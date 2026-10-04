-------------------------------
---- ENVIRONMENT VARIABLES ----
-------------------------------

hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")
-- "Breeze-Dark" is a colour scheme, not a Qt style: Qt only knows Breeze,
-- Oxygen, Fusion, Windows. An invalid override makes Qt drop back to its
-- default style and ignore the qt6ct palette, which is why Dolphin turned white.
hl.env("QT_STYLE_OVERRIDE", "Breeze")

-- GTK4 (4.22) defaults to the Vulkan renderer. On this hybrid Intel+NVIDIA
-- laptop that froze GTK windows solid: the main loop parks in poll waiting for
-- a frame while [vkcf]/[vkrt]/[vkps] driver threads sit on futexes and the
-- process holds ~37 fds on /dev/nvidia0. OpenGL is the stable path here.
hl.env("GSK_RENDERER", "opengl")
