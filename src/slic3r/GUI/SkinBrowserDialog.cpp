#include "SkinBrowserDialog.hpp"

#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/button.h>
#include <wx/statbmp.h>
#include <wx/scrolwin.h>
#include <wx/image.h>
#include <wx/font.h>
#include <wx/colour.h>
#include <wx/msgdlg.h>
#include <wx/wrapsizer.h>

#include "GUI.hpp"
#include "I18N.hpp"
#include "libslic3r/Utils.hpp" // resources_dir()

#include <nlohmann/json.hpp>
#include <boost/filesystem.hpp>

#include <algorithm>
#include <fstream>
#include <sstream>

namespace fs = boost::filesystem;
using json = nlohmann::json;

namespace Slic3r
{
    namespace GUI
    {

        // ─────────────────────────────────────────────────────────────────────────────
        // Layout constants
        // ─────────────────────────────────────────────────────────────────────────────
        static constexpr int kThumbSize = 120; // image px
        static constexpr int kCellW = 136;     // cell width  px
        static constexpr int kCellH = 158;     // cell height px (image + label)
        static constexpr int kGridCols = 4;
        static constexpr int kCellGap = 6;
        static constexpr int kCatListW = 210; // left panel width
        static constexpr int kDialogW = kCatListW + kGridCols * (kCellW + kCellGap) + 48;
        static constexpr int kDialogH = 560;
        static constexpr int kVariantCount = 20;

        // Selection highlight colour (matches QIDIStudio blue theme accent)
        static const wxColour kSelColour{0x00, 0x6E, 0xC7};
        static const wxColour kSelBg{0xD6, 0xEC, 0xFF};
        static const wxColour kNormBg{0xF5, 0xF5, 0xF5};

