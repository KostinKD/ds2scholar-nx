#include <cassert>
#include <rex/kernel/xam/lan_peer.h>
int main() {
  using namespace rex::kernel::xam::lan;
  const IP remote{192,168,1,76}, local{192,168,1,95};
  const std::array<uint8_t,8> old{0xAE,0xE1,0x33,0x36,0x8C,0x77,0x23,0x76};
  const std::array<uint8_t,8> active{0xAE,0x91,0xBB,0x5C,0x22,0xAE,0x9E,0xF6};
  PeerRecord cached{MakeAddress(remote,3074,0xB13EBABEBABEBABEull),old};
  SessionAddresses table;
  const auto current=table.Register({cached.address,active});
  assert(table.Register(cached)!=current); // Actual old/new keys produce the duplicate-host condition.
  const auto originalAddress=cached.address;
  assert(UseActiveSessionKey(cached,remote,active));
  assert(cached.id==active && cached.address==originalAddress);
  assert(table.Register(cached)==current && table.Incoming(remote,active)==current);
  assert(!UseActiveSessionKey(cached,remote,active));
  cached.id=old;
  assert(!UseActiveSessionKey(cached,local,active) && cached.id==old);
  assert(!UseActiveSessionKey(cached,remote,{}) && cached.id==old);
  cached.id={};
  assert((!UseActiveSessionKey(cached,remote,active) && cached.id==std::array<uint8_t,8>{}));
}
