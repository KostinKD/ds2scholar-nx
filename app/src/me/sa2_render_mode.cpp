// Sonic Adventure 2: render resolution per console mode and MSAA (see sa2_render_mode.h).
#include "sa2_render_mode.h"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <string>

#include <fmt/format.h>

#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/platform.h>
#include <rex/ui/keybinds.h>
#include <rex/ui/switch_saltynx.h>

#include "cpu/sa2_enhancements.h"

#if REX_PLATFORM_SWITCH
#include <switch.h>
#endif

REXCVAR_DEFINE_INT32(sa2_render_height_handheld, 720, "SA2",
                     "Render height in handheld mode (the PC's starting mode unless sa2_render_docked): 720 = the "
                     "game's own 1280x720. Any multiple of 180 from 360 to 2160 (others are rounded to the nearest); "
                     "the width follows at 16:9")
    .range(180, 4320)
    .lifecycle(rex::cvar::Lifecycle::kHotReload);
REXCVAR_DEFINE_INT32(sa2_render_height_docked, 1080, "SA2",
                     "Render height in docked mode (the TV): 1080 = 1920x1080. Any multiple of 180 from 360 to "
                     "2160; switching between docked and handheld changes it at the next frame")
    .range(180, 4320)
    .lifecycle(rex::cvar::Lifecycle::kHotReload);
REXCVAR_DEFINE_BOOL(sa2_render_docked, false, "SA2",
                    "PC only: start in the simulated docked mode (sa2_render_height_docked). The bind_sa2_docked key "
                    "(F9) switches between docked and handheld while the game runs, like docking the Switch. The "
                    "Switch itself always follows the console");
REXCVAR_DEFINE_INT32(sa2_msaa, 0, "SA2",
                     "Multisample anti-aliasing of the game's own (single-sample) render targets: 0 = off, as the "
                     "game and as before (default); 2 or 4 = that many samples per pixel, resolved when the game "
                     "copies the image. The game's 4x surfaces (Direct3D's fast Clear aliases) stay as they are. Read "
                     "at start")
    .range(0, 4)
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
REXCVAR_DEFINE_INT32(sa2_render_test_toggle_at, 0, "SA2",
                     "Test (PC): toggle the simulated docked mode after this presented swap (0 = never)")
    .range(0, 2000000000);
REXCVAR_DEFINE_INT32(sa2_render_test_toggle_every, 0, "SA2",
                     "Test (PC): after sa2_render_test_toggle_at, toggle again every this many presented swaps "
                     "(0 = once)")
    .range(0, 2000000000);

// Non-CPU group: the new behaviours have their own keys like every other change (docs/enhancements.md).
SA2_ENHANCEMENT(g_render_scale, sa2_gpu_render_scale, sa2::enh::kNonCpu, true,
                "GPU: render at sa2_render_height_handheld / sa2_render_height_docked (720 / 1080 by default), "
                "following docked / handheld live; off = always the game's 1280x720");
SA2_ENHANCEMENT(g_msaa, sa2_gpu_msaa, sa2::enh::kNonCpu, true,
                "GPU: honour sa2_msaa (2x / 4x host multisampling of the game's single-sample render targets, "
                "resolved at the game's copies); with sa2_msaa = 0 (default) nothing changes");

