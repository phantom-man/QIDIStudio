#pragma once


#include "../wxExtensions.hpp"

#include <wx/tglbtn.h>

namespace Slic3r {
namespace GUI {

class RadioBox : public wxBitmapToggleButton
{
public:
    RadioBox(wxWindow *parent);

public:
    void SetValue(bool value) override;
	bool GetValue();
    void Rescale();
    bool Disable() {
        return wxBitmapToggleButton::Disable();
    }
    bool Enable() {
        return wxBitmapToggleButton::Enable();
    }

private:
    void update();

private:
    ScalableBitmap m_on;
    ScalableBitmap m_off;
    ScalableBitmap m_ban;
};

}}



