#ifndef PRESET_SYNC_PANEL_HPP
#define PRESET_SYNC_PANEL_HPP

#include <wx/panel.h>
#include <wx/stattext.h>
#include <wx/gauge.h>
#include <wx/bmpbuttn.h>
#include <memory>
#include <string>

#include "Utils/MaterialsDatabaseClient.hpp"

namespace Slic3r
{
    namespace GUI
    {

        // ---------------------------------------------------------------------------
        // PresetSyncPanel
        //
        // A compact status-bar widget that lives at the bottom of the main window
        // (or in Preferences).  Shows one of:
        //
        //   "Material profiles  v2.7.0  ✓ Up to date"
        //   "Material profiles  Checking…"
        //   "Material profiles  Downloading… 42%"   (gauge visible)
        //   "Material profiles  v2.8.0 available  [Update]"
        //   "Material profiles  ⚠ Sync failed      [Retry]"
        //
        // Owns an instance of MaterialsDatabaseClient; callers only need to
        // call reload_presets_callback() when OnBundleReady fires.
        // ---------------------------------------------------------------------------
        class PresetSyncPanel : public wxPanel
        {
        public:
            using OnBundleReady = std::function<void(const std::string &bundle_path)>;

            explicit PresetSyncPanel(wxWindow *parent,
                                     const std::string &cache_dir,
                                     OnBundleReady ready_cb = nullptr);
            ~PresetSyncPanel() override = default;

            // Trigger an immediate re-check (e.g. user clicked Retry or app launched)
            void start_sync();

            // Expose the client for integration tests
            MaterialsDatabaseClient &client() { return *m_client; }

        private:
            void build_ui();
            void set_status_text(const std::string &text);
            void show_progress(bool visible, int pct = 0);

            void on_state_changed(MaterialsDatabaseClient::SyncState state,
                                  const std::string &message);
            void on_bundle_ready(const std::string &bundle_path);

            void on_action_button(wxCommandEvent &);

            std::unique_ptr<MaterialsDatabaseClient> m_client;
            OnBundleReady m_ready_cb;

            wxStaticText *m_label{nullptr};
            wxGauge *m_gauge{nullptr};
            wxButton *m_action_btn{nullptr}; // "Update" or "Retry"

            MaterialsDatabaseClient::SyncState m_last_state{MaterialsDatabaseClient::SyncState::Idle};

            wxDECLARE_EVENT_TABLE();
        };

    } // namespace GUI
} // namespace Slic3r

#endif // PRESET_SYNC_PANEL_HPP
