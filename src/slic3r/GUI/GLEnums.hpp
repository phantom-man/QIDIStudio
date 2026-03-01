#pragma once

namespace Slic3r {
namespace GUI {

    enum class EPickingEffect
    {
        Disabled,
        StencilOutline,
        Silhouette
    };

    enum class ERenderPipelineStage
    {
        Normal,
        Silhouette
    };

} // namespace Slic3r
} // namespace GUI

