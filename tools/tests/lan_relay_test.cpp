// P2P relay client packets (sdk/include/rex/kernel/xam/lan_relay.h) against the server format of
// ds3os-x360 X360RelayService (Tools/Tests/test_x360_relay_udp.py).
#include <cassert>
#include <cstdio>
#include <rex/kernel/xam/lan_relay.h>
#include <monocypher-ed25519.h>

using namespace rex::kernel::xam;

int main() {
  constexpr uint64_t a = 0xB13E98C73B92CE1D, b = 0xB13EBABEBABEBAC0;
  const auto reg = relay::Register(a, 6002);
  const std::vector<uint8_t> want_reg{'D', 'S', '2', 'R', 1, 1, 0xB1, 0x3E, 0x98, 0xC7, 0x3B, 0x92, 0xCE, 0x1D, 0x17, 0x72};
  assert(reg == want_reg);

  const std::vector<uint8_t> payload{0xF5, 0x02, 0x10, 0x00, 0x02, 0xFF};
  const auto out = relay::Data(b, 10010, payload);
  assert(out.size() == relay::kAddressedHeader + payload.size() && out[5] == relay::kDataOut &&
         relay::Get(out, 6, 8) == b && relay::Get(out, 14, 2) == 10010 && out.back() == 0xFF);

  // What the relay sends back: type 3 from b, port 6002, payload.
  std::vector<uint8_t> in = relay::Header(relay::kDataIn);
  relay::Put(in, b, 8);
  relay::Put(in, 6002, 2);
  in.insert(in.end(), payload.begin(), payload.end());
  const auto parsed = relay::Parse(in);
  assert(parsed && parsed->type == relay::kDataIn && parsed->xuid == b && parsed->port == 6002 &&
         in.size() - parsed->payload == payload.size() && in[parsed->payload] == 0xF5);

  std::vector<uint8_t> ack = relay::Header(relay::kAck);
  relay::Put(ack, a, 8);
  relay::Put(ack, 6002, 2);
  assert(relay::Parse(ack) && relay::Parse(ack)->type == relay::kAck);
  ack.push_back(0);
  assert(!relay::Parse(ack));                                            // ack with extra bytes
  assert(!relay::Parse(reg));                                            // a client type never comes back
  assert(!relay::Parse(std::vector<uint8_t>(in.begin(), in.begin() + 10)));  // short
  auto wrong = in;
  wrong[4] = 2;
  assert(!relay::Parse(wrong));                                          // version
  wrong = in;
  wrong[0] = 'X';
  assert(!relay::Parse(wrong));                                          // a game packet, not the relay's

  const auto ip = relay::PseudoIP(a);
  assert(ip[0] == 100 && (ip[1] & 0xC0) == 64 && ip[3] != 0 && relay::PseudoIP(a) == ip);
  assert(relay::PseudoIP(b) != ip);
  assert(lan::PeerIP(lan::MakeAddress(ip, 3074, a)) == ip);              // a valid peer IP for the handles
  assert(relay::AddressXuid(lan::MakeAddress(ip, 3074, a)) == a);
  const std::vector<uint8_t> want_hello{'D', 'S', '2', 'V', 1, 0, 1, 0};  // test_x360_client_protocol_udp.py
  assert(relay::ClientHello() == want_hello && relay::ClientHello(2)[6] == 2);

  // Console-key access (docs/online-access.md; sizes and layout as test_x360_access_udp.py).
  namespace access = relay::access;
  relay::access::Ticket ticket{};
  for (int i = 0; i < 16; ++i) ticket[i] = uint8_t(0xA0 + i);
  const auto hello2 = relay::ClientHello(ticket);
  assert(hello2.size() == 24 && hello2[4] == 2 && hello2[6] == 1 && hello2[8] == 0xA0 && hello2[23] == 0xAF);
  // RFC 8032 test 1: seed -> public key, the signature of an empty message (Monocypher, as the console signs)
  uint8_t seed[32], secret[64];
  access::Key key;
  const char* seed_hex = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60";
  for (int i = 0; i < 32; ++i) sscanf(seed_hex + 2 * i, "%2hhx", &seed[i]);
  crypto_ed25519_key_pair(secret, key.data(), seed);
  assert(key[0] == 0xd7 && key[1] == 0x5a && key[31] == 0x1a);
  access::Signature signature;
  crypto_ed25519_sign(signature.data(), secret, nullptr, 0);
  assert(signature[0] == 0xe5 && signature[1] == 0x56 && signature[63] == 0x0b);
  const uint64_t xuid = 0xB13E98C73B92CE1Dull;
  const auto hello = access::Hello(xuid, key, "ThisNameIsLongerThan15");
  assert(hello.size() == 62 && hello[5] == access::kHello && hello[13] == 0x1D && hello[14] == 0xd7 && hello[46] == 15 &&
         hello[47] == 'T' && hello[61] == 'e');
  access::Nonce nonce{};
  nonce[0] = 7;
  const auto signed_bytes = access::Signed(nonce, xuid, key);
  assert(signed_bytes.size() == 14 + 32 + 8 + 32 && signed_bytes[0] == 'D' && signed_bytes[14] == 7 && signed_bytes[46] == 0xB1);
  crypto_ed25519_sign(signature.data(), secret, signed_bytes.data(), signed_bytes.size());
  assert(crypto_ed25519_check(signature.data(), key.data(), signed_bytes.data(), signed_bytes.size()) == 0);
  const auto proof = access::Proof(xuid, key, signature);
  assert(proof.size() == 110 && proof[5] == access::kProof && proof[46] == signature[0] && proof[109] == signature[63]);
  std::vector<uint8_t> challenge{'D', 'S', '2', 'A', 1, 2};
  challenge.resize(38, 9);
  assert(access::ParseChallenge(challenge) && (*access::ParseChallenge(challenge))[31] == 9);
  challenge.push_back(0);
  assert(!access::ParseChallenge(challenge));                            // wrong size
  std::vector<uint8_t> result{'D', 'S', '2', 'A', 1, 4, access::kApproved};
  result.insert(result.end(), ticket.begin(), ticket.end());
  assert(access::ParseResult(result) && access::ParseResult(result)->ticket == ticket);
  result[5] = 2;
  assert(!access::ParseResult(result));                                  // a challenge is not a result
  puts("lan relay: client hello, register/data packets, relay replies, rejection, pseudo IP and address XUID passed");
  puts("access: hello v2, RFC 8032 vector, hello/proof/challenge/result layout passed");
}
