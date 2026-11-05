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

#include <rex/kernel/xam/module.h>
#include <rex/kernel/xam/private.h>
#include <algorithm>
#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/hook.h>
#include <rex/types.h>
#include <rex/string.h>
#include <rex/system/kernel_state.h>
#include <rex/system/xenumerator.h>
#include <rex/system/xtypes.h>

#if REX_PLATFORM_WIN32
#include <rex/platform.h>
#endif
// ds2-nx (online recon): inet_addr for the title-server address (net_dns_address).
#if REX_PLATFORM_WIN32
#include <winsock2.h>
#else
#include <arpa/inet.h>
#endif

#include <fmt/format.h>

namespace rex {
namespace kernel {
namespace xam {
using namespace rex::system;
using namespace rex::system::xam;

// https://github.com/LestaD/SourceEngine2007/blob/master/se2007/engine/xboxsystem.cpp#L518
uint32_t xeXamEnumerate(uint32_t handle, uint32_t flags, mapped_void buffer_ptr,
                        uint32_t buffer_size, uint32_t* items_returned, uint32_t overlapped_ptr) {
  assert_true(flags == 0);

  auto e = REX_KERNEL_OBJECTS()->LookupObject<XEnumerator>(handle);
  if (!e) {
    return X_ERROR_INVALID_HANDLE;
  }

  auto run = [e, buffer_ptr](uint32_t& extended_error, uint32_t& length) -> X_RESULT {
    X_RESULT result;
    uint32_t item_count = 0;
    if (!buffer_ptr) {
      result = X_ERROR_INVALID_PARAMETER;
    } else {
      result = e->WriteItems(buffer_ptr.guest_address(), buffer_ptr.as<uint8_t*>(), &item_count);
    }
    extended_error = X_HRESULT_FROM_WIN32(result);
    length = item_count;
    return result;
  };

  if (items_returned) {
    assert_true(!overlapped_ptr);
    uint32_t extended_error;
    uint32_t item_count;
    X_RESULT result = run(extended_error, item_count);
    *items_returned = result == X_ERROR_SUCCESS ? item_count : 0;
    return result;
  } else if (overlapped_ptr) {
    assert_true(!items_returned);
    REX_KERNEL_STATE()->CompleteOverlappedDeferredEx(run, overlapped_ptr);
    return X_ERROR_IO_PENDING;
  } else {
    assert_always();
    return X_ERROR_INVALID_PARAMETER;
  }
}

u32 XamEnumerate_entry(u32 handle, u32 flags, mapped_void buffer, u32 buffer_length,
                       mapped_u32 items_returned, ppc_ptr_t<XAM_OVERLAPPED> overlapped) {
  uint32_t dummy;
  auto result =
      xeXamEnumerate(handle, flags, buffer, buffer_length,
                     !overlapped.guest_address() ? &dummy : nullptr, overlapped.guest_address());
  if (!overlapped && items_returned) {
    *items_returned = dummy;
  }
  return result;
}

REXCVAR_DECLARE(bool, net_online_probe);   // xam_net.cpp (online recon)
REXCVAR_DECLARE(std::string, net_dns_address);
uint32_t ServerAddress();  // xam_net.cpp: net_dns_address as an IPv4 address (a host name resolved), network order

// ds2-nx (2026-10-20, online recon, net_online_probe only): XamCreateEnumeratorHandle(user, app, open message, close
// message, extra size, items, flags, handle out). Dark Souls II's XTitleServerCreateEnumerator (sub_82FD6440) opens
// the Live title-server list (app 0xFC, messages 0x58039 / 0x5803A, 212 bytes of private data) and connects to one of
// the servers at random (sub_82EB9898 / sub_82EB9DC8): one XTITLE_SERVER_INFO (IN_ADDR, flags, 200-char description)
// at net_dns_address. Anything else stays unsupported, as before.
REXCVAR_DEFINE_INT32(net_title_server_count, 4, "Net",
                     "net_online_probe: how many Live title servers (net_dns_address and the next addresses) the game "
                     "gets. 1 for a real server (ds3os-x360); 4 = as before")
    .range(1, 4);

u32 XamCreateEnumeratorHandle_entry(u32 user_index, u32 app_id, u32 open_message, u32 close_message,
                                    u32 extra_size, u32 item_count, u32 flags, mapped_u32 handle_out) {
  if (REXCVAR_GET(net_online_probe) && app_id == 0xFC && open_message == 0x58039 && handle_out) {
    constexpr size_t kTitleServerInfo = 208;
    auto e = make_object<XStaticUntypedEnumerator>(REX_KERNEL_STATE(), item_count ? item_count : 1,
                                                    kTitleServerInfo);
    void* extra = nullptr;
    const auto result = e->Initialize(user_index, app_id, open_message, close_message, flags, extra_size, &extra);
    if (XFAILED(result)) return result;
    // Four servers, net_dns_address and the next three addresses: after RequestQueryLoginServerInfo the game opens
    // its next connection to a title server it has not used yet (sub_82EB9DC8 keeps the used ones in a set at
    // +220 and retries 3 times on a used one), so a single server ends in "service not available".
    // ds2scholar-nx (2026-10-25): with the login reply right (docs/online.md: field 3 = the same port) SotFS continues
    // on the same connection, so one server is enough; a real server answers from one address, and a reply from
    // another address than the game wrote to is taken for a new incoming connection. net_title_server_count.
    const uint32_t first = ntohl(ServerAddress());
    const uint32_t count = uint32_t(std::clamp(REXCVAR_GET(net_title_server_count), 1, 4));
    for (uint32_t k = 0; k < count && k < item_count; ++k) {
      uint8_t* item = e->AppendItem();
      std::memset(item, 0, kTitleServerInfo);
      const uint32_t ina = htonl(first + k);  // network order in memory
      std::memcpy(item + 0, &ina, 4);
      std::snprintf(reinterpret_cast<char*>(item + 8), 200, "%u.%u.%u.%u", (first + k) >> 24, ((first + k) >> 16) & 0xFF,
                    ((first + k) >> 8) & 0xFF, (first + k) & 0xFF);
    }
    *handle_out = e->handle();
    REXLOG_INFO("[net] XTitleServerCreateEnumerator: servers from {} (items {}, extra {})",
                REXCVAR_GET(net_dns_address), item_count, extra_size);
    return X_ERROR_SUCCESS;
  }
  if (REXCVAR_GET(net_online_probe))
    REXLOG_INFO("[net] XamCreateEnumeratorHandle app {:08X} open {:08X} close {:08X}: unsupported", app_id,
                open_message, close_message);
  return X_ERROR_INVALID_PARAMETER;
}

u32 XamGetPrivateEnumStructureFromHandle_entry(u32 handle, mapped_u32 out_object_ptr) {
  auto e = REX_KERNEL_OBJECTS()->LookupObject<XEnumerator>(handle);
  if (!e) {
    return X_STATUS_INVALID_HANDLE;
  }

  // Caller takes the reference.
  // It's released in ObDereferenceObject.
  e->RetainHandle();

  if (out_object_ptr.guest_address()) {
    *out_object_ptr = e->guest_object();
  }

  return X_STATUS_SUCCESS;
}

}  // namespace xam
}  // namespace kernel
}  // namespace rex

REX_EXPORT(__imp__XamEnumerate, rex::kernel::xam::XamEnumerate_entry)
REX_EXPORT(__imp__XamCreateEnumeratorHandle, rex::kernel::xam::XamCreateEnumeratorHandle_entry)
REX_EXPORT(__imp__XamGetPrivateEnumStructureFromHandle,
           rex::kernel::xam::XamGetPrivateEnumStructureFromHandle_entry)
