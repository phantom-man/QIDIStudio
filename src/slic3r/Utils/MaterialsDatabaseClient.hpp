#ifndef MATERIALS_DATABASE_CLIENT_HPP
#define MATERIALS_DATABASE_CLIENT_HPP

#include <string>
#include <functional>
#include <atomic>
#include <thread>
#include <mutex>
#include <optional>

namespace Slic3r
{

// ---------------------------------------------------------------------------
// Build-time constants — values injected by CI via -DNEXUS_MATERIALS_API_KEY=
// Falls back to empty string; public/read endpoints work without a key.
// ---------------------------------------------------------------------------
#ifndef NEXUS_MATERIALS_API_BASE_URL
#define NEXUS_MATERIALS_API_BASE_URL "https://materials.nexusslicer.io/v1"
#endif

#ifndef NEXUS_MATERIALS_API_KEY
#define NEXUS_MATERIALS_API_KEY ""
#endif

    // ---------------------------------------------------------------------------
    // MaterialsDatabaseClient
    //
    // Responsibilities:
    //   1. Check the remote manifest for a newer profile bundle version.
    //   2. Download the bundle zip on cache miss.
    //   3. Unpack into the local vendor cache dir.
    //   4. Notify the GUI layer via callbacks (always called on the main thread).
    //
    // Threading model:
    //   Construction and all public methods are safe to call from the main thread.
    //   Network I/O runs on a detached worker thread.
    //   Callbacks are posted back via wxCallAfter so they arrive on the wx event loop.
    // ---------------------------------------------------------------------------
    class MaterialsDatabaseClient
    {
    public:
        // Status visible to status-bar panel
        enum class SyncState
        {
            Idle,
            Checking,
            Downloading,
            UpToDate,
            Updated, // bundle was just replaced; caller should reload presets
            Error
        };

        struct BundleInfo
        {
            std::string version; // semver string, e.g. "2.7.0"
            std::string url;     // absolute URL to the .zip
            std::string sha256;  // hex digest for integrity check
            std::size_t size_bytes = 0;
        };

        using OnStateChanged = std::function<void(SyncState, const std::string &message)>;
        using OnBundleReady = std::function<void(const std::string &bundle_path)>; // extracted dir

        // cache_dir : e.g. AppConfig::get_data_dir() / "cache" / "materials"
        explicit MaterialsDatabaseClient(const std::string &cache_dir);
        ~MaterialsDatabaseClient();

        // Non-copyable
        MaterialsDatabaseClient(const MaterialsDatabaseClient &) = delete;
        MaterialsDatabaseClient &operator=(const MaterialsDatabaseClient &) = delete;

        // Register callbacks (call before start())
        void set_on_state_changed(OnStateChanged cb) { m_on_state = std::move(cb); }
        void set_on_bundle_ready(OnBundleReady cb) { m_on_ready = std::move(cb); }

        // Kick off the background version check + optional download.
        // Safe to call multiple times; a running check is a no-op.
        void start_sync();

        // Cancel any in-flight network operation.
        void cancel();

        // Synchronous helpers (called from background thread internally)
        // Exposed for unit-tests.
        static std::optional<BundleInfo> fetch_manifest(const std::string &base_url,
                                                        const std::string &api_key);
        static bool download_bundle(const BundleInfo &info,
                                    const std::string &dest_path,
                                    std::atomic<bool> &cancelled,
                                    std::function<void(int /*pct*/)> progress_cb);
        static bool verify_sha256(const std::string &file_path,
                                  const std::string &expected_hex);
        static bool unzip_bundle(const std::string &zip_path,
                                 const std::string &out_dir);

        // Returns the path of the most recently installed bundle dir (may be empty)
        std::string installed_bundle_dir() const;
        // Returns installed version string, or "" if none
        std::string installed_version() const;

    private:
        void worker_thread();
        void notify_state(SyncState s, const std::string &msg = {});
        void write_version_stamp(const std::string &version);
        std::string read_version_stamp() const;

        std::string m_cache_dir;
        std::string m_bundle_dir; // cache_dir / "bundle"
        std::string m_api_key = NEXUS_MATERIALS_API_KEY;
        std::string m_base_url = NEXUS_MATERIALS_API_BASE_URL;

        OnStateChanged m_on_state;
        OnBundleReady m_on_ready;

        std::atomic<bool> m_running{false};
        std::atomic<bool> m_cancelled{false};
        std::thread m_worker;
        mutable std::mutex m_mutex;
    };

} // namespace Slic3r

#endif // MATERIALS_DATABASE_CLIENT_HPP
