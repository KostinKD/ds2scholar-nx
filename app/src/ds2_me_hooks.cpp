// SotFS (2026-10-21): the addresses below are DS2's translated by masked byte signature, each the only match in SotFS
// (docs/analysis/xdk.md, "D3D"): 829BF328->829EF4F0, 829C2E28->829F2FF0, 829C3240->829F3408, 829C2800->829F29C8,
// 829C2D88->829F2F50, 829BE590->829EE758, 829BE438->829EE600, 829BE1F8->829EE3C0. Checked in the SotFS listing (the
// signature masks load/store offsets): lwz r30,0x3310(r31) / lwz r29,0x330C(r31) at 0x829EF53C / 0x829EF544, and
// `addi r10,r3,1152` at 0x829EE60C (DS2 0x829BE444). The run-time facts in this text (census rates, "never an
// implausible pointer") are DS2's; NOT confirmed on SotFS.
// Dark Souls II hooks for the native renderer (src/me, from sa2-nx), with ds2's addresses: docs/analysis/d3d.md (found
// by signature, tools/d3d_find.py, confirmed at run time with ds2_d3d_census_s). sa2-nx's src/me/sa2_me_hooks.cpp,
// minus sa2's native Direct3D layer (sa2_api_*: Clear / Resolve / WindowScissor / inline allocator as records) and the
// shader container dump (ds2's Create*Shader functions are not identified yet).
//
// The renderer reads the game's PM4 ring by itself; these hooks only feed it what the ring cannot say:
//   - Shader objects: the draw-time shader load sub_829EF4F0 (r3 = device) reads the bound VS from device+0x3310 and
//     the PS from device+0x330C, the same offsets as sa2's XDK (confirmed: never an implausible pointer at run time).
//   - Draw records (NoteDrawCall: primitive type, then r5..r7 as D3D received them):
//       D3DDevice_DrawVertices        sub_829F2FF0 (dev, type, start, count)        never called by ds2 (census)
//       D3DDevice_DrawIndexedVertices sub_829F3408 (dev, type, base, start, count)  the game's main path
//       D3DDevice_DrawVerticesUP      sub_829F29C8 (dev, type, count, data, stride) UI
//     D3DDevice_DrawIndexedVerticesUP sub_829F2F50 (180-260 calls a second in the Forest) is only counted: sa2 had no
//     such hook and its argument layout for NoteDrawCall is not established.
//   - The state flushes FlushState calls (the direct renderer's FlushRunsDirect, off unless its keys are on):
//     shader constants sub_829EE758 (r5 = 0x4000 VS / 0x4400 PS), fetch constants sub_829EE600 (shadow device+1152,
//     `addi r10,r3,1152` at 0x829EE60C, as sa2), register groups sub_829EE3C0.
// Every hook calls the original (__imp__sub_X).

#include <cstdint>
#include <cstring>

#include <rex/hook.h>
#include <rex/logging.h>
#include <rex/ppc.h>

#include "ds2_d3d_census.h"
#include "me/me_native_system.h"

namespace {

inline uint32_t Load32(const uint8_t* base, uint32_t address) {
  uint32_t v;
  std::memcpy(&v, base + address, 4);
  return __builtin_bswap32(v);
}

constexpr uint32_t kDeviceVertexShader = 0x3310;
constexpr uint32_t kDevicePixelShader = 0x330C;

// The draw records (NoteDrawCall) read the bound shaders from the same device fields.
const bool g_device_layout_set = [] {
  me::native::SetDeviceShaderOffsets(kDeviceVertexShader, kDevicePixelShader);
  return true;
}();

// Guest heap from 0x30000000 (virtual) up through the physical windows (census: the device always passed this).
inline bool PlausibleDevice(uint32_t p) { return p >= 0x30000000u; }

template <void (*Original)(PPCContext&, uint8_t*)>
inline void Draw(PPCContext& ctx, uint8_t* base, ds2::census::Fn fn) {
  ds2::census::Count(fn);
  auto direct = me::native::BeginDrawDirect(base, ctx.r3.u32);
  me::native::NoteDrawCall(base, ctx.r3.u32, ctx.r4.u32, ctx.r5.u32, ctx.r6.u32, ctx.r7.u32, &direct);
  Original(ctx, base);
  me::native::EndDrawDirect(base, direct);
}

}  // namespace

