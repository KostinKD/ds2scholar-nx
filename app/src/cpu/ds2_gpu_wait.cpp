// SotFS (2026-10-21): the addresses are DS2's translated by masked byte signature (docs/analysis/xex.md); the profile
// figures below are DS2's. 2026-10-22: SotFS's sub_829E9E28 re-read against DS2's sub_829B9C60 word by word: equal
// but for the save/restore-gpr helpers (82FB711C/82FB716C -> 82FEBECC/82FEBF1C), the time call (829958E8 ->
// 829C5B18, equal but for its import thunk) and the timeout global (8343B718 -> 8346BC98, 0x1388 = 5000 ms in both);
// the device offsets 11024/11069 (0x2B10/0x2B3D) and 0x2B08/0x2B8C are the same. The hash is now SotFS's (DS2's
// was 0x0A79B4B0C4E0BE3E). Console profile with the check failing (opt LTO, 2026-10-22, ds2_009.log): the wait is
// 28 % of the main thread's samples, D3DDevice_Swap sub_829EB6E8 61 % inclusive.
// Dark Souls II: the game's Direct3D GPU wait sleeps instead of spinning (CPU enhancement ds2_cpu_gpu_wait_sleep).
// From sa2-nx's app/src/cpu/sa2_gpu_wait.cpp (its sub_8254F400): the same XDK code, the same device offsets.
//
// WHAT THE GAME DOES (stage 5, 2026-10-18)
//   Direct3D's waits for the GPU loop on one iteration function, sub_829E9E28 (224 bytes, 6 call sites; e.g.
//   sub_829D8408 waits until the GPU read pointer passes a point of the ring). r3 = the wait record sub_829E9D30
//   fills: [0] device, [8] the read pointer seen last time ([[device+11024]]), [12]/[16] the tick of the last change,
//   [20] the time base at the start. One iteration is 32 db16cyc delays (4 x 8, the bdnz at 0x829E9E48), then: GPU
//   already declared hung (bit 0x02 of [device+11069]) -> 0 (stop); the read pointer moved -> remember it and its
//   tick; no movement for longer than the game's limit -> the hang check sub_829F13A8; else 1 (keep waiting).
//   Console stack profile (step 1 NRO, 4 intervals at 17.5-19.5 fps, switch_logs 2026-10-18 11:50): on the game's main
//   thread sub_829E9E28 is the hottest function (8.0 % self), sub_829D8408 (its caller) 25.8 % of the running guest
//   stacks, D3DDevice_Swap sub_829EB6E8 42.5 % inclusive.
//
// WHAT THIS DOES
//   Before an iteration in which nothing can have changed - the same wait record as the previous iteration on this
//   thread, the read pointer still the one the record saw, and no ring progress since the previous iteration returned
//   (me::native::RingProgress, bumped by the ring thread after each ring segment, each fence write and each interrupt)
//   - it sleeps until the ring thread reports progress, at most ds2_gpu_wait_max_us. Then the original iteration runs
//   as always. The counter is read AFTER the original returns, i.e. before the caller re-checks its condition, so a
//   change the caller could have missed always shows as progress and the next iteration does not sleep.
//
// WHY IT IS EXACT: the game reads the same memory and takes the same decisions; it only reaches them later, by at most
//   one wake-up latency (or max_us when the wake-up comes from something the ring does not report).
// RISK: a wait whose condition changes without ring progress or an interrupt gains up to max_us per iteration.
// KEY: ds2_cpu_gpu_wait_sleep (with sa2_cpu_enhancements); ds2_gpu_wait_max_us. The code is checked against its hash
//   (FNV-1a of the 224 bytes in out/default_image.bin) before the first use; a mismatch leaves it off with a warning.
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>

#include <rex/cvar.h>
#include <rex/hook.h>
#include <rex/logging.h>
#include <rex/platform.h>
#include <rex/ppc.h>

#include "cpu/sa2_enhancements.h"
#include "me/me_native_system.h"

