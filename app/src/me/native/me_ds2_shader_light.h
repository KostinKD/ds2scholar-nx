#pragma once
#include <cstdint>
#include <span>
#include <algorithm>
#include <utility>
#include <vector>
namespace sa2::native {
// SotFS container hashes verified in ds2_049 / ds2_075, not runtime shader numbers.
// PS95/1255: ds2_087/091, both VS135 passes; HLSL blends by TEXCOORD7.w.
// SpecId 0 bit 23 is free of the renderer's depth/raster/7e3 variant bits.
constexpr uint32_t kDs2ShaderLightSpec = uint32_t(1) << 23;
constexpr uint32_t Ds2ShaderLightMask(uint64_t fingerprint) {
  switch (fingerprint) {
    case 0x04762adf6a086695ULL: return 1;  // PS31: no flipbook interpolation
    case 0x3c14b756c88a2b7fULL: return 2;  // PS385: linear fog shaping
    case 0x41db93b1dec497deULL: return 4;  // PS421: modulate instead of overlay
    case 0x9942495d3b412155ULL: return 8;  // PS961: first material layer
    case 0x0feaa33b192cdc87ULL: return 16;  // PS95: first diffuse/material layer
    case 0xcaee55f06defe9d8ULL: return 16;  // PS1255: corresponding normal prepass
    default: return 0;
  }
}
// DXC emits either OpSpecConstantOp BitwiseAnd or function-scope OpBitwiseAnd
// of SpecId 0. Both specialize in the driver; the renderer's older generic
// probe only recognized the first form. Keep this broader probe local to DS2
// light variants so that existing shader switches retain their behavior.
inline bool Ds2ShaderLightSupported(std::span<const uint32_t> words) {
  if (words.size() < 5 || words[0] != 0x07230203u) return false;
  std::vector<uint32_t> spec_ids, bits;
  std::vector<std::pair<uint32_t, uint32_t>> ands;
  for (size_t i = 5; i < words.size();) {
    const uint32_t size = words[i] >> 16, op = words[i] & 0xFFFF;
    if (!size || size > words.size() - i) return false;
    if (op == 71 && size == 4 && words[i + 2] == 1 && words[i + 3] == 0)
      spec_ids.push_back(words[i + 1]);
    if (op == 43 && size == 4 && words[i + 3] == kDs2ShaderLightSpec)
      bits.push_back(words[i + 2]);
    if (op == 52 && size == 6 && words[i + 3] == 199)
      ands.emplace_back(words[i + 4], words[i + 5]);
    if (op == 199 && size == 5) ands.emplace_back(words[i + 3], words[i + 4]);
    i += size;
  }
  const auto has = [](const auto& ids, uint32_t id) {
    return std::find(ids.begin(), ids.end(), id) != ids.end();
  };
  for (const auto& [a, b] : ands)
    if ((has(spec_ids, a) && has(bits, b)) || (has(spec_ids, b) && has(bits, a))) return true;
  return false;
}
}  // namespace sa2::native
