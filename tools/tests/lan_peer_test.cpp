#include <cassert>
#include <rex/kernel/xam/lan_peer.h>

int main() {
  using namespace rex::kernel::xam::lan;
  const IP ip{127, 0, 0, 2};
  const auto address = MakeAddress(ip, 3074, 0xB13EBABEBABEBAC0ull);
  assert(address[0] == 127 && address[3] == 2 && address[4] == 127 && address[7] == 2);
  assert(address[8] == 0x0C && address[9] == 0x02);
  assert(address[10] == 2 && address[15] == 0xC0);
  assert(address != MakeAddress(ip, 3074, 0xB13EBABEBABEBAC1ull));
  assert(PeerIP(address) == ip);
  assert(!PeerIP(Address{}));
  auto fallback = address;
  for (int i = 4; i < 8; ++i) fallback[i] = 0;
  assert(PeerIP(fallback) == ip);
  Key key{};
  key[0] = 0x12;
  key[15] = 0x34;
  const auto session = MakeSession(address, 0xAE01020304050607ull, key);
  assert(session[0] == 0xAE && session[7] == 7);
  assert(session[8] == 127 && session[15] == 2);
  assert(session[44] == 0x12 && session[59] == 0x34);
  assert(ValidSession(session));
  assert(!ValidSession(Session{}));
  assert(!ValidSession(MakeSession(address, 0, key)));
  assert(!ValidSession(MakeSession(Address{}, 1, key)));
  const IP remote{127, 0, 0, 3};
  const std::array<uint8_t, 8> id{0xAE, 1, 2, 3, 4, 5, 6, 7};
  const auto peer = ConfiguredPeer(remote, remote, 0xB13EBABEBABEBAC1ull, id, 3074);
  assert(peer && peer->id == id && PeerIP(peer->address) == remote);
  assert(peer->address[15] == 0xC1);
  assert(!ConfiguredPeer(ip, remote, 1, id, 3074));
  assert(!ConfiguredPeer(remote, remote, 0, id, 3074));
  assert(!ConfiguredPeer(remote, remote, 1, {}, 3074));
  assert(!ConfiguredPeer(remote, remote, 1, id, 0));
}
