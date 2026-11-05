/**
 ******************************************************************************
 * Xenia : Xbox 360 Emulator Research Project                                 *
 ******************************************************************************
 * Copyright 2022 Ben Vanik. All rights reserved.                             *
 * Released under the BSD license - see LICENSE in the root for more details. *
 ******************************************************************************
 *
 * @modified    Tom Clay, 2026 - Adapted for ReXGlue runtime
 */

// Disable warnings about unused parameters for kernel functions
#pragma GCC diagnostic ignored "-Wunused-parameter"

#include <cstring>
#include <cerrno>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <random>
#include <atomic>
#include <chrono>
#include <set>
#include <thread>
#include <vector>

#if REX_PLATFORM_MAC
#include <sys/select.h>
#endif

#include <rex/chrono/clock.h>
#include <rex/kernel/xam/module.h>
#include <rex/kernel/xam/private.h>
#include <rex/kernel/xam/lan_peer.h>
#include <rex/kernel/xam/lan_relay.h>
#include <rex/kernel/xboxkrnl/error.h>
#include <rex/kernel/xboxkrnl/threading.h>
#include <rex/logging.h>
#include <rex/cvar.h>
#include <rex/hook.h>
#include <rex/types.h>

#include <monocypher-ed25519.h>
#include <rex/string.h>
#include <rex/runtime.h>
#include <rex/system/kernel_state.h>
#include <rex/system/xevent.h>
#include <rex/system/xsocket.h>
#include <rex/system/xthread.h>
#include <rex/system/xam/user_profile.h>
#include <rex/system/xtypes.h>

#if REX_PLATFORM_WIN32
// NOTE: must be included last as it expects windows.h to already be included.
#define _WINSOCK_DEPRECATED_NO_WARNINGS  // inet_addr
#include <winsock2.h>                    // NOLINT(build/include_order)
#include <ws2tcpip.h>                    // getaddrinfo, inet_ntop
#elif REX_PLATFORM_SWITCH
#include <fcntl.h>
#include <netdb.h>
#include <sys/select.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/ip.h>
#include <sys/socket.h>
// libnx's socket.h pulls in the SSL service types; only socketInitialize is needed (socketInitializeDefault = NULL).
extern "C" uint32_t socketInitialize(const void* config);
extern "C" void randomGet(void* buf, size_t len);  // libnx kernel/random.h: ChaCha from the kernel's entropy
#elif REX_PLATFORM_LINUX || REX_PLATFORM_MAC
#include <fcntl.h>
#include <netdb.h>
#include <sys/select.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/ip.h>
#include <sys/socket.h>
#endif

