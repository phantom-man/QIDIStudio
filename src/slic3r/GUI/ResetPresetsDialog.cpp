#include "ResetPresetsDialog.hpp"

#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/button.h>
#include <wx/checklst.h>
#include <wx/checkbox.h>
#include <wx/font.h>
#include <wx/colour.h>

#include "GUI_App.hpp"
#include "I18N.hpp"

namespace Slic3r
{
    namespace GUI
    {

        wxBEGIN_EVENT_TABLE(ResetPresetsDialog, wxDialog)
            wxEND_EVENT_TABLE()

                ResetPresetsDialog::ResetPresetsDialog(wxWindow *parent,
                                                       const std::vector<std::string> &custom_names)
            : wxDialog(parent, wxID_ANY, _L("Reset material profiles"),
                       wxDefaultPosition, wxSize(520, 480),
                       wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER)
        {
            build_ui(custom_names);
        }

        void ResetPresetsDialog::build_ui(const std::vector<std::string> &custom_names)
        {
            SetBackgroundColour(wxColour(0x22, 0x22, 0x22));

            auto *root = new wxBoxSizer(wxVERTICAL);

            // ── Warning header ────────────────────────────────────────────────────────
            auto *warning_icon = new wxStaticText(this, wxID_ANY, wxString::FromUTF8("\u26A0 "));
            wxFont icon_font = warning_icon->GetFont();
            icon_font.SetPointSize(18);
            warning_icon->SetFont(icon_font);
            warning_icon->SetForegroundColour(wxColour(0xFF, 0xCC, 0x00));

            m_warning_label = new wxStaticText(this, wxID_ANY,
                                               _L("Reset to system material profiles"));
            wxFont hdr = m_warning_label->GetFont();
            hdr.SetPointSize(13);
            hdr.SetWeight(wxFONTWEIGHT_BOLD);
            m_warning_label->SetFont(hdr);
            m_warning_label->SetForegroundColour(*wxWHITE);

            auto *hdr_sizer = new wxBoxSizer(wxHORIZONTAL);
            hdr_sizer->Add(warning_icon, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, 6);
            hdr_sizer->Add(m_warning_label, 0, wxALIGN_CENTER_VERTICAL);
            root->Add(hdr_sizer, 0, wxALL, 16);

            // ── Body text ─────────────────────────────────────────────────────────────
            int n = static_cast<int>(custom_names.size());
            wxString body;
            if (n == 0)
            {
                body = _L("No custom profiles found. The system profiles will be "
                          "re-synced from the NexusSlicer materials database.");
            }
            else
            {
                body = wxString::Format(
                    _L("The following %d custom material profile(s) will be "
                       "permanently deleted and cannot be recovered.\n\n"
                       "System profiles will be re-synced from the NexusSlicer "
                       "materials database.\n\n"
                       "Uncheck any profile you want to keep."),
                    n);
            }
            auto *body_label = new wxStaticText(this, wxID_ANY, body,
                                                wxDefaultPosition, wxDefaultSize,
                                                wxST_NO_AUTORESIZE);
            body_label->SetForegroundColour(wxColour(0xCC, 0xCC, 0xCC));
            body_label->Wrap(480);
            root->Add(body_label, 0, wxLEFT | wxRIGHT | wxBOTTOM, 16);

            // ── Profile checklist (hidden when no custom profiles) ────────────────────
            if (n > 0)
            {
                m_count_label = new wxStaticText(this, wxID_ANY,
                                                 wxString::Format(_L("Custom profiles (%d):"), n));
                m_count_label->SetForegroundColour(wxColour(0xAA, 0xAA, 0xAA));
                root->Add(m_count_label, 0, wxLEFT | wxRIGHT | wxBOTTOM, 4);

                wxArrayString items;
                for (auto &name : custom_names)
                    items.Add(wxString::FromUTF8(name.c_str()));

                m_profile_list = new wxCheckListBox(this, wxID_ANY,
                                                    wxDefaultPosition, wxSize(-1, 160),
                                                    items);
                // All checked == will be deleted
                for (unsigned int i = 0; i < m_profile_list->GetCount(); ++i)
                    m_profile_list->Check(i, true);

                root->Add(m_profile_list, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 16);

                // Select all / none toggle
                auto *sel_all = new wxCheckBox(this, wxID_ANY, _L("Select all"));
                sel_all->SetValue(true);
                sel_all->SetForegroundColour(wxColour(0xCC, 0xCC, 0xCC));
                sel_all->Bind(wxEVT_CHECKBOX, &ResetPresetsDialog::on_toggle_select_all, this);
                root->Add(sel_all, 0, wxLEFT | wxBOTTOM, 16);
            }

            root->AddStretchSpacer();

            // ── Separator ─────────────────────────────────────────────────────────────
            auto *sep = new wxStaticLine(this);
            root->Add(sep, 0, wxEXPAND | wxLEFT | wxRIGHT, 0);

            // ── Buttons ───────────────────────────────────────────────────────────────
            m_btn_cancel = new wxButton(this, wxID_CANCEL, _L("Cancel"));
            m_btn_reset = new wxButton(this, wxID_OK,
                                       n > 0 ? _L("Delete and Re-sync") : _L("Re-sync profiles"));
            m_btn_reset->SetForegroundColour(*wxWHITE);
            m_btn_reset->SetBackgroundColour(wxColour(0xC0, 0x30, 0x30));

            auto *btn_sizer = new wxBoxSizer(wxHORIZONTAL);
            btn_sizer->AddStretchSpacer();
            btn_sizer->Add(m_btn_cancel, 0, wxALL, 8);
            btn_sizer->Add(m_btn_reset, 0, wxALL, 8);
            root->Add(btn_sizer, 0, wxEXPAND);

            SetSizerAndFit(root);
            CentreOnParent();

            m_btn_cancel->Bind(wxEVT_BUTTON, &ResetPresetsDialog::on_cancel, this);
            m_btn_reset->Bind(wxEVT_BUTTON, &ResetPresetsDialog::on_reset, this);
        }

        bool ResetPresetsDialog::has_kept_profiles() const
        {
            return m_profile_list != nullptr;
        }

        std::vector<std::string> ResetPresetsDialog::kept_profiles() const
        {
            std::vector<std::string> kept;
            if (!m_profile_list)
                return kept;
            for (unsigned int i = 0; i < m_profile_list->GetCount(); ++i)
            {
                if (!m_profile_list->IsChecked(i)) // unchecked == keep
                    kept.push_back(m_profile_list->GetString(i).ToUTF8().data());
            }
            return kept;
        }

        void ResetPresetsDialog::on_cancel(wxCommandEvent &) { EndModal(wxID_CANCEL); }
        void ResetPresetsDialog::on_reset(wxCommandEvent &) { EndModal(wxID_OK); }

        void ResetPresetsDialog::on_toggle_select_all(wxCommandEvent &evt)
        {
            if (!m_profile_list)
                return;
            bool checked = dynamic_cast<wxCheckBox *>(evt.GetEventObject())->GetValue();
            for (unsigned int i = 0; i < m_profile_list->GetCount(); ++i)
                m_profile_list->Check(i, checked);
        }

    } // namespace GUI
} // namespace Slic3r
