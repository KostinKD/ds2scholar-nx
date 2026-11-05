#pragma once
/**
 * ds2-nx (2026-10-16): where the GPU thread's time goes around a hitch. The owner's sessions hitch for 0.35-0.7 s when
 * a new area loads and when a bonfire is lit, always on content seen for the first time; the candidates are shader
 * translation, D3D12 pipeline creation and texture loading. Each is timed and summed per kind and per thread class:
 * "worker" for the pipeline creation threads (async, does not hold a frame), "gpu" for any other thread (the command
 * processor: synchronous, holds the frame). Once a second, if the second had more than 50 ms of such work, one log
 * line with the counts, the sums and the longest single item.
 */

#include <array>
#include <chrono>
#include <cstdint>
#include <mutex>

#include <rex/logging.h>

namespace rex::graphics::d3d12::stall {

// kWait: the GPU thread waiting for the creation threads at the end of a submission (PipelineCache::EndSubmission).
enum Kind { kTranslate, kPipeline, kTexture, kWait, kKindCount };

// Set by the pipeline creation threads of PipelineCache for their whole life.
inline thread_local bool tls_is_worker = false;

struct Totals {
  std::array<uint32_t, kKindCount> count{};
  std::array<double, kKindCount> ms{};
  std::array<double, kKindCount> longest{};
};

inline std::mutex g_mutex;
inline std::array<Totals, 2> g_totals;  // [0] gpu thread(s), [1] worker threads
inline std::chrono::steady_clock::time_point g_report_at{};

inline void Report(std::chrono::steady_clock::time_point now) {
  const auto& g = g_totals[0];
  const auto& w = g_totals[1];
  const double sum = g.ms[0] + g.ms[1] + g.ms[2] + g.ms[3] + w.ms[0] + w.ms[1] + w.ms[2];
  if (sum > 50.0) {
    REXLOG_INFO(
        "[gpu-stall] 1 s: gpu thread: translate {} ({:.0f} ms, max {:.0f}), pipeline {} ({:.0f} ms, max {:.0f}), "
        "texture {} ({:.0f} ms, max {:.0f}), wait for workers {} ({:.0f} ms, max {:.0f}); workers: translate {} "
        "({:.0f} ms), pipeline {} ({:.0f} ms, max {:.0f})",
        g.count[kTranslate], g.ms[kTranslate], g.longest[kTranslate], g.count[kPipeline], g.ms[kPipeline],
        g.longest[kPipeline], g.count[kTexture], g.ms[kTexture], g.longest[kTexture], g.count[kWait], g.ms[kWait],
        g.longest[kWait], w.count[kTranslate],
        w.ms[kTranslate], w.count[kPipeline], w.ms[kPipeline], w.longest[kPipeline]);
  }
  g_totals = {};
  g_report_at = now + std::chrono::seconds(1);
}

// Times its scope as one item of `kind`.
class Scope {
 public:
  explicit Scope(Kind kind) : kind_(kind), start_(std::chrono::steady_clock::now()) {}
  ~Scope() {
    const auto now = std::chrono::steady_clock::now();
    const double ms = std::chrono::duration<double, std::milli>(now - start_).count();
    std::lock_guard<std::mutex> lock(g_mutex);
    Totals& t = g_totals[tls_is_worker ? 1 : 0];
    ++t.count[kind_];
    t.ms[kind_] += ms;
    if (ms > t.longest[kind_]) {
      t.longest[kind_] = ms;
    }
    if (g_report_at.time_since_epoch().count() == 0) {
      g_report_at = now + std::chrono::seconds(1);
    } else if (now >= g_report_at) {
      Report(now);
    }
  }
  Scope(const Scope&) = delete;
  Scope& operator=(const Scope&) = delete;

 private:
  Kind kind_;
  std::chrono::steady_clock::time_point start_;
};

}  // namespace rex::graphics::d3d12::stall
