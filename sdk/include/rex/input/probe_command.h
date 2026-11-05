#pragma once

#include <cstdint>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>

namespace rex::input::probe {
struct Command {
  uint64_t id;
  int duration_ms;
  uint16_t buttons;
  int16_t lx, ly, rx, ry;
};
inline std::optional<Command> Parse(std::string_view text) {
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string_view::npos || text[first] == '-') return std::nullopt;
  std::istringstream stream{std::string(text)};
  uint64_t id;
  int duration, buttons, lx, ly, rx, ry;
  if (!(stream >> id >> duration >> std::hex >> buttons >> std::dec >> lx >> ly >> rx >> ry)) {
    return std::nullopt;
  }
  stream >> std::ws;
  if (!stream.eof() || duration < 0 || duration > 10000 || buttons < 0 || buttons > 0xFFFF ||
      lx < -32768 || lx > 32767 || ly < -32768 || ly > 32767 ||
      rx < -32768 || rx > 32767 || ry < -32768 || ry > 32767) {
    return std::nullopt;
  }
  return Command{id, duration, static_cast<uint16_t>(buttons), static_cast<int16_t>(lx),
                 static_cast<int16_t>(ly), static_cast<int16_t>(rx), static_cast<int16_t>(ry)};
}
}  // namespace rex::input::probe