namespace rex {
namespace kernel {
namespace xam {
using namespace rex::system;
using namespace rex::system::xam;

// https://github.com/G91/TitanOffLine/blob/1e692d9bb9dfac386d08045ccdadf4ae3227bb5e/xkelib/xam/xamNet.h
enum {
  XNCALLER_INVALID = 0x0,
  XNCALLER_TITLE = 0x1,
  XNCALLER_SYSAPP = 0x2,
  XNCALLER_XBDM = 0x3,
  XNCALLER_TEST = 0x4,
  NUM_XNCALLER_TYPES = 0x4,
};

// https://github.com/pmrowla/hl2sdk-csgo/blob/master/common/xbox/xboxstubs.h
typedef struct {
  // FYI: IN_ADDR should be in network-byte order.
  in_addr ina;                    // IP address (zero if not static/DHCP)
  in_addr inaOnline;              // Online IP address (zero if not online)
  rex::be<uint16_t> wPortOnline;  // Online port
  uint8_t abEnet[6];              // Ethernet MAC address
  uint8_t abOnline[20];           // Online identification
} XNADDR;

typedef struct {
  rex::be<int32_t> status;
  rex::be<uint32_t> cina;
  in_addr aina[8];
} XNDNS;

// ds2-nx (2026-10-20, online recon): pretend the console is online, to see what the game asks for. Off = as before
// (no cable). With it: XNetGetEthernetLinkStatus reports a 100 Mbps link, XNetDnsLookup logs the host name and answers
// net_dns_address, the user is signed in to Live with every privilege (xam_user.cpp), and connect / send are logged.
REXCVAR_DEFINE_BOOL(net_online_probe, false, "Net",
                    "Recon: report a cable and a Live sign-in, log DNS lookups, connects and the first bytes sent");
REXCVAR_DEFINE_BOOL(ds2_socket_buffer_endian, false, "Net",
                    "Decode guest big-endian SO_SNDBUF/SO_RCVBUF integers before native setsockopt");
#if !REX_PLATFORM_WIN32
// ds2scholar-nx (2026-10-25, console online): a failed recvfrom left the guest's last error at 0 off Windows. Dark Souls
// II polls a non-blocking socket and needs WSAEWOULDBLOCK (10035) for "no data yet", as Winsock gives on the PC.
static uint32_t PosixErrorToWsa(int error) {
  switch (error) {
    case EAGAIN:
#if defined(EWOULDBLOCK) && EWOULDBLOCK != EAGAIN
    case EWOULDBLOCK:
#endif
      return 10035;  // WSAEWOULDBLOCK
    case EINTR: return 10004;         // WSAEINTR
    case EBADF: return 10009;         // WSAEBADF
    case EINVAL: return 10022;        // WSAEINVAL
    case EMSGSIZE: return 10040;      // WSAEMSGSIZE
    case ECONNRESET: return 10054;    // WSAECONNRESET
    case ENOTCONN: return 10057;      // WSAENOTCONN
    case ECONNREFUSED: return 10061;  // WSAECONNREFUSED
    case EHOSTUNREACH: return 10065;  // WSAEHOSTUNREACH
    case ENETUNREACH: return 10051;   // WSAENETUNREACH
    default: return 10022;  // WSAEINVAL; an unknown failure must not look like an empty receive queue.
  }
}
#endif

REXCVAR_DEFINE_STRING(net_dns_address, "127.0.0.1", "Net",
                      "net_online_probe: the online server, IPv4 or a host name (net_dns_fallback_address), that every "
                      "XNetDnsLookup answers");
REXCVAR_DEFINE_BOOL(net_p2p_diagnostics, false, "Net",
                    "Experimental diagnostics of XNADDR resolution and Live peer lookup; no transport changes");
REXCVAR_DEFINE_BOOL(net_p2p_guest_log, false, "Net",
                    "Capture SotFS internal network log through its optional callback (diagnostic only)");
REXCVAR_DEFINE_BOOL(net_p2p_game_trace, false, "Net",
                    "Trace SotFS initial game-message handlers without changing their results");
REXCVAR_DEFINE_BOOL(net_p2p_name_trace, false, "Net",
                    "Trace SotFS SignData identifiers before and after user-name resolution");
REXCVAR_DEFINE_BOOL(net_p2p_summon_name_probe, false, "Net",
                    "LAN test pair only: fill an empty pending summon name when the configured peer XUID matches");
REXCVAR_DEFINE_BOOL(net_p2p_lan, false, "Net",
                    "Experimental direct LAN session/address support between modified clients");
REXCVAR_DEFINE_BOOL(net_p2p_session_addresses, false, "Net",
                    "net_p2p_lan: keep distinct guest addresses for different session keys (experimental)");
REXCVAR_DEFINE_BOOL(net_p2p_active_session_key, false, "Net",
                    "net_p2p_session_addresses: resolve cached configured peer against the active XSession key (experimental)");
REXCVAR_DEFINE_STRING(net_p2p_address, "127.0.0.1", "Net", "net_p2p_lan: this client's local IPv4 address");
REXCVAR_DEFINE_BOOL(net_p2p_title_identity, false, "Net",
                    "net_p2p_lan: use session identity for TitleXnAddr (experimental)");
REXCVAR_DEFINE_UINT32(net_p2p_port, 3074, "Net", "net_p2p_lan: advertised game port (1..65535)");
REXCVAR_DEFINE_STRING(net_p2p_peer_address, "", "Net", "net_p2p_lan: explicitly configured test peer IPv4");
REXCVAR_DEFINE_UINT64(net_p2p_peer_xuid, 0, "Net", "net_p2p_lan: XUID of the explicitly configured test peer");
REXCVAR_DEFINE_BOOL(net_p2p_relay, false, "Net",
                    "net_p2p_session_addresses: peers through the online server's relay (net_dns_address, "
                    "net_p2p_relay_port; docs/online-relay.md), addressed by XUID: any NAT, no LAN IPs, no configured "
                    "peer. Game sockets bind to a free native port; peers see a 100.64.x.y address");
REXCVAR_DEFINE_UINT32(net_p2p_relay_port, 1002, "Net", "net_p2p_relay: UDP port of the relay");
REXCVAR_DEFINE_BOOL(net_client_hello, false, "Net",
                    "Before the game's first datagram to net_dns_address:net_client_hello_port on a socket, send the "
                    "port's client protocol from that socket (server X360MinClientProtocol refuses older builds)");
REXCVAR_DEFINE_UINT32(net_client_hello_port, 1000, "Net", "net_client_hello: the server's X360 login port");
REXCVAR_DEFINE_BOOL(net_wake_trace, false, "Net",
                    "Diagnostics: after a pause of 20 s or more between the game's socket calls (console sleep), log "
                    "every socket call for 90 s: thread, entry, exit, duration, last error");
REXCVAR_DEFINE_STRING(net_dns_fallback_address, "", "Net",
                      "net_dns_address given as a host name: the IPv4 address used when the name does not resolve");
REXCVAR_DEFINE_BOOL(net_access, false, "Net",
                    "net_client_hello: before the login, prove this console's own key to the server (Ed25519, "
                    "access/<XUID>.key in the user data folder, made on first use) and send the server's ticket "
                    "with the hello. The owner approves new keys (server X360AccessRequired; docs/online-access.md)");
REXCVAR_DEFINE_UINT32(net_access_timeout_ms, 400, "Net", "net_access: longest wait for each server reply")
    .range(50, 3000);

// ds2scholar-nx (2026-10-29, online): net_dns_address may be a host name (online.ds2scholar.download), so the server can
// move without new player configs. An IPv4 literal is parsed on every call, as before. A name is resolved once, after the
// game's WSAStartup has brought the sockets up, and kept for the session; if it does not resolve (or before
// WSAStartup), net_dns_fallback_address is used. Network byte order; INADDR_NONE when there is no usable address.
static std::atomic<bool> g_sockets_started{false};
static std::atomic<bool> g_server_resolved{false};
static std::atomic<uint32_t> g_server_address{INADDR_NONE};

uint32_t ServerAddress() {
  const std::string& name = REXCVAR_GET(net_dns_address);
  const uint32_t literal = inet_addr(name.c_str());
  if (literal != INADDR_NONE || name.empty()) return literal;
  if (g_server_resolved.load(std::memory_order_acquire)) return g_server_address.load(std::memory_order_relaxed);
  const uint32_t fallback = inet_addr(REXCVAR_GET(net_dns_fallback_address).c_str());
  if (!g_sockets_started.load(std::memory_order_acquire)) return fallback;
  static std::mutex resolve_mutex;
  std::lock_guard lock(resolve_mutex);
  if (g_server_resolved.load(std::memory_order_acquire)) return g_server_address.load(std::memory_order_relaxed);
  addrinfo hints{};
  hints.ai_family = AF_INET;
  hints.ai_socktype = SOCK_DGRAM;
  addrinfo* found = nullptr;
  const auto start = std::chrono::steady_clock::now();
  const int rc = getaddrinfo(name.c_str(), nullptr, &hints, &found);
  const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
  uint32_t address = fallback;
  if (rc == 0 && found && found->ai_addr && found->ai_family == AF_INET) {
    address = reinterpret_cast<const sockaddr_in*>(found->ai_addr)->sin_addr.s_addr;
    char text[INET_ADDRSTRLEN] = {};
    inet_ntop(AF_INET, &address, text, sizeof(text));
    REXLOG_INFO("[net] server name {} -> {} ({} ms)", name, text, ms);
  } else {
    REXLOG_WARN("[net] server name {} did not resolve (getaddrinfo {}, {} ms); fallback net_dns_fallback_address '{}'{}",
                name, rc, ms, REXCVAR_GET(net_dns_fallback_address),
                fallback == INADDR_NONE ? ": none, the online server is unreachable" : "");
  }
  if (found) freeaddrinfo(found);
  g_server_address.store(address, std::memory_order_relaxed);
  g_server_resolved.store(true, std::memory_order_release);
  return address;
}

// ds2scholar-nx (2026-10-29, net_access; docs/online-access.md): the console key. 32 random bytes (the Ed25519 seed)
// in <user data>/access/<XUID>.key, made on first use and never sent; the server knows only the public key.
struct AccessKey {
  std::array<uint8_t, 64> secret{};  // Monocypher's secret key: seed || public key
  relay::access::Key public_key{};
};

static void FillRandom(uint8_t* data, size_t size) {
#if REX_PLATFORM_SWITCH
  randomGet(data, size);
#else
  std::random_device device;  // MSVC/libc++ on Windows: the system's cryptographic generator
  for (size_t i = 0; i < size; i += 4) {
    const uint32_t value = device();
    std::memcpy(data + i, &value, std::min<size_t>(4, size - i));
  }
#endif
}

static std::optional<AccessKey> LoadAccessKey(uint64_t xuid) {
  const auto root = REX_KERNEL_STATE()->emulator()->user_data_root();
  if (root.empty()) return std::nullopt;
  const auto path = root / "access" / fmt::format("{:016X}.key", xuid);
  std::array<uint8_t, 32> seed{};
  bool loaded = false;
  {
    std::ifstream file(path, std::ios::binary);
    loaded = file.read(reinterpret_cast<char*>(seed.data()), seed.size()) && file.gcount() == 32;
  }
  if (!loaded) {
    FillRandom(seed.data(), seed.size());
    std::error_code error;
    std::filesystem::create_directories(path.parent_path(), error);
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    file.write(reinterpret_cast<const char*>(seed.data()), seed.size());
    if (!file.flush()) {
      REXLOG_ERROR("[access] cannot write the console key {}", path.string());
      return std::nullopt;
    }
    REXLOG_INFO("[access] new console key {} (the owner approves it on the server once)", path.string());
  }
  AccessKey key;
  crypto_ed25519_key_pair(key.secret.data(), key.public_key.data(), seed.data());  // wipes the seed
  return key;
}

// Hello -> challenge, proof -> result on a socket of its own; the server's ticket when the key is approved.
static std::optional<relay::access::Ticket> AccessTicket(uint16_t login_port) {
  namespace access = relay::access;
  auto* profile = REX_KERNEL_STATE()->user_profile();
  const uint64_t xuid = profile->xuid();
  const auto key = LoadAccessKey(xuid);
  if (!key) return std::nullopt;
  sockaddr_in server{};
  server.sin_family = AF_INET;
  server.sin_addr.s_addr = ServerAddress();
  server.sin_port = htons(login_port);
  if (server.sin_addr.s_addr == INADDR_NONE) return std::nullopt;
#if REX_PLATFORM_WIN32
  using Socket = SOCKET;
  const Socket invalid = INVALID_SOCKET;
  auto close_socket = [](Socket s) { closesocket(s); };
#else
  using Socket = int;
  const Socket invalid = -1;
  auto close_socket = [](Socket s) { close(s); };
#endif
  const Socket s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (s == invalid) return std::nullopt;
  const auto timeout = std::chrono::milliseconds(REXCVAR_GET(net_access_timeout_ms));
  // One request, the first reply from the server that `parse` accepts, or nothing by the deadline.
  auto exchange = [&](const std::vector<uint8_t>& request, auto parse) -> decltype(parse(std::span<const uint8_t>{})) {
    if (sendto(s, reinterpret_cast<const char*>(request.data()), int(request.size()), 0,
               reinterpret_cast<const sockaddr*>(&server), sizeof(server)) != int(request.size())) {
      return std::nullopt;
    }
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    std::array<uint8_t, 256> buffer{};
    for (;;) {
      const auto left = std::chrono::duration_cast<std::chrono::microseconds>(deadline - std::chrono::steady_clock::now());
      if (left.count() <= 0) return std::nullopt;
      fd_set read_set;
      FD_ZERO(&read_set);
      FD_SET(s, &read_set);
      timeval wait{long(left.count() / 1000000), long(left.count() % 1000000)};
      if (select(int(s) + 1, &read_set, nullptr, nullptr, &wait) <= 0) return std::nullopt;
      sockaddr_in from{};
#if REX_PLATFORM_WIN32
      int from_size = sizeof(from);
#else
      socklen_t from_size = sizeof(from);
#endif
      const int got = recvfrom(s, reinterpret_cast<char*>(buffer.data()), int(buffer.size()), 0,
                               reinterpret_cast<sockaddr*>(&from), &from_size);
      if (got <= 0) return std::nullopt;
      if (from.sin_addr.s_addr != server.sin_addr.s_addr || from.sin_port != server.sin_port) continue;
      if (auto parsed = parse(std::span<const uint8_t>(buffer.data(), size_t(got)))) return parsed;
    }
  };
  std::optional<access::Result> result;
  for (int attempt = 0; attempt < 2 && !result; ++attempt) {
    const auto nonce = exchange(access::Hello(xuid, key->public_key, profile->name()), access::ParseChallenge);
    if (!nonce) continue;
    const auto signed_bytes = access::Signed(*nonce, xuid, key->public_key);
    access::Signature signature;
    crypto_ed25519_sign(signature.data(), key->secret.data(), signed_bytes.data(), signed_bytes.size());
    result = exchange(access::Proof(xuid, key->public_key, signature), access::ParseResult);
  }
  close_socket(s);
  static const char* const kStatus[] = {"approved", "waiting for the owner's approval", "refused by the owner",
                                        "not accepted (signature or challenge)"};
  if (!result) {
    REXLOG_WARN("[access] no answer from the server ({} ms per reply, 2 attempts)", timeout.count());
    return std::nullopt;
  }
  REXLOG_INFO("[access] console key {:02x}{:02x}{:02x}{:02x}... of {:016X}: {}", key->public_key[0], key->public_key[1],
              key->public_key[2], key->public_key[3], xuid,
              result->status < 4 ? kStatus[result->status] : "unknown answer");
  if (result->status != access::kApproved) return std::nullopt;
  return result->ticket;
}

using LanPeer = lan::PeerRecord;
static std::mutex g_lan_mutex;
static std::map<uint32_t, LanPeer> g_lan_peers;
static lan::SessionAddresses g_lan_session_addresses;
static std::array<uint8_t, 8> g_lan_active_id{};
static PPCFunc* g_sotfs_original_log = nullptr;
static PPCFunc* g_sotfs_original_game_message = nullptr;
static PPCFunc* g_sotfs_original_sign_list_parser = nullptr;

static std::string SotfsStringBytes(uint8_t* base, uint32_t object) {
  const auto length = memory::load_and_swap<uint32_t>(base + object + 16);
  const auto capacity = memory::load_and_swap<uint32_t>(base + object + 20);
  const auto data = capacity < 16 ? object : memory::load_and_swap<uint32_t>(base + object);
  std::string hex;
  for (uint32_t i = 0; data && i < std::min(length, 32u); ++i) {
    hex += fmt::format("{:02X}", base[data + i]);
  }
  return fmt::format("len={} cap={} encoding={} bytes={}", length, capacity, base[object + 28], hex);
}

static void SotfsSignListParser(PPCContext& ctx, uint8_t* base) {
  const auto object = ctx.r3.u32;
  g_sotfs_original_sign_list_parser(ctx, base);
  if (!ctx.r3.u32) return;
  const auto count = memory::load_and_swap<uint32_t>(base + object + 48);
  const auto entries = memory::load_and_swap<uint32_t>(base + object + 44);
  static std::atomic<uint32_t> traced{0};
  for (uint32_t i = 0; entries && i < std::min(count, 16u); ++i) {
    if (traced.fetch_add(1, std::memory_order_relaxed) >= 64) break;
    const auto entry = memory::load_and_swap<uint32_t>(base + entries + i * 4);
    const auto name = memory::load_and_swap<uint32_t>(base + entry + 44);
    if (!name) continue;
    REXLOG_INFO("[p2p-name] SignData={:08X} field5={:08X} {}", entry, name, SotfsStringBytes(base, name));
  }
}

static void EnableSotfsNameTrace() {
  if (!REXCVAR_GET(net_p2p_name_trace)) return;
  static std::once_flag once;
  std::call_once(once, [] {
    auto* memory = REX_KERNEL_MEMORY();
    // SotFS GetSignListResponse vtable820FDAC4, parser slot+28=82EB72A8.
    const std::array<uint8_t, 16> signature{
        0x7D, 0x88, 0x02, 0xA6, 0x48, 0x13, 0x4C, 0x21,
        0x94, 0x21, 0xFF, 0x90, 0x7C, 0x7D, 0x1B, 0x78};
    if (std::memcmp(memory->TranslateVirtual(0x82EB72A8), signature.data(), signature.size()) ||
        memory::load_and_swap<uint32_t>(memory->TranslateVirtual(0x820FDAE0)) != 0x82EB72A8) {
      REXLOG_WARN("[p2p-name] SignData trace not installed: signature mismatch");
      return;
    }
    auto* dispatcher = REX_KERNEL_STATE()->function_dispatcher();
    g_sotfs_original_sign_list_parser = dispatcher->GetFunction(0x82EB72A8);
    if (g_sotfs_original_sign_list_parser && dispatcher->SetFunction(0x82EB72A8, SotfsSignListParser)) {
      REXLOG_INFO("[p2p-name] SignData parser trace installed");
    }
  });
}

static void ProbeSotfsSummonName(PPCContext& ctx, uint8_t* base, uint32_t peer, uint32_t identity) {
  if (!REXCVAR_GET(net_p2p_summon_name_probe) || !REXCVAR_GET(net_p2p_lan) || !identity) return;
  const auto read = [base](uint32_t a) { return memory::load_and_swap<uint32_t>(base + a); };
  // 8298F0E0 reads the platform identity's gamertag at+56; the adjoining
  // XUID at+48 was observed in both PC processes, and must match our explicit peer.
  const auto xuid = memory::load_and_swap<uint64_t>(base + identity + 48);
  if (!REXCVAR_GET(net_p2p_peer_xuid) || xuid != REXCVAR_GET(net_p2p_peer_xuid) ||
      read(identity) != 0x82064C24) return;
  const auto root = read(0x834ABB44);
  const auto summon = root ? read(root + 12) : 0;
  if (!summon) return;
  auto* copy_name = REX_KERNEL_STATE()->function_dispatcher()->GetFunction(0x8296B778);
  if (!copy_name) return;
  const auto fill = [&](uint32_t object) {
    // Vtable82014768: getter8247C810 returns object+60, receiver+92 is
    // 8247D7E8. Only the empty inline string is eligible; never replace a name.
    if (!object || read(object) != 0x82014768 || read(object + 76) || read(object + 80) != 7) return;
    PPCContext saved = ctx;
    saved.r3.u64 = object + 60;
    saved.r4.u64 = peer;
    copy_name(saved, base);
    REXLOG_INFO("[p2p-name-probe] peer={:016X} object={:08X} name length={} before message={}",
                xuid, object, read(object + 76), ctx.r4.u32);
  };
  fill(read(summon + 32));
  const auto first = read(summon + 40), last = read(summon + 44);
  if (first && last >= first && last - first <= 64 && (last - first) % 4 == 0) {
    for (auto at = first; at < last; at += 4) fill(read(at));
  }
}

// SotFS824878D8 is the virtual +4 receiver in vtable820148F4 (IDs4..18).
// 8243B510 dispatches it with r4=id, r5=payload, r6=length, r7=MemberRef.
// In particular ID4 ->82486A60 ->82483300 matches the peer's online ID
// against pending summon objects before calling their virtual +92 method.
static void SotfsGameMessage(PPCContext& ctx, uint8_t* base) {
  const auto id = ctx.r4.u32;
  const auto peer = ctx.r7.u32;
  const auto payload = ctx.r5.u32;
  const auto length = ctx.r6.u32;
  const auto member = peer ? memory::load_and_swap<uint32_t>(base + peer) : 0;
  const auto identity = member ? memory::load_and_swap<uint32_t>(base + member + 12) : 0;
  ProbeSotfsSummonName(ctx, base, peer, identity);
  static std::atomic<uint32_t> count{0};
  if (count.fetch_add(1, std::memory_order_relaxed) < 256) {
    REXLOG_INFO("[p2p-game-rx] id={} length={} payload={:08X} peer={:08X} member={:08X} identity={:08X}",
                id, length, payload, peer, member, identity);
    if (identity) {
      const auto vtable = memory::load_and_swap<uint32_t>(base + identity);
      REXLOG_INFO("[p2p-game-rx] identity vtable={:08X} text-method={:08X}", vtable,
                  memory::load_and_swap<uint32_t>(base + vtable + 12));
    }
  }
  g_sotfs_original_game_message(ctx, base);
}

static void EnableSotfsGameTrace() {
  if (!REXCVAR_GET(net_p2p_game_trace) && !REXCVAR_GET(net_p2p_summon_name_probe)) return;
  static std::once_flag once;
  std::call_once(once, [] {
    auto* memory = REX_KERNEL_MEMORY();
    // mflr r12; bl savegpr26; stwu r1,-480(r1); clrlwi r11,r4,24.
    const std::array<uint8_t, 16> prologue{
        0x7D, 0x88, 0x02, 0xA6, 0x48, 0xB6, 0x45, 0xE5,
        0x94, 0x21, 0xFE, 0x20, 0x54, 0x8B, 0x06, 0x3E};
    if (std::memcmp(memory->TranslateVirtual(0x824878D8), prologue.data(), prologue.size()) ||
        memory::load_and_swap<uint32_t>(memory->TranslateVirtual(0x820148F8)) != 0x824878D8) {
      REXLOG_WARN("[p2p-game-rx] trace not installed: SotFS signature mismatch");
      return;
    }
    auto* dispatcher = REX_KERNEL_STATE()->function_dispatcher();
    g_sotfs_original_game_message = dispatcher->GetFunction(0x824878D8);
    if (g_sotfs_original_game_message && dispatcher->SetFunction(0x824878D8, SotfsGameMessage)) {
      REXLOG_INFO("[p2p-game-rx] initial game-message trace installed");
    }
  });
}

static void SotfsNetworkLog(PPCContext& ctx, uint8_t* base) {
  const uint32_t address = ctx.r4.u32;
  if (!address || address > UINT32_MAX - 4096) return;
  std::u16string message;
  for (uint32_t offset = 0; offset < 4096; offset += 2) {
    const auto value = memory::load_and_swap<uint16_t>(base + address + offset);
    if (!value) break;
    message.push_back(char16_t(value));
  }
  REXLOG_INFO("[p2p-game] {:08X} {}", ctx.r3.u32, rex::string::to_utf8(message));
  if (message.find(u"reason=") != std::u16string::npos) {
    REXLOG_INFO("[p2p] Guest leave reason caller; stack:{}", HostStackNames());
  }
  if (g_sotfs_original_log) g_sotfs_original_log(ctx, base);
}

static void EnableSotfsNetworkLog() {
  EnableSotfsGameTrace();
  if (!REXCVAR_GET(net_p2p_guest_log)) return;
  static std::once_flag once;
  std::call_once(once, [] {
    auto* memory = REX_KERNEL_MEMORY();
    // SotFS82971660: optional callback8352E504, user8352E508; r3=severity,
    // r4=formatted UTF-16BE text. Verify its code before touching game state.
    const std::array<uint8_t, 16> signature{
        0x7D, 0x88, 0x02, 0xA6, 0x48, 0x67, 0xA8, 0x61,
        0x94, 0x21, 0xFF, 0x60, 0x3D, 0x60, 0x83, 0x53};
    if (std::memcmp(memory->TranslateVirtual(0x82971660), signature.data(), signature.size())) {
      REXLOG_WARN("[p2p] Guest logger not installed: signature mismatch");
      return;
    }
    const auto previous = memory::load_and_swap<uint32_t>(memory->TranslateVirtual(0x8352E504));
    auto* dispatcher = REX_KERNEL_STATE()->function_dispatcher();
    if (previous) {
      g_sotfs_original_log = dispatcher->GetFunction(previous);
      if (!g_sotfs_original_log) {
        REXLOG_WARN("[p2p] Guest logger not installed: unknown existing callback {:08X}", previous);
        return;
      }
    }
    const auto thunk = dispatcher->AllocateThunk(SotfsNetworkLog, 0);
    if (!thunk) return;
    memory::store_and_swap<uint32_t>(memory->TranslateVirtual(0x8352E504), thunk);
    REXLOG_INFO("[p2p] SotFS network logger callback {:08X} installed, preserving {:08X}", thunk, previous);
  });
}

static uint32_t LanIPValue(const lan::IP& ip) {
  return (uint32_t(ip[0]) << 24) | (uint32_t(ip[1]) << 16) | (uint32_t(ip[2]) << 8) | ip[3];
}

static bool SessionAddressesEnabled() {
  return REXCVAR_GET(net_p2p_lan) && REXCVAR_GET(net_p2p_session_addresses);
}

static bool RelayEnabled() { return SessionAddressesEnabled() && REXCVAR_GET(net_p2p_relay); }

// Only the guest sees reserved addresses. Never pass one to the OS.
static bool TranslateLanDestination(N_XSOCKADDR_IN& address) {
  if (!SessionAddressesEnabled() || !lan::SessionAddresses::IsHandle(address.sin_addr)) return true;
  std::lock_guard lock(g_lan_mutex);
  const auto ip = g_lan_session_addresses.Outgoing(address.sin_addr);
  if (!ip) return false;
  address.sin_addr = LanIPValue(*ip);
  return true;
}

static uint32_t IncomingLanAddress(uint32_t address, uint16_t port) {
  if (!SessionAddressesEnabled() || (port != 10010 && port != 6002 && port != 10004)) return address;
  const lan::IP ip{uint8_t(address >> 24), uint8_t(address >> 16), uint8_t(address >> 8), uint8_t(address)};
  std::lock_guard lock(g_lan_mutex);
  if (const auto handle = g_lan_session_addresses.Incoming(ip, g_lan_active_id)) return *handle;
  const uint32_t native_ip = inet_addr(REXCVAR_GET(net_p2p_peer_address).c_str());
  lan::IP configured{};
  std::memcpy(configured.data(), &native_ip, 4);
  const auto game_port = REXCVAR_GET(net_p2p_port);
  if (game_port > 65535) return address;
  const auto peer = lan::ConfiguredPeer(ip, configured, REXCVAR_GET(net_p2p_peer_xuid),
                                       g_lan_active_id, uint16_t(game_port));
  if (!peer) return address;
  const auto handle = g_lan_session_addresses.Register(*peer);
  if (!handle) return address;
  REXLOG_INFO("[p2p] Incoming {:08X} session -> {:08X}", address, handle);
  return handle;
}

static std::optional<lan::Address> LocalLanAddress() {
  const auto port = REXCVAR_GET(net_p2p_port);
  const uint64_t xuid = REX_KERNEL_STATE()->user_profile()->xuid();
  if (!port || port > 65535) return std::nullopt;
  if (RelayEnabled()) return lan::MakeAddress(relay::PseudoIP(xuid), uint16_t(port), xuid);
  const uint32_t native_ip = inet_addr(REXCVAR_GET(net_p2p_address).c_str());
  if (!native_ip || native_ip == INADDR_NONE) return std::nullopt;
  lan::IP ip{};
  std::memcpy(ip.data(), &native_ip, 4);
  return lan::MakeAddress(ip, uint16_t(port), xuid);
}

// --- net_wake_trace ------------------------------------------------------------------------------------------------
// ds2scholar-nx (2026-10-29, ds2_156): after ~14 min of console sleep the game hung on "Initialization online mode",
// drawing at 30 fps but sending nothing to the server (before the sleep: a 23-byte heartbeat to :1001 every 25 s).
// On the PC a 3-minute process suspend instead retransmits for 43 s and then gives up. This shows where the Switch's
// network thread goes after the wake: a call that enters and never leaves, an error, or no calls at all.
class WakeCall {
 public:
  WakeCall(const char* name, uint32_t socket_handle) : name_(name), socket_(socket_handle) {
    if (!REXCVAR_GET(net_wake_trace)) return;
    static std::atomic<int64_t> last_call_ms{0};
    static std::atomic<int64_t> trace_until_ms{0};
    static std::atomic<int> traced{0};  // calls logged in the current window (non-blocking polls are frequent)
    start_ = std::chrono::steady_clock::now();
    const int64_t now_ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(start_.time_since_epoch()).count();
    const int64_t last = last_call_ms.exchange(now_ms);
    if (last && now_ms - last >= 20000) {
      trace_until_ms = now_ms + 90000;
      traced = 0;
      REXLOG_INFO("[wake] socket calls resume after a pause of {} ms; tracing them for 90 s", now_ms - last);
    }
    active_ = now_ms < trace_until_ms && traced++ < 4000;
    if (active_) REXLOG_INFO("[wake] > {} socket {:08X} ({} ms since the previous socket call)", name_, socket_, now_ms - last);
  }
  ~WakeCall() {
    if (!active_) return;
    const auto ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start_).count();
    REXLOG_INFO("[wake] < {} socket {:08X} after {} ms, last error {}", name_, socket_, ms, XThread::GetLastError());
  }

