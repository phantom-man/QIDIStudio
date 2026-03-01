#pragma once

#include <admesh/stl.h>

namespace Slic3r {

class Model;
class TriangleMesh;
class ModelObject;

// Load an STL file into a provided model.
[[nodiscard]] extern bool load_stl(const char *path, Model *model, const char *object_name = nullptr, ImportstlProgressFn stlFn = nullptr, int custom_header_length = 80);

[[nodiscard]] extern bool store_stl(const char *path, TriangleMesh *mesh, bool binary);
[[nodiscard]] extern bool store_stl(const char *path, ModelObject *model_object, bool binary);
[[nodiscard]] extern bool store_stl(const char *path, Model *model, bool binary);

}; // namespace Slic3r

