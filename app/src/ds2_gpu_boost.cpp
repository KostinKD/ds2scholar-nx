// ds2-nx: the handheld GPU profile (from sa2-nx's src/cpu/sa2_gpu_boost.cpp; nfsmw-nx does the same).
//
// Stage 5, frame rate (2026-10-17): the console is GPU-bound at the Things Betwixt bonfire (GPU ~105 ms per frame,
// 9 fps) and runs the stock handheld GPU clock, 307.2 MHz: sa2-nx and nfsmw-nx ask the performance manager for the
// official handheld configuration 0x92220008 (GPU 460.8 MHz, memory 1331.2 MHz), ds2 never did. The SDK's
// switch_apm.cpp checks with the real clocks for 1.5 s that the memory clock did not move and reverts if it did;
// docked, nothing is requested. What it did goes to rex_stderr.log ("[apm] ...").
// A clock, not a setting: the same frames are drawn, sooner. More power draw in handheld mode.
#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/platform.h>

#if REX_PLATFORM_SWITCH
extern "C" {
void RexSwitchApmRequestGpuMhz(int mhz);
void RexSwitchApmKeepHigher(int keep);
void RexSwitchClocksHoldEnable(int enabled);
void RexSwitchApmApply(void);
}
#endif

REXCVAR_DEFINE_BOOL(ds2_gpu_boost, true, "DS2",
                    "Switch, handheld: ask for the official 460.8 MHz GPU profile 0x92220008 (memory clock checked "
                    "unchanged, else reverted). false = the stock 307.2 MHz, as before 2026-10-17");

// ds2scholar-nx (2026-10-24): console with an overclock (GPU already 921.6 MHz): the requested 0x92220008 changed
// nothing at start, but after the HOME menu the system restored it at stock clocks (CPU 1020, GPU 460.8 MHz) and the
// game stayed at 18-25 fps.
REXCVAR_DEFINE_BOOL(ds2_gpu_boost_keep_higher, false, "DS2",
                    "ds2_gpu_boost: request nothing when the GPU already runs at 460.8 MHz or above (an overclock), so "
                    "the console keeps its own configuration after the HOME menu. false = always request, as before");

// ds2scholar-nx (2026-10-24, ds2_079): with ds2_gpu_boost_keep_higher the port asked apm for nothing, and the clocks
// still came back at stock after HOME (CPU 1020, GPU 307.2): the overclock sysmodule stops applying its profile.
REXCVAR_DEFINE_BOOL(ds2_clocks_hold_after_home, false, "DS2",
                    "Switch: if the CPU or GPU clock falls below the one seen at the start of play (after the HOME "
                    "menu), ask the clock sysmodule (sys-clk / Horizon OC) to override them back; released on exit or "
                    "on a dock change. false = leave the clocks to the system, as before");

namespace ds2 {

void ApplyGpuBoost() {
#if REX_PLATFORM_SWITCH
  RexSwitchClocksHoldEnable(REXCVAR_GET(ds2_clocks_hold_after_home) ? 1 : 0);
  if (!REXCVAR_GET(ds2_gpu_boost)) return;
  REXLOG_INFO("ds2_gpu_boost: requesting the 460.8 MHz handheld GPU profile (result in rex_stderr.log)");
  RexSwitchApmRequestGpuMhz(460);
  RexSwitchApmKeepHigher(REXCVAR_GET(ds2_gpu_boost_keep_higher) ? 1 : 0);
  RexSwitchApmApply();
#endif
}

}  // namespace ds2
