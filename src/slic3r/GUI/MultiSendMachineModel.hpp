#pragma once


#include "DeviceManager.hpp"

namespace Slic3r { 
namespace GUI {

class MultiSendMachineModel : public wxDataViewModel
{
public:
    MultiSendMachineModel();
    ~MultiSendMachineModel();

    void Init();

    wxDataViewItem AddMachine(MachineObject* obj);

private:
};

} // namespace GUI
} // namespace Slic3r

