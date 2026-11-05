#include <cassert>
#include <rex/kernel/xam/lan_peer.h>

int main() {
  using namespace rex::kernel::xam::lan;
  SessionAddresses table;
  assert(!SessionAddresses::IsHandle(0xFFFFFFFFu)); // Preserve UDP broadcast.
  assert(!SessionAddresses::IsHandle(0xC0A8014Cu));
  const IP ip{192,168,1,76}, other{192,168,1,95};
  const std::array<uint8_t,8> first{0xAE,1}, second{0xAE,2};
  PeerRecord old{MakeAddress(ip,3074,0xB13EBABEBABEBABEull),first};
  PeerRecord current{old.address,second};
  const auto a=table.Register(old), b=table.Register(current);
  assert(a && b && a!=b);
  assert(SessionAddresses::IsHandle(a) && SessionAddresses::IsHandle(b));
  assert(table.Register(old)==a && table.Register(current)==b);
  // Resolving the stale first-session object must not overwrite the new key.
  assert(table.Lookup(b)->id==second && table.Lookup(a)->id==first);
  assert(table.Incoming(ip,second)==b && table.Incoming(ip,first)==a);
  assert(table.Outgoing(a)==ip && table.Outgoing(b)==ip);
  auto stripped=current;
  for (unsigned i=16;i<36;i++) stripped.address[i]=0;
  assert(table.Register(stripped)==b); // Title XNADDR can omit SGADDR.
  assert(table.Lookup(b)->address==stripped.address);
  PeerRecord third{MakeAddress(other,3074,8),second};
  const auto c=table.Register(third);
  assert(c!=b && table.Incoming(other,second)==c);
  assert(table.Unregister(a));
  assert(!table.Lookup(a) && !table.Outgoing(a));
  assert(table.Lookup(b)->id==second);
  assert(!table.Unregister(a));
  table.Clear();
  assert(!table.Lookup(b) && !table.Incoming(ip,second));
  // Cleared addresses can still be cached by guest code; never reuse them.
  const auto d=table.Register(current);
  assert(d!=a && d!=b && d!=c);
  assert(!table.Outgoing(b));
  assert(!table.Register(PeerRecord{}));
  assert(!table.Register(PeerRecord{current.address,{}}));
}
