// Prints the XXH3-64 of each file (the "container" hash the native renderer logs as "library nN: ... container <hash>").
//   xxh3_files <file> [...]
#define XXH_INLINE_ALL
#include "xxhash.h"
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>
int main(int argc, char** argv) {
  for (int i = 1; i < argc; ++i) {
    std::ifstream f(argv[i], std::ios::binary);
    std::vector<char> b((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    std::printf("%016llx %s\n", (unsigned long long)XXH3_64bits(b.data(), b.size()), argv[i]);
  }
}
