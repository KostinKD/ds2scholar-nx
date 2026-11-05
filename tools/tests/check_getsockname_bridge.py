"""Exercise the actual getsockname bridge with a real Windows UDP socket.

Kernel objects/pointers are test doubles; the entry body is extracted verbatim.
This verifies ABI bytes and errors, not the game's session handshake.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'out/bot_pair/getsockname_test'
OUT.mkdir(parents=True, exist_ok=True)


def entry(text):
    start = text.index('u32 NetDll_getsockname_entry(')
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


PREAMBLE = r'''
#include <winsock2.h>
#include <cstdint>
#include <cstring>
#include <memory>
#include <cassert>
#include <cstdio>
#define REX_PLATFORM_WIN32 1
#define REXCVAR_GET(name) name
#define REXKRNL_WARN(...) ((void)0)
#define REXLOG_INFO(...) ((void)0)
#include <optional>
#include <array>
namespace lan {
  using Address = std::array<uint8_t, 36>;
  using IP = std::array<uint8_t, 4>;
  inline std::optional<IP> PeerIP(const Address&) { return std::nullopt; }
}
inline uint32_t LanIPValue(const lan::IP&) { return 0; }
inline std::optional<lan::Address> LocalLanAddress() { return std::nullopt; }
using u32 = uint32_t;
bool net_p2p_lan = true;
template<class T> struct BE {
  uint8_t bytes[sizeof(T)]{};
  operator T() const { T value=0; for(auto b:bytes) value=T((value<<8)|b); return value; }
  BE& operator=(T value) { for(int i=int(sizeof(T))-1;i>=0;--i) { bytes[i]=uint8_t(value); value>>=8; } return *this; }
};
struct XSOCKADDR_IN { BE<uint16_t> sin_family, sin_port; BE<uint32_t> sin_addr; char x_sin_zero[8]; };
static_assert(sizeof(XSOCKADDR_IN)==16);
template<class T> using ppc_ptr_t = T*;
using mapped_u32 = BE<uint32_t>*;
SOCKET active_socket;
struct XSocket { uint64_t native_handle() const { return active_socket; } };
struct Table {
  template<class T> std::shared_ptr<T> LookupObject(u32 h) { return h==1 ? std::make_shared<T>() : nullptr; }
} table;
#define REX_KERNEL_OBJECTS() (&table)
struct XThread { inline static uint32_t error; static void SetLastError(uint32_t e) { error=e; } };
'''

MAIN = r'''
int main() {
  WSADATA data{};
  assert(WSAStartup(MAKEWORD(2,2), &data)==0);
  active_socket=socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  assert(active_socket!=INVALID_SOCKET);
  sockaddr_in local{};
  local.sin_family=AF_INET;
  local.sin_addr.s_addr=htonl(0x7F000002);
  assert(bind(active_socket,reinterpret_cast<sockaddr*>(&local),sizeof(local))==0);
  int length=sizeof(local);
  assert(getsockname(active_socket,reinterpret_cast<sockaddr*>(&local),&length)==0);
  XSOCKADDR_IN guest{};
  BE<uint32_t> size{}; size=16;
  assert(NetDll_getsockname_entry(1,1,&guest,&size)==0);
  assert(uint16_t(guest.sin_family)==AF_INET);
  assert(uint16_t(guest.sin_port)==ntohs(local.sin_port) && uint16_t(guest.sin_port)!=0);
  assert(uint32_t(guest.sin_addr)==0x7F000002 && uint32_t(size)==16);
  assert(guest.sin_family.bytes[0]==0 && guest.sin_family.bytes[1]==2);
  assert(std::memcmp(guest.sin_port.bytes,&local.sin_port,2)==0);
  for(char b:guest.x_sin_zero) assert(b==0);
  size=15;
  assert(NetDll_getsockname_entry(1,1,&guest,&size)==uint32_t(-1) && XThread::error==10014);
  size=16;
  assert(NetDll_getsockname_entry(1,0,&guest,&size)==uint32_t(-1) && XThread::error==10038);
  assert(NetDll_getsockname_entry(1,1,nullptr,&size)==uint32_t(-1) && XThread::error==10014);
  assert(NetDll_getsockname_entry(1,1,&guest,nullptr)==uint32_t(-1) && XThread::error==10014);
  net_p2p_lan=false;
  std::memset(&guest,0xA5,sizeof(guest)); size=11;
  assert(NetDll_getsockname_entry(7,1,&guest,&size)==7 && uint32_t(size)==11);
  for(auto b:reinterpret_cast<const unsigned char(&)[16]>(guest)) assert(b==0xA5);
  closesocket(active_socket); WSACleanup();
  std::puts("PASS: actual UDP address/port, guest byte order, padding, invalid handles/pointers/length, default-off");
}
'''

source = (ROOT / 'sdk/src/kernel/xam/xam_net.cpp').read_text(encoding='utf-8')
cpp = OUT / 'getsockname.cpp'
exe = OUT / 'getsockname.exe'
cpp.write_text(PREAMBLE + entry(source) + MAIN, encoding='utf-8')
subprocess.run(['clang++', '-std=c++20', str(cpp), '-lws2_32', '-o', str(exe)], check=True)
subprocess.run([str(exe)], check=True)
