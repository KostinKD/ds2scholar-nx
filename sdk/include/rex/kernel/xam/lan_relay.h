#pragma once
// P2P relay client packets (net_p2p_relay; docs/online-relay.md). The server side is ds3os-x360 X360RelayService.
// All values big-endian. Datagrams start with "DS2R", version 1, a type:
//   1 register  client -> relay  XUID u64, game port u16
//   4 ack       relay -> client  XUID u64, game port u16
//   2 data      client -> relay  to XUID u64, to port u16, payload
//   3 data      relay -> client  from XUID u64, from port u16, payload

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <optional>
#include <span>
#include <string_view>
#include <vector>

#include <rex/kernel/xam/lan_peer.h>

namespace rex::kernel::xam::relay {

constexpr uint8_t kVersion = 1;
constexpr uint8_t kRegister = 1, kDataOut = 2, kDataIn = 3, kAck = 4;
constexpr size_t kHeader = 6;
constexpr size_t kAddressedHeader = kHeader + 8 + 2;  // data and ack: XUID, port
constexpr size_t kMaxPayload = 1400 - kAddressedHeader;

inline void Put(std::vector<uint8_t>& out, uint64_t value, int bytes) {
  for (int i = bytes - 1; i >= 0; --i) out.push_back(uint8_t(value >> (8 * i)));
}

inline uint64_t Get(std::span<const uint8_t> in, size_t at, int bytes) {
  uint64_t value = 0;
  for (int i = 0; i < bytes; ++i) value = (value << 8) | in[at + i];
  return value;
}

inline std::vector<uint8_t> Header(uint8_t type) { return {'D', 'S', '2', 'R', kVersion, type}; }

inline std::vector<uint8_t> Register(uint64_t xuid, uint16_t game_port) {
  auto out = Header(kRegister);
  Put(out, xuid, 8);
  Put(out, game_port, 2);
  return out;
}

inline std::vector<uint8_t> Data(uint64_t to_xuid, uint16_t to_port, std::span<const uint8_t> payload) {
  auto out = Header(kDataOut);
  out.reserve(kAddressedHeader + payload.size());
  Put(out, to_xuid, 8);
  Put(out, to_port, 2);
  out.insert(out.end(), payload.begin(), payload.end());
  return out;
}

// A datagram from the relay: type, the XUID and port it names, and where the payload starts.
struct Incoming {
  uint8_t type = 0;
  uint64_t xuid = 0;
  uint16_t port = 0;
  size_t payload = 0;
};

inline std::optional<Incoming> Parse(std::span<const uint8_t> datagram) {
  if (datagram.size() < kAddressedHeader || std::memcmp(datagram.data(), "DS2R", 4) != 0 ||
      datagram[4] != kVersion || (datagram[5] != kDataIn && datagram[5] != kAck))
    return std::nullopt;
  if (datagram[5] == kAck && datagram.size() != kAddressedHeader) return std::nullopt;
  return Incoming{datagram[5], Get(datagram, kHeader, 8), uint16_t(Get(datagram, kHeader + 8, 2)),
                  kAddressedHeader};
}

// The address a relayed player gets instead of a LAN IP: 100.64.0.0/10 (shared address space, never routed here)
// with 22 bits of the XUID. It is only a key for the guest's address handles; packets go by XUID.
inline lan::IP PseudoIP(uint64_t xuid) {
  const uint32_t bits = uint32_t(xuid & 0x3FFFFF);
  lan::IP ip{100, uint8_t(64 | (bits >> 16)), uint8_t(bits >> 8), uint8_t(bits)};
  if (ip[3] == 0) ip[3] = 1;
  return ip;
}

// Client hello for the server's X360MinClientProtocol (ds3os-x360 X360LoginService): "DS2V", version 1, client
// protocol (u16), one zero byte; sent from the login socket before the game's first login datagram. Protocol 1: the
// first build that sends it (relay with XUIDs kept by handle, 1.10.0-wake2). Raise it when an older client would break
// sessions with a newer one.
constexpr uint16_t kClientProtocol = 1;

inline std::vector<uint8_t> ClientHello(uint16_t protocol = kClientProtocol) {
  std::vector<uint8_t> out{'D', 'S', '2', 'V', 1};
  Put(out, protocol, 2);
  out.push_back(0);
  return out;
}

// Version 2 of the hello (net_access): the same plus the 16-byte ticket of an approved console key.
inline std::vector<uint8_t> ClientHello(const std::array<uint8_t, 16>& ticket, uint16_t protocol = kClientProtocol) {
  std::vector<uint8_t> out{'D', 'S', '2', 'V', 2};
  Put(out, protocol, 2);
  out.push_back(0);
  out.insert(out.end(), ticket.begin(), ticket.end());
  return out;
}

// Console-key access (net_access; docs/online-access.md; server: ds3os-x360 X360LoginService::HandleAccess). From a
// socket of its own to the login port: hello -> challenge, proof -> result. "DS2A", version 1, a type:
//   1 hello      XUID u64, public key 32, name length u8, name 15 (zero-padded)     62 bytes
//   2 challenge  nonce 32                                                            38 bytes
//   3 proof      XUID u64, public key 32, Ed25519 signature 64                      110 bytes
//   4 result     status u8, ticket 16                                                23 bytes
// The signature covers kAccessContext (14 bytes) || nonce || XUID (8, big-endian) || public key.
namespace access {
constexpr uint8_t kHello = 1, kChallenge = 2, kProof = 3, kResult = 4;
constexpr uint8_t kApproved = 0, kPending = 1, kRejected = 2, kInvalid = 3;
constexpr char kContext[] = "DS2A access v1";
using Key = std::array<uint8_t, 32>;
using Nonce = std::array<uint8_t, 32>;
using Signature = std::array<uint8_t, 64>;
using Ticket = std::array<uint8_t, 16>;

inline std::vector<uint8_t> Header(uint8_t type) { return {'D', 'S', '2', 'A', 1, type}; }

inline std::vector<uint8_t> Hello(uint64_t xuid, const Key& key, std::string_view name) {
  auto out = Header(kHello);
  Put(out, xuid, 8);
  out.insert(out.end(), key.begin(), key.end());
  const size_t length = std::min<size_t>(name.size(), 15);
  out.push_back(uint8_t(length));
  out.insert(out.end(), name.begin(), name.begin() + length);
  out.resize(62, 0);
  return out;
}

inline std::vector<uint8_t> Signed(const Nonce& nonce, uint64_t xuid, const Key& key) {
  std::vector<uint8_t> out(kContext, kContext + 14);
  out.insert(out.end(), nonce.begin(), nonce.end());
  Put(out, xuid, 8);
  out.insert(out.end(), key.begin(), key.end());
  return out;
}

inline std::vector<uint8_t> Proof(uint64_t xuid, const Key& key, const Signature& signature) {
  auto out = Header(kProof);
  Put(out, xuid, 8);
  out.insert(out.end(), key.begin(), key.end());
  out.insert(out.end(), signature.begin(), signature.end());
  return out;
}

inline bool IsType(std::span<const uint8_t> datagram, uint8_t type, size_t size) {
  return datagram.size() == size && std::memcmp(datagram.data(), "DS2A", 4) == 0 && datagram[4] == 1 &&
         datagram[5] == type;
}

inline std::optional<Nonce> ParseChallenge(std::span<const uint8_t> datagram) {
  if (!IsType(datagram, kChallenge, 38)) return std::nullopt;
  Nonce nonce;
  std::memcpy(nonce.data(), datagram.data() + 6, 32);
  return nonce;
}

struct Result {
  uint8_t status = kInvalid;
  Ticket ticket{};
};

inline std::optional<Result> ParseResult(std::span<const uint8_t> datagram) {
  if (!IsType(datagram, kResult, 23)) return std::nullopt;
  Result result;
  result.status = datagram[6];
  std::memcpy(result.ticket.data(), datagram.data() + 7, 16);
  return result;
}
}  // namespace access

// The XUID a peer address carries (SGADDR bytes 24..31, lan::MakeAddress); 0 if there is none.
inline uint64_t AddressXuid(const lan::Address& address) {
  uint64_t xuid = 0;
  for (int i = 0; i < 8; ++i) xuid = (xuid << 8) | address[24 + i];
  return xuid;
}

}  // namespace rex::kernel::xam::relay