 private:
  const char* name_;
  uint32_t socket_;
  bool active_ = false;
  std::chrono::steady_clock::time_point start_;
};

// --- P2P relay (net_p2p_relay; docs/online-relay.md) ------------------------------------------------------------
// Game sockets bound to a port register (own XUID, that game port) with the relay from their own native socket, at
// bind and every 10 s, so the relay learns their NAT mapping. sendto to a peer handle wraps the packet for the relay
// with the peer's XUID; recvfrom unwraps relayed packets and names the sender by an address handle for its XUID.
struct RelaySocket {
  uint64_t native = 0;
  uint16_t game_port = 0;
  std::chrono::steady_clock::time_point registered;  // last register sent
};
static std::mutex g_relay_mutex;
static std::map<uint32_t, RelaySocket> g_relay_sockets;  // guest socket handle
static std::set<uint32_t> g_hello_sockets;  // net_client_hello: guest sockets that sent it (under g_relay_mutex)
static std::map<uint32_t, uint64_t> g_relay_handle_xuid;  // address handle -> XUID (under g_lan_mutex)

static bool RelayEndpoint(uint32_t& ip, uint16_t& port) {
  const uint32_t native_ip = ServerAddress();
  const uint32_t relay_port = REXCVAR_GET(net_p2p_relay_port);
  if (!native_ip || native_ip == INADDR_NONE || !relay_port || relay_port > 65535) return false;
  ip = ntohl(native_ip);
  port = uint16_t(relay_port);
  return true;
}

static void RelaySendNative(uint64_t native, const std::vector<uint8_t>& packet) {
  uint32_t ip = 0;
  uint16_t port = 0;
  if (!RelayEndpoint(ip, port)) return;
  sockaddr_in to{};
  to.sin_family = AF_INET;
  to.sin_addr.s_addr = htonl(ip);
  to.sin_port = htons(port);
#if REX_PLATFORM_WIN32
  ::sendto(SOCKET(native), reinterpret_cast<const char*>(packet.data()), int(packet.size()), 0,
           reinterpret_cast<const sockaddr*>(&to), sizeof(to));
#else
  ::sendto(int(native), packet.data(), packet.size(), 0, reinterpret_cast<const sockaddr*>(&to), sizeof(to));
#endif
}

static void RelayAddSocket(uint32_t socket_handle, uint64_t native, uint16_t game_port) {
  {
    std::lock_guard lock(g_relay_mutex);
    g_relay_sockets[socket_handle] = {native, game_port, std::chrono::steady_clock::now()};
    RelaySendNative(native, relay::Register(REX_KERNEL_STATE()->user_profile()->xuid(), game_port));
  }
  REXLOG_INFO("[relay] socket {:08X} game port {} registers with {}:{}", socket_handle, game_port,
              REXCVAR_GET(net_dns_address), REXCVAR_GET(net_p2p_relay_port));
}

static std::optional<uint16_t> RelayGamePort(uint32_t socket_handle) {
  std::lock_guard lock(g_relay_mutex);
  const auto found = g_relay_sockets.find(socket_handle);
  if (found == g_relay_sockets.end()) return std::nullopt;
  return found->second.game_port;
}

// RelayGamePort for sendto/recvfrom, which also renews the registration every 10 s. No keepalive thread: on the
// Switch std::thread threw std::system_error at the first P2P bind (relay1, ds2_153/154); the game polls recvfrom on
// its non-blocking P2P sockets all the time (WSAEventSelect), so these calls come often enough.
static std::optional<uint16_t> RelayGamePortKeepalive(uint32_t socket_handle) {
  std::lock_guard lock(g_relay_mutex);
  const auto found = g_relay_sockets.find(socket_handle);
  if (found == g_relay_sockets.end()) return std::nullopt;
  auto& socket = found->second;
  const auto now = std::chrono::steady_clock::now();
  if (now - socket.registered >= std::chrono::seconds(10)) {
    socket.registered = now;
    RelaySendNative(socket.native, relay::Register(REX_KERNEL_STATE()->user_profile()->xuid(), socket.game_port));
  }
  return socket.game_port;
}

// The address handle the game sees for a relayed peer (created on its first packet, so any number of peers work).
static uint32_t RelayPeerHandle(uint64_t xuid) {
  std::lock_guard lock(g_lan_mutex);
  const lan::PeerRecord peer{lan::MakeAddress(relay::PseudoIP(xuid), uint16_t(REXCVAR_GET(net_p2p_port)), xuid),
                             g_lan_active_id};
  const uint32_t handle = g_lan_session_addresses.Register(peer);
  if (handle) g_relay_handle_xuid[handle] = xuid;
  return handle;
}

static uint64_t RelayHandleXuid(uint32_t handle) {
  std::lock_guard lock(g_lan_mutex);
  if (const auto peer = g_lan_session_addresses.Lookup(handle)) {
    if (const uint64_t xuid = relay::AddressXuid(peer->address)) return xuid;
  }
  const auto found = g_relay_handle_xuid.find(handle);
  return found != g_relay_handle_xuid.end() ? found->second : 0;
}

namespace lan {
uint32_t CreateSession(uint32_t flags, uint32_t info_ptr, uint32_t nonce_ptr) {
  EnableSotfsNetworkLog();
  if (!info_ptr || !nonce_ptr || info_ptr > UINT32_MAX - 60 || nonce_ptr > UINT32_MAX - 8 ||
      !REX_KERNEL_MEMORY()->LookupHeap(info_ptr) || !REX_KERNEL_MEMORY()->LookupHeap(info_ptr + 59) ||
      !REX_KERNEL_MEMORY()->LookupHeap(nonce_ptr) || !REX_KERNEL_MEMORY()->LookupHeap(nonce_ptr + 7)) {
    return 0x80070057;
  }
  auto* info = REX_KERNEL_MEMORY()->TranslateVirtual<uint8_t*>(info_ptr);
  Session wire{};
  if (flags & 1) {
    const auto address = LocalLanAddress();
    if (!address) return 0x80070057;
    std::random_device random;
    std::uniform_int_distribution<uint64_t> distribution;
    const uint64_t id = (distribution(random) & 0x00FFFFFFFFFFFFFFull) | 0xAE00000000000000ull;
    Key key{};
    for (auto& byte : key) byte = uint8_t(random());
    wire = MakeSession(*address, id, key);
    std::memcpy(info, wire.data(), wire.size());
    memory::store_and_swap<uint64_t>(REX_KERNEL_MEMORY()->TranslateVirtual(nonce_ptr), distribution(random));
  } else {
    std::memcpy(wire.data(), info, wire.size());
    if (!ValidSession(wire)) return 0x80070057;
  }
  Address address{};
  std::copy_n(wire.begin() + 8, 36, address.begin());
  const auto ip = PeerIP(address);
  if (!ip) return 0x80070057;
  LanPeer peer{address, {}};
  std::copy_n(wire.begin(), 8, peer.id.begin());
  {
    std::lock_guard lock(g_lan_mutex);
    g_lan_peers[LanIPValue(*ip)] = peer;
    g_lan_active_id = peer.id;
    if (SessionAddressesEnabled()) g_lan_session_addresses.Register(peer);
  }
  REXLOG_INFO("[p2p] {}Session flags={:08X} info@{:08X} host={}.{}.{}.{}:{} id={:016X}",
              (flags & 1) ? "CreateHost" : "Join", flags, info_ptr,
              (*ip)[0], (*ip)[1], (*ip)[2], (*ip)[3], (uint16_t(address[8]) << 8) | address[9],
              memory::load_and_swap<uint64_t>(wire.data()));
  return 0;
}
void EndSession() {
  std::lock_guard lock(g_lan_mutex);
  g_lan_active_id = {};
  g_lan_peers.clear();
  g_lan_session_addresses.Clear();
}
}  // namespace lan

// ds2scholar-nx (2026-10-25, online recon): which recompiled functions created a socket. The guest LR is not kept by
// the optimised codegen, so on the PC the host stack is symbolized (dbghelp: the generated sub_XXXXXXXX are real
// functions with their PDB names). PC and net_online_probe only.
#if REX_PLATFORM_WIN32
#include <dbghelp.h>
#include <mutex>
#pragma comment(lib, "dbghelp.lib")
std::string HostStackNames() {
  static std::mutex lock;
  std::lock_guard guard(lock);
  static const bool ready = SymInitialize(GetCurrentProcess(), nullptr, TRUE) != FALSE;
  if (!ready) return "(no symbols)";
  void* frames[48];
  const USHORT count = CaptureStackBackTrace(1, 48, frames, nullptr);
  alignas(SYMBOL_INFO) char buffer[sizeof(SYMBOL_INFO) + 256];
  auto* symbol = reinterpret_cast<SYMBOL_INFO*>(buffer);
  std::string out;
  for (USHORT i = 0; i < count; ++i) {
    symbol->SizeOfStruct = sizeof(SYMBOL_INFO);
    symbol->MaxNameLen = 255;
    DWORD64 displacement = 0;
    if (!SymFromAddr(GetCurrentProcess(), DWORD64(frames[i]), &displacement, symbol)) continue;
    const std::string_view name(symbol->Name);
    if (name.find("sub_") == std::string_view::npos) continue;  // only the guest's functions
    out += ' ';
    out += name;
  }
  return out.empty() ? std::string(" (no guest frames)") : out;
}
#else
std::string HostStackNames() { return {}; }
#endif

typedef struct {
  uint8_t flags;
  uint8_t reserved;
  rex::be<uint16_t> probes_xmit;
  rex::be<uint16_t> probes_recv;
  rex::be<uint16_t> data_len;
  rex::be<uint32_t> data_ptr;
  rex::be<uint16_t> rtt_min_in_msecs;
  rex::be<uint16_t> rtt_med_in_msecs;
  rex::be<uint32_t> up_bits_per_sec;
  rex::be<uint32_t> down_bits_per_sec;
} XNQOSINFO;

typedef struct {
  rex::be<uint32_t> count;
  rex::be<uint32_t> count_pending;
  XNQOSINFO info[1];
} XNQOS;

struct Xsockaddr_t {
  rex::be<uint16_t> sa_family;
  char sa_data[14];
};

struct X_WSADATA {
  rex::be<uint16_t> version;
  rex::be<uint16_t> version_high;
  char description[256 + 1];
  char system_status[128 + 1];
  rex::be<uint16_t> max_sockets;
  rex::be<uint16_t> max_udpdg;
  rex::be<uint32_t> vendor_info_ptr;
};

struct XWSABUF {
  rex::be<uint32_t> len;
  rex::be<uint32_t> buf_ptr;
};

struct XWSAOVERLAPPED {
  rex::be<uint32_t> internal;
  rex::be<uint32_t> internal_high;
  union {
    struct {
      rex::be<uint32_t> low;
      rex::be<uint32_t> high;
    } offset;  // must be named to avoid GCC error
    rex::be<uint32_t> pointer;
  };
  rex::be<uint32_t> event_handle;
};

void LoadSockaddr(const uint8_t* ptr, sockaddr* out_addr) {
  out_addr->sa_family = memory::load_and_swap<uint16_t>(ptr + 0);
  switch (out_addr->sa_family) {
    case AF_INET: {
      auto in_addr = reinterpret_cast<sockaddr_in*>(out_addr);
      in_addr->sin_port = memory::load_and_swap<uint16_t>(ptr + 2);
      // Maybe? Depends on type.
      in_addr->sin_addr.s_addr = *(uint32_t*)(ptr + 4);
      break;
    }
    default:
      assert_unhandled_case(out_addr->sa_family);
      break;
  }
}

void StoreSockaddr(const sockaddr& addr, uint8_t* ptr) {
  switch (addr.sa_family) {
    case AF_UNSPEC:
      std::memset(ptr, 0, sizeof(addr));
      break;
    case AF_INET: {
      auto& in_addr = reinterpret_cast<const sockaddr_in&>(addr);
      memory::store_and_swap<uint16_t>(ptr + 0, in_addr.sin_family);
      memory::store_and_swap<uint16_t>(ptr + 2, in_addr.sin_port);
      // Maybe? Depends on type.
      memory::store_and_swap<uint32_t>(ptr + 4, in_addr.sin_addr.s_addr);
      break;
    }
    default:
      assert_unhandled_case(addr.sa_family);
      break;
  }
}

// https://github.com/joolswills/mameox/blob/master/MAMEoX/Sources/xbox_Network.cpp#L136
struct XNetStartupParams {
  uint8_t cfgSizeOfStruct;
  uint8_t cfgFlags;
  uint8_t cfgSockMaxDgramSockets;
  uint8_t cfgSockMaxStreamSockets;
  uint8_t cfgSockDefaultRecvBufsizeInK;
  uint8_t cfgSockDefaultSendBufsizeInK;
  uint8_t cfgKeyRegMax;
  uint8_t cfgSecRegMax;
  uint8_t cfgQosDataLimitDiv4;
  uint8_t cfgQosProbeTimeoutInSeconds;
  uint8_t cfgQosProbeRetries;
  uint8_t cfgQosSrvMaxSimultaneousResponses;
  uint8_t cfgQosPairWaitTimeInSeconds;
};

XNetStartupParams xnet_startup_params = {};

u32 NetDll_XNetStartup_entry(u32 caller, ppc_ptr_t<XNetStartupParams> params) {
  if (params) {
    assert_true(params->cfgSizeOfStruct == sizeof(XNetStartupParams));
    std::memcpy(&xnet_startup_params, params, sizeof(XNetStartupParams));
  }

  auto xam = REX_KERNEL_STATE()->GetKernelModule<XamModule>("xam.xex");

  /*
  if (!xam->xnet()) {
    auto xnet = new XNet(REX_KERNEL_STATE());
    xnet->Initialize();

    xam->set_xnet(xnet);
  }
  */

  return 0;
}

u32 NetDll_XNetCleanup_entry(u32 caller, mapped_void params) {
  auto xam = REX_KERNEL_STATE()->GetKernelModule<XamModule>("xam.xex");
  // auto xnet = xam->xnet();
  // xam->set_xnet(nullptr);

  // TODO: Shut down and delete.
  // delete xnet;

  return 0;
}

u32 NetDll_XNetGetOpt_entry(u32 one, u32 option_id, mapped_void buffer_ptr,
                            mapped_u32 buffer_size) {
  assert_true(one == 1);
  switch (option_id) {
    case 1:
      if (*buffer_size < sizeof(XNetStartupParams)) {
        *buffer_size = sizeof(XNetStartupParams);
        return 0x2738;  // WSAEMSGSIZE
      }
      std::memcpy(buffer_ptr, &xnet_startup_params, sizeof(XNetStartupParams));
      return 0;
    default:
      REXKRNL_ERROR("NetDll_XNetGetOpt: option {} unimplemented", option_id);
      return 0x2726;  // WSAEINVAL
  }
}

u32 NetDll_XNetRandom_entry(u32 caller, mapped_void buffer_ptr, u32 length) {
  // For now, constant values.
  // This makes replicating things easier.
  std::memset(buffer_ptr, 0xBB, length);

  return 0;
}

u32 NetDll_WSAStartup_entry(u32 caller, u16 version, ppc_ptr_t<X_WSADATA> data_ptr) {
  EnableSotfsNameTrace();
// TODO(benvanik): abstraction layer needed.
#if REX_PLATFORM_WIN32
  WSADATA wsaData;
  ZeroMemory(&wsaData, sizeof(WSADATA));
  int ret = WSAStartup(version, &wsaData);

  auto data_out = REX_KERNEL_MEMORY()->TranslateVirtual(data_ptr.guest_address());

  if (data_ptr) {
    data_ptr->version = wsaData.wVersion;
    data_ptr->version_high = wsaData.wHighVersion;
    std::memcpy(&data_ptr->description, wsaData.szDescription, 0x100);
    std::memcpy(&data_ptr->system_status, wsaData.szSystemStatus, 0x80);
    data_ptr->max_sockets = wsaData.iMaxSockets;
    data_ptr->max_udpdg = wsaData.iMaxUdpDg;

    // Some games (5841099F) want this value round-tripped - they'll compare if
    // it changes and bugcheck if it does.
    uint32_t vendor_ptr = memory::load_and_swap<uint32_t>(data_out + 0x190);
    memory::store_and_swap<uint32_t>(data_out + 0x190, vendor_ptr);
  }
#else
  int ret = 0;
#if REX_PLATFORM_SWITCH
  // ds2scholar-nx (2026-10-25, online): libnx's BSD sockets need socketInitialize before the first socket(); only the
  // nxlink log did it so far. Once, with net_online_probe (a failure means it is already up).
  static const bool sockets_up = [] {
    if (!REXCVAR_GET(net_online_probe)) return false;
    const uint32_t rc = socketInitialize(nullptr);  // socketInitializeDefault
    REXLOG_INFO("[net] Switch sockets: socketInitializeDefault -> {:08X}", rc);
    return true;
  }();
  (void)sockets_up;
#endif
  if (data_ptr) {
    // Guess these values!
    data_ptr->version = version;
    data_ptr->description[0] = '\0';
    data_ptr->system_status[0] = '\0';
    data_ptr->max_sockets = 100;
    data_ptr->max_udpdg = 1024;
  }
#endif

  // ds2scholar-nx (online): sockets are up (on the Switch only with net_online_probe); a host name in net_dns_address
  // resolves now, once, rather than in the middle of a session.
#if REX_PLATFORM_WIN32
  const bool sockets_ready = ret == 0;
#elif REX_PLATFORM_SWITCH
  const bool sockets_ready = sockets_up;
#else
  const bool sockets_ready = true;
#endif
  if (sockets_ready && !g_sockets_started.exchange(true) && REXCVAR_GET(net_online_probe)) ServerAddress();

  // DEBUG
  /*
  auto xam = REX_KERNEL_STATE()->GetKernelModule<XamModule>("xam.xex");
  if (!xam->xnet()) {
    auto xnet = new XNet(REX_KERNEL_STATE());
    xnet->Initialize();

    xam->set_xnet(xnet);
  }
  */

  return ret;
}

u32 NetDll_WSACleanup_entry(u32 caller) {
  // This does nothing. Xenia needs WSA running.
  return 0;
}

u32 NetDll_WSAGetLastError_entry() {
  return XThread::GetLastError();
}

u32 NetDll_WSARecvFrom_entry(u32 caller, u32 socket, ppc_ptr_t<XWSABUF> buffers_ptr,
                             u32 buffer_count, mapped_u32 num_bytes_recv, mapped_u32 flags_ptr,
                             ppc_ptr_t<XSOCKADDR_IN> from_addr,
                             ppc_ptr_t<XWSAOVERLAPPED> overlapped_ptr,
                             mapped_void completion_routine_ptr) {
  WakeCall wake_call("WSARecvFrom", socket);
  if (overlapped_ptr) {
    // auto evt = REX_KERNEL_OBJECTS()->LookupObject<XEvent>(
    //    overlapped_ptr->event_handle);

    // if (evt) {
    //  //evt->Set(0, false);
    //}
  }

  // we're not going to be receiving packets any time soon
  // return error so we don't wait on that - Cancerous
  return -1;
}

// If the socket is a VDP socket, buffer 0 is the game data length, and buffer 1
// is the unencrypted game data.
u32 NetDll_WSASendTo_entry(u32 caller, u32 socket_handle, ppc_ptr_t<XWSABUF> buffers,
                           u32 num_buffers, mapped_u32 num_bytes_sent, u32 flags,
                           ppc_ptr_t<XSOCKADDR_IN> to_ptr, u32 to_len,
                           ppc_ptr_t<XWSAOVERLAPPED> overlapped, mapped_void completion_routine) {
  WakeCall wake_call("WSASendTo", socket_handle);
  assert(!overlapped);
  assert(!completion_routine);

  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  // Our sockets implementation doesn't support multiple buffers, so we need
  // to combine the buffers the game has given us!
  std::vector<uint8_t> combined_buffer_mem;
  uint32_t combined_buffer_size = 0;
  uint32_t combined_buffer_offset = 0;
  for (uint32_t i = 0; i < num_buffers; i++) {
    combined_buffer_size += buffers[i].len;
    combined_buffer_mem.resize(combined_buffer_size);
    uint8_t* combined_buffer = combined_buffer_mem.data();

    std::memcpy(combined_buffer + combined_buffer_offset,
                REX_KERNEL_MEMORY()->TranslateVirtual(buffers[i].buf_ptr), buffers[i].len);
    combined_buffer_offset += buffers[i].len;
  }

  N_XSOCKADDR_IN native_to(to_ptr);
  if (!TranslateLanDestination(native_to)) {
    XThread::SetLastError(10049);
    return ~0u;
  }
  socket->SendTo(combined_buffer_mem.data(), combined_buffer_size, flags, &native_to, to_len);

  // TODO: Instantly complete overlapped

  return 0;
}

u32 NetDll_WSAWaitForMultipleEvents_entry(u32 num_events, mapped_u32 events, u32 wait_all,
                                          u32 timeout, u32 alertable) {
  WakeCall wake_call("WSAWaitForMultipleEvents", 0);
  if (num_events > 64) {
    XThread::SetLastError(87);  // ERROR_INVALID_PARAMETER
    return ~0u;
  }

  uint64_t timeout_wait = (uint64_t)timeout;

  X_STATUS result = 0;
  do {
    result = xboxkrnl::xeNtWaitForMultipleObjectsEx(num_events, events, wait_all, 1, alertable,
                                                    timeout != -1 ? &timeout_wait : nullptr);
  } while (result == X_STATUS_ALERTED);

  if (XFAILED(result)) {
    uint32_t error = xboxkrnl::xeRtlNtStatusToDosError(result);
    XThread::SetLastError(error);
    return ~0u;
  }
  return 0;
}

u32 NetDll_WSACreateEvent_entry() {
  XEvent* ev = new XEvent(REX_KERNEL_STATE());
  ev->Initialize(true, false);
  return ev->handle();
}

u32 NetDll_WSACloseEvent_entry(u32 event_handle) {
  X_STATUS result = REX_KERNEL_OBJECTS()->ReleaseHandle(event_handle);
  if (XFAILED(result)) {
    uint32_t error = xboxkrnl::xeRtlNtStatusToDosError(result);
    XThread::SetLastError(error);
    return 0;
  }
  return 1;
}

u32 NetDll_WSAResetEvent_entry(u32 event_handle) {
  X_STATUS result = xboxkrnl::xeNtClearEvent(event_handle);
  if (XFAILED(result)) {
    uint32_t error = xboxkrnl::xeRtlNtStatusToDosError(result);
    XThread::SetLastError(error);
    return 0;
  }
  return 1;
}

u32 NetDll_WSASetEvent_entry(u32 event_handle) {
  X_STATUS result = xboxkrnl::xeNtSetEvent(event_handle, nullptr);
  if (XFAILED(result)) {
    uint32_t error = xboxkrnl::xeRtlNtStatusToDosError(result);
    XThread::SetLastError(error);
    return 0;
  }
  return 1;
}

struct XnAddrStatus {
  // Address acquisition is not yet complete
  static const uint32_t XNET_GET_XNADDR_PENDING = 0x00000000;
  // XNet is uninitialized or no debugger found
  static const uint32_t XNET_GET_XNADDR_NONE = 0x00000001;
  // Host has ethernet address (no IP address)
  static const uint32_t XNET_GET_XNADDR_ETHERNET = 0x00000002;
  // Host has statically assigned IP address
  static const uint32_t XNET_GET_XNADDR_STATIC = 0x00000004;
  // Host has DHCP assigned IP address
  static const uint32_t XNET_GET_XNADDR_DHCP = 0x00000008;
  // Host has PPPoE assigned IP address
  static const uint32_t XNET_GET_XNADDR_PPPOE = 0x00000010;
  // Host has one or more gateways configured
  static const uint32_t XNET_GET_XNADDR_GATEWAY = 0x00000020;
  // Host has one or more DNS servers configured
  static const uint32_t XNET_GET_XNADDR_DNS = 0x00000040;
  // Host is currently connected to online service
  static const uint32_t XNET_GET_XNADDR_ONLINE = 0x00000080;
  // Network configuration requires troubleshooting
  static const uint32_t XNET_GET_XNADDR_TROUBLESHOOT = 0x00008000;
};

u32 NetDll_XNetGetTitleXnAddr_entry(u32 caller, ppc_ptr_t<XNADDR> addr_ptr) {
  if (REXCVAR_GET(net_p2p_lan) && REXCVAR_GET(net_p2p_title_identity) && addr_ptr) {
    if (const auto address = LocalLanAddress()) {
      // Direct LAN identity only. A synthetic SGADDR is not a Live online token.
      std::memcpy(addr_ptr.host_address(), address->data(), 16);
      std::memset(addr_ptr->abOnline, 0, 20);
      return XnAddrStatus::XNET_GET_XNADDR_ETHERNET | XnAddrStatus::XNET_GET_XNADDR_STATIC |
             XnAddrStatus::XNET_GET_XNADDR_GATEWAY | XnAddrStatus::XNET_GET_XNADDR_DNS |
             XnAddrStatus::XNET_GET_XNADDR_ONLINE;
    }
  }
  // Just return a loopback address atm.
  addr_ptr->ina.s_addr = htonl(INADDR_LOOPBACK);
  addr_ptr->inaOnline.s_addr = 0;
  addr_ptr->wPortOnline = 0;

  // TODO(gibbed): A proper mac address.
  // RakNet's 360 version appears to depend on abEnet to create "random" 64-bit
  // numbers. A zero value will cause RakPeer::Startup to fail. This causes
  // 58411436 to crash on startup.
  // The 360-specific code is scrubbed from the RakNet repo, but there's still
  // traces of what it's doing which match the game code.
  // https://github.com/facebookarchive/RakNet/blob/master/Source/RakPeer.cpp#L382
  // https://github.com/facebookarchive/RakNet/blob/master/Source/RakPeer.cpp#L4527
  // https://github.com/facebookarchive/RakNet/blob/master/Source/RakPeer.cpp#L4467
  // "Mac address is a poor solution because you can't have multiple connections
  // from the same system"
  std::memset(addr_ptr->abEnet, 0xCC, 6);

  std::memset(addr_ptr->abOnline, 0, 20);

  if (REXCVAR_GET(net_online_probe)) {
    // A Live-reachable address: online flag and a non-zero online address (the cable is there too).
    addr_ptr->inaOnline.s_addr = ServerAddress();
    addr_ptr->wPortOnline = 1000;
    static int logged = 0;
    if (logged++ < 4) REXLOG_INFO("[net] XNetGetTitleXnAddr -> online (0xE6)");
    return XnAddrStatus::XNET_GET_XNADDR_ETHERNET | XnAddrStatus::XNET_GET_XNADDR_STATIC |
           XnAddrStatus::XNET_GET_XNADDR_GATEWAY | XnAddrStatus::XNET_GET_XNADDR_DNS |
           XnAddrStatus::XNET_GET_XNADDR_ONLINE;
  }
  return XnAddrStatus::XNET_GET_XNADDR_STATIC;
}

u32 NetDll_XNetGetDebugXnAddr_entry(u32 caller, ppc_ptr_t<XNADDR> addr_ptr) {
  addr_ptr.Zero();

  // XNET_GET_XNADDR_NONE causes caller to gracefully return.
  return XnAddrStatus::XNET_GET_XNADDR_NONE;
}

u32 NetDll_XNetXnAddrToMachineId_entry(u32 caller, ppc_ptr_t<XNADDR> addr_ptr, mapped_u32 id_ptr) {
  // Tell the caller we're not signed in to live (non-zero ret)
  return 1;
}

void NetDll_XNetInAddrToString_entry(u32 caller, u32 in_addr, mapped_string string_out,
                                     u32 string_size) {
  // ds2-nx (2026-10-20): the dotted address itself (the guest passes the IN_ADDR by value, network order as a
  // big-endian value). It was always "666.666.666.666".
  const std::string text = fmt::format("{}.{}.{}.{}", in_addr >> 24, (in_addr >> 16) & 0xFF, (in_addr >> 8) & 0xFF,
                                       in_addr & 0xFF);
  if (REXCVAR_GET(net_online_probe)) REXLOG_INFO("[net] XNetInAddrToString {:08X} -> '{}'", in_addr, text);
  rex::string::copy_truncating(string_out, text, string_size);
}

// This converts a XNet address to an IN_ADDR. The IN_ADDR is used for
// subsequent socket calls (like a handle to a XNet address)
u32 NetDll_XNetXnAddrToInAddr_entry(u32 caller, ppc_ptr_t<XNADDR> xn_addr, mapped_void xid,
                                    mapped_void in_addr) {
  if (REXCVAR_GET(net_p2p_diagnostics)) {
    std::string address_bytes, key_bytes;
    if (xn_addr) {
      const auto* bytes = reinterpret_cast<const uint8_t*>(xn_addr.host_address());
      for (size_t i = 0; i < sizeof(XNADDR); ++i) address_bytes += fmt::format("{:02X}", bytes[i]);
    }
    if (xid) {
      const auto* bytes = static_cast<const uint8_t*>(xid.host_address());
      for (size_t i = 0; i < 8; ++i) key_bytes += fmt::format("{:02X}", bytes[i]);
    }
    REXLOG_INFO("[p2p] XnAddrToInAddr caller={} xnaddr@{:08X}={} xnkid@{:08X}={} out@{:08X}; stack:{}",
                caller, xn_addr.guest_address(), address_bytes, xid.guest_address(), key_bytes,
                in_addr.guest_address(), HostStackNames());
  }
  if (REXCVAR_GET(net_p2p_lan)) {
    if (!xn_addr || !xid || !in_addr) return 10022;
    LanPeer peer{};
    std::memcpy(peer.address.data(), xn_addr.host_address(), peer.address.size());
    std::memcpy(peer.id.data(), xid.host_address(), peer.id.size());
    const auto ip = lan::PeerIP(peer.address);
    if (!ip) return 10022;
    {
      std::lock_guard lock(g_lan_mutex);
      if (SessionAddressesEnabled()) {
        if (REXCVAR_GET(net_p2p_active_session_key)) {
          const uint32_t native_ip = inet_addr(REXCVAR_GET(net_p2p_peer_address).c_str());
          lan::IP configured{};
          std::memcpy(configured.data(), &native_ip, 4);
          const auto previous = peer.id;
          if (REXCVAR_GET(net_p2p_peer_xuid) && lan::UseActiveSessionKey(peer, configured, g_lan_active_id)) {
            REXLOG_INFO("[p2p] Cached peer XNKID {:016X} -> active {:016X}",
                        memory::load_and_swap<uint64_t>(previous.data()),
                        memory::load_and_swap<uint64_t>(peer.id.data()));
          }
        }
        const auto handle = g_lan_session_addresses.Register(peer);
        if (!handle) return 10022;
        // The guest resolves its host twice: from the session search (XNADDR with the XUID in abOnline) and when the
        // member joins (same address, abOnline zeroed). The second call replaces the record, so the relay keeps the
        // XUID by handle. Without it the guest's first packet failed with 10049 whenever the host's packet had not
        // arrived first: Switch host, PC guest over a VPN (2026-10-29, ds2_187).
        if (const uint64_t xuid = relay::AddressXuid(peer.address)) g_relay_handle_xuid[handle] = xuid;
        memory::store_and_swap<uint32_t>(in_addr.host_address(), handle);
        REXLOG_INFO("[p2p] Resolve session -> {:08X} ({}.{}.{}.{})", handle,
                    (*ip)[0], (*ip)[1], (*ip)[2], (*ip)[3]);
        return 0;
      }
      g_lan_peers[LanIPValue(*ip)] = peer;
    }
    std::memcpy(in_addr.host_address(), ip->data(), ip->size());
    REXLOG_INFO("[p2p] Resolve -> {}.{}.{}.{}", (*ip)[0], (*ip)[1], (*ip)[2], (*ip)[3]);
    return 0;
  }
  if (REXCVAR_GET(net_online_probe)) REXLOG_INFO("[net] XNetXnAddrToInAddr -> 1 (stub)");
  return 1;
}

// Does the reverse of the above.
// FIXME: Arguments may not be correct.
u32 NetDll_XNetInAddrToXnAddr_entry(u32 caller, u32 in_addr, ppc_ptr_t<XNADDR> xn_addr,
                                    mapped_void xid) {
  if (REXCVAR_GET(net_p2p_lan)) {
    if (!xn_addr || !xid) return 10022;
    std::lock_guard lock(g_lan_mutex);
    if (SessionAddressesEnabled() && lan::SessionAddresses::IsHandle(in_addr)) {
      const auto peer = g_lan_session_addresses.Lookup(in_addr);
      if (!peer) return 10022;
      std::memcpy(xn_addr.host_address(), peer->address.data(), peer->address.size());
      std::memcpy(xid.host_address(), peer->id.data(), peer->id.size());
      REXLOG_INFO("[p2p] Reverse session {:08X} -> XNADDR", in_addr);
      return 0;
    }
    auto found = g_lan_peers.find(in_addr);
    if (found == g_lan_peers.end()) {
      const uint32_t native_ip = inet_addr(REXCVAR_GET(net_p2p_peer_address).c_str());
      const auto port = REXCVAR_GET(net_p2p_port);
      if (native_ip && native_ip != INADDR_NONE && port && port <= 65535) {
        lan::IP configured{};
        std::memcpy(configured.data(), &native_ip, 4);
        const lan::IP requested{uint8_t(in_addr >> 24), uint8_t(in_addr >> 16),
                                uint8_t(in_addr >> 8), uint8_t(in_addr)};
        const auto peer = lan::ConfiguredPeer(requested, configured, REXCVAR_GET(net_p2p_peer_xuid),
                                               g_lan_active_id, uint16_t(port));
        if (peer) {
          g_lan_peers[in_addr] = *peer;
          found = g_lan_peers.find(in_addr);
          REXLOG_INFO("[p2p] Reverse {:08X} registered configured peer XUID={:016X}",
                      in_addr, REXCVAR_GET(net_p2p_peer_xuid));
        }
      }
    }
    if (found == g_lan_peers.end()) {
      REXLOG_INFO("[p2p] Reverse {:08X} missing; stack:{}", in_addr, HostStackNames());
      return 10022;
    }
    std::memcpy(xn_addr.host_address(), found->second.address.data(), 36);
    std::memcpy(xid.host_address(), found->second.id.data(), 8);
    REXLOG_INFO("[p2p] Reverse {:08X} -> XNADDR", in_addr);
    return 0;
  }
  if (REXCVAR_GET(net_online_probe)) REXLOG_INFO("[net] XNetInAddrToXnAddr -> 1 (stub)");
  return 1;
}

u32 NetDll_XNetUnregisterInAddr_entry(u32 caller, u32 in_addr) {
  if (!SessionAddressesEnabled()) return 1;  // Preserve the former stub result.
  std::lock_guard lock(g_lan_mutex);
  g_lan_session_addresses.Unregister(in_addr);
  REXLOG_INFO("[p2p] Unregister session address {:08X}", in_addr);
  return 0;
}

// https://www.google.com/patents/WO2008112448A1?cl=en
// Reserves a port for use by system link
u32 NetDll_XNetSetSystemLinkPort_entry(u32 caller, u32 port) {
  return 1;
}

// https://github.com/ILOVEPIE/Cxbx-Reloaded/blob/master/src/CxbxKrnl/EmuXOnline.h#L39
struct XEthernetStatus {
  static const uint32_t XNET_ETHERNET_LINK_ACTIVE = 0x01;
  static const uint32_t XNET_ETHERNET_LINK_100MBPS = 0x02;
  static const uint32_t XNET_ETHERNET_LINK_10MBPS = 0x04;
  static const uint32_t XNET_ETHERNET_LINK_FULL_DUPLEX = 0x08;
  static const uint32_t XNET_ETHERNET_LINK_HALF_DUPLEX = 0x10;
};

u32 NetDll_XNetGetEthernetLinkStatus_entry(u32 caller) {
  WakeCall wake_call("XNetGetEthernetLinkStatus", 0);
  // XNET_ETHERNET_LINK_ACTIVE | XNET_ETHERNET_LINK_100MBPS | XNET_ETHERNET_LINK_FULL_DUPLEX
  static int logged = 0;
  if (REXCVAR_GET(net_online_probe) && logged++ < 4) REXLOG_INFO("[net] XNetGetEthernetLinkStatus -> 0x0B");
  return REXCVAR_GET(net_online_probe) ? 0x0B : 0;
}

u32 NetDll_XNetDnsLookup_entry(u32 caller, mapped_string host, u32 event_handle, mapped_u32 pdns) {
  // TODO(gibbed): actually implement this
  const bool probe = REXCVAR_GET(net_online_probe);
  REXLOG_INFO("[net] XNetDnsLookup '{}'{}", host ? std::string(host.host_address()) : std::string(),
              probe ? fmt::format(" -> {}", REXCVAR_GET(net_dns_address)) : std::string(" (no network)"));
  if (pdns) {
    auto dns_guest = REX_KERNEL_MEMORY()->SystemHeapAlloc(sizeof(XNDNS));
    auto dns = REX_KERNEL_MEMORY()->TranslateVirtual<XNDNS*>(dns_guest);
    std::memset(dns, 0, sizeof(XNDNS));
    dns->status = 1;  // non-zero = error
    if (probe) {
      dns->status = 0;
      dns->cina = 1;
      dns->aina[0].s_addr = ServerAddress();  // network order, as the guest's
    }
    *pdns = dns_guest;
  }
  if (event_handle) {
    auto ev = REX_KERNEL_OBJECTS()->LookupObject<XEvent>(event_handle);
    assert_not_null(ev);
    ev->Set(0, false);
  }
  return 0;
}

u32 NetDll_XNetDnsRelease_entry(u32 caller, ppc_ptr_t<XNDNS> dns) {
  if (!dns) {
    return X_STATUS_INVALID_PARAMETER;
  }
  REX_KERNEL_MEMORY()->SystemHeapFree(dns.guest_address());
  return 0;
}

// ds2-nx (online recon): XNetServerToInAddr(caller, title server address, service id, secure address out). With
// net_online_probe the "secure" address is the server's own (no Live security association); else a stub, as before.
// ds2-nx (online recon): WSAEventSelect(caller, socket, event, network events). A stub before (r3 left as it was);
// with net_online_probe it succeeds and is logged.
u32 NetDll_WSAEventSelect_entry(u32 caller, u32 socket_handle, u32 event_handle, u32 events) {
  if (!REXCVAR_GET(net_online_probe)) return 0;
  REXLOG_INFO("[net] WSAEventSelect socket {:08X} event {:08X} events {:X}", socket_handle, event_handle, events);
  // As in Winsock, WSAEventSelect makes the socket non-blocking: Dark Souls II then polls recvfrom (1232 bytes) on
  // its network thread, which hung on a blocking host socket. The event itself is not signalled yet (TODO: when the
  // host socket has data).
#if REX_PLATFORM_WIN32
  if (auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle)) {
    uint32_t non_blocking = 1;
    socket->IOControl(FIONBIO, reinterpret_cast<uint8_t*>(&non_blocking));
  }
#else
  // ds2scholar-nx (2026-10-25, console hung on "Logging in"): FIONBIO was not even defined here on the Switch (libnx
  // has it in <sys/filio.h>), so the socket stayed blocking and the game's network thread waited in recvfrom forever.
  // fcntl(O_NONBLOCK) is what libnx's BSD sockets support.
  if (auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle)) {
    const int fd = int(socket->native_handle());
    const int flags = fcntl(fd, F_GETFL, 0);
    const int rc = flags < 0 ? flags : fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    REXLOG_INFO("[net] WSAEventSelect: socket {:08X} (fd {}) non-blocking -> {}", socket_handle, fd, rc);
  }
#endif
  return 0;
}

