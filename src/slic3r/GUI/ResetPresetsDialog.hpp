#ifndef RESET_PRESETS_DIALOG_HPP
#define RESET_PRESETS_DIALOG_HPP

#include <wx/dialog.h>
#include <vector>
#include <string>

class wxStaticText;
class wxCheckListBox;
class wxButton;

namespace Slic3r
{
    namespace GUI
    {

        // ---------------------------------------------------------------------------
        // ResetPresetsDialog
        //
        // Warns the user that resetting will permanently delete their custom filament
        // profiles then re-syncs system profiles from the materials database cache.
        //
        // Usage:
        //   ResetPresetsDialog dlg(parent);
        //   if (dlg.ShowModal() == wxID_OK) {
        //       // Caller deletes user filament profiles and calls preset_bundle->reset()
        //       do_reset();
        //   }
        // ---------------------------------------------------------------------------
        class ResetPresetsDialog : public wxDialog
        {
        public:
            // custom_names: list of user-created filament preset names to display.
            explicit ResetPresetsDialog(wxWindow *parent,
                                        const std::vector<std::string> &custom_names = {});

            // Returns true when the user also checked "keep these selected profiles".
            // Kept profiles are accessible via kept_profiles().
            bool has_kept_profiles() const;
            std::vector<std::string> kept_profiles() const;

        private:
            void build_ui(const std::vector<std::string> &custom_names);
            void on_cancel(wxCommandEvent &);
            void on_reset(wxCommandEvent &);
            void on_toggle_select_all(wxCommandEvent &);

            wxStaticText *m_warning_label{nullptr};
            wxStaticText *m_count_label{nullptr};
            wxCheckListBox *m_profile_list{nullptr};
            wxButton *m_btn_reset{nullptr};
            wxButton *m_btn_cancel{nullptr};

            wxDECLARE_EVENT_TABLE();
        };

    } // namespace GUI
} // namespace Slic3r

#endif // RESET_PRESETS_DIALOG_HPP
