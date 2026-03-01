#pragma once



namespace Slic3r { namespace GUI {
    
enum PartState {
    psUnCheck,
    psChecked,
    psSkipped
};


typedef std::vector<std::pair<int, PartState>> PartsInfo;

}}