// ds2-nx (online recon): getsockopt(caller, socket, level, option, value out, length in/out). A stub before; with
// net_online_probe a 4-byte option reads back 64 KB for the buffer sizes (SO_SNDBUF 0x1001 / SO_RCVBUF 0x1002) and 0
// for anything else.
u32 NetDll_getsockopt_entry(u32 caller, u32 socket_handle, u32 level, u32 optname, mapped_u32 optval,
                            mapped_u32 optlen) {
  if (!REXCVAR_GET(net_online_probe)) return 0;
  const uint32_t value = (level == 0xFFFF && (optname == 0x1001 || optname == 0x1002)) ? 0x10000 : 0;
  if (optval) *optval = value;
  if (optlen) *optlen = 4;
  REXLOG_INFO("[net] getsockopt socket {:08X} level {:X} option {:X} -> {:X}", socket_handle, level, optname, value);
  return 0;
}

u32 NetDll_XNetServerToInAddr_entry(u32 caller, u32 ina, u32 service_id, mapped_u32 secure_out) {
  if (!REXCVAR_GET(net_online_probe)) return 1;
  if (secure_out) {
    const uint32_t raw = ina;  // the guest passed the IN_ADDR by value: its bytes are network order
    *secure_out = raw;
  }
  REXLOG_INFO("[net] XNetServerToInAddr {:08X} service {:08X} -> same address", ina, service_id);
  return 0;
}

