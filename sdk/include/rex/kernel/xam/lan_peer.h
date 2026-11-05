#pragma once

#include <array>
#include <algorithm>
#include <cstdint>
#include <optional>
#include <map>

namespace rex::kernel::xam::lan {
using IP = std::array<uint8_t, 4>;
using Address = std::array<uint8_t, 36>;
using Session = std::array<uint8_t, 60>;
using Key = std::array<uint8_t, 16>;
struct PeerRecord { Address address; std::array<uint8_t, 8> id; };

inline Address MakeAddress(IP ip, uint16_t port, uint64_t xuid) {
  Address out{};
  std::copy(ip.begin(), ip.end(), out.begin());
  std::copy(ip.begin(), ip.end(), out.begin() + 4);
  out[8] = uint8_t(port >> 8);
  out[9] = uint8_t(port);
  out[10] = 2;  // locally administered MAC, one address per test profile
  for (int i = 0; i < 5; ++i) out[11 + i] = uint8_t(xuid >> ((4 - i) * 8));
  std::copy(ip.begin(), ip.end(), out.begin() + 16);  // SGADDR.ina, direct LAN only
  for (int i = 0; i < 8; ++i) out[24 + i] = uint8_t(xuid >> ((7 - i) * 8));
  out[32] = 1;  // SGADDR platform: Xbox 360
  return out;
}
inline Session MakeSession(Address address, uint64_t id, Key key) {
  Session out{};
  for (int i = 0; i < 8; ++i) out[i] = uint8_t(id >> ((7 - i) * 8));
  std::copy(address.begin(), address.end(), out.begin() + 8);
  std::copy(key.begin(), key.end(), out.begin() + 44);
  return out;
}
inline std::optional<IP> PeerIP(const Address& address) {
  IP ip{};
  std::copy_n(address.begin() + 4, 4, ip.begin());
  if (ip == IP{}) std::copy_n(address.begin(), 4, ip.begin());
  if (ip == IP{} || ip[0] >= 224) return std::nullopt;
  return ip;
}
inline bool ValidSession(const Session& session) {
  Address address{};
  std::copy_n(session.begin() + 8, 36, address.begin());
  return std::any_of(session.begin(), session.begin() + 8, [](uint8_t b) { return b != 0; }) &&
         PeerIP(address).has_value() && (address[8] || address[9]);
}
inline std::optional<PeerRecord> ConfiguredPeer(IP requested, IP configured, uint64_t xuid,
                                               std::array<uint8_t, 8> id, uint16_t port) {
  if (requested != configured || !xuid || !port ||
      !std::any_of(id.begin(), id.end(), [](uint8_t b) { return b != 0; })) return std::nullopt;
  const auto address = MakeAddress(configured, port, xuid);
  if (!PeerIP(address)) return std::nullopt;
  return PeerRecord{address, id};
}

// An existing guest PlayerData may retain the previous session's XNKID after
// roles reverse. Opt-in caller may resolve only the configured peer against
// the current XSession key, leaving unrelated peers and invalid keys untouched.
inline bool UseActiveSessionKey(PeerRecord& peer, IP configured, std::array<uint8_t,8> active) {
  if (PeerIP(peer.address) != configured || peer.id == active ||
      !std::any_of(peer.id.begin(), peer.id.end(), [](uint8_t b) { return b != 0; }) ||
      !std::any_of(active.begin(), active.end(), [](uint8_t b) { return b != 0; })) return false;
  peer.id = active;
  return true;
}

// Guest IN_ADDR handles for the explicit one-peer LAN experiment. A physical
// endpoint reused with a different XNKID must not replace the earlier record.
// Reserved handles never reach the OS: xam_net translates them at the socket edge.
// Caller serializes access. Clear removes associations but never recycles handles
// because guest network objects can outlive XSessionDelete.
class SessionAddresses {
 public:
  static bool IsHandle(uint32_t address) {
    return (address & 0xF0000000u) == 0xF0000000u && address != 0xFFFFFFFFu;
  }

  uint32_t Register(const PeerRecord& peer) {
    const auto ip = PeerIP(peer.address);
    if (!ip || !std::any_of(peer.id.begin(), peer.id.end(), [](uint8_t b) { return b != 0; })) return 0;
    for (auto& [handle, record] : peers_) {
      if (record.id == peer.id && PeerIP(record.address) == ip) {
        record = peer;
        return handle;
      }
    }
    if (next_ == 0xFFFFFFFFu) return 0;
    const uint32_t handle = next_++;
    peers_.emplace(handle, peer);
    return handle;
  }

  std::optional<PeerRecord> Lookup(uint32_t handle) const {
    const auto found = peers_.find(handle);
    if (found == peers_.end()) return std::nullopt;
    return found->second;
  }

  std::optional<IP> Outgoing(uint32_t handle) const {
    const auto peer = Lookup(handle);
    return peer ? PeerIP(peer->address) : std::nullopt;
  }

  std::optional<uint32_t> Incoming(IP ip, std::array<uint8_t, 8> id) const {
    for (const auto& [handle, peer] : peers_) {
      if (peer.id == id && PeerIP(peer.address) == ip) return handle;
    }
    return std::nullopt;
  }

  bool Unregister(uint32_t handle) { return peers_.erase(handle) != 0; }
  void Clear() { peers_.clear(); }

 private:
  std::map<uint32_t, PeerRecord> peers_;
  uint32_t next_ = 0xF0000001u;
};

// Runtime bridge, defined in xam_net.cpp. Called only behind net_p2p_lan.
uint32_t CreateSession(uint32_t flags, uint32_t info_ptr, uint32_t nonce_ptr);
void EndSession();
}  // namespace rex::kernel::xam::lan
