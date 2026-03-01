#pragma once

// ╔══════════════════════════════════════════════════════════════════════════╗
// ║  QidiTheme.hpp — Dark Forge Visual Identity                             ║
// ║  Single source of truth for all brand colours, typography, and strings. ║
// ║  Version 1.0 — 2026-03-01                                               ║
// ╚══════════════════════════════════════════════════════════════════════════╝
//
//  Usage:
//    #include "QidiTheme.hpp"
//    wxColour bg = QidiTheme::BACKGROUND;
//    StateColor accent(QidiTheme::ACCENT_CYAN);
//
//  Integration points:
//    - GUI_App.cpp   → update_label_colours()  uses these instead of raw RGB
//    - StateColor.cpp → gDarkColors map gets our brand entries
//    - AboutDialog.cpp → TAGLINE, APP_FULL_NAME
//    - GUI_Colors.cpp  → 3D viewport brand colours
//    - CMakeLists.txt  → SLIC3R_APP_FULL_NAME can be set to BRAND_NAME

#include <wx/colour.h>

// ImGui helpers are only compiled when imgui is already in scope.
// Include this header AFTER imgui.h in translation units that need ImVec4 factories.
#ifdef IMGUI_VERSION
#   include "imgui/imgui.h"
#endif

namespace QidiTheme {

// ─── BRAND STRINGS ────────────────────────────────────────────────────────────
// Keep in sync with version.inc and resource string tables.
inline constexpr const char* BRAND_NAME         = "NexusSlicer";       // Final brand name: USPTO-clear, zero existing conflicts, nexusslicer.com
                                                                        // TODO: update icon/dialog strings after Wyoming C-Corp + domain registered
inline constexpr const char* TAGLINE            = "Precision, Accelerated.";
inline constexpr const char* THEME_NAME         = "Dark Forge";
inline constexpr const char* ICON_FILENAME      = "QIDIStudio_192px.png";
inline constexpr const char* ICON_ICO_FILENAME  = "QIDIStudioTitle.ico";

// ─── DARK FORGE PALETTE (hex) ─────────────────────────────────────────────────
//
//  Primary:  forge black backgrounds
//  Accent 1: electric cyan  — interactive elements, active states, tech signal
//  Accent 2: molten orange  — warnings, heat, printing-in-progress
//  Surface:  graphite panels
//  Text:     off-white primary, muted secondary
//
inline constexpr const char* HEX_BACKGROUND         = "#0D0D0F";   // forge black
inline constexpr const char* HEX_SURFACE            = "#1C1C21";   // graphite
inline constexpr const char* HEX_SURFACE_ELEVATED   = "#2A2A32";   // elevated panel
inline constexpr const char* HEX_SURFACE_HOVER      = "#34343E";   // hover state
inline constexpr const char* HEX_BORDER             = "#3A3A45";   // subtle border
inline constexpr const char* HEX_ACCENT_CYAN        = "#00D4FF";   // electric cyan
inline constexpr const char* HEX_ACCENT_CYAN_DIM    = "#0099BB";   // dimmed cyan
inline constexpr const char* HEX_ACCENT_CYAN_GLOW   = "#4DE8FF";   // hovered cyan
inline constexpr const char* HEX_ACCENT_ORANGE      = "#FF6B35";   // molten orange
inline constexpr const char* HEX_ACCENT_ORANGE_DIM  = "#C45228";   // dimmed orange
inline constexpr const char* HEX_TEXT_PRIMARY       = "#E8E8EC";   // primary text
inline constexpr const char* HEX_TEXT_SECONDARY     = "#8888A0";   // secondary/hint text
inline constexpr const char* HEX_TEXT_DISABLED      = "#444455";   // disabled text
inline constexpr const char* HEX_SUCCESS            = "#22C55E";   // green — print ok
inline constexpr const char* HEX_WARNING            = "#F59E0B";   // amber — caution
inline constexpr const char* HEX_ERROR              = "#EF4444";   // red — error
inline constexpr const char* HEX_MODIFIED           = "#F1754E";   // orange-red — modified param

// ─── wxCOLOUR FACTORIES ───────────────────────────────────────────────────────
// These functions are trivially inlined; the string constructor accepts hex.
// All are noexcept by wxColour contract (invalid hex → opaque black).

inline wxColour BACKGROUND()         { return wxColour(HEX_BACKGROUND); }
inline wxColour SURFACE()            { return wxColour(HEX_SURFACE); }
inline wxColour SURFACE_ELEVATED()   { return wxColour(HEX_SURFACE_ELEVATED); }
inline wxColour SURFACE_HOVER()      { return wxColour(HEX_SURFACE_HOVER); }
inline wxColour BORDER()             { return wxColour(HEX_BORDER); }
inline wxColour ACCENT_CYAN()        { return wxColour(HEX_ACCENT_CYAN); }
inline wxColour ACCENT_CYAN_DIM()    { return wxColour(HEX_ACCENT_CYAN_DIM); }
inline wxColour ACCENT_CYAN_GLOW()   { return wxColour(HEX_ACCENT_CYAN_GLOW); }
inline wxColour ACCENT_ORANGE()      { return wxColour(HEX_ACCENT_ORANGE); }
inline wxColour ACCENT_ORANGE_DIM()  { return wxColour(HEX_ACCENT_ORANGE_DIM); }
inline wxColour TEXT_PRIMARY()       { return wxColour(HEX_TEXT_PRIMARY); }
inline wxColour TEXT_SECONDARY()     { return wxColour(HEX_TEXT_SECONDARY); }
inline wxColour TEXT_DISABLED()      { return wxColour(HEX_TEXT_DISABLED); }
inline wxColour SUCCESS()            { return wxColour(HEX_SUCCESS); }
inline wxColour WARNING()            { return wxColour(HEX_WARNING); }
inline wxColour ERROR_COLOR()        { return wxColour(HEX_ERROR); }     // "ERROR" clashes with Windows macro
inline wxColour MODIFIED()           { return wxColour(HEX_MODIFIED); }

// ─── ImVec4 FACTORIES (for ImGui / 3D viewport) ───────────────────────────────
// Converts hex string palette to normalised float RGBA expected by ImGui.

#ifdef IMGUI_VERSION
namespace ImGui {

// Helper: parse "#RRGGBB" to normalised [0,1] floats
inline ImVec4 from_hex(const char* hex, float alpha = 1.0f) {
    // Skip '#' if present
    if (hex && *hex == '#') ++hex;
    unsigned int rgb = 0;
    for (int i = 0; i < 6 && hex && *hex; ++i, ++hex) {
        char c = *hex;
        int  d = (c >= '0' && c <= '9') ? c - '0' :
                 (c >= 'A' && c <= 'F') ? c - 'A' + 10 :
                 (c >= 'a' && c <= 'f') ? c - 'a' + 10 : 0;
        rgb = (rgb << 4) | d;
    }
    const float inv = 1.0f / 255.0f;
    return ImVec4(
        static_cast<float>((rgb >> 16) & 0xFF) * inv,
        static_cast<float>((rgb >>  8) & 0xFF) * inv,
        static_cast<float>( rgb        & 0xFF) * inv,
        alpha
    );
}

// Viewport background — forge black (slightly lighter than UI background for depth)
inline ImVec4 VIEWPORT_BG()      { return from_hex(HEX_SURFACE,       1.0f); }
inline ImVec4 ACCENT_CYAN()      { return from_hex(HEX_ACCENT_CYAN,   1.0f); }
inline ImVec4 ACCENT_ORANGE()    { return from_hex(HEX_ACCENT_ORANGE, 1.0f); }
inline ImVec4 SUCCESS()          { return from_hex(HEX_SUCCESS,       1.0f); }
inline ImVec4 ERROR_COLOR()      { return from_hex(HEX_ERROR,         1.0f); }
inline ImVec4 TEXT_PRIMARY()     { return from_hex(HEX_TEXT_PRIMARY,  1.0f); }
inline ImVec4 TEXT_SECONDARY()   { return from_hex(HEX_TEXT_SECONDARY,1.0f); }

} // namespace ImGui
#endif // IMGUI_VERSION

// ─── INTEGRATION NOTES ────────────────────────────────────────────────────────
// StateColor.cpp: gDarkColors static map already updated with brand values.
//   kBrandCyan (#00D4FF), kBrandOrange (#FF6B35), kBrandSurface (#1C1C21) etc.
//   Sync those constexpr strings with HEX_* above if palette changes.
//
// GUI_Colors.cpp / RenderColor::colors[]: apply ImGui namespace factories above
//   when GL/ImGui context is available (after OpenGLManager::init()).
//   Example:
//     RenderColor::colors[RenderCol_3D_Background] = QidiTheme::ImGui::VIEWPORT_BG();
//
// resources/shaders/: brand colours injected as WGSL/GLSL uniforms via
//   GLShadersManager::set_uniform("u_accent_color", …)

} // namespace QidiTheme