u32 NetDll_XNetQosServiceLookup_entry(u32 caller, u32 flags, u32 event_handle, mapped_u32 pqos) {
  // Set pqos as some games will try accessing it despite non-successful result
  if (pqos) {
    auto qos_guest = REX_KERNEL_MEMORY()->SystemHeapAlloc(sizeof(XNQOS));
    auto qos = REX_KERNEL_MEMORY()->TranslateVirtual<XNQOS*>(qos_guest);
    qos->count = qos->count_pending = 0;
    *pqos = qos_guest;
  }
  if (event_handle) {
    auto ev = REX_KERNEL_OBJECTS()->LookupObject<XEvent>(event_handle);
    assert_not_null(ev);
    ev->Set(0, false);
  }
  return 0;
}

u32 NetDll_XNetQosRelease_entry(u32 caller, ppc_ptr_t<XNQOS> qos) {
  if (!qos) {
    return X_STATUS_INVALID_PARAMETER;
  }
  REX_KERNEL_MEMORY()->SystemHeapFree(qos.guest_address());
  return 0;
}

u32 NetDll_XNetQosListen_entry(u32 caller, mapped_void id, mapped_void data, u32 data_size, u32 r7,
                               u32 flags) {
  return X_ERROR_FUNCTION_FAILED;
}

