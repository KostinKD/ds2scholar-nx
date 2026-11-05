#include <cassert>
#include <rex/input/probe_command.h>

int main() {
  using rex::input::probe::Parse;
  const auto command = Parse("42 200 1000 -32768 32767 0 0");
  assert(command && command->id == 42 && command->duration_ms == 200);
  assert(command->buttons == 0x1000 && command->lx == -32768 && command->ly == 32767);
  assert(Parse("43 0 0 0 0 0 0"));  // explicit release
  assert(Parse("44 10000 ffff 0 0 0 0"));
  assert(!Parse(""));
  assert(!Parse("-1 200 0 0 0 0 0"));
  assert(!Parse("45 200 1000 0 0 0"));
  assert(!Parse("45 200 1000 0 0 0 0 trailing"));
  assert(!Parse("45 -1 0 0 0 0 0"));
  assert(!Parse("45 10001 0 0 0 0 0"));
  assert(!Parse("45 200 10000 0 0 0 0"));
  assert(!Parse("45 200 0 32768 0 0 0"));
  assert(!Parse("45 200 0 -32769 0 0 0"));
  assert(!Parse("45 200 0 999999999999999999999 0 0 0"));
}
