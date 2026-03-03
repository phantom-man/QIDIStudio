#include "PresetSyncPanel.hpp"

#include <wx/sizer.h>
#include <wx/button.h>
#include <wx/gauge.h>

#include "GUI_App.hpp"
#include "I18N.hpp"
#include "libslic3r/AppConfig.hpp"

namespace Slic3r
{
    namespace GUI
    {

        wxBEGIN_EVENT_TABLE(PresetSyncPanel, wxPanel)
            wxEND_EVENT_TABLE()

                PresetSyncPanel::PresetSyncPanel(wxWindow *parent,
                                                 const std::string &cache_dir,
                                                 OnBundleReady ready_cb)
            : wxPanel(parent, wxID_ANY), m_ready_cb(std::move(ready_cb))
        {
            m_client = std::make_unique<MaterialsDatabaseClient>(cache_dir);

            m_client->set_on_state_changed([this](MaterialsDatabaseClient::SyncState s,
                                                  const std::string &msg)
                                           { on_state_changed(s, msg); });
            m_client->set_on_bundle_ready([this](const std::string &path)
                                          { on_bundle_ready(path); });

            build_ui();
        }

        void PresetSyncPanel::build_ui()
        {
            SetBackgroundColour(GetParent()->GetBackgroundColour());

            auto *sizer = new wxBoxSizer(wxHORIZONTAL);

            m_label = new wxStaticText(this, wxID_ANY, _L("Material profiles  \xC2\xB7  checking…"));
            m_label->SetForegroundColour(wxColour(0xAA, 0xAA, 0xAA));
            sizer->Add(m_label, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, 8);

            m_gauge = new wxGauge(this, wxID_ANY, 100, wxDefaultPosition, wxSize(120, 14));
            m_gauge->Hide();
            sizer->Add(m_gauge, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, 8);

            m_action_btn = new wxButton(this, wxID_ANY, _L("Update"),
                                        wxDefaultPosition, wxSize(80, -1));
            m_action_btn->Hide();
            m_action_btn->Bind(wxEVT_BUTTON, &PresetSyncPanel::on_action_button, this);
            sizer->Add(m_action_btn, 0, wxALIGN_CENTER_VERTICAL);

            SetSizerAndFit(sizer);
        }

        void PresetSyncPanel::start_sync()
        {
            set_status_text("Material profiles  \xC2\xB7  checking\xE2\x80\xA6");
            m_action_btn->Hide();
            show_progress(false);
            Layout();
            m_client->start_sync();
        }

        void PresetSyncPanel::set_status_text(const std::string &text)
        {
            m_label->SetLabel(wxString::FromUTF8(text.c_str()));
            m_label->GetParent()->Layout();
        }

        void PresetSyncPanel::show_progress(bool visible, int pct)
        {
            if (visible)
            {
                m_gauge->SetValue(pct);
                m_gauge->Show();
            }
            else
            {
                m_gauge->Hide();
            }
            Layout();
            GetParent()->Layout();
        }

        void PresetSyncPanel::on_state_changed(MaterialsDatabaseClient::SyncState state,
                                               const std::string &message)
        {
            m_last_state = state;
            using S = MaterialsDatabaseClient::SyncState;

            m_action_btn->Hide();
            show_progress(false);

            switch (state)
            {
            case S::Idle:
                set_status_text("Material profiles  \xC2\xB7  idle");
                break;
            case S::Checking:
                set_status_text("Material profiles  \xC2\xB7  checking\xE2\x80\xA6");
                break;
            case S::Downloading:
            {
                // Extract percentage from message if present
                auto pct_pos = message.rfind('%');
                int pct = 0;
                if (pct_pos != std::string::npos)
                {
                    auto space = message.rfind(' ', pct_pos - 1);
                    if (space != std::string::npos)
                        pct = std::stoi(message.substr(space + 1, pct_pos - space - 1));
                }
                show_progress(true, pct);
                set_status_text(message);
                break;
            }
            case S::UpToDate:
                set_status_text(message.empty()
                                    ? "Material profiles  \xC2\xB7  \xE2\x9C\x93 Up to date"
                                    : message);
                break;
            case S::Updated:
                set_status_text(message.empty()
                                    ? "Material profiles  \xC2\xB7  \xE2\x9C\x93 Updated"
                                    : message);
                break;
            case S::Error:
                set_status_text("\xE2\x9A\xA0 " + (message.empty() ? "Sync failed" : message));
                m_action_btn->SetLabel(_L("Retry"));
                m_action_btn->Show();
                break;
            }
            Layout();
            GetParent()->Layout();
        }

        void PresetSyncPanel::on_bundle_ready(const std::string &bundle_path)
        {
            if (m_ready_cb)
                m_ready_cb(bundle_path);
        }

        void PresetSyncPanel::on_action_button(wxCommandEvent &)
        {
            // Both "Update" and "Retry" do the same thing: re-trigger sync
            m_client->cancel();
            start_sync();
        }

    } // namespace GUI
} // namespace Slic3r