u32 NetDll_inet_addr_entry(mapped_string addr_ptr) {
  if (!addr_ptr) {
    return -1;
  }

  uint32_t addr = inet_addr(addr_ptr);
  // https://docs.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-inet_addr#return-value
  // Based on console research it seems like x360 uses old version of inet_addr
  // In case of empty string it return 0 instead of -1
  if (REXCVAR_GET(net_online_probe))
    REXLOG_INFO("[net] inet_addr '{}' -> {:08X}", std::string(addr_ptr.host_address()), rex::byte_swap(addr));
  if (addr == -1 && !addr_ptr.value().length()) {
    return 0;
  }

  return rex::byte_swap(addr);
}

u32 NetDll_socket_entry(u32 caller, u32 af, u32 type, u32 protocol) {
  WakeCall wake_call("socket", 0);
  XSocket* socket = new XSocket(REX_KERNEL_STATE());
  X_STATUS result =
      socket->Initialize(XSocket::AddressFamily((uint32_t)af), XSocket::Type((uint32_t)type),
                         XSocket::Protocol((uint32_t)protocol));

  if (REXCVAR_GET(net_online_probe))
    REXLOG_INFO("[net] socket af {} type {} protocol {} -> {}; guest stack:{}", af, type, protocol,
                XFAILED(result) ? std::string("failed") : fmt::format("{:08X}", socket->handle()), HostStackNames());
  if (XFAILED(result)) {
    socket->Release();

    uint32_t error = xboxkrnl::xeRtlNtStatusToDosError(result);
    XThread::SetLastError(error);
    return -1;
  }

  return socket->handle();
}

u32 NetDll_closesocket_entry(u32 caller, u32 socket_handle) {
  WakeCall wake_call("closesocket", socket_handle);
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  {
    std::lock_guard lock(g_relay_mutex);
    g_relay_sockets.erase(socket_handle);
    g_hello_sockets.erase(socket_handle);
  }
  // TODO: Absolutely delete this object. It is no longer valid after calling
  // closesocket.
  socket->Close();
  socket->ReleaseHandle();
  return 0;
}

i32 NetDll_shutdown_entry(u32 caller, u32 socket_handle, i32 how) {
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  auto ret = socket->Shutdown(how);
  if (ret == -1) {
#if REX_PLATFORM_WIN32
    uint32_t error_code = WSAGetLastError();
    XThread::SetLastError(error_code);
#else
    XThread::SetLastError(REXCVAR_GET(net_online_probe) ? PosixErrorToWsa(errno) : 0);
#endif
  }
  return ret;
}

u32 NetDll_setsockopt_entry(u32 caller, u32 socket_handle, u32 level, u32 optname,
                            mapped_void optval_ptr, u32 optlen) {
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  // SotFS calls returning to 0x8333CE24/0x8333CE50 pass a guest int (stw), not a host int. The game connection asks for
  // 0x8000 bytes from the login reply: forwarding 00 00 80 00 to little-endian libnx asks for 8 MiB instead.
  // Keep this experiment limited to the two integer buffer-size options; other option layouts are untouched.
  uint32_t buffer_bytes = 0;
  void* native_optval = optval_ptr.host_address();
  const bool decode_buffer = REXCVAR_GET(ds2_socket_buffer_endian) && optval_ptr && optlen == 4 &&
                             level == 0xFFFF && (optname == 0x1001 || optname == 0x1002);
  if (decode_buffer) {
    buffer_bytes = memory::load_and_swap<uint32_t>(native_optval);
    native_optval = &buffer_bytes;
  }
  X_STATUS status = socket->SetOption(level, optname, native_optval, optlen);
#if REX_PLATFORM_WIN32
  const int native_error = XFAILED(status) ? WSAGetLastError() : 0;
#else
  const int native_error = XFAILED(status) ? errno : 0;
#endif
  if (REXCVAR_GET(net_online_probe))
    REXLOG_INFO("[net] setsockopt socket {:08X} level {:X} option {:X} length {} -> {:08X}; decoded buffer {} bytes {} native error {}",
                socket_handle, level, optname, optlen, status, decode_buffer, buffer_bytes, native_error);
  return XSUCCEEDED(status) ? 0 : -1;
}

u32 NetDll_ioctlsocket_entry(u32 caller, u32 socket_handle, u32 cmd, mapped_void arg_ptr) {
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  X_STATUS status = socket->IOControl(cmd, arg_ptr);
  if (REXCVAR_GET(net_online_probe))
    REXLOG_INFO("[net] ioctlsocket socket {:08X} command {:08X} -> {:08X}", socket_handle, cmd, status);
  if (XFAILED(status)) {
    XThread::SetLastError(xboxkrnl::xeRtlNtStatusToDosError(status));
    return -1;
  }

  // TODO
  return 0;
}

u32 NetDll_bind_entry(u32 caller, u32 socket_handle, ppc_ptr_t<XSOCKADDR_IN> name, u32 namelen) {
  WakeCall wake_call("bind", socket_handle);
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  N_XSOCKADDR_IN native_name(name);
  if (REXCVAR_GET(net_p2p_lan) && name && uint32_t(name->sin_addr) == 0 && uint16_t(name->sin_port) != 0) {
    const auto local = LocalLanAddress();
    if (!local) { XThread::SetLastError(10022); return -1; }
    // Only bind to specific loopback addresses (127.0.0.X) on PC to allow two local processes to share ports.
    // On physical network interfaces or Switch (Horizon OS), bind to INADDR_ANY (0.0.0.0) so the OS allows listening.
    if ((*local)[0] == 127) {
      const uint32_t address = (uint32_t((*local)[0]) << 24) | (uint32_t((*local)[1]) << 16) |
                               (uint32_t((*local)[2]) << 8) | (*local)[3];
      native_name.sin_addr = address;
    }
    REXLOG_INFO("[p2p] Bind {:08X} {} port {}", socket_handle, REXCVAR_GET(net_p2p_address), uint16_t(name->sin_port));
  }
  const uint16_t relay_game_port =
      RelayEnabled() && name && uint32_t(name->sin_addr) == 0 ? uint16_t(name->sin_port) : uint16_t(0);
  if (relay_game_port) {
    native_name.sin_addr = 0;  // any interface, a free port: all traffic goes through the relay
    native_name.sin_port = 0;
  }
  X_STATUS status = socket->Bind(&native_name, namelen);
  if (relay_game_port && XSUCCEEDED(status)) RelayAddSocket(socket_handle, socket->native_handle(), relay_game_port);
  if (REXCVAR_GET(net_online_probe) && name)
    REXLOG_INFO("[net] bind socket {:08X} port {} -> {:08X}", socket_handle, uint16_t(name->sin_port), status);
  if (XFAILED(status)) {
    XThread::SetLastError(xboxkrnl::xeRtlNtStatusToDosError(status));
    return -1;
  }

  return 0;
}

u32 NetDll_getsockname_entry(u32 caller, u32 socket_handle, ppc_ptr_t<XSOCKADDR_IN> name,
                            mapped_u32 namelen) {
  if (!REXCVAR_GET(net_p2p_lan)) {
    // REX_EXPORT_STUB left r3 untouched (the caller argument), including its log.
    REXKRNL_WARN("__imp__NetDll_getsockname STUB");
    return caller;
  }
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) { XThread::SetLastError(10038); return uint32_t(-1); }
  if (!name || !namelen || *namelen < sizeof(XSOCKADDR_IN)) {
    XThread::SetLastError(10014);
    return uint32_t(-1);
  }
  sockaddr_in native{};
#if REX_PLATFORM_WIN32
  int length = sizeof(native);
  const int result = ::getsockname(SOCKET(socket->native_handle()), reinterpret_cast<sockaddr*>(&native), &length);
  const uint32_t error = result == -1 ? WSAGetLastError() : 0;
#else
  socklen_t length = sizeof(native);
  const int result = ::getsockname(int(socket->native_handle()), reinterpret_cast<sockaddr*>(&native), &length);
  const uint32_t error = result == -1 ? PosixErrorToWsa(errno) : 0;
#endif
  if (result == -1) { XThread::SetLastError(error); return uint32_t(-1); }
  name->sin_family = native.sin_family;
  name->sin_port = ntohs(native.sin_port);
  if (const auto game_port = RelayGamePort(socket_handle)) name->sin_port = *game_port;
  name->sin_addr = ntohl(native.sin_addr.s_addr);
  if (name->sin_addr == 0 && REXCVAR_GET(net_p2p_lan)) {
    if (const auto local = LocalLanAddress()) {
      const auto ip = lan::PeerIP(*local);
      if (ip) {
        name->sin_addr = LanIPValue(*ip);
      }
    }
  }
  std::memset(name->x_sin_zero, 0, sizeof(name->x_sin_zero));
  *namelen = sizeof(XSOCKADDR_IN);
  REXLOG_INFO("[p2p] getsockname {:08X} -> {:08X}:{}; stack:{}", socket_handle,
              uint32_t(name->sin_addr), uint16_t(name->sin_port), HostStackNames());
  return 0;
}

u32 NetDll_connect_entry(u32 caller, u32 socket_handle, ppc_ptr_t<XSOCKADDR> name, u32 namelen) {
  WakeCall wake_call("connect", socket_handle);
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  N_XSOCKADDR native_name(name);
  if (SessionAddressesEnabled() && name && namelen >= sizeof(XSOCKADDR_IN) &&
      uint16_t(name->address_family) == XSocket::X_AF_INET) {
    N_XSOCKADDR_IN destination(reinterpret_cast<const XSOCKADDR_IN*>(name.host_address()));
    if (!TranslateLanDestination(destination)) {
      XThread::SetLastError(10049);
      return ~0u;
    }
    std::memcpy(native_name.sa_data, &destination.sin_port, sizeof(native_name.sa_data));
  }
  if (REXCVAR_GET(net_online_probe) && name) {
    const auto* in = reinterpret_cast<const XSOCKADDR_IN*>(name.host_address());
    const uint32_t a = in->sin_addr;
    REXLOG_INFO("[net] connect socket {:08X} to {}.{}.{}.{}:{}", socket_handle, a >> 24, (a >> 16) & 0xFF,
                (a >> 8) & 0xFF, a & 0xFF, uint16_t(in->sin_port));
  }
  X_STATUS status = socket->Connect(&native_name, namelen);
  if (REXCVAR_GET(net_online_probe)) REXLOG_INFO("[net] connect socket {:08X} -> status {:08X}", socket_handle, status);
  if (XFAILED(status)) {
    XThread::SetLastError(xboxkrnl::xeRtlNtStatusToDosError(status));
    return -1;
  }

  return 0;
}

u32 NetDll_listen_entry(u32 caller, u32 socket_handle, i32 backlog) {
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  X_STATUS status = socket->Listen(backlog);
  if (XFAILED(status)) {
    XThread::SetLastError(xboxkrnl::xeRtlNtStatusToDosError(status));
    return -1;
  }

  return 0;
}

u32 NetDll_accept_entry(u32 caller, u32 socket_handle, ppc_ptr_t<XSOCKADDR> addr_ptr,
                        mapped_u32 addrlen_ptr) {
  if (!addr_ptr) {
    // WSAEFAULT
    XThread::SetLastError(0x271E);
    return -1;
  }

  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  N_XSOCKADDR native_addr(addr_ptr);
  int native_len = *addrlen_ptr;
  auto new_socket = socket->Accept(&native_addr, &native_len);
  if (new_socket) {
    addr_ptr->address_family = native_addr.address_family;
    std::memcpy(addr_ptr->sa_data, native_addr.sa_data, *addrlen_ptr - 2);
    *addrlen_ptr = native_len;

    return new_socket->handle();
  } else {
    return -1;
  }
}

struct x_fd_set {
  rex::be<uint32_t> fd_count;
  rex::be<uint32_t> fd_array[64];
};

struct host_set {
  uint32_t count;
  object_ref<XSocket> sockets[64];

  void Load(const x_fd_set* guest_set) {
    assert_true(guest_set->fd_count < 64);
    this->count = guest_set->fd_count;
    for (uint32_t i = 0; i < this->count; ++i) {
      auto socket_handle = static_cast<X_HANDLE>(guest_set->fd_array[i]);
      if (socket_handle == -1) {
        this->count = i;
        break;
      }
      // Convert from Xenia -> native
      auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
      assert_not_null(socket);
      this->sockets[i] = socket;
    }
  }

  void Store(x_fd_set* guest_set) {
    guest_set->fd_count = 0;
    for (uint32_t i = 0; i < this->count; ++i) {
      auto socket = this->sockets[i];
      guest_set->fd_array[guest_set->fd_count++] = socket->handle();
    }
  }

  void Store(fd_set* native_set) {
    FD_ZERO(native_set);
    for (uint32_t i = 0; i < this->count; ++i) {
      FD_SET(this->sockets[i]->native_handle(), native_set);
    }
  }

  void UpdateFrom(fd_set* native_set) {
    uint32_t new_count = 0;
    for (uint32_t i = 0; i < this->count; ++i) {
      auto socket = this->sockets[i];
      if (FD_ISSET(socket->native_handle(), native_set)) {
        this->sockets[new_count++] = socket;
      }
    }
    this->count = new_count;
  }
};

i32 NetDll_select_entry(i32 caller, i32 nfds, ppc_ptr_t<x_fd_set> readfds,
                        ppc_ptr_t<x_fd_set> writefds, ppc_ptr_t<x_fd_set> exceptfds,
                        mapped_void timeout_ptr) {
  WakeCall wake_call("select", 0);
  host_set host_readfds = {};
  fd_set native_readfds = {};
  if (readfds) {
    host_readfds.Load(readfds);
    host_readfds.Store(&native_readfds);
  }
  host_set host_writefds = {};
  fd_set native_writefds = {};
  if (writefds) {
    host_writefds.Load(writefds);
    host_writefds.Store(&native_writefds);
  }
  host_set host_exceptfds = {};
  fd_set native_exceptfds = {};
  if (exceptfds) {
    host_exceptfds.Load(exceptfds);
    host_exceptfds.Store(&native_exceptfds);
  }
  timeval* timeout_in = nullptr;
  timeval timeout;
  if (timeout_ptr) {
    timeout = {static_cast<int32_t>(timeout_ptr.as_array<int32_t>()[0]),
               static_cast<int32_t>(timeout_ptr.as_array<int32_t>()[1])};
    chrono::Clock::ScaleGuestDurationTimeval(reinterpret_cast<int32_t*>(&timeout.tv_sec),
                                             reinterpret_cast<int32_t*>(&timeout.tv_usec));
    timeout_in = &timeout;
  }
  int ret = select(nfds, readfds ? &native_readfds : nullptr, writefds ? &native_writefds : nullptr,
                   exceptfds ? &native_exceptfds : nullptr, timeout_in);
  if (readfds) {
    host_readfds.UpdateFrom(&native_readfds);
    host_readfds.Store(readfds);
  }
  if (writefds) {
    host_writefds.UpdateFrom(&native_writefds);
    host_writefds.Store(writefds);
  }
  if (exceptfds) {
    host_exceptfds.UpdateFrom(&native_exceptfds);
    host_exceptfds.Store(exceptfds);
  }

  // TODO(gibbed): modify ret to be what's actually copied to the guest fd_sets?
  return ret;
}