// Draw-time shader load (FlushState's shader part, called from every Draw*).
REX_EXTERN(__imp__sub_829EF4F0);
REX_HOOK_RAW(sub_829EF4F0) {
  ds2::census::Count(ds2::census::kShaderLoad);
  const uint32_t device = ctx.r3.u32;
  ds2::census::NoteShaderLoad(base, device);
  if (PlausibleDevice(device)) {
    const uint32_t vs = Load32(base, device + kDeviceVertexShader), ps = Load32(base, device + kDevicePixelShader);
    if (!me::native::ShaderObjectsFinished(vs, ps)) {
      me::native::NoteShaderObject(base, vs, true);
      me::native::NoteShaderObject(base, ps, false);
    }
  }
  __imp__sub_829EF4F0(ctx, base);
}

REX_EXTERN(__imp__sub_829F2FF0);
REX_HOOK_RAW(sub_829F2FF0) { Draw<__imp__sub_829F2FF0>(ctx, base, ds2::census::kDrawVertices); }

REX_EXTERN(__imp__sub_829F3408);
REX_HOOK_RAW(sub_829F3408) { Draw<__imp__sub_829F3408>(ctx, base, ds2::census::kDrawIndexedVertices); }

REX_EXTERN(__imp__sub_829F29C8);
REX_HOOK_RAW(sub_829F29C8) { Draw<__imp__sub_829F29C8>(ctx, base, ds2::census::kDrawVerticesUP); }

REX_EXTERN(__imp__sub_829F2F50);
REX_HOOK_RAW(sub_829F2F50) {  // D3DDevice_DrawIndexedVerticesUP: counted only (see the header)
  ds2::census::Count(ds2::census::kDrawIndexedVerticesUP);
  __imp__sub_829F2F50(ctx, base);
}

// The state flushes: r3 = device, r4 = dirty mask (bit 63 first), r5 = the first register, r6 = the shadow.
REX_EXTERN(__imp__sub_829EE758);
REX_HOOK_RAW(sub_829EE758) {  // shader constants: 16 registers a bit (r5 = 0x4000 VS / 0x4400 PS)
  ds2::census::Count(ds2::census::kFlushConstants);
  if (me::native::FlushRunsDirect(ctx, base, ctx.r3.u32, ctx.r4.u64, ctx.r5.u32, ctx.r6.u32,
                                  me::native::FlushKind::kConstants, &__imp__sub_829EE758))
    return;
  __imp__sub_829EE758(ctx, base);
}

REX_EXTERN(__imp__sub_829EE600);
REX_HOOK_RAW(sub_829EE600) {  // fetch constants: 6 registers a bit from 0x4800, then the 0x5000 end packet
  ds2::census::Count(ds2::census::kFlushFetch);
  if (me::native::FlushRunsDirect(ctx, base, ctx.r3.u32, ctx.r4.u64, 0x4800, ctx.r3.u32 + 1152,
                                  me::native::FlushKind::kFetch, &__imp__sub_829EE600))
    return;
  __imp__sub_829EE600(ctx, base);
}

REX_EXTERN(__imp__sub_829EE3C0);
REX_HOOK_RAW(sub_829EE3C0) {  // register groups: 1 register a bit
  ds2::census::Count(ds2::census::kFlushGroups);
  if (me::native::FlushRunsDirect(ctx, base, ctx.r3.u32, ctx.r4.u64, ctx.r5.u32, ctx.r6.u32,
                                  me::native::FlushKind::kGroups, &__imp__sub_829EE3C0))
    return;
  __imp__sub_829EE3C0(ctx, base);
}
