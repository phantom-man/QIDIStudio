/**
 * StudioApiServer.cpp — NexusSlicer local HTTP API server implementation.
 *
 * Dependencies (all header-only from the Boost 1.84 install):
 *   boost/beast.hpp           — HTTP server
 *   boost/asio.hpp            — I/O event loop
 *   boost/json.hpp            — JSON serialization (Boost.JSON, header-only)
 *
 * Thread safety:
 *   All Plater / Model access is marshalled to the wxWidgets main thread via
 *   `wxGetApp().CallAfter()` + std::promise<T> / std::future<T> round-trip.
 *   The server thread blocks on the future while the main thread fulfils it.
 */

#pragma once // prevent double-include of internal helpers

#include "StudioApiServer.hpp"

// ── Boost.Beast + Boost.Asio ───────────────────────────────────────────────────
// Beast requires BOOST_BEAST_USE_STD_STRING_VIEW for C++17+
#define BOOST_BEAST_USE_STD_STRING_VIEW 1

#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/version.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/io_context.hpp>
#include <boost/asio/strand.hpp>

// ── Boost.JSON (header-only mode) ─────────────────────────────────────────────
#include <boost/json.hpp>

// ── STL ───────────────────────────────────────────────────────────────────────
#include <chrono>
#include <future>
#include <sstream>
#include <string>
#include <vector>

// ── QIDIStudio internals ──────────────────────────────────────────────────────
#include "Plater.hpp"
#include "libslic3r/Model.hpp"
#include "libslic3r/Format/STL.hpp"
#include "GUI_App.hpp"

// ── Platform ──────────────────────────────────────────────────────────────────
#include <wx/wx.h> // wxGetApp(), wxCommandEvent

#include <boost/log/trivial.hpp>

namespace beast = boost::beast;
namespace http = boost::beast::http;
namespace asio = boost::asio;
using tcp = asio::ip::tcp;

namespace Slic3r
{
    namespace GUI
    {

        // ─── Server implementation ────────────────────────────────────────────────────

        struct StudioApiServer::Impl
        {
            asio::io_context ioc{1}; // single-thread io_context
            tcp::acceptor acceptor{ioc};
        };

        // ─── Constructor / Destructor ─────────────────────────────────────────────────

        StudioApiServer::StudioApiServer(Plater *plater, uint16_t port)
            : m_plater(plater), m_port(port), m_impl(std::make_unique<Impl>())
        {
        }

        StudioApiServer::~StudioApiServer()
        {
            stop();
        }

        // ─── Lifecycle ────────────────────────────────────────────────────────────────

        void StudioApiServer::start()
        {
            if (m_running.exchange(true))
            {
                return; // already running
            }

            try
            {
                tcp::endpoint ep{asio::ip::make_address("127.0.0.1"), m_port};
                m_impl->acceptor.open(ep.protocol());
                m_impl->acceptor.set_option(asio::socket_base::reuse_address(true));
                m_impl->acceptor.bind(ep);
                m_impl->acceptor.listen(asio::socket_base::max_listen_connections);
                BOOST_LOG_TRIVIAL(info) << "[StudioApi] listening on 127.0.0.1:" << m_port;
            }
            catch (const std::exception &ex)
            {
                BOOST_LOG_TRIVIAL(error) << "[StudioApi] start() failed: " << ex.what();
                m_running.store(false);
                return;
            }

            m_thread = std::jthread([this](std::stop_token st)
                                    { _serve_loop(std::move(st)); });
        }

        void StudioApiServer::stop()
        {
            if (!m_running.exchange(false))
            {
                return; // already stopped
            }
            // Cancel the acceptor so the server thread unblocks
            asio::post(m_impl->ioc, [this]()
                       {
        beast::error_code ec;
        m_impl->acceptor.cancel(ec);
        m_impl->acceptor.close(ec); });
            // jthread destructor auto-requests stop + joins
        }

        // ─── Request dispatch helpers ─────────────────────────────────────────────────

        namespace
        {

            // Run a callable on the wxWidgets main thread and block until it returns T.
            // Callable signature:  T callable()
            template <typename T, typename Fn>
            T call_on_main_thread(Fn &&fn)
            {
                std::promise<T> p;
                std::future<T> fut = p.get_future();

                wxGetApp().CallAfter([fn = std::forward<Fn>(fn), &p]() mutable
                                     {
        try {
            p.set_value(fn());
        } catch (...) {
            p.set_exception(std::current_exception());
        } });

                return fut.get(); // blocks server thread — OK (not the UI thread)
            }

            // Build a minimal HTTP response helper
            template <class Body, class Allocator>
            http::response<http::string_body>
            make_response(http::request<Body, http::basic_fields<Allocator>> &req,
                          http::status status,
                          std::string_view content_type,
                          std::string body)
            {
                http::response<http::string_body> res{status, req.version()};
                res.set(http::field::server, "NexusSlicer/" BOOST_BEAST_VERSION_STRING);
                res.set(http::field::content_type, content_type);
                res.set(http::field::access_control_allow_origin, "*"); // allow VS Code webview
                res.keep_alive(req.keep_alive());
                res.body() = std::move(body);
                res.prepare_payload();
                return res;
            }

