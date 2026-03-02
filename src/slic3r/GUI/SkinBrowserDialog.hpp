#pragma once

#include <wx/dialog.h>
#include <wx/listbox.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/button.h>
#include <wx/stattext.h>
#include <wx/panel.h>
#include <wx/bitmap.h>

#include <string>
#include <vector>
#include <map>

namespace Slic3r
{
    namespace GUI
    {

        // Suggested print parameters read from resources/assets/metadata.json for
        // each skin asset category.
        struct SkinAssetMeta
        {
            double tile_mm{15.0};
            double relief{1.2};
            std::string label; // human-readable display name
            std::string group; // grouping: Organic / Industrial / Natural / Geometric
        };

        // ─────────────────────────────────────────────────────────────────────────────
        // SkinBrowserDialog
        //
        // Two-panel gallery dialog for selecting a displacement-map skin asset:
        //
        //   ┌─ Category list ────┬─ Thumbnail grid (4 columns, scrollable) ──────────┐
        //   │  Organic           │  [img] Coarse·Flat   [img] Coarse·Bevel  …       │
        //   │  ▶ Reptile Scales  │  [img] Medium·Flat   [img] Medium·Bevel  …       │
        //   │    Dragon Scales   │  …                                                │
        //   │  Industrial        ├────────────────────────────────────────────────── │
        //   │    Chainmail       │  Selected: reptile_scales_03.png                  │
        //   │    …               │                                          OK Cancel│
        //   └────────────────────┴──────────────────────────────────────────────────┘
        //
        // Call ShowModal().  If wxID_OK:
        //   get_png_path()   → absolute path of the chosen PNG
        //   get_tile_mm()    → category default tile size (mm)
        //   get_relief()     → category default relief depth (mm)
        // ─────────────────────────────────────────────────────────────────────────────
        class SkinBrowserDialog : public wxDialog
        {
        public:
            explicit SkinBrowserDialog(wxWindow *parent);

            // ── Accessors – valid only after ShowModal() returned wxID_OK ─────────
            std::string get_png_path() const { return m_selected_path; }
            double get_tile_mm() const { return m_tile_mm; }
            double get_relief() const { return m_relief; }

        private:
            // ── Internal category record ──────────────────────────────────────────
            struct CategoryInfo
            {
                std::string folder;  // e.g. "reptile_scales"
                std::string display; // e.g. "Reptile Scales"
                std::string group;   // e.g. "Organic"
            };

            // ── UI widgets ────────────────────────────────────────────────────────
            wxListBox *m_cat_list{nullptr};
            wxScrolledWindow *m_thumb_win{nullptr};
            wxSizer *m_thumb_sizer{nullptr};
            wxStaticText *m_path_label{nullptr};
            wxButton *m_ok_btn{nullptr};
            wxPanel *m_selected_cell{nullptr}; // last highlighted thumbnail panel

            // ── Data ─────────────────────────────────────────────────────────────
            std::string m_assets_root;
            std::vector<CategoryInfo> m_categories;
            std::map<std::string, SkinAssetMeta> m_meta;

            // ── Cached result (written in on_ok) ─────────────────────────────────
            std::string m_selected_path;
            double m_tile_mm{15.0};
            double m_relief{1.2};

            // ── Helpers ──────────────────────────────────────────────────────────
            void init_assets_root();
            void load_metadata();
            void build_category_list();                            // populate left listbox
            void populate_thumbnails(const std::string &category); // fill right panel
            void select_thumbnail(wxPanel *cell, const std::string &path,
                                  const std::string &category);

            // variant index → short label, e.g. 3 → "Coarse · Dome"
            static std::string variant_label(int one_based_index);

            // ── Event handlers ───────────────────────────────────────────────────
            void on_category_selected(wxCommandEvent &evt);
            void on_ok(wxCommandEvent &evt);
        };

    } // namespace GUI
} // namespace Slic3r
