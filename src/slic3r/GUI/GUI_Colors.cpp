#include "GUI_Colors.hpp"
#include "imgui/imgui.h"
// QidiTheme is included AFTER imgui.h so IMGUI_VERSION is defined — enables
// QidiTheme::ImGui::* factories.
#include "../QidiTheme.hpp"


namespace Slic3r{

ImVec4 RenderColor::colors[RenderCol_Count] = { };

// Call once from OpenGLManager::init() or GLCanvas3D constructor to populate
// the Dark Forge 3D viewport colour table.
void RenderColor::init_dark_forge()
{
    // 3D canvas background — graphite surface (slightly lighter than forge-black
    // so models read clearly against it)
    colors[RenderCol_3D_Background]      = QidiTheme::ImGui::VIEWPORT_BG();

    // Print plates
    colors[RenderCol_Plate_Unselected]   = ImVec4(0.16f, 0.16f, 0.20f, 1.0f);  // #29293300ish
    colors[RenderCol_Plate_Selected]     = QidiTheme::ImGui::ACCENT_CYAN();
    colors[RenderCol_Plate_Default]      = ImVec4(0.13f, 0.13f, 0.17f, 1.0f);
    colors[RenderCol_Plate_Line_Top]     = QidiTheme::ImGui::from_hex(QidiTheme::HEX_BORDER, 1.0f);
    colors[RenderCol_Plate_Line_Bottom]  = QidiTheme::ImGui::from_hex(QidiTheme::HEX_BORDER, 0.5f);

    // Model states
    colors[RenderCol_Model_Disable]      = QidiTheme::ImGui::TEXT_SECONDARY();
    colors[RenderCol_Model_Unprintable]  = QidiTheme::ImGui::ERROR_COLOR();
    colors[RenderCol_Model_Neutral]      = QidiTheme::ImGui::TEXT_PRIMARY();

    // Object types
    colors[RenderCol_Part]               = QidiTheme::ImGui::from_hex("#3B8BE0", 1.0f);  // steel blue
    colors[RenderCol_Modifier]           = QidiTheme::ImGui::from_hex("#8B5CF6", 1.0f);  // purple
    colors[RenderCol_Negtive_Volume]     = QidiTheme::ImGui::ERROR_COLOR();
    colors[RenderCol_Support_Enforcer]   = QidiTheme::ImGui::SUCCESS();
    colors[RenderCol_Support_Blocker]    = QidiTheme::ImGui::ACCENT_ORANGE();

    // Axes — XYZ convention: red/green/blue but brand-adjusted for Dark Forge
    colors[RenderCol_Axis_X]             = ImVec4(1.00f, 0.27f, 0.27f, 1.0f);  // warm red
    colors[RenderCol_Axis_Y]             = ImVec4(0.27f, 0.90f, 0.45f, 1.0f);  // brand green
    colors[RenderCol_Axis_Z]             = QidiTheme::ImGui::ACCENT_CYAN();     // brand cyan

    // Grabbers — brighter than axes for UI clarity
    colors[RenderCol_Grabber_X]          = ImVec4(1.00f, 0.35f, 0.35f, 1.0f);
    colors[RenderCol_Grabber_Y]          = ImVec4(0.35f, 1.00f, 0.55f, 1.0f);
    colors[RenderCol_Grabber_Z]          = QidiTheme::ImGui::from_hex(QidiTheme::HEX_ACCENT_CYAN_GLOW, 1.0f);

    // Flatten plane
    colors[RenderCol_Flatten_Plane]      = QidiTheme::ImGui::from_hex(QidiTheme::HEX_ACCENT_CYAN, 0.35f);
    colors[RenderCol_Flatten_Plane_Hover]= QidiTheme::ImGui::from_hex(QidiTheme::HEX_ACCENT_CYAN, 0.65f);
}

const char* GetRenderColName(RenderCol idx)
{
    switch (idx)
    {
    case RenderCol_3D_Background: return "3D Background";
    case RenderCol_Plate_Unselected: return "Plate Unselected";
    case RenderCol_Plate_Selected: return "Plate Selected";
    case RenderCol_Plate_Default: return "Plate Default";
    case RenderCol_Plate_Line_Top: return "Plate Line Top";
    case RenderCol_Plate_Line_Bottom: return "Plate Line Bottom";
    case RenderCol_Model_Disable: return "Model Disable";
    case RenderCol_Model_Unprintable: return "Model Unprintable";
    case RenderCol_Model_Neutral: return "Model Neutral";
    case RenderCol_Part: return "Part";
    case RenderCol_Modifier: return "Modifier";
    case RenderCol_Negtive_Volume: return "Negtive Volume";
    case RenderCol_Support_Enforcer: return "Support Enforcer";
    case RenderCol_Support_Blocker: return "Support Blocker";
    case RenderCol_Axis_X: return "Axis X";
    case RenderCol_Axis_Y: return "Axis Y";
    case RenderCol_Axis_Z: return "Axis Z";
    case RenderCol_Grabber_X: return "Grabber X";
    case RenderCol_Grabber_Y: return "Grabber Y";
    case RenderCol_Grabber_Z: return "Grabber Z";
    case RenderCol_Flatten_Plane: return "Flatten Plane";
    case RenderCol_Flatten_Plane_Hover: return "Flatten Plane Hover";
    }
    return "Unknown";
}

}
