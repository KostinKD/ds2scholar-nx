/**
 ******************************************************************************
 * Xenia : Xbox 360 Emulator Research Project                                 *
 ******************************************************************************
 * Copyright 2021 Ben Vanik. All rights reserved.                             *
 * Released under the BSD license - see LICENSE in the root for more details. *
 ******************************************************************************
 *
 * @modified    Tom Clay, 2026 - Adapted for ReXGlue runtime
 */

#include <rex/kernel/xam/apps/xlivebase_app.h>
#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/string.h>
#include <rex/thread.h>
#include <rex/kernel/xam/user_lookup.h>
#include <rex/system/xam/user_profile.h>

#include <algorithm>
#include <chrono>
#include <map>
#include <mutex>
#include <random>
#include <string>
#include <vector>

#include <fmt/format.h>
#include <rex/platform.h>

#if REX_PLATFORM_WIN32
// After the rex headers, which bring in windows.h (as in xam_net.cpp).
#include <winsock2.h>  // NOLINT(build/include_order)
#include <ws2tcpip.h>  // inet_pton
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace rex {
namespace kernel {
namespace xam {
using namespace rex::system;
using namespace rex::system::xam;
REXCVAR_DECLARE(bool, net_online_probe);  // xam_net.cpp (online recon)
REXCVAR_DECLARE(bool, net_p2p_diagnostics);
REXCVAR_DEFINE_BOOL(net_user_name_lookup, false, "Net",
                    "Resolve XUserFindUsers through the local profile and an explicit XUID/gamertag directory");
REXCVAR_DEFINE_STRING(net_user_name_directory, "", "Net",
                      "net_user_name_lookup: semicolon-separated hexadecimal XUID=gamertag entries");
REXCVAR_DEFINE_BOOL(net_name_service, false, "Net",
                    "net_user_name_lookup: ask the online server (net_dns_address, net_name_service_port) for "
                    "gamertags of XUIDs not in net_user_name_directory; unknown ones get Player-XXXX");
REXCVAR_DEFINE_UINT32(net_name_service_port, 1000, "Net", "net_name_service: UDP port (the X360 login port)");
REXCVAR_DEFINE_UINT32(net_name_service_timeout_ms, 250, "Net",
                      "net_name_service: longest wait for the server, once per new XUID batch (cached after)");
REXCVAR_DECLARE(std::string, net_dns_address);
uint32_t ServerAddress();  // xam_net.cpp: net_dns_address as an IPv4 address (a host name resolved), network order
namespace {

// net_name_service: XUID -> gamertag from the server, with the time it was learnt (empty = unknown).
struct CachedName {
  std::string gamertag;
  std::chrono::steady_clock::time_point when;
};
std::mutex g_name_mutex;
std::map<uint64_t, CachedName> g_name_cache;

bool Fresh(const CachedName& entry, std::chrono::steady_clock::time_point now) {
  // Known names are kept for 10 minutes (a player can rename), unknown ones are asked again after 30 s.
  return now - entry.when < (entry.gamertag.empty() ? std::chrono::seconds(30) : std::chrono::minutes(10));
}

// One request/reply with the server; false on any failure (the caller falls back to Player-XXXX).
bool AskServer(const std::vector<uint64_t>& xuids, std::vector<names::User>& reply_names) {
  const uint32_t port = REXCVAR_GET(net_name_service_port);
  sockaddr_in server{};
  server.sin_family = AF_INET;
  server.sin_port = htons(uint16_t(port));
  server.sin_addr.s_addr = ServerAddress();
  if (port == 0 || port > 65535 || server.sin_addr.s_addr == INADDR_NONE) return false;
  uint32_t nonce = 0;
  {
    std::random_device random;
    nonce = random();
  }
  const auto request = names::BuildServiceRequest(xuids, nonce);
  if (request.empty()) return false;
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
  if (s == invalid) return false;
  bool ok = false;
  if (sendto(s, reinterpret_cast<const char*>(request.data()), int(request.size()), 0,
             reinterpret_cast<const sockaddr*>(&server), sizeof(server)) == int(request.size())) {
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::milliseconds(std::min<uint32_t>(REXCVAR_GET(net_name_service_timeout_ms), 2000));
    std::vector<uint8_t> buffer(512);
    while (!ok) {
      const auto left = std::chrono::duration_cast<std::chrono::microseconds>(deadline - std::chrono::steady_clock::now());
      if (left.count() <= 0) break;
      fd_set read_set;
      FD_ZERO(&read_set);
      FD_SET(s, &read_set);
      timeval wait{long(left.count() / 1000000), long(left.count() % 1000000)};
      if (select(int(s) + 1, &read_set, nullptr, nullptr, &wait) <= 0) break;
      sockaddr_in from{};
#if REX_PLATFORM_WIN32
      int from_size = sizeof(from);
#else
      socklen_t from_size = sizeof(from);
#endif
      const int got = recvfrom(s, reinterpret_cast<char*>(buffer.data()), int(buffer.size()), 0,
                               reinterpret_cast<sockaddr*>(&from), &from_size);
      if (got <= 0) break;
      // Anything else (another sender, an old reply) is ignored until the deadline.
      ok = from.sin_addr.s_addr == server.sin_addr.s_addr && from.sin_port == server.sin_port &&
           names::ParseServiceReply({buffer.data(), size_t(got)}, nonce, xuids, reply_names);
    }
  }
  close_socket(s);
  return ok;
}

// Gamertags for the XUIDs of a lookup that the static directory does not know: cached server names, one server
// request for the missing ones, Player-XXXX for whatever stays unknown.
std::vector<names::User> ServiceNames(const std::vector<uint64_t>& xuids) {
  std::vector<names::User> result;
  std::vector<uint64_t> missing;
  const auto now = std::chrono::steady_clock::now();
  {
    std::lock_guard lock(g_name_mutex);
    for (const auto xuid : xuids) {
      const auto found = g_name_cache.find(xuid);
      if (found == g_name_cache.end() || !Fresh(found->second, now)) {
        if (missing.size() < names::kServiceMaxCount) missing.push_back(xuid);
      }
    }
  }
  if (!missing.empty()) {
    std::vector<names::User> answered;
    const bool ok = AskServer(missing, answered);
    std::lock_guard lock(g_name_mutex);
    if (ok) {
      for (const auto& user : answered) g_name_cache[user.xuid] = {user.gamertag, now};
    }
    REXLOG_INFO("[user-lookup] server names: asked {}, {}", missing.size(),
                ok ? fmt::format("answered {} known", std::count_if(answered.begin(), answered.end(),
                                                                    [](const auto& u) { return !u.gamertag.empty(); }))
                   : std::string("no answer"));
  }
  std::lock_guard lock(g_name_mutex);
  for (const auto xuid : xuids) {
    const auto found = g_name_cache.find(xuid);
    if (found != g_name_cache.end() && !found->second.gamertag.empty()) {
      result.push_back({xuid, found->second.gamertag});
    } else {
      result.push_back({xuid, names::FallbackName(xuid)});
    }
  }
  return result;
}

}  // namespace

namespace apps {
using namespace rex::system;

XLiveBaseApp::XLiveBaseApp(KernelState* kernel_state) : App(kernel_state, 0xFC) {}

// http://mb.mirage.org/bugzilla/xliveless/main.c

X_HRESULT XLiveBaseApp::DispatchMessageSync(uint32_t message, uint32_t buffer_ptr,
                                            uint32_t buffer_length) {
  // NOTE: buffer_length may be zero or valid.
  auto buffer = memory_->TranslateVirtual(buffer_ptr);
  const auto valid_range = [this](uint32_t address, uint32_t size, bool write) {
    if (!address || !size || address > UINT32_MAX - (size - 1)) return false;
    auto* heap = memory_->LookupHeap(address);
    if (!heap || heap != memory_->LookupHeap(address + size - 1)) return false;
    const auto access = uint32_t(heap->QueryRangeAccess(address, address + size - 1));
    const uint32_t required = write ? 3 : 1;
    return (access & required) == required;
  };
  if (REXCVAR_GET(net_user_name_lookup) && message == 0x58017) {
    // SotFS826B06D0/826B0784 passes two output words before XUserFindUsers.
    // BASE_MSG_HEADER is32 bytes; the old error aborts the request before dispatch.
    if (buffer_length || !valid_range(buffer_ptr, 8, true)) return X_E_INVALIDARG;
    memory::store_and_swap<uint32_t>(buffer, 0);
    memory::store_and_swap<uint32_t>(buffer + 4, 32);
    return X_E_SUCCESS;
  }
  if (REXCVAR_GET(net_user_name_lookup) && message == 0x0005000E &&
      buffer_length == 40 && valid_range(buffer_ptr, 40, false)) {
    const auto task = memory::load_and_swap<uint32_t>(buffer);
    if (valid_range(task, 76, false)) {
      const auto ordinal = memory::load_and_swap<uint32_t>(memory_->TranslateVirtual(task));
      if (ordinal == 2563) {  // SotFS826B06D0: XUserFindUsers ordinal0xA03.
        const auto* args = memory_->TranslateVirtual(task);
        const auto request = memory::load_and_swap<uint32_t>(args + 24);
        const auto request_size = memory::load_and_swap<uint32_t>(args + 28);
        const auto output = memory::load_and_swap<uint32_t>(args + 44);
        const auto output_size = memory::load_and_swap<uint32_t>(args + 48);
        if (request_size > 65536 || output_size > 65536 ||
            !valid_range(request, request_size, false) || !valid_range(output, output_size, true))
          return X_E_INVALIDARG;
        auto directory = names::ParseDirectory(REXCVAR_GET(net_user_name_directory));
        const auto& profile = kernel_state_->user_profile();
        directory.push_back({profile->xuid(), profile->name()});
        if (REXCVAR_GET(net_name_service)) {
          // Only XUIDs the static directory does not name: two entries for one XUID would make it ambiguous.
          std::vector<uint64_t> unknown;
          for (const auto xuid : names::RequestedXuids(
                   {memory_->TranslateVirtual<const uint8_t*>(request), request_size})) {
            if (std::none_of(directory.begin(), directory.end(), [&](const auto& u) { return u.xuid == xuid; }))
              unknown.push_back(xuid);
          }
          if (!unknown.empty()) {
            const auto served = ServiceNames(unknown);
            directory.insert(directory.end(), served.begin(), served.end());
          }
        }
        const auto result = names::Resolve(
            {memory_->TranslateVirtual<const uint8_t*>(request), request_size},
            {memory_->TranslateVirtual<uint8_t*>(output), output_size}, output, directory);
        REXLOG_INFO("[user-lookup] message={:08X} ordinal={} request={:08X}/{} output={:08X}/{} status={} count={}",
                    message, ordinal, request, request_size, output, output_size, int(result),
                    result == names::Status::Success ? memory::load_and_swap<uint32_t>(memory_->TranslateVirtual(output)) : 0);
        if (result == names::Status::Success) return X_E_SUCCESS;
        if (result == names::Status::InsufficientBuffer) return 0x8007007A;  // HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER)
        std::string bytes;
        const auto* data = memory_->TranslateVirtual<const uint8_t*>(request);
        for (uint32_t i = 0; i < std::min(request_size, 96u); ++i) bytes += fmt::format("{:02X}", data[i]);
        REXLOG_WARN("[user-lookup] unsupported request layout: {}", bytes);
        return X_E_INVALIDARG;
      }
    }
  }
  if (message == 0x00058017 && REXCVAR_GET(net_p2p_diagnostics) && buffer_ptr &&
      memory_->LookupHeap(buffer_ptr) && memory_->LookupHeap(buffer_ptr + 31)) {
    std::string bytes;
    for (size_t i = 0; i < 32; ++i) bytes += fmt::format("{:02X}", buffer[i]);
    REXLOG_INFO("[p2p] Live58017 args@{:08X} arg2={:08X} first32={}", buffer_ptr, buffer_length, bytes);
  }
  switch (message) {
    case 0x00058004: {
      // Called on startup, seems to just return a bool in the buffer.
      assert_true(!buffer_length || buffer_length == 4);
      REXKRNL_DEBUG("XLiveBaseGetLogonId({:08X})", buffer_ptr);
      memory::store_and_swap<uint32_t>(buffer + 0, 1);  // ?
      return X_E_SUCCESS;
    }
    case 0x00058006: {
      assert_true(!buffer_length || buffer_length == 4);
      REXKRNL_DEBUG("XLiveBaseGetNatType({:08X})", buffer_ptr);
      memory::store_and_swap<uint32_t>(buffer + 0, 1);  // XONLINE_NAT_OPEN
      return X_E_SUCCESS;
    }
    case 0x00058007: {
      // Occurs if title calls XOnlineGetServiceInfo, expects dwServiceId
      // and pServiceInfo. pServiceInfo should contain pointer to
      // XONLINE_SERVICE_INFO structure.
      REXKRNL_DEBUG("CXLiveLogon::GetServiceInfo({:08X}, {:08X})", buffer_ptr, buffer_length);
      return 0x80151802;  // ERROR_CONNECTION_INVALID
    }
    case 0x00058020: {
      // 0x00058004 is called right before this.
      // We should create a XamEnumerate-able empty list here, but I'm not
      // sure of the format.
      // buffer_length seems to be the same ptr sent to 0x00058004.
      REXKRNL_DEBUG("CXLiveFriends::Enumerate({:08X}, {:08X}) unimplemented", buffer_ptr,
                    buffer_length);
      return X_E_FAIL;
    }
    case 0x00058023: {
      REXKRNL_DEBUG(
          "CXLiveMessaging::XMessageGameInviteGetAcceptedInfo({:08X}, {:08X}) "
          "unimplemented",
          buffer_ptr, buffer_length);
      return X_E_FAIL;
    }
    case 0x00058046: {
      // Required to be successful for 4D530910 to detect signed-in profile
      // Doesn't seem to set anything in the given buffer, probably only takes
      // input
      REXKRNL_DEBUG("XLiveBaseUnk58046({:08X}, {:08X}) unimplemented", buffer_ptr, buffer_length);
      return X_E_SUCCESS;
    }
    case 0x00058037: {
      REXKRNL_DEBUG("XPresenceInitialize({:08X}, {:08X})", buffer_ptr, buffer_length);
      return X_E_SUCCESS;
    }
    case 0x00058035: {
      // ds2-nx (2026-10-20, online recon, net_online_probe only): XStorageBuildServerPath. Layout read from Dark Souls
      // II's call: +0 user index, +8 XUID, +16 storage facility (2 = per title), +20/+24 facility info pointer/size,
      // +28 item name (UTF-16), +32 server path out (UTF-16), +36 its length in characters (in: capacity).
      if (!REXCVAR_GET(net_online_probe)) break;
      const uint32_t facility = memory::load_and_swap<uint32_t>(buffer + 16);
      const uint32_t name_ptr = memory::load_and_swap<uint32_t>(buffer + 28);
      const uint32_t path_ptr = memory::load_and_swap<uint32_t>(buffer + 32);
      const uint32_t length_ptr = memory::load_and_swap<uint32_t>(buffer + 36);
      std::u16string name;
      if (name_ptr) name = memory::load_and_swap<std::u16string>(memory_->TranslateVirtual(name_ptr));
      const std::string path = "/title/465307E4/" + rex::string::to_utf8(name);
      const uint32_t capacity = length_ptr ? memory::load_and_swap<uint32_t>(memory_->TranslateVirtual(length_ptr)) : 0;
      REXLOG_INFO("[net] XStorageBuildServerPath facility {} item '{}' -> '{}' (capacity {})", facility,
                  rex::string::to_utf8(name), path, capacity);
      if (path_ptr && capacity > path.size()) {
        auto* out = memory_->TranslateVirtual(path_ptr);
        for (size_t i = 0; i <= path.size(); ++i)
          memory::store_and_swap<uint16_t>(out + i * 2, i < path.size() ? uint16_t(path[i]) : 0);
      }
      if (length_ptr)
        memory::store_and_swap<uint32_t>(memory_->TranslateVirtual(length_ptr), uint32_t(path.size() + 1));
      return X_E_SUCCESS;
    }
    case 0x0005000A: {
      // ds2-nx (online recon): XStorageEnumerate. Arguments marshalled behind the first word (not decoded yet):
      // answered as success with nothing written, i.e. whatever results the game cleared stay empty.
      if (!REXCVAR_GET(net_online_probe)) break;
      REXLOG_INFO("[net] XStorageEnumerate({:08X}, {}) -> success, nothing written", buffer_ptr, buffer_length);
      return X_E_SUCCESS;
    }
    case 0x00050009: {
      // ds2-nx (online recon): XStorageDownloadToMemory. No title storage behind it: the file is not there.
      if (!REXCVAR_GET(net_online_probe)) break;
      REXLOG_INFO("[net] XStorageDownloadToMemory({:08X}, {}) -> not found", buffer_ptr, buffer_length);
      return X_E_FAIL;
    }
  }
  REXKRNL_ERROR(
      "Unimplemented XLIVEBASE message app={:08X}, msg={:08X}, arg1={:08X}, "
      "arg2={:08X}",
      app_id(), message, buffer_ptr, buffer_length);
  return X_E_FAIL;
}

}  // namespace apps
}  // namespace xam
}  // namespace kernel
}  // namespace rex
