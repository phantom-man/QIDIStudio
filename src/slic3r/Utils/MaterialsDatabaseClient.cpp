#include "MaterialsDatabaseClient.hpp"

#include <boost/filesystem.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/property_tree/ptree.hpp>
#include <boost/property_tree/json_parser.hpp>

#include <wx/app.h>

#include <fstream>
#include <sstream>
#include <iomanip>
#include <openssl/sha.h>

// miniz / minizip for zip extraction (already a dep via libslic3r)
#include "miniz/miniz.h"

namespace fs = boost::filesystem;
namespace beast = boost::beast;
namespace http = beast::http;
namespace net = boost::asio;
using tcp = net::ip::tcp;

namespace Slic3r
{

    // ---------------------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------------------
    namespace
    {

        // Parse  https://host[:port]/path  into parts.
        struct UrlParts
        {
            std::string scheme;
            std::string host;
            std::string port;
            std::string target;
        };

        UrlParts parse_url(const std::string &url)
        {
            UrlParts p;
            // Minimal parser — assumes https://
            std::string rest = url;
            auto scheme_end = rest.find("://");
            if (scheme_end != std::string::npos)
            {
                p.scheme = rest.substr(0, scheme_end);
                rest = rest.substr(scheme_end + 3);
            }
            auto path_start = rest.find('/');
            std::string authority;
            if (path_start != std::string::npos)
            {
                authority = rest.substr(0, path_start);
                p.target = rest.substr(path_start);
            }
            else
            {
                authority = rest;
                p.target = "/";
            }
            auto colon = authority.find(':');
            if (colon != std::string::npos)
            {
                p.host = authority.substr(0, colon);
                p.port = authority.substr(colon + 1);
            }
            else
            {
                p.host = authority;
                p.port = (p.scheme == "https") ? "443" : "80";
            }
            return p;
        }

        // Synchronous HTTPS GET -> response body string.
        // Returns empty on error.
        std::string https_get(const std::string &url,
                              const std::string &api_key,
                              const std::atomic<bool> &cancelled)
        {
            try
            {
                auto parts = parse_url(url);
                net::io_context ioc;
                net::ssl::context ssl_ctx(net::ssl::context::tlsv12_client);
                ssl_ctx.set_default_verify_paths();
                beast::ssl_stream<beast::tcp_stream> stream(ioc, ssl_ctx);

                if (!SSL_set_tlsext_host_name(stream.native_handle(), parts.host.c_str()))
                    return {};

                tcp::resolver resolver(ioc);
                auto const results = resolver.resolve(parts.host, parts.port);
                beast::get_lowest_layer(stream).connect(results);
                stream.handshake(net::ssl::stream_base::client);

                http::request<http::empty_body> req{http::verb::get, parts.target, 11};
                req.set(http::field::host, parts.host);
                req.set(http::field::user_agent, "QIDIStudio/1.0 MaterialsSync");
                if (!api_key.empty())
                    req.set("X-API-Key", api_key);

                http::write(stream, req);

                beast::flat_buffer buf;
                http::response<http::string_body> res;
                http::read(stream, buf, res);

                beast::error_code ec;
                stream.shutdown(ec);

                if (res.result() == http::status::ok)
                    return res.body();
            }
            catch (...)
            {
            }
            return {};
        }