SA2_ENHANCEMENT(g_gpu_wait_sleep, ds2_cpu_gpu_wait_sleep, sa2::enh::kCpu, false,
                "The game's Direct3D GPU wait (sub_829E9E28) sleeps until the ring thread makes progress instead of "
                "spinning");
REXCVAR_DEFINE_INT32(ds2_gpu_wait_max_us, 1000, "SA2 enhancements",
                     "ds2_cpu_gpu_wait_sleep: longest sleep per iteration of the game's GPU wait, in microseconds")
    .range(50, 100000)
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);

namespace {

constexpr uint32_t kIteration = 0x829E9E28;
constexpr uint32_t kIterationBytes = 224;
constexpr uint64_t kIterationHash = 0x41AD1CDEDE0DA0ECull;

constexpr uint32_t kDeviceReadPointerWord = 11024;  // address of the word the GPU writes the read pointer back to
constexpr uint32_t kDeviceState = 11069;            // bit 0x02: GPU declared hung

inline uint32_t PhysOff(uint32_t a) {
#if REX_PLATFORM_WIN32 || (REX_PLATFORM_MAC && REX_ARCH_ARM64)
  return a >= 0xE0000000u ? 0x1000u : 0u;
#else
  (void)a;
  return 0u;
#endif
}
inline uint32_t Ld32(const uint8_t* base, uint32_t a) {
  uint32_t v;
  std::memcpy(&v, base + a + PhysOff(a), 4);
  return __builtin_bswap32(v);
}
inline uint8_t Ld8(const uint8_t* base, uint32_t a) { return base[a + PhysOff(a)]; }

// The previous iteration on this thread: its record, the record's start time base, and the progress counter when it
// returned.
thread_local uint32_t t_record = 0;
thread_local uint32_t t_record_start = 0;
thread_local uint32_t t_progress = 0;

std::atomic<int> g_state{0};  // 0 unknown, 1 on, -1 off (code check failed or key off); set by the first call

}  // namespace

REX_EXTERN(__imp__sub_829E9E28);
REX_HOOK_RAW(sub_829E9E28) {
  int state = g_state.load(std::memory_order_relaxed);
  if (state == 0) {
    state = (g_gpu_wait_sleep.active &&
             sa2::enh::GuestCodeMatches(base, kIteration, kIterationBytes, kIterationHash, "ds2_cpu_gpu_wait_sleep"))
                ? 1
                : -1;
    g_state.store(state, std::memory_order_relaxed);
    REXLOG_INFO("[enh] ds2_cpu_gpu_wait_sleep: first call of sub_829E9E28, {}", state > 0 ? "sleeping on ring progress"
                : (g_gpu_wait_sleep.active ? "off (code check failed)" : "off (key)"));
  }
  if (state < 0) {
    __imp__sub_829E9E28(ctx, base);
    return;
  }
  const uint32_t record = ctx.r3.u32;
  const uint32_t start = Ld32(base, record + 20);
  if (record == t_record && start == t_record_start) {
    const uint32_t device = Ld32(base, record);
    if (device && !(Ld8(base, device + kDeviceState) & 0x02)) {
      const uint32_t word = Ld32(base, device + kDeviceReadPointerWord);
      if (word && Ld32(base, word) == Ld32(base, record + 8) && me::native::RingProgress() == t_progress) {
        static const uint32_t max_us = uint32_t(REXCVAR_GET(ds2_gpu_wait_max_us));
        const auto t0 = std::chrono::steady_clock::now();
        me::native::WaitRingProgress(t_progress, max_us);
        g_gpu_wait_sleep.Use();
        g_gpu_wait_sleep.Add(uint64_t(std::chrono::duration_cast<std::chrono::microseconds>(
                                          std::chrono::steady_clock::now() - t0)
                                          .count()));
      }
    }
  }
  __imp__sub_829E9E28(ctx, base);
  t_record = record;
  t_record_start = start;
  t_progress = me::native::RingProgress();
}

namespace {
const bool g_unit = [] {
  g_gpu_wait_sleep.amount_unit = "us asleep";
  return true;
}();
}  // namespace
