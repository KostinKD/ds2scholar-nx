#pragma once
#include <algorithm>
#include <charconv>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <span>
#include <string>
#include <string_view>
#include <vector>
namespace rex::kernel::xam::names {
struct User {
  uint64_t xuid;
  std::string gamertag;
};
enum class Status { Success, InvalidArgument, InsufficientBuffer };
inline std::vector<User> ParseDirectory(std::string_view text) {
  std::vector<User> users;
  while (!text.empty()) {
    const auto end = text.find(';');
    const auto entry = text.substr(0, end);
    const auto equals = entry.find('=');
    if (equals != std::string_view::npos) {
      auto key = entry.substr(0, equals);
      if (key.starts_with("0x") || key.starts_with("0X"))
        key.remove_prefix(2);
      uint64_t xuid = 0;
      const auto result =
          std::from_chars(key.data(), key.data() + key.size(), xuid, 16);
      if (!key.empty() && result.ec == std::errc{} &&
          result.ptr == key.data() + key.size())
        users.push_back({xuid, std::string(entry.substr(equals + 1))});
    }
    if (end == std::string_view::npos)
      break;
    text.remove_prefix(end + 1);
  }
  return users;
}
inline uint32_t Read32(std::span<const uint8_t> b, size_t p) {
  return uint32_t(b[p]) << 24 | uint32_t(b[p + 1]) << 16 |
         uint32_t(b[p + 2]) << 8 | b[p + 3];
}
inline uint64_t Read64(std::span<const uint8_t> b, size_t p) {
  return uint64_t(Read32(b, p)) << 32 | Read32(b, p + 4);
}
inline uint32_t ReadWire32(std::span<const uint8_t> b, size_t p) {
  return uint32_t(b[p + 3]) << 24 | uint32_t(b[p + 2]) << 16 |
         uint32_t(b[p + 1]) << 8 | b[p];
}
inline uint64_t ReadWire64(std::span<const uint8_t> b, size_t p) {
  return uint64_t(ReadWire32(b, p + 4)) << 32 | ReadWire32(b, p);
}
inline bool Valid(const User &user) {
  return user.xuid && !user.gamertag.empty() && user.gamertag.size() <= 15 &&
         user.gamertag.find('\0') == std::string::npos;
}
inline bool SameName(std::string_view a, std::string_view b) {
  const auto lower = [](unsigned char c) {
    return c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c;
  };
  return a.size() == b.size() &&
         std::equal(a.begin(), a.end(), b.begin(),
                    [&](auto x, auto y) { return lower(x) == lower(y); });
}
inline void Write(std::span<uint8_t> b, size_t p, uint64_t value, size_t size) {
  for (size_t i = 0; i < size; ++i) {
    b[p + size - 1 - i] = uint8_t(value);
    value >>= 8;
  }
}
inline Status Resolve(std::span<const uint8_t> request,
                      std::span<uint8_t> output, uint32_t output_address,
                      std::span<const User> directory) {
  // SotFS's marshalled wire request is little-endian, unlike the output in
  // guest memory. BASE_MSG_HEADER32 + issuer XUID8 + count4 + records24.
  if (request.size() < 44)
    return Status::InvalidArgument;
  const auto count = ReadWire32(request, 40);
  if (count > 256 || request.size() != 44 + size_t(count) * 24)
    return Status::InvalidArgument;
  const size_t required = 8 + size_t(count) * 24;
  if (!output_address ||
      output_address > std::numeric_limits<uint32_t>::max() - required)
    return Status::InvalidArgument;
  if (output.size() < required)
    return Status::InsufficientBuffer;
  std::vector<const User *> resolved;
  for (uint32_t i = 0; i < count; ++i) {
    const auto at = 44 + size_t(i) * 24;
    const auto xuid = ReadWire64(request, at);
    const auto first = request.begin() + at + 8;
    const auto last = std::find(first, first + 16, uint8_t(0));
    const std::string gamertag(first, last);
    const User *found = nullptr;
    bool ambiguous = false;
    for (const auto &user : directory) {
      if (!Valid(user) ||
          (xuid ? user.xuid != xuid : !SameName(user.gamertag, gamertag)))
        continue;
      if (found &&
          (found->xuid != user.xuid || found->gamertag != user.gamertag)) {
        ambiguous = true;
        break;
      }
      found = &user;
    }
    if (found && !ambiguous)
      resolved.push_back(found);
  }
  // Only write after all validation/reads, including when input aliases output.
  std::fill_n(output.begin(), required, uint8_t(0));
  Write(output, 0, resolved.size(), 4);
  Write(output, 4, output_address + 8, 4);
  for (size_t i = 0; i < resolved.size(); ++i) {
    Write(output, 8 + i * 24, resolved[i]->xuid, 8);
    std::copy(resolved[i]->gamertag.begin(), resolved[i]->gamertag.end(),
              output.begin() + 16 + i * 24);
  }
  return Status::Success;
}
// XUIDs asked by a SotFS XUserFindUsers request (same layout checks as Resolve); empty if it is not valid.
// Records looked up by gamertag only (XUID 0) are left out.
inline std::vector<uint64_t> RequestedXuids(std::span<const uint8_t> request) {
  std::vector<uint64_t> xuids;
  if (request.size() < 44)
    return xuids;
  const auto count = ReadWire32(request, 40);
  if (count > 256 || request.size() != 44 + size_t(count) * 24)
    return xuids;
  for (uint32_t i = 0; i < count; ++i) {
    const auto xuid = ReadWire64(request, 44 + size_t(i) * 24);
    if (xuid && std::find(xuids.begin(), xuids.end(), xuid) == xuids.end())
      xuids.push_back(xuid);
  }
  return xuids;
}

// Gamertag of a player whose name is not known: the same "Player-XXXX" a device gets from
// net_profile_generate_xuid without net_profile_name, so both sides show the same name.
inline std::string FallbackName(uint64_t xuid) {
  char text[16];
  std::snprintf(text, sizeof(text), "Player-%04X", unsigned(xuid & 0xFFFF));
  return text;
}

// Server gamertag lookup (ds3os-x360 X360NameService) on the title server's login port. Request: "DS2N",
// version 1, count (1..16), nonce u32, count XUIDs (big-endian), zero padded to the largest reply so the
// server never answers with more bytes than it got. Reply: "DS2n", 1, count, nonce, then per XUID: XUID u64,
// length u8, gamertag (empty: unknown).
constexpr size_t kServiceHeader = 10;
constexpr size_t kServiceEntry = 24;
constexpr size_t kServiceMaxCount = 16;

inline std::vector<uint8_t> BuildServiceRequest(std::span<const uint64_t> xuids, uint32_t nonce) {
  std::vector<uint8_t> packet;
  if (xuids.empty() || xuids.size() > kServiceMaxCount)
    return packet;
  packet.resize(kServiceHeader + xuids.size() * kServiceEntry);
  const char magic[4] = {'D', 'S', '2', 'N'};
  std::copy(magic, magic + 4, packet.begin());
  packet[4] = 1;
  packet[5] = uint8_t(xuids.size());
  Write(packet, 6, nonce, 4);
  for (size_t i = 0; i < xuids.size(); ++i)
    Write(packet, kServiceHeader + i * 8, xuids[i], 8);
  return packet;
}

// Names from a reply to BuildServiceRequest(asked, nonce); false if it is not that reply. Unknown XUIDs come
// back with an empty gamertag; invalid gamertags are dropped (the XUID then counts as unknown).
inline bool ParseServiceReply(std::span<const uint8_t> reply, uint32_t nonce, std::span<const uint64_t> asked,
                              std::vector<User> &names) {
  names.clear();
  if (reply.size() < kServiceHeader || reply[0] != 'D' || reply[1] != 'S' || reply[2] != '2' ||
      reply[3] != 'n' || reply[4] != 1 || reply[5] != asked.size() || Read32(reply, 6) != nonce)
    return false;
  size_t at = kServiceHeader;
  for (const auto xuid : asked) {
    if (at + 9 > reply.size() || Read64(reply, at) != xuid)
      return false;
    const size_t length = reply[at + 8];
    if (length > 15 || at + 9 + length > reply.size())
      return false;
    User user{xuid, std::string(reply.begin() + at + 9, reply.begin() + at + 9 + length)};
    if (!Valid(user))
      user.gamertag.clear();
    names.push_back(std::move(user));
    at += 9 + length;
  }
  return at == reply.size();
}
} // namespace rex::kernel::xam::names
