#pragma once

#include <wx/dialog.h>
#include <wx/spinctrl.h>
#include <wx/textctrl.h>

#include <string>

namespace Slic3r {
namespace GUI {

enum class TextureDialogMode { Apply, Adjust };

// Dialog for applying a displacement texture to a model volume or adjusting
// the depth of an already-applied texture.
//
// Apply mode  – shows a PNG file picker, tile size, and relief depth.
// Adjust mode – PNG is read-only (shows source texture), exposes tile size,
//               relief depth spinner, and quick ±0.2 / ±0.5 mm buttons.
class TextureParamsDialog : public wxDialog
{
public:
    TextureParamsDialog(wxWindow*          parent,
                        TextureDialogMode  mode,
                        const std::string& initial_png     = "",
                        double             initial_tile_mm = 15.0,
                        double             initial_relief  = 1.2);

    // Accessors – call after ShowModal() == wxID_OK
    std::string get_png_path()  const;
    double      get_tile_mm()   const;
    double      get_relief()    const;

private:
    TextureDialogMode  m_mode;
    wxTextCtrl*        m_png_ctrl    { nullptr };
    wxSpinCtrlDouble*  m_tile_ctrl   { nullptr };
    wxSpinCtrlDouble*  m_relief_ctrl { nullptr };

    void on_browse(wxCommandEvent&);
    void on_quick_adjust(double delta);
};

} // namespace GUI
} // namespace Slic3r
