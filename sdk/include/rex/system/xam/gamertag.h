#pragma once
// ds2scholar-nx: a 360 gamertag from a Switch nickname (docs/online-public-plan.md, stage A).
// Gamertags allow letters, digits, space, _ - . and up to 15 characters (SotFS sign names, server X360Names).
// Cyrillic is transliterated (Даниил -> Daniil); a nickname with anything that has no Latin form gives "".

#include <cstdint>
#include <string>
#include <string_view>

namespace rex::system::xam::gamertag {

// Latin form of one Cyrillic letter (lower case), or nullptr if the code point is not one.
inline const char* CyrillicLatin(uint32_t c) {
  static const char* const kRussian[32] = {"a", "b",  "v",  "g",    "d", "e", "zh", "z",  "i",  "y", "k",
                                           "l", "m",  "n",  "o",    "p", "r", "s",  "t",  "u",  "f", "kh",
                                           "ts", "ch", "sh", "shch", "",  "y", "",   "e",  "yu", "ya"};
  if (c >= 0x0410 && c <= 0x042F) return kRussian[c - 0x0410];  // А..Я
  if (c >= 0x0430 && c <= 0x044F) return kRussian[c - 0x0430];  // а..я
  switch (c) {
    case 0x0401: case 0x0451: return "e";   // Ё ё
    case 0x0406: case 0x0456: return "i";   // І і
    case 0x0407: case 0x0457: return "yi";  // Ї ї
    case 0x0404: case 0x0454: return "ye";  // Є є
    case 0x0490: case 0x0491: return "g";   // Ґ ґ
    case 0x040E: case 0x045E: return "u";   // Ў ў
    default: return nullptr;
  }
}

inline bool IsUpperCyrillic(uint32_t c) {
  return (c >= 0x0400 && c <= 0x042F) || c == 0x0490;
}

inline bool IsGamertagChar(char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == ' ' || c == '_' ||
         c == '-' || c == '.';
}

// The gamertag for a UTF-8 nickname: ASCII gamertag characters as they are, Cyrillic transliterated, spaces at the
// ends trimmed, cut to 15. "" if the nickname has any other character (or is malformed UTF-8) or ends up empty.
inline std::string FromNickname(std::string_view nickname) {
  std::string out;
  for (size_t i = 0; i < nickname.size();) {
    const auto byte = uint8_t(nickname[i]);
    if (byte < 0x80) {
      if (!IsGamertagChar(char(byte))) return "";
      out.push_back(char(byte));
      ++i;
      continue;
    }
    // Cyrillic is in the two-byte range (U+0400..U+04FF); anything longer has no Latin form here.
    if ((byte & 0xE0) != 0xC0 || i + 1 >= nickname.size() || (uint8_t(nickname[i + 1]) & 0xC0) != 0x80) return "";
    const uint32_t c = (uint32_t(byte & 0x1F) << 6) | (uint8_t(nickname[i + 1]) & 0x3F);
    const char* latin = CyrillicLatin(c);
    if (!latin) return "";
    std::string part(latin);
    if (IsUpperCyrillic(c) && !part.empty()) part[0] = char(part[0] - 'a' + 'A');
    out += part;
    i += 2;
  }
  while (!out.empty() && out.back() == ' ') out.pop_back();
  while (!out.empty() && out.front() == ' ') out.erase(out.begin());
  if (out.size() > 15) out.resize(15);
  while (!out.empty() && out.back() == ' ') out.pop_back();
  return out;
}

}  // namespace rex::system::xam::gamertag
