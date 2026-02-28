#include "TextureParamsDialog.hpp"

#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/button.h>
#include <wx/filedlg.h>

#include "GUI.hpp"          // _L()
#include "I18N.hpp"
#include "libslic3r/Utils.hpp" // resources_dir()

#include <algorithm>
#include <boost/filesystem.hpp>

namespace Slic3r {
namespace GUI {

TextureParamsDialog::TextureParamsDialog(wxWindow*          parent,
                                         TextureDialogMode  mode,
                                         const std::string& initial_png,
                                         double             initial_tile_mm,
                                         double             initial_relief)
    : wxDialog(parent,
               wxID_ANY,
               mode == TextureDialogMode::Apply ? _L("Apply Texture") : _L("Adjust Texture Depth"),
               wxDefaultPosition,
               wxSize(480, -1),
               wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER)
    , m_mode(mode)
{
    wxBoxSizer* main_sizer = new wxBoxSizer(wxVERTICAL);

    // ----------------------------------------------------------------
    // PNG file row
    // ----------------------------------------------------------------
    wxFlexGridSizer* grid = new wxFlexGridSizer(0, 2, 6, 10);
    grid->AddGrowableCol(1, 1);

    grid->Add(new wxStaticText(this, wxID_ANY, _L("Texture file:")),
              0, wxALIGN_CENTER_VERTICAL);

    wxBoxSizer* file_row = new wxBoxSizer(wxHORIZONTAL);
    m_png_ctrl = new wxTextCtrl(this, wxID_ANY,
                                wxString::FromUTF8(initial_png),
                                wxDefaultPosition, wxDefaultSize,
                                wxTE_READONLY);
    file_row->Add(m_png_ctrl, 1, wxEXPAND);

    if (mode == TextureDialogMode::Apply) {
        wxButton* browse_btn = new wxButton(this, wxID_ANY, _L("Browse..."),
                                            wxDefaultPosition, wxDefaultSize,
                                            wxBU_EXACTFIT);
        browse_btn->Bind(wxEVT_BUTTON, &TextureParamsDialog::on_browse, this);
        file_row->AddSpacer(4);
        file_row->Add(browse_btn, 0, wxALIGN_CENTER_VERTICAL);
    }
    grid->Add(file_row, 1, wxEXPAND);

    // ----------------------------------------------------------------
    // Tile size row
    // ----------------------------------------------------------------
    grid->Add(new wxStaticText(this, wxID_ANY, _L("Tile size (mm):")),
              0, wxALIGN_CENTER_VERTICAL);
    m_tile_ctrl = new wxSpinCtrlDouble(this, wxID_ANY, wxEmptyString,
                                       wxDefaultPosition, wxDefaultSize,
                                       wxSP_ARROW_KEYS,
                                       1.0, 200.0, initial_tile_mm, 0.5);
    m_tile_ctrl->SetDigits(1);
    // Explicit SetValue ensures the committed internal value matches the
    // displayed default even if the user never touches the control.
    // On Windows, wxSpinCtrlDouble can return 0 from GetValue() when only
    // the constructor's `initial` param was used and the control was never
    // interacted with.
    m_tile_ctrl->SetValue(initial_tile_mm);
    grid->Add(m_tile_ctrl, 1, wxEXPAND);

    // ----------------------------------------------------------------
    // Relief depth row
    // ----------------------------------------------------------------
    grid->Add(new wxStaticText(this, wxID_ANY, _L("Relief depth (mm):")),
              0, wxALIGN_CENTER_VERTICAL);
    m_relief_ctrl = new wxSpinCtrlDouble(this, wxID_ANY, wxEmptyString,
                                         wxDefaultPosition, wxDefaultSize,
                                         wxSP_ARROW_KEYS,
                                         0.1, 20.0, initial_relief, 0.1);
    m_relief_ctrl->SetDigits(2);
    m_relief_ctrl->SetValue(initial_relief);  // force-commit default, same reason
    grid->Add(m_relief_ctrl, 1, wxEXPAND);

    main_sizer->Add(grid, 0, wxEXPAND | wxALL, 12);

    // ----------------------------------------------------------------
    // Quick-adjust buttons (Adjust mode only)
    // ----------------------------------------------------------------
    if (mode == TextureDialogMode::Adjust) {
        main_sizer->AddSpacer(2);
        main_sizer->Add(new wxStaticText(this, wxID_ANY, _L("Quick adjust:")),
                        0, wxLEFT, 12);
        main_sizer->AddSpacer(4);

        wxBoxSizer* btn_row = new wxBoxSizer(wxHORIZONTAL);

        struct BtnDef { const char* label; double delta; };
        BtnDef defs[] = { {"-0.5", -0.5}, {"-0.2", -0.2}, {"+0.2", +0.2}, {"+0.5", +0.5} };
        for (const auto& b : defs) {
            wxButton* btn = new wxButton(this, wxID_ANY, b.label,
                                         wxDefaultPosition, wxSize(56, -1));
            double d = b.delta;
            btn->Bind(wxEVT_BUTTON, [this, d](wxCommandEvent&) { on_quick_adjust(d); });
            btn_row->Add(btn, 0, wxRIGHT, 4);
        }
        main_sizer->Add(btn_row, 0, wxLEFT | wxBOTTOM, 12);
    }

    // ----------------------------------------------------------------
    // OK / Cancel
    // ----------------------------------------------------------------
    main_sizer->AddStretchSpacer(1);

    wxBoxSizer* dlg_btns = new wxBoxSizer(wxHORIZONTAL);
    wxButton* ok_btn     = new wxButton(this, wxID_OK,     _L("OK"));
    wxButton* cancel_btn = new wxButton(this, wxID_CANCEL, _L("Cancel"));
    ok_btn->SetDefault();
    // Intercept OK so we can snapshot widget values into plain POD fields
    // BEFORE EndModal fires.  wx can begin unwinding child widget state
    // during the modal-loop wind-down; reading m_*_ctrl after that point
    // is unsafe on Windows.
    ok_btn->Bind(wxEVT_BUTTON, &TextureParamsDialog::on_ok, this);
    dlg_btns->Add(ok_btn,     0, wxRIGHT, 8);
    dlg_btns->Add(cancel_btn, 0);
    main_sizer->Add(dlg_btns, 0, wxALIGN_RIGHT | wxALL, 12);

    SetSizerAndFit(main_sizer);
    Centre();
}

void TextureParamsDialog::on_browse(wxCommandEvent& /*evt*/)
{
    // Default to resources/assets/ if it exists — saves the user navigating
    // there every time.  Falls back to the directory of the currently-selected
    // PNG (if any), then to wxEmptyString (OS default).
    namespace fs = boost::filesystem;
    wxString default_dir = wxEmptyString;

    const std::string assets_dir = Slic3r::resources_dir() + "/assets";
    if (fs::is_directory(assets_dir)) {
        default_dir = wxString::FromUTF8(assets_dir);
    } else {
        // Fall back to the directory of the currently-selected file.
        const wxString cur = m_png_ctrl->GetValue();
        if (!cur.IsEmpty())
            default_dir = wxFileName(cur).GetPath();
    }

    wxFileDialog dlg(this,
                     _L("Select Texture Image"),
                     default_dir,
                     wxEmptyString,
                     _L("Image files") + " (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg"
                         + "|" + _L("All files") + " (*.*)|*.*",
                     wxFD_OPEN | wxFD_FILE_MUST_EXIST);
    if (dlg.ShowModal() == wxID_OK)
        m_png_ctrl->SetValue(dlg.GetPath());
}

void TextureParamsDialog::on_quick_adjust(double delta)
{
    double v = m_relief_ctrl->GetValue() + delta;
    v = std::max(0.1, std::min(20.0, v));
    m_relief_ctrl->SetValue(v);
}

void TextureParamsDialog::on_ok(wxCommandEvent& /*evt*/)
{
    // Snapshot all widget values into plain fields BEFORE EndModal triggers
    // the modal-loop wind-down.  On Windows the wind-down restores focus to
    // the parent 3D canvas which can fire handlers that clear the Selection
    // and corrupt widget state before ShowModal() actually returns.
    m_cached_png      = std::string(m_png_ctrl->GetValue().ToUTF8());
    m_cached_tile_mm  = m_tile_ctrl->GetValue();
    m_cached_relief   = m_relief_ctrl->GetValue();
    EndModal(wxID_OK);
}

std::string TextureParamsDialog::get_png_path() const
{
    return m_cached_png;
}

double TextureParamsDialog::get_tile_mm() const
{
    return m_cached_tile_mm;
}

double TextureParamsDialog::get_relief() const
{
    return m_cached_relief;
}

} // namespace GUI
} // namespace Slic3r
