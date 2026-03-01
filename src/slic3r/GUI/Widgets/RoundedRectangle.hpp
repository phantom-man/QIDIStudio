#pragma once


#include "../wxExtensions.hpp"

class RoundedRectangle : public wxWindow
{
public:
    RoundedRectangle(wxWindow *parent, wxColour col, wxPoint pos, wxSize size, double radius, int type = 0);
    ~RoundedRectangle(){};

private:
    double m_radius;
    int      m_type;
    wxColour m_color;

public:
    void OnPaint(wxPaintEvent &evt);
    DECLARE_EVENT_TABLE()
};