        // Download url to dest_path, calling progress_cb with 0-100.
        bool https_download(const std::string &url,
                            const std::string &dest_path,
                            const std::string &api_key,
                            std::size_t expected_bytes,
                            std::atomic<bool> &cancelled,
                            std::function<void(int)> progress_cb)
        {
            try
            {
                auto parts = parse_url(url);
                net::io_context ioc;
                net::ssl::context ssl_ctx(net::ssl::context::tlsv12_client);
                ssl_ctx.set_default_verify_paths();
                beast::ssl_stream<beast::tcp_stream> stream(ioc, ssl_ctx);
                SSL_set_tlsext_host_name(stream.native_handle(), parts.host.c_str());

                tcp::resolver resolver(ioc);
                beast::get_lowest_layer(stream).connect(resolver.resolve(parts.host, parts.port));
                stream.handshake(net::ssl::stream_base::client);

                http::request<http::empty_body> req{http::verb::get, parts.target, 11};
                req.set(http::field::host, parts.host);
                req.set(http::field::user_agent, "QIDIStudio/1.0 MaterialsSync");
                if (!api_key.empty())
                    req.set("X-API-Key", api_key);

                http::write(stream, req);

                // Stream the response body directly to file
                beast::flat_buffer buf;
                http::response_parser<http::dynamic_body> parser;
                parser.body_limit(256 * 1024 * 1024); // 256 MB cap

                std::ofstream out(dest_path, std::ios::binary);
                if (!out.is_open())
                    return false;

                std::size_t received = 0;
                while (!parser.is_done())
                {
                    if (cancelled.load())
                        return false;
                    beast::error_code ec;
                    http::read_some(stream, buf, parser, ec);
                    if (ec && ec != http::error::need_buffer)
                        break;
                    auto &body = parser.get().body();
                    for (auto const &buf_seq : body.data())
                    {
                        auto *data = static_cast<const char *>(buf_seq.data());
                        auto size = buf_seq.size();
                        out.write(data, static_cast<std::streamsize>(size));
                        received += size;
                    }
                    body.consume(body.size());
                    if (expected_bytes > 0 && progress_cb)
                        progress_cb(static_cast<int>(received * 100 / expected_bytes));
                }
                if (progress_cb)
                    progress_cb(100);
                return out.good();
            }
            catch (...)
            {
            }
            return false;
        }

        std::string sha256_file(const std::string &path)
        {
            std::ifstream f(path, std::ios::binary);
            if (!f.is_open())
                return {};
            SHA256_CTX ctx;
            SHA256_Init(&ctx);
            char buf[65536];
            while (f.read(buf, sizeof(buf)) || f.gcount() > 0)
                SHA256_Update(&ctx, buf, static_cast<size_t>(f.gcount()));
            unsigned char digest[SHA256_DIGEST_LENGTH];
            SHA256_Final(digest, &ctx);
            std::ostringstream ss;
            for (auto b : digest)
                ss << std::hex << std::setw(2) << std::setfill('0') << (int)b;
            return ss.str();
        }

    } // namespace anonymous

    // ---------------------------------------------------------------------------
    // MaterialsDatabaseClient
    // ---------------------------------------------------------------------------

    MaterialsDatabaseClient::MaterialsDatabaseClient(const std::string &cache_dir)
        : m_cache_dir(cache_dir), m_bundle_dir(cache_dir + "/bundle")
    {
        fs::create_directories(m_bundle_dir);
    }

    MaterialsDatabaseClient::~MaterialsDatabaseClient()
    {
        cancel();
        if (m_worker.joinable())
            m_worker.join();
    }

    void MaterialsDatabaseClient::start_sync()
    {
        bool expected = false;
        if (!m_running.compare_exchange_strong(expected, true))
            return; // already running

        m_cancelled.store(false);
        m_worker = std::thread([this]
                               { worker_thread(); });
        m_worker.detach();
    }

    void MaterialsDatabaseClient::cancel()
    {
        m_cancelled.store(true);
    }

    // --- Static helpers ----------------------------------------------------------

    std::optional<MaterialsDatabaseClient::BundleInfo>
    MaterialsDatabaseClient::fetch_manifest(const std::string &base_url,
                                            const std::string &api_key)
    {
        std::atomic<bool> dummy{false};
        std::string body = https_get(base_url + "/manifest.json", api_key, dummy);
        if (body.empty())
            return std::nullopt;

        try
        {
            std::istringstream ss(body);
            boost::property_tree::ptree pt;
            boost::property_tree::read_json(ss, pt);

            BundleInfo info;
            info.version = pt.get<std::string>("version");
            info.url = pt.get<std::string>("url");
            info.sha256 = pt.get<std::string>("sha256");
            info.size_bytes = pt.get<std::size_t>("size_bytes", 0);
            return info;
        }
        catch (...)
        {
        }
        return std::nullopt;
    }

    bool MaterialsDatabaseClient::download_bundle(const BundleInfo &info,
                                                  const std::string &dest_path,
                                                  std::atomic<bool> &cancelled,
                                                  std::function<void(int)> progress_cb)
    {
        return https_download(info.url, dest_path, NEXUS_MATERIALS_API_KEY,
                              info.size_bytes, cancelled, progress_cb);
    }

    bool MaterialsDatabaseClient::verify_sha256(const std::string &file_path,
                                                const std::string &expected_hex)
    {
        if (expected_hex.empty())
            return true; // no checksum provided — skip
        return sha256_file(file_path) == expected_hex;
    }

