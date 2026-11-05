// SotFS (2026-10-21): every address here is DS2's translated by masked byte signature, each the only match in SotFS
// (docs/analysis/xdk.md, "D3D"; logs/sigmatch_d3d.log). The census itself is how they get confirmed at run time.
// Stage 4, step 1: runtime confirmation of the Direct3D functions found by signature (docs/analysis/d3d.md). Each
// function below is hooked (a strong sub_X replaces the generator's weak alias, so direct calls and the function table
// both come here), counted and passed to the original (__imp__sub_X) unchanged. Every ds2_d3d_census_s seconds one log
// line with the calls per second of each, so a wrong address shows as a function that never runs or runs at an
// implausible rate. The draw-time shader load also checks the device fields it is supposed to read: the bound vertex
// shader at +0x3310 and pixel shader at +0x330C (the same offsets as sa2-nx's XDK) must be guest pointers.
// 0 turns the logging off; the hooks always count (one relaxed atomic add). The functions the native renderer
// hooks (shader load, Draw*, the flushes: app/src/ds2_me_hooks.cpp) are counted from there (ds2_d3d_census.h).

#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>

#include <fmt/format.h>

#include <rex/cvar.h>
#include <rex/hook.h>
#include <rex/logging.h>
#include <rex/ppc.h>

#include "ds2_d3d_census.h"

REXCVAR_DEFINE_INT32(ds2_d3d_census_s, 0, "DS2", "Log the call rate of the hooked D3D functions every N seconds (0: off)");

namespace {

using namespace ds2::census;

constexpr std::array<const char*, kFnCount> kNames = {
    "Swap 829EB6E8", "flip 829EA7E8", "display 829EA918", "DrawVertices 829F2FF0", "DrawIndexedVertices 829F3408",
    "BeginVertices 829F2508", "DrawVerticesUP 829F29C8", "BeginIndexedVertices 829F2A10",
    "DrawIndexedVerticesUP 829F2F50", "shader load 829EF4F0", "flush constants 829EE758", "flush fetch 829EE600",
    "flush groups 829EE3C0", "rect? 829DC890", "rect? 829DC9E8", "rect? 829E1010", "rect? 829F4050",
    "rect? 829FB2F8", "rect? 829FBCB0"};

std::array<std::atomic<uint64_t>, kFnCount> g_calls{};
std::atomic<uint64_t> g_vs_null{0}, g_ps_null{0}, g_vs_bad{0}, g_ps_bad{0};
std::mutex g_report_mutex;
std::chrono::steady_clock::time_point g_report_at{};
std::array<uint64_t, kFnCount> g_last{};

uint32_t LoadBE32(const uint8_t* base, uint32_t addr) {
  uint32_t v;
  std::memcpy(&v, base + addr, 4);
  return __builtin_bswap32(v);
}

// Guest heap pointers on the 360: virtual allocations from 0x30000000, physical ones (XPhysicalAlloc) in the
// 0xA0000000-0xFFFFFFFF windows; below 0x30000000 is not heap. 0 = nothing bound.
bool PlausibleGuestPointer(uint32_t p) { return p >= 0x30000000u; }

void Report() {
  const int interval = REXCVAR_GET(ds2_d3d_census_s);
  if (interval <= 0) {
    return;
  }
  const auto now = std::chrono::steady_clock::now();
  std::lock_guard<std::mutex> lock(g_report_mutex);
  if (g_report_at.time_since_epoch().count() == 0) {
    g_report_at = now + std::chrono::seconds(interval);
    return;
  }
  if (now < g_report_at) {
    return;
  }
  g_report_at = now + std::chrono::seconds(interval);
  std::string line;
  for (int i = 0; i < kFnCount; ++i) {
    const uint64_t c = g_calls[i].load(std::memory_order_relaxed);
    line += fmt::format("{} {:.1f}/s; ", kNames[i], double(c - g_last[i]) / interval);
    g_last[i] = c;
  }
  REXLOG_INFO("[ds2-d3d] {}shader load: VS null {} bad {}, PS null {} bad {}", line, g_vs_null.load(),
              g_vs_bad.load(), g_ps_null.load(), g_ps_bad.load());
}

}  // namespace

void ds2::census::Count(Fn fn) { g_calls[fn].fetch_add(1, std::memory_order_relaxed); }

void ds2::census::NoteShaderLoad(const uint8_t* base, uint32_t device) {
  if (!PlausibleGuestPointer(device)) {
    g_vs_bad.fetch_add(1, std::memory_order_relaxed);
    return;
  }
  const uint32_t vs = LoadBE32(base, device + 0x3310);
  const uint32_t ps = LoadBE32(base, device + 0x330C);
  if (vs == 0) g_vs_null.fetch_add(1, std::memory_order_relaxed);
  else if (!PlausibleGuestPointer(vs)) g_vs_bad.fetch_add(1, std::memory_order_relaxed);
  if (ps == 0) g_ps_null.fetch_add(1, std::memory_order_relaxed);
  else if (!PlausibleGuestPointer(ps)) g_ps_bad.fetch_add(1, std::memory_order_relaxed);
}

#define DS2_COUNT_HOOK(addr, fn)          \
  REX_EXTERN(__imp__sub_##addr);          \
  REX_HOOK_RAW(sub_##addr) {              \
    ds2::census::Count(fn);               \
    __imp__sub_##addr(ctx, base);         \
  }

// Swap: also the reporting point (once per presented frame).
REX_EXTERN(__imp__sub_829EB6E8);
REX_HOOK_RAW(sub_829EB6E8) {
  ds2::census::Count(kSwap);
  __imp__sub_829EB6E8(ctx, base);
  Report();
}

DS2_COUNT_HOOK(829EA7E8, kFlip)
DS2_COUNT_HOOK(829EA918, kDisplaySetup)
DS2_COUNT_HOOK(829F2508, kBeginVertices)
DS2_COUNT_HOOK(829F2A10, kBeginIndexedVertices)
DS2_COUNT_HOOK(829DC890, kRect6C0)
DS2_COUNT_HOOK(829DC9E8, kRect818)
DS2_COUNT_HOOK(829E1010, kRectE48)
DS2_COUNT_HOOK(829F4050, kRect3E88)
DS2_COUNT_HOOK(829FB2F8, kRectB130)
DS2_COUNT_HOOK(829FBCB0, kRectBAE8)