// ds2scholar-nx (2026-10-23): dynamic resolution. Console, Forest of Fallen Giants (ds2_062): the in-game stutters are
// GPU frames of 50-110 ms (scene 36-45 ms: one particle/fog pixel shader blended over the screen many times), e.g. 0.6 s
// at ~16 fps. 540 costs ~30 % less GPU than 720 (Majula, 28.8 -> 20.0 ms busy). Handheld only; L+R+Plus turns it on
// and off in game (switch_input_driver.cpp).
REXCVAR_DEFINE_BOOL(ds2_dynamic_resolution, false, "DS2",
                    "Handheld: while the GPU is over ds2_dynamic_resolution_budget_ms per frame the game is drawn at "
                    "ds2_dynamic_resolution_low, and back at sa2_render_height_handheld once there is room. "
                    "L+R+Plus toggles it in game. false = fixed resolution, as before")
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
REXCVAR_DEFINE_INT32(ds2_dynamic_resolution_low, 540, "DS2",
                     "ds2_dynamic_resolution: render height while the GPU is over budget (multiple of 180)")
    .range(360, 2160)
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
REXCVAR_DEFINE_DOUBLE(ds2_dynamic_resolution_budget_ms, 31.0, "DS2",
                      "ds2_dynamic_resolution: GPU busy time per frame (real ms) above which the resolution drops")
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
// ds2scholar-nx (2026-10-24, console ds2_081): going dark <-> bright, the game renders a light probe (6 faces with their
// mip chains, ~318 resolves a frame) for 2-5 frames of 60-70 ms GPU (scene 26 ms instead of 12): over before the 4
// smoothed frames above the budget add up. A single frame above this drops at once. 0 = off (only the smoothed rule).
REXCVAR_DEFINE_DOUBLE(ds2_dynamic_resolution_spike_ms, 0.0, "DS2",
                      "ds2_dynamic_resolution: one frame with more GPU busy time than this (real ms) drops to the low "
                      "height at once, without waiting for the smoothed budget rule. 0 = off, as before")
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
REXCVAR_DEFINE_INT32(ds2_dynamic_resolution_test_every, 0, "DS2",
                     "Test: with ds2_dynamic_resolution on, switch between the two heights every this many frames "
                     "regardless of the GPU (the PC has no per-frame GPU time). 0 = off")
    .range(0, 100000)
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
REXCVAR_DEFINE_DOUBLE(ds2_dynamic_resolution_ratio, 1.45, "DS2",
                      "ds2_dynamic_resolution: GPU cost of the normal height over the low one, to predict when going back "
                      "fits (console Majula 720 / 540: 28.8 / 20.0 ms busy)")
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
// ds2scholar-nx (2026-10-25, owner: the 720 <-> 540 flapping is visible). Console ds2_103 / ds2_105: 7 of 9 returns to
// 720 dropped again 1-4 s later; the prediction (low-height time x ds2_dynamic_resolution_ratio) said 9-26 ms where 720
// then measured 31+. Each quick re-drop doubles how long the low height is kept (5 -> 10 -> 20 -> 40 -> 80 s); a minute at
// the normal height without a drop halves it again. false = always 150 frames, as before.
REXCVAR_DEFINE_BOOL(ds2_dynamic_resolution_backoff, false, "DS2",
                    "ds2_dynamic_resolution: when it drops again within 10 s of going back, keep the low height twice "
                    "as long next time (up to 80 s); a minute without a drop halves it. false = always 5 s, as before")
    .lifecycle(rex::cvar::Lifecycle::kInitOnly);
// ds2scholar-nx (2026-10-25, owner): a status notice (ui_status_toasts) on every automatic 720 <-> 540 switch too. Off by
// default: while a notice is up the presenter paints on the UI thread, and these switches come in the heavy moments.
REXCVAR_DEFINE_BOOL(ds2_status_toast_resolution, false, "DS2",
                    "Show a short notice when dynamic resolution changes the render height by itself. false = only "
                    "the shortcuts show one");

extern "C" void RexShowStatus(const char* text);  // rex_app.cpp (SDK)