u32 NetDll_recv_entry(u32 caller, u32 socket_handle, mapped_void buf_ptr, u32 buf_len, u32 flags) {
  WakeCall wake_call("recv", socket_handle);
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  return socket->Recv(buf_ptr, buf_len, flags);
}

u32 NetDll_recvfrom_entry(u32 caller, u32 socket_handle, mapped_void buf_ptr, u32 buf_len,
                          u32 flags, ppc_ptr_t<XSOCKADDR_IN> from_ptr, mapped_u32 fromlen_ptr) {
  WakeCall wake_call("recvfrom", socket_handle);
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  N_XSOCKADDR_IN native_from;
  if (from_ptr) {
    native_from = *from_ptr;
  }
  uint32_t native_fromlen = fromlen_ptr ? fromlen_ptr.value() : 0;
  if (REXCVAR_GET(net_online_probe)) {
    static int logged = 0;
    if (logged++ < 16) REXLOG_INFO("[net] recvfrom socket {:08X} up to {} bytes (enter)", socket_handle, buf_len);
  }
  if (RelayEnabled() && RelayGamePortKeepalive(socket_handle)) {
    uint32_t relay_ip = 0;
    uint16_t relay_port = 0;
    RelayEndpoint(relay_ip, relay_port);
    std::vector<uint8_t> datagram(size_t(buf_len) + relay::kAddressedHeader);
    for (;;) {
      N_XSOCKADDR_IN from{};
      uint32_t from_size = sizeof(from);
      const int got = socket->RecvFrom(datagram.data(), uint32_t(datagram.size()), flags, &from, &from_size);
      if (got < 0) {
#if REX_PLATFORM_WIN32
        XThread::SetLastError(WSAGetLastError());
#else
        XThread::SetLastError(PosixErrorToWsa(errno));
#endif
        return uint32_t(-1);
      }
      const auto parsed = uint32_t(from.sin_addr) == relay_ip && uint16_t(from.sin_port) == relay_port
                              ? relay::Parse({datagram.data(), size_t(got)})
                              : std::nullopt;
      if (parsed && parsed->type == relay::kAck) {
        static std::atomic<unsigned> acks{};
        if (acks.fetch_add(1) < 8)
          REXLOG_INFO("[relay] registered: socket {:08X} game port {}", socket_handle, parsed->port);
        continue;  // never the game's: read the next datagram (a non-blocking socket then reports no data)
      }
      uint32_t length = uint32_t(got);
      const uint8_t* payload = datagram.data();
      if (parsed) {
        payload += parsed->payload;
        length -= uint32_t(parsed->payload);
        from.sin_addr = RelayPeerHandle(parsed->xuid);
        from.sin_port = parsed->port;
      }
      length = std::min(length, uint32_t(buf_len));
      std::memcpy(buf_ptr.host_address(), payload, length);
      if (from_ptr) {
        from_ptr->sin_family = 2;
        from_ptr->sin_port = uint16_t(from.sin_port);
        from_ptr->sin_addr = uint32_t(from.sin_addr);
        std::memset(from_ptr->x_sin_zero, 0, sizeof(from_ptr->x_sin_zero));
      }
      if (fromlen_ptr) *fromlen_ptr = sizeof(XSOCKADDR_IN);
      if (parsed && REXCVAR_GET(net_p2p_diagnostics)) {
        static std::atomic<unsigned> logged{};
        if (logged.fetch_add(1) < 64)
          REXLOG_INFO("[relay] RX {:08X} <- {:016X}:{} {} bytes as {:08X}", socket_handle, parsed->xuid,
                      parsed->port, length, uint32_t(from.sin_addr));
      }
      return length;
    }
  }
  int ret =
      socket->RecvFrom(buf_ptr, buf_len, flags, &native_from, fromlen_ptr ? &native_fromlen : 0);
#if !REX_PLATFORM_WIN32
  const int recv_error = ret == -1 ? errno : 0;
#endif

  if (from_ptr) {
    from_ptr->sin_family = native_from.sin_family;
    from_ptr->sin_port = native_from.sin_port;
    from_ptr->sin_addr = ret >= 0 ? IncomingLanAddress(native_from.sin_addr, native_from.sin_port)
                                 : uint32_t(native_from.sin_addr);
    std::memset(from_ptr->x_sin_zero, 0, sizeof(from_ptr->x_sin_zero));
  }
  if (fromlen_ptr) {
    *fromlen_ptr = native_fromlen;
  }

  if (ret > 0 && from_ptr && REXCVAR_GET(net_p2p_diagnostics) && REXCVAR_GET(net_p2p_lan) &&
      uint32_t(from_ptr->sin_addr) != ntohl(ServerAddress())) {
    static std::atomic<unsigned> counts[2]{};
    const bool control = uint16_t(from_ptr->sin_port) == 10010;
    if (counts[control].fetch_add(1) < (control ? 256u : 128u)) {
      std::string bytes;
      const auto* data = static_cast<const uint8_t*>(buf_ptr.host_address());
      for (int i = 0; i < std::min(ret, control ? 256 : 96); ++i) bytes += fmt::format("{:02X}", data[i]);
      REXLOG_INFO("[p2p] RX {:08X} <- {:08X}:{} {} bytes data={}", socket_handle,
                  uint32_t(from_ptr->sin_addr), uint16_t(from_ptr->sin_port), ret, bytes);
    }
  }

  if (ret == -1) {
// TODO: Better way of getting the error code
#if REX_PLATFORM_WIN32
    uint32_t error_code = WSAGetLastError();
    XThread::SetLastError(error_code);
#else
    XThread::SetLastError(REXCVAR_GET(net_online_probe) ? PosixErrorToWsa(recv_error) : 0);
#endif
  }

  if (REXCVAR_GET(net_online_probe)) {
    static int results_logged = 0;
    if (results_logged++ < 16) {
#if REX_PLATFORM_WIN32
      REXLOG_INFO("[net] recvfrom socket {:08X} -> {} WSA {}", socket_handle, ret,
                  ret == -1 ? XThread::GetLastError() : 0);
#else
      REXLOG_INFO("[net] recvfrom socket {:08X} -> {} errno {} WSA {}", socket_handle, ret,
                  recv_error, ret == -1 ? XThread::GetLastError() : 0);
#endif
    }
  }

  return ret;
}

u32 NetDll_send_entry(u32 caller, u32 socket_handle, mapped_void buf_ptr, u32 buf_len, u32 flags) {
  WakeCall wake_call("send", socket_handle);
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  if (REXCVAR_GET(net_online_probe) && buf_ptr) {
    const auto* b = static_cast<const uint8_t*>(buf_ptr.host_address());
    std::string hex;
    for (u32 i = 0; i < std::min<u32>(buf_len, 64); ++i) hex += fmt::format("{:02X}", b[i]);
    REXLOG_INFO("[net] send socket {:08X} {} bytes: {}", socket_handle, buf_len, hex);
  }
  return socket->Send(buf_ptr, buf_len, flags);
}

u32 NetDll_sendto_entry(u32 caller, u32 socket_handle, mapped_void buf_ptr, u32 buf_len, u32 flags,
                        ppc_ptr_t<XSOCKADDR_IN> to_ptr, u32 to_len) {
  WakeCall wake_call("sendto", socket_handle);
  auto socket = REX_KERNEL_OBJECTS()->LookupObject<XSocket>(socket_handle);
  if (!socket) {
    // WSAENOTSOCK
    XThread::SetLastError(0x2736);
    return -1;
  }

  N_XSOCKADDR_IN native_to(to_ptr);
  if (RelayEnabled() && to_ptr && lan::SessionAddresses::IsHandle(uint32_t(to_ptr->sin_addr)) &&
      RelayGamePortKeepalive(socket_handle)) {
    const uint64_t xuid = RelayHandleXuid(uint32_t(to_ptr->sin_addr));
    uint32_t relay_ip = 0;
    uint16_t relay_port = 0;
    if (!xuid || !RelayEndpoint(relay_ip, relay_port) || buf_len > relay::kMaxPayload) {
      static int logged = 0;
      if (logged++ < 16)
        REXLOG_WARN("[relay] TX {:08X} -> {:08X}:{} {} bytes refused: XUID {:016X}", socket_handle,
                    uint32_t(to_ptr->sin_addr), uint16_t(to_ptr->sin_port), buf_len, xuid);
      XThread::SetLastError(10049);  // WSAEADDRNOTAVAIL
      return ~0u;
    }
    auto packet = relay::Data(xuid, uint16_t(to_ptr->sin_port),
                              {static_cast<const uint8_t*>(buf_ptr.host_address()), buf_len});
    native_to.sin_addr = relay_ip;
    native_to.sin_port = relay_port;
    const int sent = socket->SendTo(packet.data(), uint32_t(packet.size()), flags, &native_to, to_len);
    if (REXCVAR_GET(net_p2p_diagnostics)) {
      static std::atomic<unsigned> logged{};
      if (logged.fetch_add(1) < 64)
        REXLOG_INFO("[relay] TX {:08X} -> {:016X}:{} {} bytes result={}", socket_handle, xuid,
                    uint16_t(to_ptr->sin_port), buf_len, sent);
    }
    return sent == int(packet.size()) ? buf_len : uint32_t(sent);
  }
  if (!TranslateLanDestination(native_to)) {
    XThread::SetLastError(10049);
    return ~0u;
  }
  if (REXCVAR_GET(net_online_probe) && buf_ptr) {
    static int logged = 0;
    if (logged++ < 64) {
      const auto* b = static_cast<const uint8_t*>(buf_ptr.host_address());
      std::string hex;
      for (u32 i = 0; i < std::min<u32>(buf_len, 96); ++i) hex += fmt::format("{:02X}", b[i]);
      const uint32_t a = to_ptr ? uint32_t(to_ptr->sin_addr) : 0;
      REXLOG_INFO("[net] sendto socket {:08X} {}.{}.{}.{}:{} {} bytes: {}", socket_handle, a >> 24, (a >> 16) & 0xFF,
                  (a >> 8) & 0xFF, a & 0xFF, to_ptr ? uint16_t(to_ptr->sin_port) : 0, buf_len, hex);
    }
  }
  if (REXCVAR_GET(net_client_hello) && to_ptr && uint16_t(to_ptr->sin_port) == REXCVAR_GET(net_client_hello_port) &&
      uint32_t(to_ptr->sin_addr) == ntohl(ServerAddress())) {
    bool first = false;
    {
      std::lock_guard lock(g_relay_mutex);
      first = g_hello_sockets.insert(socket_handle).second;
    }
    if (first) {
      std::optional<relay::access::Ticket> ticket;
      if (REXCVAR_GET(net_access)) ticket = AccessTicket(uint16_t(to_ptr->sin_port));
      const auto hello = ticket ? relay::ClientHello(*ticket) : relay::ClientHello();
      sockaddr_in to{};
      to.sin_family = AF_INET;
      to.sin_addr.s_addr = ServerAddress();
      to.sin_port = htons(uint16_t(to_ptr->sin_port));
#if REX_PLATFORM_WIN32
      const int sent = ::sendto(SOCKET(socket->native_handle()), reinterpret_cast<const char*>(hello.data()),
                                int(hello.size()), 0, reinterpret_cast<const sockaddr*>(&to), sizeof(to));
#else
      const int sent = int(::sendto(int(socket->native_handle()), hello.data(), hello.size(), 0,
                                    reinterpret_cast<const sockaddr*>(&to), sizeof(to)));
#endif
      REXLOG_INFO("[net] client hello{}: socket {:08X} protocol {} -> {}:{} ({})", ticket ? " with an access ticket" : "",
                  socket_handle, relay::kClientProtocol, REXCVAR_GET(net_dns_address), uint16_t(to_ptr->sin_port), sent);
    }
  }
  const auto result = socket->SendTo(buf_ptr, buf_len, flags, &native_to, to_len);
  if (to_ptr && REXCVAR_GET(net_p2p_diagnostics) && REXCVAR_GET(net_p2p_lan) &&
      uint32_t(to_ptr->sin_addr) != ntohl(ServerAddress())) {
    static std::atomic<unsigned> counts[2]{};
    const bool control = uint16_t(to_ptr->sin_port) == 10010;
    // SotFS RUDP close observed in 20261026_211710: F5 02 seq 50 00 06 FF.
    // Capture the caller even after the packet dump budget is exhausted. This
    // only observes the existing send; it does not alter the close or timeout.
    const auto* packet = static_cast<const uint8_t*>(buf_ptr.host_address());
    if (control && buf_len == 7 && packet && packet[0] == 0xF5 && packet[1] == 0x02 &&
        packet[3] == 0x50 && packet[4] == 0 && packet[5] == 0x06) {
      REXLOG_INFO("[p2p] Control close {:08X} -> {:08X}:{} result={}; stack:{}", socket_handle,
                  uint32_t(to_ptr->sin_addr), uint16_t(to_ptr->sin_port), result, HostStackNames());
    }
    if (counts[control].fetch_add(1) < (control ? 256u : 128u)) {
      std::string bytes;
      const auto* data = static_cast<const uint8_t*>(buf_ptr.host_address());
      for (u32 i = 0; i < std::min(buf_len, control ? 256u : 96u); ++i) bytes += fmt::format("{:02X}", data[i]);
      REXLOG_INFO("[p2p] TX {:08X} -> {:08X}:{} {} bytes result={} data={}", socket_handle,
                  uint32_t(to_ptr->sin_addr), uint16_t(to_ptr->sin_port), buf_len, result, bytes);
    }
  }
  return result;
}

u32 NetDll___WSAFDIsSet_entry(u32 socket_handle, ppc_ptr_t<x_fd_set> fd_set) {
  const uint8_t max_fd_count = std::min((uint32_t)fd_set->fd_count, uint32_t(64));
  for (uint8_t i = 0; i < max_fd_count; i++) {
    if (fd_set->fd_array[i] == socket_handle) {
      return 1;
    }
  }
  return 0;
}

void NetDll_WSASetLastError_entry(u32 error_code) {
  XThread::SetLastError(error_code);
}

}  // namespace xam
}  // namespace kernel
}  // namespace rex