            // Serialise all volumes in the model to a binary STL byte vector.
            // Must be called on the main thread (owns the Model).
            std::vector<uint8_t> model_to_stl(Model *model, bool selected_only = false)
            {
                if (!model)
                {
                    return {};
                }

                // Collect triangles from all objects (or selected volumes)
                TriangleMesh merged;
                for (const ModelObject *obj : model->objects)
                {
                    if (!obj)
                    {
                        continue;
                    }
                    for (const ModelVolume *vol : obj->volumes)
                    {
                        if (!vol || vol->type() != ModelVolumeType::MODEL_PART)
                        {
                            continue;
                        }
                        // TODO: respect `selected_only` once selection API is stable
                        TriangleMesh mesh = vol->mesh();
                        mesh.transform(obj->instances.empty()
                                           ? Transform3d::Identity()
                                           : obj->instances[0]->get_matrix());
                        merged.merge(mesh);
                    }
                }

                if (merged.empty())
                {
                    return {};
                }

                // Write to an in-memory buffer via a std::ostringstream
                // Binary STL: 80-byte header + uint32 count + (50 bytes × count)
                const auto &facets = merged.its.indices;
                const auto &verts = merged.its.vertices;
                const uint32_t tri_count = static_cast<uint32_t>(facets.size());

                std::vector<uint8_t> buf;
                buf.reserve(84 + 50 * tri_count);

                // 80-byte header
                const char header[] = "NexusSlicer binary STL export                                                   ";
                buf.insert(buf.end(), header, header + 80);

                // Triangle count
                const uint8_t *cnt_bytes = reinterpret_cast<const uint8_t *>(&tri_count);
                buf.insert(buf.end(), cnt_bytes, cnt_bytes + 4);

                for (const auto &face : facets)
                {
                    const auto &v0 = verts[face[0]];
                    const auto &v1 = verts[face[1]];
                    const auto &v2 = verts[face[2]];

                    // Compute normal
                    const Vec3f edge1 = v1 - v0, edge2 = v2 - v0;
                    Vec3f n = edge1.cross(edge2);
                    const float len = n.norm();
                    if (len > 1e-12f)
                    {
                        n /= len;
                    }

                    // Normal (3 floats)
                    const uint8_t *np = reinterpret_cast<const uint8_t *>(n.data());
                    buf.insert(buf.end(), np, np + 12);
                    // Vertices (3 × 3 floats)
                    for (int vi : {0, 1, 2})
                    {
                        const uint8_t *vp = reinterpret_cast<const uint8_t *>(verts[face[vi]].data());
                        buf.insert(buf.end(), vp, vp + 12);
                    }
                    // Attribute byte count (2 bytes, = 0)
                    buf.push_back(0x00);
                    buf.push_back(0x00);
                }

                return buf;
            }

            // Serialise current slicer config snapshot as compact JSON
            std::string config_to_json(const Plater *plater)
            {
                if (!plater)
                {
                    return "{}";
                }

                boost::json::object obj;
                // Expose the subset of config most useful for the VS Code extension
                try
                {
                    const auto &config = plater->config();
                    obj["layer_height"] = config.opt_float("layer_height");
                    obj["first_layer_height"] = config.opt_float("first_layer_height");
                    obj["infill_density"] = config.opt_float("fill_density");
                    obj["perimeters"] = config.opt_int("perimeters");
                    obj["support_material"] = config.opt_bool("support_material");
                    obj["brim_width"] = config.opt_float("brim_width");
                    obj["filament_diameter"] = config.opt_float("filament_diameter");
                    obj["nozzle_diameter"] = config.opt_float("nozzle_diameter");
                }
                catch (const std::exception &ex)
                {
                    obj["_error"] = ex.what();
                }

                return boost::json::serialize(obj);
            }

        } // anonymous namespace

        // ─── HTTP request handler (runs on server thread) ─────────────────────────────