        // ─────────────────────────────────────────────────────────────────────────────
        // SkinBrowserDialog — constructor
        // ─────────────────────────────────────────────────────────────────────────────
        SkinBrowserDialog::SkinBrowserDialog(wxWindow *parent)
            : wxDialog(parent,
                       wxID_ANY,
                       _L("Skin Asset Browser"),
                       wxDefaultPosition,
                       wxSize(kDialogW, kDialogH),
                       wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER)
        {
            // Initialise image handlers (no-op if already done)
            if (!wxImage::FindHandler(wxBITMAP_TYPE_PNG))
                wxImage::AddHandler(new wxPNGHandler);

            init_assets_root();
            load_metadata();

            // ── Top: left list + right scrolled window ────────────────────────────
            auto *top_sizer = new wxBoxSizer(wxHORIZONTAL);

            // Left category list
            m_cat_list = new wxListBox(this, wxID_ANY,
                                       wxDefaultPosition, wxSize(kCatListW, -1),
                                       0, nullptr, wxLB_SINGLE | wxLB_SORT);
            m_cat_list->SetFont(m_cat_list->GetFont().Larger());
            top_sizer->Add(m_cat_list, 0, wxEXPAND | wxRIGHT, 6);

            // Right scrolled thumbnail window
            m_thumb_win = new wxScrolledWindow(this, wxID_ANY,
                                               wxDefaultPosition, wxDefaultSize,
                                               wxVSCROLL | wxSUNKEN_BORDER);
            m_thumb_win->SetScrollRate(0, 20);
            m_thumb_win->SetBackgroundColour(*wxWHITE);

            m_thumb_sizer = new wxWrapSizer(wxHORIZONTAL, wxWRAPSIZER_DEFAULT_FLAGS);
            m_thumb_win->SetSizer(m_thumb_sizer);

            top_sizer->Add(m_thumb_win, 1, wxEXPAND);

            // ── Bottom: path label + buttons ─────────────────────────────────────
            m_path_label = new wxStaticText(this, wxID_ANY, _L("No skin selected"),
                                            wxDefaultPosition, wxDefaultSize,
                                            wxST_ELLIPSIZE_START);
            m_path_label->SetFont(m_path_label->GetFont().Smaller());

            m_ok_btn = new wxButton(this, wxID_OK, _L("Select"));
            auto *cxl = new wxButton(this, wxID_CANCEL, _L("Cancel"));
            m_ok_btn->Enable(false); // enabled once a thumbnail is chosen

            auto *btn_sizer = new wxBoxSizer(wxHORIZONTAL);
            btn_sizer->Add(m_path_label, 1, wxALIGN_CENTRE_VERTICAL | wxRIGHT, 10);
            btn_sizer->Add(m_ok_btn, 0, wxRIGHT, 6);
            btn_sizer->Add(cxl, 0);

            // ── Root sizer ────────────────────────────────────────────────────────
            auto *root = new wxBoxSizer(wxVERTICAL);
            root->Add(top_sizer, 1, wxEXPAND | wxALL, 8);
            root->Add(new wxStaticLine(this), 0, wxEXPAND | wxLEFT | wxRIGHT, 8);
            root->Add(btn_sizer, 0, wxEXPAND | wxALL, 8);
            SetSizer(root);

            // ── Bind events ───────────────────────────────────────────────────────
            m_cat_list->Bind(wxEVT_LISTBOX, &SkinBrowserDialog::on_category_selected, this);
            m_ok_btn->Bind(wxEVT_BUTTON, &SkinBrowserDialog::on_ok, this);

            // ── Populate categories then auto-select first ────────────────────────
            build_category_list();
            if (m_cat_list->GetCount() > 0)
            {
                m_cat_list->SetSelection(0);
                wxCommandEvent dummy;
                on_category_selected(dummy);
            }

            Layout();
            CentreOnParent();
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // init_assets_root — locate resources/assets/
        // ─────────────────────────────────────────────────────────────────────────────
        void SkinBrowserDialog::init_assets_root()
        {
            m_assets_root = resources_dir() + "/assets";
            if (!fs::is_directory(m_assets_root))
                m_assets_root.clear();
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // load_metadata — parse resources/assets/metadata.json (optional: graceful fall-
        //                 back to defaults if file absent or malformed)
        // ─────────────────────────────────────────────────────────────────────────────
        void SkinBrowserDialog::load_metadata()
        {
            if (m_assets_root.empty())
                return;

            const std::string meta_path = m_assets_root + "/metadata.json";
            if (!fs::is_regular_file(meta_path))
                return;

            try
            {
                std::ifstream ifs(meta_path);
                json root = json::parse(ifs);

                for (auto &[key, val] : root.items())
                {
                    SkinAssetMeta meta;
                    if (val.contains("tile_mm"))
                        meta.tile_mm = val["tile_mm"].get<double>();
                    if (val.contains("relief"))
                        meta.relief = val["relief"].get<double>();
                    if (val.contains("label"))
                        meta.label = val["label"].get<std::string>();
                    if (val.contains("group"))
                        meta.group = val["group"].get<std::string>();
                    m_meta[key] = meta;
                }
            }
            catch (...)
            {
                // Non-fatal: gallery works, just uses default tile_mm / relief
            }
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // build_category_list — enumerate sub-directories of assets root
        // ─────────────────────────────────────────────────────────────────────────────
        void SkinBrowserDialog::build_category_list()
        {
            m_categories.clear();
            m_cat_list->Clear();

            if (m_assets_root.empty())
                return;

            // Collect all sub-directory names
            std::vector<CategoryInfo> cats;
            try
            {
                for (const auto &entry : fs::directory_iterator(m_assets_root))
                {
                    if (!fs::is_directory(entry))
                        continue;
                    const std::string folder = entry.path().filename().string();
                    if (folder.empty() || folder[0] == '.')
                        continue;

                    CategoryInfo ci;
                    ci.folder = folder;

                    // Prefer label from metadata.json; fall back to folder_to_display()
                    if (m_meta.count(folder) && !m_meta.at(folder).label.empty())
                        ci.display = m_meta.at(folder).label;
                    else
                        ci.display = folder_to_display(folder);

                    if (m_meta.count(folder))
                        ci.group = m_meta.at(folder).group;
                    else
                        ci.group = "Other";

                    cats.push_back(ci);
                }
            }
            catch (...)
            {
            }

            // Sort: first by group, then by display name
            std::sort(cats.begin(), cats.end(), [](const CategoryInfo &a, const CategoryInfo &b)
                      {
        if (a.group != b.group) return a.group < b.group;
        return a.display < b.display; });

            m_categories = cats;

            // Populate wxListBox — show "Group › Display" grouping as a simple label
            std::string last_group;
            for (const auto &ci : m_categories)
            {
                if (ci.group != last_group)
                {
                    // Group separator as a disabled item (we use a leading ▸ prefix)
                    m_cat_list->Append("── " + ci.group + " ──");
                    last_group = ci.group;
                }
                m_cat_list->Append("  " + ci.display);
            }
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // populate_thumbnails — fill the right panel with thumbnail cells
        // ─────────────────────────────────────────────────────────────────────────────
        void SkinBrowserDialog::populate_thumbnails(const std::string &category)
        {
            // Remove existing children
            m_thumb_win->DestroyChildren();
            m_thumb_sizer->Clear(false);
            m_selected_cell = nullptr;

            if (m_assets_root.empty() || category.empty())
            {
                m_thumb_win->FitInside();
                return;
            }

            const std::string cat_dir = m_assets_root + "/" + category;

            for (int i = 1; i <= kVariantCount; ++i)
            {
                // Filename pattern: <category>_01.png … <category>_20.png
                char fname[64];
                std::snprintf(fname, sizeof(fname), "%s_%02d.png", category.c_str(), i);
                const std::string png_path = cat_dir + "/" + fname;

                // ── Outer border panel (provides the selection highlight frame) ──
                auto *cell = new wxPanel(m_thumb_win, wxID_ANY,
                                         wxDefaultPosition, wxSize(kCellW, kCellH));
                cell->SetBackgroundColour(kNormBg);

                auto *cell_sizer = new wxBoxSizer(wxVERTICAL);

                // ── Image ─────────────────────────────────────────────────────────
                wxStaticBitmap *sbmp;
                if (fs::is_regular_file(png_path))
                {
                    wxImage img(png_path, wxBITMAP_TYPE_PNG);
                    if (img.IsOk())
                    {
                        img.Rescale(kThumbSize, kThumbSize, wxIMAGE_QUALITY_BICUBIC);
                        sbmp = new wxStaticBitmap(cell, wxID_ANY, wxBitmap(img),
                                                  wxDefaultPosition, wxSize(kThumbSize, kThumbSize));
                    }
                    else
                    {
                        sbmp = new wxStaticBitmap(cell, wxID_ANY, wxNullBitmap,
                                                  wxDefaultPosition, wxSize(kThumbSize, kThumbSize));
                    }
                }
                else
                {
                    // Missing file — grey placeholder
                    wxBitmap placeholder(kThumbSize, kThumbSize);
                    {
                        wxMemoryDC dc(placeholder);
                        dc.SetBackground(wxBrush(wxColour(200, 200, 200)));
                        dc.Clear();
                        dc.SetTextForeground(wxColour(120, 120, 120));
                        dc.DrawText("?", kThumbSize / 2 - 5, kThumbSize / 2 - 8);
                    }
                    sbmp = new wxStaticBitmap(cell, wxID_ANY, placeholder,
                                              wxDefaultPosition, wxSize(kThumbSize, kThumbSize));
                }

                cell_sizer->Add(sbmp, 0, wxALIGN_CENTRE_HORIZONTAL | wxTOP, 7);

                // ── Label ─────────────────────────────────────────────────────────
                auto *lbl = new wxStaticText(cell, wxID_ANY, variant_label(i),
                                             wxDefaultPosition, wxSize(kCellW - 4, -1),
                                             wxALIGN_CENTRE_HORIZONTAL | wxST_NO_AUTORESIZE);
                lbl->SetFont(lbl->GetFont().Smaller());
                lbl->Wrap(kCellW - 8);
                cell_sizer->Add(lbl, 0, wxALIGN_CENTRE_HORIZONTAL | wxTOP, 3);

                cell->SetSizer(cell_sizer);

                // ── Mouse bindings (capture path in lambda value) ─────────────────
                const std::string path_copy = png_path;
                const std::string cat_copy = category;
                wxPanel *cell_ptr = cell;

                auto on_click = [this, cell_ptr, path_copy, cat_copy](wxMouseEvent &)
                {
                    select_thumbnail(cell_ptr, path_copy, cat_copy);
                };
                auto on_dblclick = [this, cell_ptr, path_copy, cat_copy](wxMouseEvent &)
                {
                    select_thumbnail(cell_ptr, path_copy, cat_copy);
                    // Accept immediately, same as clicking OK
                    wxCommandEvent dummy_evt(wxEVT_BUTTON, wxID_OK);
                    on_ok(dummy_evt);
                };

                // Bind on cell and all children so the whole cell area is clickable
                auto bind_mouse = [&](wxWindow *w)
                {
                    w->Bind(wxEVT_LEFT_DOWN, on_click);
                    w->Bind(wxEVT_LEFT_DCLICK, on_dblclick);
                };
                bind_mouse(cell);
                bind_mouse(sbmp);
                bind_mouse(lbl);

                m_thumb_sizer->Add(cell, 0, wxALL, kCellGap / 2);
            }

            m_thumb_win->SetSizer(m_thumb_sizer);
            m_thumb_win->FitInside();
            m_thumb_win->Scroll(0, 0);
            m_thumb_win->Layout();
            m_thumb_win->Refresh();
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // select_thumbnail — highlight cell, update path label
        // ─────────────────────────────────────────────────────────────────────────────
        void SkinBrowserDialog::select_thumbnail(wxPanel *cell,
                                                 const std::string &path,
                                                 const std::string &category)
        {
            // De-select previous
            if (m_selected_cell && m_selected_cell != cell)
            {
                m_selected_cell->SetBackgroundColour(kNormBg);
                m_selected_cell->Refresh();
                // Also refresh all children so labels update colour
                for (wxWindowList::iterator it = m_selected_cell->GetChildren().begin();
                     it != m_selected_cell->GetChildren().end(); ++it)
                    (*it)->SetBackgroundColour(kNormBg);
            }

            m_selected_cell = cell;
            cell->SetBackgroundColour(kSelBg);
            for (wxWindowList::iterator it = cell->GetChildren().begin();
                 it != cell->GetChildren().end(); ++it)
                (*it)->SetBackgroundColour(kSelBg);
            cell->Refresh();

            m_selected_path = path;

            // Pull category defaults
            if (m_meta.count(category))
            {
                m_tile_mm = m_meta.at(category).tile_mm;
                m_relief = m_meta.at(category).relief;
            }

            // Path label — show just filename for readability
            m_path_label->SetLabel(fs::path(path).filename().string());
            m_ok_btn->Enable(true);
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // on_category_selected — sync thumbnail panel with list selection
        // ─────────────────────────────────────────────────────────────────────────────
        void SkinBrowserDialog::on_category_selected(wxCommandEvent & /*evt*/)
        {
            int sel = m_cat_list->GetSelection();
            if (sel == wxNOT_FOUND)
                return;

            const wxString item = m_cat_list->GetString(sel);
            // Skip group-header separator lines (start with ──)
            if (item.StartsWith("──"))
            {
                // Move to the next real item if possible
                if (sel + 1 < (int)m_cat_list->GetCount())
                {
                    m_cat_list->SetSelection(sel + 1);
                    sel = sel + 1;
                }
                else
                    return;
            }

            // Find the matching CategoryInfo by display name (strip leading spaces)
            const std::string display = item.Strip(wxString::leading).ToStdString();
            for (const auto &ci : m_categories)
            {
                if (ci.display == display)
                {
                    populate_thumbnails(ci.folder);
                    return;
                }
            }
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // on_ok
        // ─────────────────────────────────────────────────────────────────────────────
        void SkinBrowserDialog::on_ok(wxCommandEvent & /*evt*/)
        {
            if (m_selected_path.empty())
            {
                wxMessageBox(_L("Please select a skin thumbnail first."),
                             _L("No selection"), wxICON_INFORMATION | wxOK, this);
                return;
            }
            EndModal(wxID_OK);
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // variant_label — map 1-based variant index to a human-readable label
        //
        // Variants are generated by generate_skin_assets.py as:
        //   4 pitches  × 5 depths = 20 variants
        //   pitches:  Coarse(4mm)  Medium(6mm)  Fine(10mm)  Ultra(16mm)
        //   depths:   Flat         Bevel        Dome        Sharp        Micro
        //   order:    01=Coarse·Flat … 05=Coarse·Micro, 06=Medium·Flat … 20=Ultra·Micro
        // ─────────────────────────────────────────────────────────────────────────────
        std::string SkinBrowserDialog::variant_label(int one_based_index)
        {
            static const char *pitches[] = {"Coarse", "Medium", "Fine", "Ultra"};
            static const char *depths[] = {"Flat", "Bevel", "Dome", "Sharp", "Micro"};

            if (one_based_index < 1 || one_based_index > kVariantCount)
                return std::to_string(one_based_index);

            const int idx = one_based_index - 1; // 0-based
            const int pitch = idx / 5;           // 0-3
            const int depth = idx % 5;           // 0-4

            return std::string(pitches[pitch]) + L" \u00B7 " + depths[depth];
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // folder_to_display — "reptile_scales" → "Reptile Scales"
        // ─────────────────────────────────────────────────────────────────────────────
        static std::string folder_to_display_impl(const std::string &folder)
        {
            std::string out;
            bool cap_next = true;
            for (char c : folder)
            {
                if (c == '_')
                {
                    out += ' ';
                    cap_next = true;
                }
                else if (cap_next)
                {
                    out += (char)std::toupper((unsigned char)c);
                    cap_next = false;
                }
                else
                {
                    out += c;
                }
            }
            return out;
        }

        std::string SkinBrowserDialog::folder_to_display(const std::string &folder)
        {
            return folder_to_display_impl(folder);
        }

    } // namespace GUI
} // namespace Slic3r
