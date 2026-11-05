// Stage 4 (2026-10-16): the native renderer's tone-map table (a 256x1 texture the game draws and resolves to 111BE000
// every frame) came out as noise. The emulated GPU and the native renderer both leave the resolve in guest memory (the
// native one through its read-back), so the same dump in both modes compares them byte for byte.
#include "ds2_guest_dump.h"

#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <rex/cvar.h>
#include <rex/filesystem.h>
#include <rex/logging.h>
#include <rex/memory.h>

REXCVAR_DEFINE_STRING(ds2_diag_guest_dump, "", "DS2",
                      "Diagnostic: '<seconds>:<hex physical address>:<hex bytes>'; at that time the range is written "
                      "to captures/guest_<address>_<native|emulated>.bin next to the executable. Empty = off");
REXCVAR_DECLARE(bool, sa2_renderer_native);

namespace ds2::guest_dump {
namespace {
std::thread g_thread;
std::mutex g_mutex;
std::condition_variable g_cv;
bool g_stop = false;
}  // namespace

void Start(rex::memory::Memory* memory) {
  const std::string spec = REXCVAR_GET(ds2_diag_guest_dump);
  if (spec.empty() || !memory || g_thread.joinable()) {
    return;
  }
  char* end = nullptr;
  const double seconds = std::strtod(spec.c_str(), &end);
  const uint32_t address = (end && *end == ':') ? uint32_t(std::strtoul(end + 1, &end, 16)) & 0x1FFFFFFF : 0;
  const uint32_t bytes = (end && *end == ':') ? uint32_t(std::strtoul(end + 1, &end, 16)) : 0;
  if (seconds <= 0 || !bytes || bytes > (16u << 20) || uint64_t(address) + bytes > 0x20000000u) {
    REXLOG_WARN("[ds2] ds2_diag_guest_dump '{}' not understood", spec);
    return;
  }
  g_thread = std::thread([memory, seconds, address, bytes] {
    std::unique_lock lock(g_mutex);
    if (g_cv.wait_for(lock, std::chrono::duration<double>(seconds), [] { return g_stop; })) {
      return;
    }
    std::vector<uint8_t> copy(bytes);
    std::memcpy(copy.data(), memory->TranslatePhysical(address), bytes);
    const auto folder = rex::filesystem::GetExecutableFolder() / "captures";
    std::error_code ec;
    std::filesystem::create_directories(folder, ec);
    const auto path = folder / fmt::format("guest_{:08X}_{}.bin", address,
                                           REXCVAR_GET(sa2_renderer_native) ? "native" : "emulated");
    bool good = false;
    if (FILE* file = std::fopen(path.string().c_str(), "wb")) {
      good = std::fwrite(copy.data(), 1, copy.size(), file) == copy.size();
      good = std::fclose(file) == 0 && good;
    }
    REXLOG_INFO("[ds2] guest dump {:08X}+{:X} at {} s: {} ({})", address, bytes, seconds, path.string(),
                good ? "written" : "FAILED");
  });
}

void Stop() {
  {
    std::lock_guard lock(g_mutex);
    g_stop = true;
  }
  g_cv.notify_all();
  if (g_thread.joinable()) {
    g_thread.join();
  }
}

}  // namespace ds2::guest_dump