    bool MaterialsDatabaseClient::unzip_bundle(const std::string &zip_path,
                                               const std::string &out_dir)
    {
        mz_zip_archive zip = {};
        if (!mz_zip_reader_init_file(&zip, zip_path.c_str(), 0))
            return false;

        fs::create_directories(out_dir);
        bool ok = true;
        for (mz_uint i = 0; i < mz_zip_reader_get_num_files(&zip); ++i)
        {
            mz_zip_archive_file_stat stat;
            if (!mz_zip_reader_file_stat(&zip, i, &stat))
            {
                ok = false;
                break;
            }
            fs::path dest = fs::path(out_dir) / stat.m_filename;
            if (mz_zip_reader_is_file_a_directory(&zip, i))
            {
                fs::create_directories(dest);
            }
            else
            {
                fs::create_directories(dest.parent_path());
                if (!mz_zip_reader_extract_to_file(&zip, i, dest.string().c_str(), 0))
                {
                    ok = false;
                    break;
                }
            }
        }
        mz_zip_reader_end(&zip);
        return ok;
    }

    std::string MaterialsDatabaseClient::installed_bundle_dir() const
    {
        return m_bundle_dir;
    }

    std::string MaterialsDatabaseClient::installed_version() const
    {
        return read_version_stamp();
    }

    // --- Private -----------------------------------------------------------------

    void MaterialsDatabaseClient::worker_thread()
    {
        notify_state(SyncState::Checking);

        auto manifest = fetch_manifest(m_base_url, m_api_key);
        if (!manifest)
        {
            notify_state(SyncState::Error, "Could not reach materials server");
            m_running.store(false);
            return;
        }

        std::string installed = read_version_stamp();
        if (installed == manifest->version)
        {
            notify_state(SyncState::UpToDate,
                         "Material profiles up to date  \xC2\xB7  v" + manifest->version);
            m_running.store(false);
            return;
        }

        notify_state(SyncState::Downloading,
                     "Downloading material profiles v" + manifest->version + "…");

        std::string zip_path = m_cache_dir + "/materials_" + manifest->version + ".zip";
        bool ok = download_bundle(*manifest, zip_path, m_cancelled,
                                  [this, &manifest](int pct)
                                  {
                                      notify_state(SyncState::Downloading,
                                                   "Downloading material profiles v" + manifest->version + "… " + std::to_string(pct) + "%");
                                  });

        if (!ok || m_cancelled.load())
        {
            fs::remove(zip_path);
            notify_state(SyncState::Error, "Download failed or cancelled");
            m_running.store(false);
            return;
        }

        if (!verify_sha256(zip_path, manifest->sha256))
        {
            fs::remove(zip_path);
            notify_state(SyncState::Error, "Bundle integrity check failed");
            m_running.store(false);
            return;
        }

        // Swap in new bundle
        std::string new_dir = m_bundle_dir + "_new";
        fs::remove_all(new_dir);
        if (!unzip_bundle(zip_path, new_dir))
        {
            notify_state(SyncState::Error, "Bundle extraction failed");
            m_running.store(false);
            return;
        }
        fs::remove(zip_path);

        {
            std::lock_guard<std::mutex> lk(m_mutex);
            fs::remove_all(m_bundle_dir);
            fs::rename(new_dir, m_bundle_dir);
        }
        write_version_stamp(manifest->version);

        notify_state(SyncState::Updated,
                     "Material profiles updated to v" + manifest->version);

        if (m_on_ready)
        {
            std::string dir = m_bundle_dir;
            wxTheApp->CallAfter([this, dir]
                                { m_on_ready(dir); });
        }

        m_running.store(false);
    }

    void MaterialsDatabaseClient::notify_state(SyncState s, const std::string &msg)
    {
        if (m_on_state)
        {
            wxTheApp->CallAfter([this, s, msg]
                                { m_on_state(s, msg); });
        }
    }

    void MaterialsDatabaseClient::write_version_stamp(const std::string &version)
    {
        std::ofstream f(m_cache_dir + "/installed_version.txt");
        if (f.is_open())
            f << version;
    }

    std::string MaterialsDatabaseClient::read_version_stamp() const
    {
        std::ifstream f(m_cache_dir + "/installed_version.txt");
        if (!f.is_open())
            return {};
        std::string v;
        f >> v;
        return v;
    }

} // namespace Slic3r
