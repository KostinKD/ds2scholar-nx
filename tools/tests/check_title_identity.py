"""Compile the actual title-address entry; verify identity consistency and opt-out."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'out/bot_pair/title_identity_test'
OUT.mkdir(parents=True, exist_ok=True)
source = (ROOT / 'sdk/src/kernel/xam/xam_net.cpp').read_text(encoding='utf-8')
start = source.index('u32 NetDll_XNetGetTitleXnAddr_entry(')
end = source.index('\nu32 NetDll_XNetGetDebugXnAddr_entry', start)
status = source[source.index('struct XnAddrStatus'):start]
preamble = r'''
#define _WINSOCK_DEPRECATED_NO_WARNINGS
#include <winsock2.h>
#undef s_addr
#include <array>
#include <optional>
#include <cstring>
#include <cassert>
#include <string>
#include <cstdio>
using u32=uint32_t;
#define REXCVAR_GET(x) x
#define REXLOG_INFO(...) ((void)0)
bool net_p2p_lan=false, net_p2p_title_identity=false, net_online_probe=true;
std::string net_dns_address="127.0.0.1";
struct XNADDR { struct {uint32_t s_addr;} ina,inaOnline; uint16_t wPortOnline; uint8_t abEnet[6],abOnline[20]; };
static_assert(sizeof(XNADDR)==36);
template<class T> struct ppc_ptr_t { T* ptr; T* operator->() const {return ptr;} explicit operator bool() const {return ptr;} void* host_address()const{return ptr;} };
std::array<uint8_t,36> local{};
std::optional<std::array<uint8_t,36>> LocalLanAddress(){return local;}
'''
main = r'''
int main(){
 XNADDR a{},legacy{};
 assert(NetDll_XNetGetTitleXnAddr_entry(1,{&legacy})==0xE6);
 for(int i=0;i<36;++i)local[i]=uint8_t(i+1);
 net_p2p_lan=true;
 NetDll_XNetGetTitleXnAddr_entry(1,{&a});
 assert(std::memcmp(&a,&legacy,36)==0);
 net_p2p_title_identity=true;
 assert(NetDll_XNetGetTitleXnAddr_entry(1,{&a})==0xE6);
 assert(std::memcmp(&a,local.data(),16)==0);
 for(auto b:a.abOnline)assert(b==0);
 net_p2p_lan=false;
 NetDll_XNetGetTitleXnAddr_entry(1,{&a});
 assert(std::memcmp(&a,&legacy,36)==0);
 puts("PASS: LAN title IP/port/MAC, zero online token, both opt-in flags required");
}
'''
cpp=OUT/'title.cpp'
exe=OUT/'title.exe'
cpp.write_text(preamble+status+source[start:end]+main,encoding='utf-8')
subprocess.run(['clang++','-std=c++20',str(cpp),'-lws2_32','-o',str(exe)],check=True)
subprocess.run([str(exe)],check=True)