        template <class Body, class Allocator>
        static http::response<http::string_body>
        handle_request(
            http::request<Body, http::basic_fields<Allocator>> &&req,
            Plater *plater)
        {
            using namespace std::string_view_literals;

            const auto target = req.target();
            const auto method = req.method();

            // CORS pre-flight
            if (method == http::verb::options)
            {
                http::response<http::string_body> res{http::status::no_content, req.version()};
                res.set(http::field::access_control_allow_origin, "*");
                res.set(http::field::access_control_allow_methods, "GET, POST, OPTIONS");
                res.set(http::field::access_control_allow_headers, "Content-Type");
                res.keep_alive(req.keep_alive());
                res.prepare_payload();
                return res;
            }

            // ── GET /api/status ────────────────────────────────────────────────────
            if (method == http::verb::get && target == "/api/status")
            {
                boost::json::object jobj;
                jobj["status"] = "ok";
                jobj["version"] = "1.0";
                jobj["product"] = "NexusSlicer";
                return make_response(req, http::status::ok, "application/json",
                                     boost::json::serialize(jobj));
            }

            // ── GET /api/mesh/selected ─────────────────────────────────────────────
            if (method == http::verb::get && target == "/api/mesh/selected")
            {
                std::vector<uint8_t> stl_bytes = call_on_main_thread<std::vector<uint8_t>>(
                    [plater]() -> std::vector<uint8_t>
                    {
                        if (!plater)
                        {
                            return {};
                        }
                        Model *model = const_cast<Model *>(&plater->model());
                        return model_to_stl(model, /*selected_only=*/true);
                    });

                if (stl_bytes.empty())
                {
                    return make_response(req, http::status::not_found,
                                         "application/json", R"({"error":"No mesh selected"})");
                }

                http::response<http::string_body> res{http::status::ok, req.version()};
                res.set(http::field::server, "NexusSlicer");
                res.set(http::field::content_type, "model/stl");
                res.set(http::field::access_control_allow_origin, "*");
                res.set("Content-Disposition", "attachment; filename=\"mesh.stl\"");
                res.keep_alive(req.keep_alive());
                res.body().assign(reinterpret_cast<const char *>(stl_bytes.data()), stl_bytes.size());
                res.prepare_payload();
                return res;
            }

            // ── GET /api/mesh/all ──────────────────────────────────────────────────
            if (method == http::verb::get && target == "/api/mesh/all")
            {
                std::vector<uint8_t> stl_bytes = call_on_main_thread<std::vector<uint8_t>>(
                    [plater]() -> std::vector<uint8_t>
                    {
                        if (!plater)
                        {
                            return {};
                        }
                        Model *model = const_cast<Model *>(&plater->model());
                        return model_to_stl(model, /*selected_only=*/false);
                    });

                if (stl_bytes.empty())
                {
                    return make_response(req, http::status::not_found,
                                         "application/json", R"({"error":"No objects in scene"})");
                }

                http::response<http::string_body> res{http::status::ok, req.version()};
                res.set(http::field::server, "NexusSlicer");
                res.set(http::field::content_type, "model/stl");
                res.set(http::field::access_control_allow_origin, "*");
                res.set("Content-Disposition", "attachment; filename=\"all_meshes.stl\"");
                res.keep_alive(req.keep_alive());
                res.body().assign(reinterpret_cast<const char *>(stl_bytes.data()), stl_bytes.size());
                res.prepare_payload();
                return res;
            }

            // ── GET /api/config/current ────────────────────────────────────────────
            if (method == http::verb::get && target == "/api/config/current")
            {
                std::string json = call_on_main_thread<std::string>(
                    [plater]() -> std::string
                    {
                        return config_to_json(plater);
                    });
                return make_response(req, http::status::ok, "application/json", std::move(json));
            }

            // ── 404 catch-all ──────────────────────────────────────────────────────
            return make_response(req, http::status::not_found, "application/json",
                                 R"({"error":"Not found"})");
        }

        // ─── Server event loop (runs on m_thread) ─────────────────────────────────────

        void StudioApiServer::_serve_loop(std::stop_token st)
        {
            beast::error_code ec;

            while (!st.stop_requested() && m_running.load())
            {
                tcp::socket socket{m_impl->ioc};
                m_impl->acceptor.accept(socket, ec);

                if (ec == asio::error::operation_aborted ||
                    ec == beast::errc::operation_canceled)
                {
                    break; // shutdown requested
                }
                if (ec)
                {
                    BOOST_LOG_TRIVIAL(warning) << "[StudioApi] accept error: " << ec.message();
                    continue;
                }

                // ── Synchronous single-request session (HTTP/1.1) ──────────────────
                try
                {
                    beast::flat_buffer buffer;
                    http::request<http::string_body> req;

                    // 5-second read timeout
                    socket.set_option(asio::ip::tcp::no_delay(true));
                    beast::get_lowest_layer(socket).expires_after(std::chrono::seconds(5));

                    http::read(socket, buffer, req, ec);
                    if (ec)
                    {
                        continue;
                    }

                    // Log request (best-effort)
                    BOOST_LOG_TRIVIAL(debug) << "[StudioApi] "
                                             << req.method_string() << " " << req.target();

                    if (on_request)
                    {
                        on_request(std::string(req.method_string()),
                                   std::string(req.target()));
                    }

                    auto res = handle_request(std::move(req), m_plater);
                    http::write(socket, res, ec);

                    socket.shutdown(tcp::socket::shutdown_send, ec);
                }
                catch (const std::exception &ex)
                {
                    BOOST_LOG_TRIVIAL(warning) << "[StudioApi] session error: " << ex.what();
                }
            }

            BOOST_LOG_TRIVIAL(info) << "[StudioApi] server stopped.";
        }

    }
} // namespace Slic3r::GUI
