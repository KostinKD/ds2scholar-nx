// Stage 3 diagnostic: how many frames the game presents. Every ds2_swap_log_s seconds one log line with the count of
// VdSwap calls (rex::kernel::xboxkrnl::VdSwapCount) in the interval and in total, so a boot test shows whether the
// game draws at all and at what rate, with the window minimized. 0 turns it off.

#include "ds2_swap_log.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>

#include <rex/cvar.h>
#include <rex/kernel/xboxkrnl/video.h>
#include <rex/logging.h>

REXCVAR_DEFINE_INT32(ds2_swap_log_s, 5, "DS2", "Log the count of VdSwap calls every N seconds (0: off)");

namespace ds2::swap_log {
namespace {
std::thread g_thread;
std::mutex g_mutex;
std::condition_variable g_cv;
bool g_stop = false;
}  // namespace

void Start() {
  const int interval = REXCVAR_GET(ds2_swap_log_s);
  if (interval <= 0 || g_thread.joinable()) {
    return;
  }
  // Polled every millisecond: besides the count, the longest time between two swaps in the interval, so a hitch of a
  // few hundred ms shows even when the second around it still counts 50+ swaps (owner, 2026-10-16: "the game hangs
  // for a few milliseconds to seconds"; whole-second counts at 60/s on a running route).
  g_thread = std::thread([interval] {
    using clock = std::chrono::steady_clock;
    uint64_t last = rex::kernel::xboxkrnl::VdSwapCount();
    uint64_t seen = last;
    auto last_swap_at = clock::now();
    auto report_at = last_swap_at + std::chrono::seconds(interval);
    double longest_ms = 0;
    int over_50 = 0, over_100 = 0;
    std::unique_lock lock(g_mutex);
    while (!g_cv.wait_for(lock, std::chrono::milliseconds(1), [] { return g_stop; })) {
      const auto now_t = clock::now();
      const uint64_t count = rex::kernel::xboxkrnl::VdSwapCount();
      if (count != seen) {
        const double gap = std::chrono::duration<double, std::milli>(now_t - last_swap_at).count();
        longest_ms = std::max(longest_ms, gap);
        over_50 += gap > 50;
        over_100 += gap > 100;
        seen = count;
        last_swap_at = now_t;
      }
      if (now_t >= report_at) {
        // A stall still in progress counts too.
        longest_ms = std::max(longest_ms, std::chrono::duration<double, std::milli>(now_t - last_swap_at).count());
        REXLOG_INFO("[ds2] VdSwap: {} in {} s ({:.1f}/s), {} in total; longest gap {:.0f} ms, gaps > 50 ms {}, > 100 ms {}",
                    count - last, interval, double(count - last) / interval, count, longest_ms, over_50, over_100);
        last = count;
        longest_ms = 0;
        over_50 = over_100 = 0;
        report_at += std::chrono::seconds(interval);
      }
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

}  // namespace ds2::swap_log
