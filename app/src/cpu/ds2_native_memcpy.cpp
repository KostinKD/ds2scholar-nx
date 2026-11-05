// SotFS (2026-10-21): DS2's sub_82997E24 is SotFS's sub_829C7FF4, byte for byte (0x4CC bytes, the same FNV hash
// 0x8C8E4E7D9C063550, tools/guest_code_hash.py); its callers translated by masked signature. The history below is DS2's.
// Dark Souls II: the XDK's vector memcpy for an unaligned source in native code (ds2_native_unaligned_memcpy).
//
// WHY (stage 5, 2026-10-18, docs/progress.md entries 42-44 and 49)
//   GCC 16.1.0 (devkitA64) turns the recompiled sub_829C7FF4 into code that copies wrong data whenever its code moves:
//   with loop barriers (found by bisection over 15 223 functions, 16 console rounds) and without them once guest memory
//   is not volatile (models' shaders from FlverShader.bnd with zeros and foreign bytes, acid colours). The cause is not
//   understood. The step 1 build is fine only because nothing moves its code; LTO would. This replaces the function so
//   that GCC never builds it.
//
// WHAT THE GAME DOES
//   sub_829C3388 (memcpy, n >= 256) copies the head up to a 128-byte boundary of the destination with sub_82FEBFF0,
//   then the 128-byte blocks with sub_829C7FF4 (source not 16-aligned) or sub_829C7CD0 (aligned), then the tail with
//   sub_82FEBFF0. sub_829C7FF4(r3 = dest, 128-aligned; r4 = source; r5 = byte count, a multiple of 128):
//     - std r30,-16(r1); std r31,-8(r1); stvlx128 v64 at r1-32; stvlx128 v65 at r1-48 (saved below the stack pointer);
//     - copies r5 bytes in 1 KB blocks (lvx128 of the aligned blocks, lvsl + vperm128 for the shift, v65 carrying the
//       last block into the next one; stvlx128 stores, full vectors at a 16-aligned destination), then 128-byte blocks;
//     - lvx128 v64 / v65 and ld r30 / r31 back from the same places; blr.
//   The caller uses neither r3/r4/r5 nor any vector register afterwards (it recomputes from r28-r31).
//
// WHAT THIS DOES
//   The same stores below r1, the copy as memmove (the same bytes for non-overlapping buffers, which memcpy requires),
//   then v64/v65/r30/r31 reloaded from below r1 as the original does. NOT reproduced: the scratch values the original
//   leaves in r0, r4-r12, v0-v63, cr6 (dead per the caller above); an overlapping copy (the original copies 1 KB per
//   step).
// CHECK: sa2_cpu_verify on: each call runs the original first on a copy of the context, then this on the same memory,
//   and compares the destination, the 48 bytes below r1 and v64/v65/r30/r31 ('[verify]' line; must stay 0).
// KEY: ds2_native_unaligned_memcpy (with sa2_cpu_enhancements). The guest code is checked against its hash first.
#include <atomic>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>

#include <rex/cvar.h>
#include <rex/hook.h>
#include <rex/logging.h>
#include <rex/platform.h>
#include <rex/ppc.h>

#include "cpu/sa2_enhancements.h"

// sa2-nx defines this key in its sa2_hot_guest.cpp, which ds2 does not build; without it VerifyMode() is always off.
REXCVAR_DEFINE_BOOL(sa2_cpu_verify, false, "SA2 enhancements",
                    "Every native replacement call is checked against the original guest code (slow; for PC tests)")
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
SA2_ENHANCEMENT(g_native_memcpy, ds2_native_unaligned_memcpy, sa2::enh::kCpu, false,
                "The XDK's vector memcpy for an unaligned source (sub_829C7FF4) in native code (GCC miscompiles the "
                "recompiled one once its code moves)");

