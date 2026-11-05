// Stage 4 diagnostic: call counters on the Direct3D functions (app/src/ds2_d3d_census.cpp, cvar ds2_d3d_census_s).
// The functions the native renderer hooks (app/src/ds2_me_hooks.cpp) are counted from those hooks: a guest function
// can have only one strong hook.

#pragma once

#include <cstdint>

namespace ds2::census {

enum Fn : int {
  kSwap, kFlip, kDisplaySetup, kDrawVertices, kDrawIndexedVertices, kBeginVertices, kDrawVerticesUP,
  kBeginIndexedVertices, kDrawIndexedVerticesUP, kShaderLoad, kFlushConstants, kFlushFetch, kFlushGroups,
  kRect6C0, kRect818, kRectE48, kRect3E88, kRectB130, kRectBAE8, kFnCount
};

void Count(Fn fn);

// The draw-time shader load's device fields (VS +0x3310, PS +0x330C): counts null and implausible pointers.
void NoteShaderLoad(const uint8_t* base, uint32_t device);

}  // namespace ds2::census