namespace sa2::render {
namespace {

std::atomic<bool> g_docked_pc{false};
std::atomic<bool> g_docked_pc_set{false};
std::atomic<uint32_t> g_last_logged_q{0};
// ds2_dynamic_resolution: -1 = not read yet; 0 / 1 = off / on (L+R+Plus flips it). g_dynamic_q: 0 = no override, else
// the low scale in quarters.
std::atomic<int> g_dynamic_on{-1};
std::atomic<uint32_t> g_dynamic_q{0};
std::atomic<bool> g_dynamic_ever{false};
// ds2scholar-nx (2026-10-25, owner): L+R+right stick click (RexAppCycleResolution) can also fix the handheld render at
// ds2_dynamic_resolution_low (with dynamic resolution off). false = sa2_render_height_handheld, as before.
std::atomic<bool> g_fixed_low{false};
bool DynamicOn() {
  int v = g_dynamic_on.load(std::memory_order_acquire);
  if (v < 0) {
    int expected = -1;
    g_dynamic_on.compare_exchange_strong(expected, REXCVAR_GET(ds2_dynamic_resolution) ? 1 : 0,
                                         std::memory_order_acq_rel);
    v = g_dynamic_on.load(std::memory_order_acquire);
  }
  if (v == 1) g_dynamic_ever.store(true, std::memory_order_relaxed);
  return v == 1;
}

// q = height / 180, from 2 (360p) to 12 (2160p); other heights go to the nearest multiple of 180.
uint32_t QuartersOf(int32_t height) {
  const int32_t q = (std::clamp(height, 360, 2160) + 90) / 180;
  return uint32_t(std::clamp(q, 2, 12));
}

bool DockedPc() {
  if (!g_docked_pc_set.load(std::memory_order_acquire)) {
    bool expected = false;
    if (g_docked_pc_set.compare_exchange_strong(expected, true, std::memory_order_acq_rel))
      g_docked_pc.store(REXCVAR_GET(sa2_render_docked), std::memory_order_release);
  }
  return g_docked_pc.load(std::memory_order_acquire);
}

}  // namespace

bool Docked() {
#if REX_PLATFORM_SWITCH
  // libnx keeps the operation mode cached; the SDK's applet loop (windowed_app_context_switch.cpp) processes the
  // OperationModeChanged message that updates it. Reverse-NX's "fake" mode is obeyed, as the window does.
  return rex::ui::switch_saltynx::BaseMode(appletGetOperationMode() == AppletOperationMode_Console);
#else
  return DockedPc();
#endif
}

uint32_t WantedScaleQuarters() {
  if (!g_render_scale.active) return 4;
  const bool docked = Docked();
  const int32_t height = docked ? REXCVAR_GET(sa2_render_height_docked) : REXCVAR_GET(sa2_render_height_handheld);
  uint32_t q = QuartersOf(height);
  if (!docked) {
    const uint32_t dynamic = g_dynamic_q.load(std::memory_order_relaxed);
    if (dynamic && dynamic < q) q = dynamic;  // ds2_dynamic_resolution
    if (g_fixed_low.load(std::memory_order_relaxed)) {  // RexAppCycleResolution: fixed low height
      q = std::min(q, QuartersOf(REXCVAR_GET(ds2_dynamic_resolution_low)));
    }
  }
  if (g_last_logged_q.exchange(q | (docked ? 0x100u : 0u), std::memory_order_relaxed) != (q | (docked ? 0x100u : 0u))) {
    REXLOG_INFO("[res] {} mode: render {}x{} (sa2_render_height_{} = {}{})", docked ? "docked" : "handheld",
                320 * q, 180 * q, docked ? "docked" : "handheld", height,
                int32_t(180 * q) != height ? fmt::format(", rounded to a multiple of 180") : std::string());
  }
  return q;
}

uint32_t ScaleQuartersOf(bool docked) {
  if (!g_render_scale.active) return 4;
  return QuartersOf(docked ? REXCVAR_GET(sa2_render_height_docked) : REXCVAR_GET(sa2_render_height_handheld));
}

void ToggleDocked() {
#if !REX_PLATFORM_SWITCH
  const bool docked = !DockedPc();
  g_docked_pc.store(docked, std::memory_order_release);
  REXLOG_INFO("[res] simulated {} (PC): render height {}", docked ? "docking" : "undocking",
              docked ? REXCVAR_GET(sa2_render_height_docked) : REXCVAR_GET(sa2_render_height_handheld));
#endif
}

void OnPresented(uint64_t presented) {
#if !REX_PLATFORM_SWITCH
  const int32_t at = REXCVAR_GET(sa2_render_test_toggle_at);
  if (at <= 0 || presented < uint64_t(at)) return;
  const int32_t every = REXCVAR_GET(sa2_render_test_toggle_every);
  if (presented == uint64_t(at) || (every > 0 && (presented - uint64_t(at)) % uint64_t(every) == 0)) {
    REXLOG_INFO("[res] test toggle at presented swap {}", presented);
    ToggleDocked();
  }
#else
  (void)presented;
#endif
}

uint32_t MsaaSamples() {
  if (!g_msaa.active) return 1;
  const int32_t samples = REXCVAR_GET(sa2_msaa);
  return samples >= 4 ? 4u : samples >= 2 ? 2u : 1u;
}

void NoteRescale() { g_render_scale.Use(); }

// Called by the renderer at every Swap with the GPU busy time of the frames finished since the previous one (the
// timestamps arrive a couple of frames late, so a smoothed value is used). Ring thread only.
bool DynamicResolutionActive() {
  DynamicOn();
  return g_dynamic_ever.load(std::memory_order_relaxed);
}

void NoteFrameGpuBusy(double busy_ms, double passes_ms) {
  static double smooth = 0.0;
  static uint32_t over = 0, under = 0, settle = 0, dwell = 0;
  if (!g_render_scale.active) return;
  const bool on = DynamicOn() && !Docked();
  const uint32_t q_low = QuartersOf(REXCVAR_GET(ds2_dynamic_resolution_low));
  const uint32_t q_high = ScaleQuartersOf(false);
  const uint32_t current = g_dynamic_q.load(std::memory_order_relaxed);
  if (!on || q_low >= q_high) {
    if (current) {
      g_dynamic_q.store(0, std::memory_order_relaxed);
      REXLOG_INFO("[res] dynamic resolution off: back to {}x{}", 320 * q_high, 180 * q_high);
    }
    over = under = 0;
    return;
  }
  // Test (PC, where the per-frame GPU time is not available): flip between the two heights every N frames.
  if (static const int32_t every = REXCVAR_GET(ds2_dynamic_resolution_test_every); every > 0) {
    static uint32_t frames = 0;
    if (++frames % uint32_t(every) == 0) {
      g_dynamic_q.store(current ? 0u : q_low, std::memory_order_relaxed);
      REXLOG_INFO("[res] dynamic resolution test flip -> {}", current ? "high" : "low");
    }
    return;
  }
  if (current && busy_ms < 0.1 * REXCVAR_GET(ds2_dynamic_resolution_budget_ms)) {  // loading screens / menus at
    // the low height (under a tenth of the budget: ~3 ms on the console): no evidence either way
    ++dwell;
    return;
  }
  smooth = smooth * 0.75 + busy_ms * 0.25;
  if (settle) {  // the frames around a rescale say nothing about the new scale
    --settle;
    return;
  }
  static const double budget = REXCVAR_GET(ds2_dynamic_resolution_budget_ms);
  static const double ratio = REXCVAR_GET(ds2_dynamic_resolution_ratio);
  static const double spike = REXCVAR_GET(ds2_dynamic_resolution_spike_ms);
  // ds2_dynamic_resolution_backoff: a drop within 300 frames (10 s) of going back doubles the frames the low height is
  // then kept (150 -> 300 -> ... -> 2400), and every 1800 frames (60 s) at the normal height without a drop halves it.
  static const bool backoff_on = REXCVAR_GET(ds2_dynamic_resolution_backoff);
  static uint32_t backoff = 0, frames_high = 0, stable_high = 0;
  static bool went_back = false;
  if (!current) {
    ++frames_high;
    if (backoff_on && backoff && ++stable_high >= 1800) {
      --backoff;
      stable_high = 0;
      REXLOG_INFO("[res] dynamic resolution: 60 s without a drop, the low height is now kept at least {} frames",
                  150u << backoff);
    }
    over = smooth > budget ? over + 1 : 0;
    // ds2_dynamic_resolution_spike_ms: on the passes' own times. busy_ms (span minus the gap category) read ~19 ms
    // in the light probe frames of 64 ms (console ds2_082: gap 42-58 ms, the CPU waits for the GPU 4 times a frame).
    const bool spiked = spike > 0.0 && passes_ms > spike;
    if (over >= 4 || spiked) {
      g_dynamic_q.store(q_low, std::memory_order_relaxed);
      REXLOG_INFO("[res] dynamic resolution: GPU {:.1f} ms a frame (budget {:.1f}{}) -> {}x{}", smooth, budget,
                  spiked && over < 4 ? fmt::format("; one frame of {:.1f} ms of passes over the spike limit {:.1f}", passes_ms, spike)
                                     : std::string(),
                  320 * q_low, 180 * q_low);
      if (REXCVAR_GET(ds2_status_toast_resolution)) {
        RexShowStatus(fmt::format("Render {}p (dynamic)", 180 * q_low).c_str());
      }
      if (backoff_on && went_back && frames_high < 300 && backoff < 4) {
        ++backoff;
        REXLOG_INFO("[res] dynamic resolution: dropped again {} frames after going back; the low height is now kept at "
                    "least {} frames", frames_high, 150u << backoff);
      }
      went_back = false;
      stable_high = 0;
      over = under = dwell = 0;
      settle = 10;
    }
  } else {
    // At least 150 frames (5 s) at the low height, and frames with almost no GPU work (loading screens, menus) say
    // nothing about the scene: they neither count towards going back nor reset the count (console ds2_063: it went
    // back on "0.0 ms" frames and dropped again a second later).
    ++dwell;
    under = smooth * ratio < budget - 2.0 ? under + 1 : 0;
    if (under >= 90 && dwell >= (150u << backoff)) {
      g_dynamic_q.store(0, std::memory_order_relaxed);
      REXLOG_INFO("[res] dynamic resolution: GPU {:.1f} ms a frame at the low height ({:.1f} predicted) -> {}x{}",
                  smooth, smooth * ratio, 320 * q_high, 180 * q_high);
      if (REXCVAR_GET(ds2_status_toast_resolution)) {
        RexShowStatus(fmt::format("Render {}p (dynamic)", 180 * q_high).c_str());
      }
      went_back = true;
      frames_high = stable_high = 0;
      over = under = 0;
      settle = 10;
    }
  }
}

}  // namespace sa2::render

