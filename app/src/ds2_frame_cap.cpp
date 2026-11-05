// ds2-nx: 30 fps with even frame pacing (stage 5, 2026-10-20, journal entry 64).
//
// At the owner's clocks (CPU 1785 / GPU 921.6 / memory 2133, handheld, 720p) the game runs 29.7-34.3 fps, median
// 33.5 (entry 63): frames land on the 60 Hz grid as a mix of one and two vblanks, and the game's own frame time
// wanders with them. Dark Souls II ran at 30 on the Xbox 360. With the presentation interval at 2 vblanks every frame
// is shown for 33.3 ms, the swapchain throttles the game to that rate, and the time saved is GPU headroom for heavier
// scenes.
// The mechanism is the SDK's: RexSwitchPerfIntervalSwap sets nwindowSetSwapInterval on every queued buffer
// (sdk/src/ui/switch_perf.cpp, next to the nwindowQueueBuffer wrapper). Its warning holds: with a median frame time
// above ~31 ms (stock clocks, ~20 fps) a frame that misses 33.3 ms waits for the third vblank, so it is off by default.
#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/platform.h>

#if REX_PLATFORM_SWITCH
extern "C" void RexSwitchPerfIntervalSwap(unsigned vblanks);
#endif

REXCVAR_DEFINE_BOOL(ds2_frame_cap_30, false, "DS2",
                    "Switch: present every frame for two vblanks (30 fps, even pacing). For raised clocks where the "
                    "game runs above 30; at stock clocks a missed frame waits a third vblank. false = as before");

namespace ds2 {

void ApplyFrameCap() {
#if REX_PLATFORM_SWITCH
  if (!REXCVAR_GET(ds2_frame_cap_30)) return;
  REXLOG_INFO("ds2_frame_cap_30: presentation interval 2 vblanks (30 fps)");
  RexSwitchPerfIntervalSwap(2);
#endif
}

}  // namespace ds2
