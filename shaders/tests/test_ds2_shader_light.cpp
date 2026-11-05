// Stable container identity and default-off contract; independent of Vulkan/game data.
#include "../../app/src/me/native/me_ds2_shader_light.h"
#include <cassert>
#include <fstream>
#include <iterator>
#include <vector>
static_assert(sa2::native::Ds2ShaderLightMask(0x04762adf6a086695ULL) == 1);
static_assert(sa2::native::Ds2ShaderLightMask(0x3c14b756c88a2b7fULL) == 2);
static_assert(sa2::native::Ds2ShaderLightMask(0x41db93b1dec497deULL) == 4);
static_assert(sa2::native::Ds2ShaderLightMask(0x9942495d3b412155ULL) == 8);
static_assert(sa2::native::Ds2ShaderLightMask(0x0feaa33b192cdc87ULL) == 16);
static_assert(sa2::native::Ds2ShaderLightMask(0xcaee55f06defe9d8ULL) == 16);
static_assert(sa2::native::Ds2ShaderLightMask(31) == 0);
static_assert(sa2::native::Ds2ShaderLightMask(0) == 0);
int main(int argc, char** argv) {
  // DXC can keep the AND in the function, or emit OpSpecConstantOp.
  const std::vector<uint32_t> local = {
    0x07230203, 0x00010500, 0, 10, 0,
    (4u << 16) | 71, 1, 1, 0,  // OpDecorate %1 SpecId 0
    (4u << 16) | 43, 2, 3, 1u << 23,  // OpConstant %uint %3 8388608
    (5u << 16) | 199, 2, 4, 1, 3,  // OpBitwiseAnd %uint %4 %1 %3
  };
  assert(sa2::native::Ds2ShaderLightSupported(local));
  auto global = local;
  global.resize(global.size() - 5);
  global.insert(global.end(), {(6u << 16) | 52, 2, 4, 199, 1, 3});
  assert(sa2::native::Ds2ShaderLightSupported(global));
  auto other_bit = local;
  other_bit[12] = 1u << 15;
  assert(!sa2::native::Ds2ShaderLightSupported(other_bit));
  auto truncated = local;
  truncated.pop_back();
  assert(!sa2::native::Ds2ShaderLightSupported(truncated));
  for (int i = 1; i < argc; ++i) {
    std::ifstream file(argv[i], std::ios::binary);
    assert(file);
    std::vector<char> bytes((std::istreambuf_iterator<char>(file)), {});
    assert(bytes.size() % 4 == 0);
    std::vector<uint32_t> words(bytes.size() / 4);
    for (size_t j = 0; j < words.size(); ++j)
      for (size_t b = 0; b < 4; ++b) words[j] |= uint32_t(uint8_t(bytes[j * 4 + b])) << (8 * b);
    assert(sa2::native::Ds2ShaderLightSupported(words));
  }
}