// From the Switch input driver (L+R+Plus): flips ds2_dynamic_resolution in game. Returns the new state (1 = on).
extern "C" unsigned RexAppToggleDynamicResolution(void) {
  const bool on = !sa2::render::DynamicOn();
  sa2::render::g_dynamic_on.store(on ? 1 : 0, std::memory_order_release);
  REXLOG_INFO("[res] dynamic resolution {} (L+R+Plus)", on ? "ON" : "OFF");
  RexShowStatus(fmt::format("Dynamic resolution: {}{}", on ? "ON" : "OFF", sa2::render::Docked() ? " (handheld only)" : "").c_str());
  return on ? 1u : 0u;
}

// From the Switch input driver (L+R+right stick click): handheld resolution mode, dynamic -> fixed high -> fixed low ->
// dynamic. Returns the new mode (0 dynamic, 1 fixed high, 2 fixed low).
extern "C" unsigned RexAppCycleResolution(void) {
  const bool dynamic = sa2::render::DynamicOn();
  const bool low = sa2::render::g_fixed_low.load(std::memory_order_relaxed);
  const unsigned mode = dynamic ? 1u : low ? 0u : 2u;
  sa2::render::g_fixed_low.store(mode == 2, std::memory_order_relaxed);
  sa2::render::g_dynamic_on.store(mode == 0 ? 1 : 0, std::memory_order_release);
  const int32_t high = 180 * int32_t(sa2::render::ScaleQuartersOf(false));
  const int32_t low_height = 180 * int32_t(sa2::render::QuartersOf(REXCVAR_GET(ds2_dynamic_resolution_low)));
  const std::string notice = mode == 0   ? fmt::format("Resolution: dynamic {}p/{}p", high, low_height)
                             : mode == 1 ? fmt::format("Resolution: {}p fixed", high)
                                         : fmt::format("Resolution: {}p fixed", low_height);
  REXLOG_INFO("[res] {} (L+R+right stick)", notice);
  RexShowStatus((notice + (sa2::render::Docked() ? " (handheld only)" : "")).c_str());
  return mode;
}

namespace sa2::render {
void NoteMsaaUse(uint64_t n) { g_msaa.UseSampled(); (void)n; }

void RegisterKeys() {
#if !REX_PLATFORM_SWITCH
  rex::ui::RegisterBind("bind_sa2_docked", "F9",
                        "Switch between the simulated docked and handheld modes (render resolution)",
                        [] { ToggleDocked(); });
#endif
}

}  // namespace sa2::render
