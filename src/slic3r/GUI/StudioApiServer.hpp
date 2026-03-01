#pragma once
/**
 * StudioApiServer.hpp — NexusSlicer local HTTP API server.
 *
 * Serves a minimal REST API on localhost:17233 that allows the
 * VS Code extension (NexusSlicer Viewer) to:
 *   GET  /api/status            → health check
 *   GET  /api/mesh/selected     → binary STL of the currently selected volume
 *   GET  /api/mesh/all          → all model objects as a single binary STL
 *   GET  /api/config/current    → key slicer settings as JSON
 *   POST /api/slice/preview     → G-code stats for the current plate (async)
 *
 * Threading model:
 *   - The server runs on a private std::jthread (not the wxWidgets UI thread).
 *   - To read model state, handlers post a task to the main thread via
 *     `CallAfterOnMainThread()` and block the server thread on a std::promise.
 *   - All wx / GUI calls MUST go through `CallAfterOnMainThread`.
 *
 * Lifecycle:
 *   StudioApiServer srv(plater, 17233);
 *   srv.start();          // call from GUI thread after Plater ready
 *   // ...
 *   srv.stop();           // call from GUI thread during shutdown
 */

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <thread>

namespace Slic3r
{
    namespace GUI
    {

        class Plater; // forward — avoid including the full header

        class StudioApiServer
        {
        public:
            explicit StudioApiServer(Plater *plater, uint16_t port = 17233);
            ~StudioApiServer();

            // ── Lifecycle ────────────────────────────────────────────────────────────
            void start(); ///< Start listening. Called from the GUI thread.
            void stop();  ///< Stop listening and join the server thread.

            bool is_running() const noexcept { return m_running.load(); }
            uint16_t port() const noexcept { return m_port; }

            // ── Callback hooks (set before start()) ──────────────────────────────────
            /** Optional: called on the server thread when any request is handled. */
            std::function<void(const std::string &method, const std::string &target)> on_request;

        private:
            Plater *m_plater;
            uint16_t m_port;
            std::atomic<bool> m_running{false};
            std::jthread m_thread;

            // Pimpl to avoid pulling beast/asio headers into every TU that includes this
            struct Impl;
            std::unique_ptr<Impl> m_impl;

            void _serve_loop(std::stop_token st);
        };

    }
} // namespace Slic3r::GUI
