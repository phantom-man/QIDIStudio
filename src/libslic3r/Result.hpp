#pragma once
// Result.hpp — std::expected-based Result type for QIDIStudio
//
// Usage:
//   Result<ModelObject*>  load_object(const std::string& path);
//   VoidResult            write_ascii(const std::string& path);
//
//   auto r = load_object(path);
//   if (!r)
//       BOOST_LOG_TRIVIAL(error) << r.error();
//   else
//       use(*r);
//
// Requires C++23 std::expected (MSVC VS 2022 17.3+, GCC 12+, Clang 16+).
// Already enabled by the project-level set(CMAKE_CXX_STANDARD 20) —
// std::expected is part of C++23 but MSVC ships it under /std:c++latest which
// is what CMAKE_CXX_STANDARD 20 maps to on recent MSVC toolsets.
//
// See: cppreference.com/w/cpp/utility/expected
//      P0323R12 (std::expected wording, merged C++23)

#include <expected>
#include <string>
#include <string_view>

namespace Slic3r
{

// ---------------------------------------------------------------------------
// Primary alias.
// Result<T> = T on success, std::string error message on failure.
// ---------------------------------------------------------------------------
template <typename T>
using Result = std::expected<T, std::string>;

// Alias for functions that succeed with no value (previously returning bool).
using VoidResult = std::expected<void, std::string>;

// ---------------------------------------------------------------------------
// Factory helpers — make call-site error paths read like prose.
// ---------------------------------------------------------------------------

/// Create an error result from a string message.
/// Example: return Err("file not found: " + path);
template <typename E>
[[nodiscard]] inline auto Err(E &&e)
{
    return std::unexpected(std::forward<E>(e));
}

/// Overload for string_view to avoid requiring a temporary std::string.
[[nodiscard]] inline std::unexpected<std::string> Err(std::string_view msg)
{
    return std::unexpected(std::string(msg));
}

/// Overload for C-string literals.
[[nodiscard]] inline std::unexpected<std::string> Err(const char *msg)
{
    return std::unexpected(std::string(msg));
}

// ---------------------------------------------------------------------------
// OK helper — symmetric with Err() for clarity at call sites.
// ---------------------------------------------------------------------------

/// Return a successful result.
/// Example: return Ok(volume);
/// Note: for void results just `return {};` works fine.
template <typename T>
[[nodiscard]] inline std::expected<std::remove_cvref_t<T>, std::string> Ok(T &&value)
{
    return std::expected<std::remove_cvref_t<T>, std::string>(std::forward<T>(value));
}

} // namespace Slic3r

// ---------------------------------------------------------------------------
// Usage examples (remove before shipping):
//
// // Old pattern (three incompatible styles in the codebase):
// bool load_stl(Model* model, const std::string& path);   // bool-return
// bool load_amf(Model* model, const std::string& path);   // bool-return
// float volume() const;  // -1.0f sentinel on error
//
// // New pattern with Result<T>:
// Result<TriangleMesh> load_stl_safe(const std::string& path)
// {
//     TriangleMesh mesh;
//     if (!stl_open(&mesh.stl, path.c_str()))
//         return Err("STL open failed: " + path);
//     return Ok(std::move(mesh));
// }
//
// // Caller:
// auto r = load_stl_safe(path);
// if (!r) { BOOST_LOG_TRIVIAL(error) << r.error(); return; }
// process(*r);
// ---------------------------------------------------------------------------
