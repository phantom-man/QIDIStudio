#pragma once
// GLResource.hpp — RAII wrappers for OpenGL name objects
//
// Usage:
//   GlBuffer  vbo;            // creates via glCreateBuffers
//   GlVao     vao;            // creates via glCreateVertexArrays
//   GlTexture tex;            // creates via glCreateTextures
//
// All wrappers are:
//   - Non-copyable (no accidental reference counting)
//   - Movable (can be stored in std::vector, returned from functions)
//   - Safe to default-construct (id == 0, no GL call until moved-to or manual init)
//   - Destructor calls the appropriate glDelete* IFF id != 0
//
// Thread safety note: GL objects must only be created/destroyed on the GL thread.

#include <utility>   // std::exchange
#include <slic3r/GUI/OpenGLManager.hpp>  // for GL_ASSERT / glsafe (if available)

// Pull in GL types without including the full gl.h chain
// (the OpenGLManager header or glad.h is already included by TUs that use this)
#ifndef GLAPIENTRY
#  ifdef _WIN32
#    define GLAPIENTRY __stdcall
#  else
#    define GLAPIENTRY
#  endif
#endif
typedef unsigned int GLenum;
typedef unsigned int GLuint;

namespace Slic3r::GUI {

// ---------------------------------------------------------------------------
// Primary template — parameterised on a Creator and Deleter function pointer.
// Both must have signature: void (GLsizei n, GLuint* ids).
// ---------------------------------------------------------------------------
template<auto Creator, auto Deleter>
class GlResource {
public:
    // Default-construct: no allocation, id stays 0.
    GlResource() noexcept = default;

    // Allocate immediately.
    void allocate() {
        if (m_id == 0)
            Creator(1, &m_id);
    }

    // Destructor — releases the resource if it was ever allocated.
    ~GlResource() { release(); }

    // Non-copyable.
    GlResource(const GlResource&)            = delete;
    GlResource& operator=(const GlResource&) = delete;

    // Move constructor — steals the id, leaves source in valid-empty state.
    GlResource(GlResource&& o) noexcept
        : m_id(std::exchange(o.m_id, 0)) {}

    // Move assignment — release own resource first, then steal.
    GlResource& operator=(GlResource&& o) noexcept {
        if (this != &o) {
            release();
            m_id = std::exchange(o.m_id, 0);
        }
        return *this;
    }

    // Explicit release (useful when you need to free before going out of scope).
    void release() noexcept {
        if (m_id != 0) {
            Deleter(1, &m_id);
            m_id = 0;
        }
    }

    // Access the underlying object name.
    [[nodiscard]] GLuint id()  const noexcept { return m_id; }
    [[nodiscard]] GLuint get() const noexcept { return m_id; }

    // Allow using the wrapper wherever a raw GLuint is expected.
    [[nodiscard]] explicit operator GLuint() const noexcept { return m_id; }

    // Bool conversion: true if the resource has been allocated.
    [[nodiscard]] explicit operator bool() const noexcept { return m_id != 0; }

private:
    GLuint m_id{0};
};

// ---------------------------------------------------------------------------
// Concrete typedefs for the three most common GL resource kinds.
// ---------------------------------------------------------------------------

// Note: glCreateBuffers / glCreateVertexArrays / glCreateTextures are the DSA
// (Direct State Access) equivalents of glGenBuffers etc.  They require OpenGL
// 4.5+.  The hardware requirement is any GPU released after 2012, which all
// target machines satisfy.
//
// The function-pointer types satisfy the (GLsizei, GLuint*) calling convention.

extern "C" {
    // Forward-declare the DSA entry points (defined in glad.h / GL headers).
    // They are resolved at runtime through the loaded GL function table.
    void GLAPIENTRY glCreateBuffers(int n, unsigned int* buffers);
    void GLAPIENTRY glDeleteBuffers(int n, const unsigned int* buffers);
    void GLAPIENTRY glCreateVertexArrays(int n, unsigned int* arrays);
    void GLAPIENTRY glDeleteVertexArrays(int n, const unsigned int* arrays);
    void GLAPIENTRY glCreateTextures(GLenum target, int n, unsigned int* textures);
    void GLAPIENTRY glDeleteTextures(int n, const unsigned int* textures);
    void GLAPIENTRY glCreateFramebuffers(int n, unsigned int* framebuffers);
    void GLAPIENTRY glDeleteFramebuffers(int n, const unsigned int* framebuffers);
    void GLAPIENTRY glCreateRenderbuffers(int n, unsigned int* renderbuffers);
    void GLAPIENTRY glDeleteRenderbuffers(int n, const unsigned int* renderbuffers);
}

using GlBuffer      = GlResource<glCreateBuffers,      glDeleteBuffers>;
using GlVao         = GlResource<glCreateVertexArrays,  glDeleteVertexArrays>;
using GlFramebuffer = GlResource<glCreateFramebuffers,  glDeleteFramebuffers>;
using GlRenderbuffer = GlResource<glCreateRenderbuffers, glDeleteRenderbuffers>;

// GlTexture is slightly special because glCreateTextures requires a target
// parameter.  We wrap it with a factory function instead.
struct GlTexture {
    GlTexture() noexcept = default;
    explicit GlTexture(GLenum target) { allocate(target); }

    void allocate(GLenum target) {
        if (m_id == 0)
            glCreateTextures(target, 1, &m_id);
    }

    ~GlTexture() { release(); }
    GlTexture(const GlTexture&)            = delete;
    GlTexture& operator=(const GlTexture&) = delete;
    GlTexture(GlTexture&& o) noexcept : m_id(std::exchange(o.m_id, 0)) {}
    GlTexture& operator=(GlTexture&& o) noexcept {
        if (this != &o) { release(); m_id = std::exchange(o.m_id, 0); }
        return *this;
    }

    void release() noexcept {
        if (m_id != 0) { glDeleteTextures(1, &m_id); m_id = 0; }
    }

    [[nodiscard]] GLuint id()  const noexcept { return m_id; }
    [[nodiscard]] GLuint get() const noexcept { return m_id; }
    [[nodiscard]] explicit operator GLuint() const noexcept { return m_id; }
    [[nodiscard]] explicit operator bool()  const noexcept { return m_id != 0; }

private:
    GLuint m_id{0};
};

} // namespace Slic3r::GUI
