"""Compile the real opt-in repair body and verify its eligibility boundaries.

Uses real big-endian guest-memory layouts in a reserved Windows arena. The game
string constructor is a recording substitute; actual constructor/handshake behavior
is separately exercised by online_pair, not asserted by this test. The fixture
context contains r3/r4 only; wrapper forwarding and hook installation are not
covered by this unit harness.
"""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'sdk/src/kernel/xam/xam_net.cpp').read_text(encoding='utf-8')
body = re.search(r'static void ProbeSotfsSummonName\(.*?\n\}', source, re.S)
assert body, 'real repair function not found'
folder = ROOT / 'out/bot_pair/name_probe_test'
folder.mkdir(parents=True, exist_ok=True)
prefix = r'''
#include <windows.h>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <type_traits>
union Reg { uint64_t u64; uint32_t u32; };
struct PPCContext { Reg r3{}, r4{}; };
using PPCFunc = void(PPCContext&, uint8_t*);
bool net_p2p_summon_name_probe = false, net_p2p_lan = false;
uint64_t net_p2p_peer_xuid = 0;
#define REXCVAR_GET(name) (name)
#define REXLOG_INFO(...) ((void)0)
namespace memory {
template<class T> T load_and_swap(const uint8_t* p) {
  T result = 0;
  for (size_t i=0; i<sizeof(T); ++i) result = (result<<8)|p[i];
  return result;
}
}
static void put(uint8_t* base, uint32_t a, uint32_t value) {
  for (int i=3; i>=0; --i) { base[a+i]=uint8_t(value); value>>=8; }
}
static unsigned copies = 0;
static void CopyName(PPCContext& ctx, uint8_t* base) {
  ++copies;
  assert(ctx.r4.u32 == 0x14000);
  const auto a = ctx.r3.u32;
  const uint8_t name[]{0, 'U', 0, 's', 0, 'e', 0, 'r', 0, 0};
  memcpy(base+a, name, sizeof(name));
  put(base,a+16,4);
  ctx.r3.u64 = 0xDEADBEEF; // Must not escape into the incoming message context.
  ctx.r4.u64 = 0xDEADBEEF;
}
struct Dispatcher {
  bool missing = false;
  PPCFunc* GetFunction(uint32_t a) {
    assert(a == 0x8296B778);
    return missing ? nullptr : CopyName;
  }
} dispatcher;
struct Kernel { Dispatcher* function_dispatcher() { return &dispatcher; } } kernel;
#define REX_KERNEL_STATE() (&kernel)
'''
suffix = r'''
int main() {
  auto* base = static_cast<uint8_t*>(VirtualAlloc(nullptr, SIZE_T(1)<<32, MEM_RESERVE, PAGE_NOACCESS));
  assert(base);
  assert(VirtualAlloc(base+0x10000,0x6000,MEM_COMMIT,PAGE_READWRITE));
  assert(VirtualAlloc(base+0x834AB000,0x1000,MEM_COMMIT,PAGE_READWRITE));
  const uint64_t peer = 0xB13EBABEBABEBAC1;
  PPCContext ctx{}; ctx.r3.u64=0x11223344; ctx.r4.u64=4;
  const auto saved = ctx;
  auto reset = [&] {
    memset(base+0x10000,0,0x6000);
    put(base,0x834ABB44,0x10000); put(base,0x1000C,0x11000);
    put(base,0x11020,0x12000);
    put(base,0x12000,0x82014768); put(base,0x12050,7);
    put(base,0x13000,0x82064C24);
    put(base,0x13030,uint32_t(peer>>32)); put(base,0x13034,uint32_t(peer));
    copies=0; dispatcher.missing=false;
    net_p2p_summon_name_probe=true; net_p2p_lan=true; net_p2p_peer_xuid=peer;
  };
  auto run = [&] {
    ProbeSotfsSummonName(ctx,base,0x14000,0x13000);
    assert(memcmp(&ctx,&saved,sizeof(ctx))==0);
  };
  reset(); net_p2p_summon_name_probe=false; run(); assert(copies==0);
  reset(); net_p2p_lan=false; run(); assert(copies==0);
  reset(); net_p2p_peer_xuid=0; run(); assert(copies==0);
  reset(); net_p2p_peer_xuid=peer+1; run(); assert(copies==0);
  reset(); put(base,0x13000,0x82000000); run(); assert(copies==0);
  reset(); put(base,0x12000,0x82000000); run(); assert(copies==0);
  reset(); put(base,0x1204C,3); run(); assert(copies==0); // Existing name stays intact.
  reset(); put(base,0x12050,15); run(); assert(copies==0); // No allocated-string replacement.
  reset(); dispatcher.missing=true; run(); assert(copies==0);
  reset(); put(base,0x834ABB44,0); run(); assert(copies==0);
  reset(); put(base,0x1000C,0); run(); assert(copies==0);
  reset(); run(); assert(copies==1); assert(memory::load_and_swap<uint32_t>(base+0x1204C)==4);
  reset(); put(base,0x11020,0); put(base,0x11028,0x15000); put(base,0x1102C,0x15004);
  put(base,0x15000,0x12000); run(); assert(copies==1);
  reset(); put(base,0x11028,0x15000); put(base,0x1102C,0x15004);
  put(base,0x15000,0x12000); run(); assert(copies==1); // Duplicate references filled once.
  reset(); put(base,0x11020,0); put(base,0x11028,0x15000); put(base,0x1102C,0x15003);
  run(); assert(copies==0);
  reset(); put(base,0x11020,0); put(base,0x11028,0x15000); put(base,0x1102C,0x15080);
  run(); assert(copies==0);
  reset(); put(base,0x11020,0); put(base,0x11028,0x15004); put(base,0x1102C,0x15000);
  run(); assert(copies==0);
  VirtualFree(base,0,MEM_RELEASE);
  puts("summon-name probe: 17 boundary cases passed; fixture r3/r4 preserved");
}
'''
test = folder / 'probe.cpp'
exe = folder / 'probe.exe'
test.write_text(prefix + body.group(0) + suffix, encoding='utf-8')
subprocess.run(['clang++', '-std=c++20', '-O1', str(test), '-o', str(exe)], check=True)
subprocess.run([str(exe)], check=True)