REX_EXPORT(__imp__NetDll_XNetStartup, rex::kernel::xam::NetDll_XNetStartup_entry)
REX_EXPORT(__imp__NetDll_XNetCleanup, rex::kernel::xam::NetDll_XNetCleanup_entry)
REX_EXPORT(__imp__NetDll_XNetGetOpt, rex::kernel::xam::NetDll_XNetGetOpt_entry)
REX_EXPORT(__imp__NetDll_XNetRandom, rex::kernel::xam::NetDll_XNetRandom_entry)
REX_EXPORT(__imp__NetDll_WSAStartup, rex::kernel::xam::NetDll_WSAStartup_entry)
REX_EXPORT(__imp__NetDll_WSACleanup, rex::kernel::xam::NetDll_WSACleanup_entry)
REX_EXPORT(__imp__NetDll_WSAGetLastError, rex::kernel::xam::NetDll_WSAGetLastError_entry)
REX_EXPORT(__imp__NetDll_WSARecvFrom, rex::kernel::xam::NetDll_WSARecvFrom_entry)
REX_EXPORT(__imp__NetDll_WSASendTo, rex::kernel::xam::NetDll_WSASendTo_entry)
REX_EXPORT(__imp__NetDll_WSAWaitForMultipleEvents,
           rex::kernel::xam::NetDll_WSAWaitForMultipleEvents_entry)
REX_EXPORT(__imp__NetDll_WSACreateEvent, rex::kernel::xam::NetDll_WSACreateEvent_entry)
REX_EXPORT(__imp__NetDll_WSACloseEvent, rex::kernel::xam::NetDll_WSACloseEvent_entry)
REX_EXPORT(__imp__NetDll_WSAResetEvent, rex::kernel::xam::NetDll_WSAResetEvent_entry)
REX_EXPORT(__imp__NetDll_WSASetEvent, rex::kernel::xam::NetDll_WSASetEvent_entry)
REX_EXPORT(__imp__NetDll_XNetGetTitleXnAddr, rex::kernel::xam::NetDll_XNetGetTitleXnAddr_entry)
REX_EXPORT(__imp__NetDll_XNetGetDebugXnAddr, rex::kernel::xam::NetDll_XNetGetDebugXnAddr_entry)
REX_EXPORT(__imp__NetDll_XNetXnAddrToMachineId,
           rex::kernel::xam::NetDll_XNetXnAddrToMachineId_entry)
REX_EXPORT(__imp__NetDll_XNetInAddrToString, rex::kernel::xam::NetDll_XNetInAddrToString_entry)
REX_EXPORT(__imp__NetDll_XNetXnAddrToInAddr, rex::kernel::xam::NetDll_XNetXnAddrToInAddr_entry)
REX_EXPORT(__imp__NetDll_XNetInAddrToXnAddr, rex::kernel::xam::NetDll_XNetInAddrToXnAddr_entry)
REX_EXPORT(__imp__NetDll_XNetSetSystemLinkPort,
           rex::kernel::xam::NetDll_XNetSetSystemLinkPort_entry)
REX_EXPORT(__imp__NetDll_XNetGetEthernetLinkStatus,
           rex::kernel::xam::NetDll_XNetGetEthernetLinkStatus_entry)
REX_EXPORT(__imp__NetDll_XNetDnsLookup, rex::kernel::xam::NetDll_XNetDnsLookup_entry)
REX_EXPORT(__imp__NetDll_XNetDnsRelease, rex::kernel::xam::NetDll_XNetDnsRelease_entry)
REX_EXPORT(__imp__NetDll_WSAEventSelect, rex::kernel::xam::NetDll_WSAEventSelect_entry)
REX_EXPORT(__imp__NetDll_getsockopt, rex::kernel::xam::NetDll_getsockopt_entry)
REX_EXPORT(__imp__NetDll_XNetServerToInAddr, rex::kernel::xam::NetDll_XNetServerToInAddr_entry)
REX_EXPORT(__imp__NetDll_XNetQosServiceLookup, rex::kernel::xam::NetDll_XNetQosServiceLookup_entry)
REX_EXPORT(__imp__NetDll_XNetQosRelease, rex::kernel::xam::NetDll_XNetQosRelease_entry)
REX_EXPORT(__imp__NetDll_XNetQosListen, rex::kernel::xam::NetDll_XNetQosListen_entry)
REX_EXPORT(__imp__NetDll_inet_addr, rex::kernel::xam::NetDll_inet_addr_entry)
REX_EXPORT(__imp__NetDll_socket, rex::kernel::xam::NetDll_socket_entry)
REX_EXPORT(__imp__NetDll_closesocket, rex::kernel::xam::NetDll_closesocket_entry)
REX_EXPORT(__imp__NetDll_shutdown, rex::kernel::xam::NetDll_shutdown_entry)
REX_EXPORT(__imp__NetDll_setsockopt, rex::kernel::xam::NetDll_setsockopt_entry)
REX_EXPORT(__imp__NetDll_ioctlsocket, rex::kernel::xam::NetDll_ioctlsocket_entry)
REX_EXPORT(__imp__NetDll_bind, rex::kernel::xam::NetDll_bind_entry)
REX_EXPORT(__imp__NetDll_connect, rex::kernel::xam::NetDll_connect_entry)
REX_EXPORT(__imp__NetDll_listen, rex::kernel::xam::NetDll_listen_entry)
REX_EXPORT(__imp__NetDll_accept, rex::kernel::xam::NetDll_accept_entry)
REX_EXPORT(__imp__NetDll_select, rex::kernel::xam::NetDll_select_entry)
REX_EXPORT(__imp__NetDll_recv, rex::kernel::xam::NetDll_recv_entry)
REX_EXPORT(__imp__NetDll_recvfrom, rex::kernel::xam::NetDll_recvfrom_entry)
REX_EXPORT(__imp__NetDll_send, rex::kernel::xam::NetDll_send_entry)
REX_EXPORT(__imp__NetDll_sendto, rex::kernel::xam::NetDll_sendto_entry)
REX_EXPORT(__imp__NetDll___WSAFDIsSet, rex::kernel::xam::NetDll___WSAFDIsSet_entry)
REX_EXPORT(__imp__NetDll_WSASetLastError, rex::kernel::xam::NetDll_WSASetLastError_entry)

REX_EXPORT_STUB(__imp__NetDll_UpnpActionCalculateWorkBufferSize);
REX_EXPORT_STUB(__imp__NetDll_UpnpActionCreate);
REX_EXPORT_STUB(__imp__NetDll_UpnpActionGetResults);
REX_EXPORT_STUB(__imp__NetDll_UpnpCleanup);
REX_EXPORT_STUB(__imp__NetDll_UpnpCloseHandle);
REX_EXPORT_STUB(__imp__NetDll_UpnpDescribeCreate);
REX_EXPORT_STUB(__imp__NetDll_UpnpDescribeGetResults);
REX_EXPORT_STUB(__imp__NetDll_UpnpDoWork);
REX_EXPORT_STUB(__imp__NetDll_UpnpEventCreate);
REX_EXPORT_STUB(__imp__NetDll_UpnpEventGetCurrentState);
REX_EXPORT_STUB(__imp__NetDll_UpnpEventUnsubscribe);
REX_EXPORT_STUB(__imp__NetDll_UpnpSearchCreate);
REX_EXPORT_STUB(__imp__NetDll_UpnpSearchGetDevices);
REX_EXPORT_STUB(__imp__NetDll_UpnpStartup);
REX_EXPORT_STUB(__imp__NetDll_WSACancelOverlappedIO);
REX_EXPORT_STUB(__imp__NetDll_WSAGetOverlappedResult);
REX_EXPORT_STUB(__imp__NetDll_WSARecv);
REX_EXPORT_STUB(__imp__NetDll_WSASend);
REX_EXPORT_STUB(__imp__NetDll_WSAStartupEx);
REX_EXPORT_STUB(__imp__NetDll_XHttpCloseHandle);
REX_EXPORT_STUB(__imp__NetDll_XHttpConnect);
REX_EXPORT_STUB(__imp__NetDll_XHttpCrackUrl);
REX_EXPORT_STUB(__imp__NetDll_XHttpCrackUrlW);
REX_EXPORT_STUB(__imp__NetDll_XHttpCreateUrl);
REX_EXPORT_STUB(__imp__NetDll_XHttpCreateUrlW);
REX_EXPORT_STUB(__imp__NetDll_XHttpDoWork);
REX_EXPORT_STUB(__imp__NetDll_XHttpGetPerfCounters);
REX_EXPORT_STUB(__imp__NetDll_XHttpOpen);
REX_EXPORT_STUB(__imp__NetDll_XHttpOpenRequest);
REX_EXPORT_STUB(__imp__NetDll_XHttpOpenRequestUsingMemory);
REX_EXPORT_STUB(__imp__NetDll_XHttpQueryAuthSchemes);
REX_EXPORT_STUB(__imp__NetDll_XHttpQueryHeaders);
REX_EXPORT_STUB(__imp__NetDll_XHttpQueryOption);
REX_EXPORT_STUB(__imp__NetDll_XHttpReadData);
REX_EXPORT_STUB(__imp__NetDll_XHttpReceiveResponse);
REX_EXPORT_STUB(__imp__NetDll_XHttpResetPerfCounters);
REX_EXPORT_STUB(__imp__NetDll_XHttpSendRequest);
REX_EXPORT_STUB(__imp__NetDll_XHttpSetCredentials);
REX_EXPORT_STUB(__imp__NetDll_XHttpSetOption);
REX_EXPORT_STUB(__imp__NetDll_XHttpSetStatusCallback);
REX_EXPORT_STUB(__imp__NetDll_XHttpShutdown);
REX_EXPORT_STUB(__imp__NetDll_XHttpStartup);
REX_EXPORT_STUB(__imp__NetDll_XHttpWriteData);
REX_EXPORT_STUB(__imp__NetDll_XNetConnect);
REX_EXPORT_STUB(__imp__NetDll_XNetCreateKey);
REX_EXPORT_STUB(__imp__NetDll_XNetDnsReverseLookup);
REX_EXPORT_STUB(__imp__NetDll_XNetDnsReverseRelease);
REX_EXPORT_STUB(__imp__NetDll_XNetGetBroadcastVersionStatus);
REX_EXPORT_STUB(__imp__NetDll_XNetGetConnectStatus);
REX_EXPORT_STUB(__imp__NetDll_XNetGetSystemLinkPort);
REX_EXPORT_STUB(__imp__NetDll_XNetGetXnAddrPlatform);
REX_EXPORT_STUB(__imp__NetDll_XNetInAddrToServer);
REX_EXPORT_STUB(__imp__NetDll_XNetQosGetListenStats);
REX_EXPORT_STUB(__imp__NetDll_XNetQosLookup);
REX_EXPORT_STUB(__imp__NetDll_XNetRegisterKey);
REX_EXPORT_STUB(__imp__NetDll_XNetReplaceKey);
REX_EXPORT_STUB(__imp__NetDll_XNetSetOpt);
REX_EXPORT_STUB(__imp__NetDll_XNetStartupEx);
REX_EXPORT_STUB(__imp__NetDll_XNetTsAddrToInAddr);
REX_EXPORT(__imp__NetDll_XNetUnregisterInAddr, rex::kernel::xam::NetDll_XNetUnregisterInAddr_entry)
REX_EXPORT_STUB(__imp__NetDll_XNetUnregisterKey);
REX_EXPORT_STUB(__imp__NetDll_XmlDownloadContinue);
REX_EXPORT_STUB(__imp__NetDll_XmlDownloadGetParseTime);
REX_EXPORT_STUB(__imp__NetDll_XmlDownloadGetReceivedDataSize);
REX_EXPORT_STUB(__imp__NetDll_XmlDownloadStart);
REX_EXPORT_STUB(__imp__NetDll_XmlDownloadStop);
REX_EXPORT_STUB(__imp__NetDll_XnpCapture);
REX_EXPORT_STUB(__imp__NetDll_XnpConfig);
REX_EXPORT_STUB(__imp__NetDll_XnpConfigUPnP);
REX_EXPORT_STUB(__imp__NetDll_XnpConfigUPnPPortAndExternalAddr);
REX_EXPORT_STUB(__imp__NetDll_XnpEthernetInterceptRecv);
REX_EXPORT_STUB(__imp__NetDll_XnpEthernetInterceptSetCallbacks);
REX_EXPORT_STUB(__imp__NetDll_XnpEthernetInterceptSetExtendedReceiveCallback);
REX_EXPORT_STUB(__imp__NetDll_XnpEthernetInterceptXmit);
REX_EXPORT_STUB(__imp__NetDll_XnpEthernetInterceptXmitAsIp);
REX_EXPORT_STUB(__imp__NetDll_XnpGetActiveSocketList);
REX_EXPORT_STUB(__imp__NetDll_XnpGetConfigStatus);
REX_EXPORT_STUB(__imp__NetDll_XnpGetKeyList);
REX_EXPORT_STUB(__imp__NetDll_XnpGetQosLookupList);
REX_EXPORT_STUB(__imp__NetDll_XnpGetSecAssocList);
REX_EXPORT_STUB(__imp__NetDll_XnpGetVlanXboxName);
REX_EXPORT_STUB(__imp__NetDll_XnpLoadConfigParams);
REX_EXPORT_STUB(__imp__NetDll_XnpLoadMachineAccount);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonClearChallenge);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonClearQEvent);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonGetChallenge);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonGetQFlags);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonGetQVals);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonGetStatus);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonSetChallengeResponse);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonSetPState);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonSetQEvent);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonSetQFlags);
REX_EXPORT_STUB(__imp__NetDll_XnpLogonSetQVals);
REX_EXPORT_STUB(__imp__NetDll_XnpNoteSystemTime);
REX_EXPORT_STUB(__imp__NetDll_XnpPersistTitleState);
REX_EXPORT_STUB(__imp__NetDll_XnpQosHistoryGetAggregateMeasurement);
REX_EXPORT_STUB(__imp__NetDll_XnpQosHistoryGetEntries);
REX_EXPORT_STUB(__imp__NetDll_XnpQosHistoryLoad);
REX_EXPORT_STUB(__imp__NetDll_XnpQosHistorySaveMeasurements);
REX_EXPORT_STUB(__imp__NetDll_XnpRegisterKeyForCallerType);
REX_EXPORT_STUB(__imp__NetDll_XnpReplaceKeyForCallerType);
REX_EXPORT_STUB(__imp__NetDll_XnpSaveConfigParams);
REX_EXPORT_STUB(__imp__NetDll_XnpSaveMachineAccount);
REX_EXPORT_STUB(__imp__NetDll_XnpSetVlanXboxName);
REX_EXPORT_STUB(__imp__NetDll_XnpToolIpProxyInject);
REX_EXPORT_STUB(__imp__NetDll_XnpToolSetCallbacks);
REX_EXPORT_STUB(__imp__NetDll_XnpUnregisterKeyForCallerType);
REX_EXPORT_STUB(__imp__NetDll_XnpUpdateConfigParams);
REX_EXPORT_STUB(__imp__NetDll_getpeername);
REX_EXPORT(__imp__NetDll_getsockname, rex::kernel::xam::NetDll_getsockname_entry)