namespace {

constexpr uint32_t kFunction = 0x829C7FF4;
constexpr uint32_t kFunctionBytes = 0x4CC;  // up to its blr at 0x829C84BC
constexpr uint64_t kFunctionHash = 0x8C8E4E7D9C063550ull;

inline uint32_t PhysOff(uint32_t a) {
#if REX_PLATFORM_WIN32 || (REX_PLATFORM_MAC && REX_ARCH_ARM64)
  return a >= 0xE0000000u ? 0x1000u : 0u;
#else
  (void)a;
  return 0u;
#endif
}
inline uint8_t* Host(uint8_t* base, uint32_t a) { return base + a + PhysOff(a); }

void StoreU64(uint8_t* base, uint32_t a, uint64_t v) {
  v = __builtin_bswap64(v);
  std::memcpy(Host(base, a), &v, 8);
}
uint64_t LoadU64(uint8_t* base, uint32_t a) {
  uint64_t v;
  std::memcpy(&v, Host(base, a), 8);
  return __builtin_bswap64(v);
}
// stvlx128: the bytes from ea up to the next 16-byte boundary, in guest (big-endian) order.
void StoreVectorLeft(uint8_t* base, uint32_t ea, const PPCVRegister& v) {
  for (uint32_t i = 0; i < 16 - (ea & 0xF); ++i) *Host(base, ea + i) = v.u8[15 - i];
}
// lvx128: the aligned 16 bytes containing ea.
void LoadVector(uint8_t* base, uint32_t ea, PPCVRegister& v) {
  const uint32_t a = ea & ~0xFu;
  for (uint32_t i = 0; i < 16; ++i) v.u8[15 - i] = *Host(base, a + i);
}

void Native(PPCContext& ctx, uint8_t* base) {
  const uint32_t sp = ctx.r1.u32, dest = ctx.r3.u32, source = ctx.r4.u32, n = ctx.r5.u32;
  StoreU64(base, sp - 16, ctx.r30.u64);
  StoreU64(base, sp - 8, ctx.r31.u64);
  StoreVectorLeft(base, sp - 32, ctx.v64);
  StoreVectorLeft(base, sp - 48, ctx.v65);
  if (n) std::memmove(Host(base, dest), Host(base, source), n);
  LoadVector(base, sp - 32, ctx.v64);
  LoadVector(base, sp - 48, ctx.v65);
  ctx.r30.u64 = LoadU64(base, sp - 16);
  ctx.r31.u64 = LoadU64(base, sp - 8);
}

std::atomic<int> g_state{0};  // 0 unknown, 1 on, -1 off; set by the first call

}  // namespace

REX_EXTERN(__imp__sub_829C7FF4);
REX_HOOK_RAW(sub_829C7FF4) {
  int state = g_state.load(std::memory_order_relaxed);
  if (state == 0) {
    state = (g_native_memcpy.active &&
             sa2::enh::GuestCodeMatches(base, kFunction, kFunctionBytes, kFunctionHash, "ds2_native_unaligned_memcpy"))
                ? 1
                : -1;
    g_state.store(state, std::memory_order_relaxed);
    REXLOG_INFO("[enh] ds2_native_unaligned_memcpy: first call of sub_829C7FF4, {}{}",
                state > 0 ? "native" : (g_native_memcpy.active ? "off (code check failed)" : "off (key)"),
                state > 0 && sa2::enh::VerifyMode() ? ", checked against the original (sa2_cpu_verify)" : "");
  }
  if (state < 0) {
    __imp__sub_829C7FF4(ctx, base);
    return;
  }
  g_native_memcpy.Use();
  g_native_memcpy.Add(ctx.r5.u32);
  if (!sa2::enh::VerifyMode()) {
    Native(ctx, base);
    return;
  }
  // The original on a copy of the context, its results kept, the memory put back; then the native on the real one.
  const uint32_t sp = ctx.r1.u32, dest = ctx.r3.u32, source = ctx.r4.u32, n = ctx.r5.u32;
  std::vector<uint8_t> dest_before(Host(base, dest), Host(base, dest) + n), red_before(48);
  std::memcpy(red_before.data(), Host(base, sp - 48), 48);
  auto copy = std::make_unique<PPCContext>();
  std::memcpy(static_cast<void*>(copy.get()), &ctx, sizeof(PPCContext));
  __imp__sub_829C7FF4(*copy, base);
  std::vector<uint8_t> dest_original(Host(base, dest), Host(base, dest) + n), red_original(48);
  std::memcpy(red_original.data(), Host(base, sp - 48), 48);
  std::memcpy(Host(base, dest), dest_before.data(), n);
  std::memcpy(Host(base, sp - 48), red_before.data(), 48);
  Native(ctx, base);
  sa2::enh::VerifyCheck();
  const bool same = std::memcmp(Host(base, dest), dest_original.data(), n) == 0 &&
                    std::memcmp(Host(base, sp - 48), red_original.data(), 48) == 0 &&
                    std::memcmp(&ctx.v64, &copy->v64, 16) == 0 && std::memcmp(&ctx.v65, &copy->v65, 16) == 0 &&
                    ctx.r30.u64 == copy->r30.u64 && ctx.r31.u64 == copy->r31.u64;
  if (!same) {
    sa2::enh::VerifyDifference();
    static std::atomic<int> logged{0};
    if (logged.fetch_add(1) < 8)
      REXLOG_WARN("[verify] ds2_native_unaligned_memcpy: differs from the original (dest {:08X} source {:08X} n {} "
                  "sp {:08X})", dest, source, n, sp);
  }
}

namespace {
const bool g_unit = [] {
  g_native_memcpy.amount_unit = "bytes";
  return true;
}();
}  // namespace
