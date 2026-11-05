// Stage 3 diagnostic: still images of what the game presents, taken from the presenter's guest output (as sa2-nx's
// recorder does), so they work with the window minimized. ds2_shot_s lists the seconds after start, e.g.
// "10,20,40"; each one is written as captures/shot_<s>s.ppm next to the executable (tools/ppm_to_png.py makes a PNG).
// Empty turns it off.

#include "ds2_shot.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <filesystem>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <rex/cvar.h>
#include <rex/filesystem.h>
#include <rex/logging.h>
#include <fmt/format.h>
#include <rex/ui/presenter.h>

REXCVAR_DEFINE_STRING(ds2_shot_s, "", "DS2",
                      "Seconds after start to save the presented image (comma separated; empty: off)");
REXCVAR_DEFINE_INT32(ds2_shot_every_s, 0, "DS2", "Also save the presented image every N seconds (0: off)");

namespace ds2::shot {
namespace {
std::thread g_thread;
std::mutex g_mutex;
std::condition_variable g_cv;
bool g_stop = false;

bool WritePpm(const std::filesystem::path& path, const rex::ui::RawImage& image) {
  FILE* f = std::fopen(path.string().c_str(), "wb");
  if (!f) {
    return false;
  }
  std::fprintf(f, "P6\n%u %u\n255\n", image.width, image.height);
  std::vector<uint8_t> row(size_t(image.width) * 3);
  for (uint32_t y = 0; y < image.height; ++y) {
    const uint8_t* src = image.data.data() + size_t(y) * image.stride;
    for (uint32_t x = 0; x < image.width; ++x) {  // R8 G8 B8 X8 -> RGB
      row[x * 3 + 0] = src[x * 4 + 0];
      row[x * 3 + 1] = src[x * 4 + 1];
      row[x * 3 + 2] = src[x * 4 + 2];
    }
    std::fwrite(row.data(), 1, row.size(), f);
  }
  return std::fclose(f) == 0;
}
}  // namespace

void Start(std::function<rex::ui::Presenter*()> get_presenter) {
  std::vector<double> seconds;  // fractions allowed: a sword trail lasts a fraction of a second
  std::stringstream list(REXCVAR_GET(ds2_shot_s));
  for (std::string item; std::getline(list, item, ',');) {
    if (!item.empty()) {
      seconds.push_back(std::stod(item));
    }
  }
  // ds2_shot_every_s: one more shot every N seconds, for play sessions (tools/win/play.ps1), up to 6 hours.
  if (const int every = REXCVAR_GET(ds2_shot_every_s); every > 0) {
    for (int s = every; s <= 6 * 3600; s += every) {
      seconds.push_back(s);
    }
    std::sort(seconds.begin(), seconds.end());
  }
  if (seconds.empty() || g_thread.joinable()) {
    return;
  }
  g_thread = std::thread([get_presenter, seconds] {
    const auto started = std::chrono::steady_clock::now();
    const auto dir = rex::filesystem::GetExecutableFolder() / "captures";
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    for (double s : seconds) {
      {
        std::unique_lock lock(g_mutex);
        if (g_cv.wait_until(lock, started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                                                    std::chrono::duration<double>(s)), [] { return g_stop; })) {
          return;
        }
      }
      rex::ui::Presenter* presenter = get_presenter ? get_presenter() : nullptr;
      rex::ui::RawImage image;
      if (!presenter || !presenter->CaptureGuestOutput(image) || !image.width || !image.height) {
        REXLOG_INFO("[ds2] shot at {} s: no guest output to capture", s);
        continue;
      }
      const auto path = dir / ("shot_" + fmt::format("{:g}", s) + "s.ppm");
      REXLOG_INFO("[ds2] shot at {} s: {}x{} -> {} ({})", s, image.width, image.height, path.string(),
                  WritePpm(path, image) ? "written" : "write failed");
    }
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

}  // namespace ds2::shot
