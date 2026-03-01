#pragma once


#include <wx/webview.h>

class WebView
{
public:
    static wxWebView *CreateWebView(wxWindow *parent, wxString const &url);
    
    static void LoadUrl(wxWebView * webView, wxString const &url);

    static bool RunScript(wxWebView * webView, wxString const & msg);

    static void RecreateAll();

    /*Find a user data path*/
    static wxString BuildEdgeUserDataPath();
};

