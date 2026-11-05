// ds2 - Dark Souls II (Xbox 360), ReXGlue recompiled project.
//
// The app of `rexglue init` (sdk/resources/templates/init) plus the game folder lookup of sa2-nx's sa2_app.h. Stage 3
// runs the plain SDK runtime with the emulated GPU: no game-specific hooks yet.

#pragma once

#include <filesystem>
#include <system_error>

#include <rex/filesystem.h>
#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/rex_app.h>
#include <rex/runtime.h>

#include "cpu/sa2_enhancements.h"
#include "ds2_input_script.h"
#include "ds2_pgo.h"

REXCVAR_DECLARE(bool, ds2_enhancements_resolve);
namespace ds2 {
void ApplyGpuBoost();  // ds2_gpu_boost.cpp
void ApplyFrameCap();  // ds2_frame_cap.cpp
}
#include "me/me_native_system.h"
#include "ds2_shot.h"
#include "ds2_guest_dump.h"
#include "ds2_swap_log.h"

class Ds2App : public rex::ReXApp {
 public:
  using rex::ReXApp::ReXApp;

  static std::unique_ptr<rex::ui::WindowedApp> Create(rex::ui::WindowedAppContext& ctx) {
    return std::unique_ptr<Ds2App>(new Ds2App(ctx, "ds2", PPCImageConfig));
  }

  // Stage 4: with sa2_renderer_native = true the graphics system is the native Vulkan renderer (src/me, from sa2-nx)
  // instead of the emulated Xenos GPU; off by default.
  void OnPreSetup(rex::RuntimeConfig& config) override {
    // Stage 5 (2026-10-17): sa2-nx's switchable enhancements are inactive until Resolve() runs (its SA2App does it
    // here); ds2 never called it, so the renderer ran without every SA2_ENHANCEMENT (render scale among them) and
    // without the keys Resolve() turns on (deferred recording, pipeline prewarm, the NVK fast paths...).
    if (REXCVAR_GET(ds2_enhancements_resolve)) {
      sa2::enh::Resolve();
      // Stage 5, busy-waits (2026-10-18): the '[enh] uses in the last N s' lines (sa2_enhancements_report_s, 0 = off),
      // as in sa2-nx's SA2App; ds2 never started them, so an enhancement's use (ds2_cpu_gpu_wait_sleep) was invisible.
      sa2::enh::StartReport();
    }
    ds2::ApplyGpuBoost();  // ds2_gpu_boost (Switch, handheld: GPU 460.8 MHz)
    ds2::ApplyFrameCap();  // ds2_frame_cap_30 (Switch: 30 fps, two vblanks per frame)
    if (me::native::Enabled()) {
      config.graphics = me::native::CreateGraphicsSystem();
      REXLOG_INFO("graphics: native Vulkan renderer (PM4 ring)");
    }
  }

  // Stage 3 diagnostics (ds2_swap_log_s, ds2_shot_s, ds2_input_script): presented frame count, still images and a
  // scripted pad. OnPostSetup runs before the guest starts (ReXApp::ConstructRuntime), so adding an input driver here
  // does not race the game's polling.
  void OnPostSetup() override {
    ds2::input_script::Install(runtime() ? runtime()->input_system() : nullptr);
    ds2::swap_log::Start();
    ds2::guest_dump::Start(runtime() ? runtime()->memory() : nullptr);
    ds2::shot::Start([this]() -> rex::ui::Presenter* {
      const auto* rt = runtime();
      const auto* graphics = rt ? rt->graphics_system() : nullptr;
      return graphics ? graphics->presenter() : nullptr;
    });
    // Stage 5 (2026-10-19, entry 54): the PGO-instrumented build (DS2_PGO=generate) saves its counts to pgo/ next to
    // the NRO every 2 minutes (nothing in other builds; src/ds2_pgo.cpp).
    ds2::pgo::Start();
  }
  // The PGO-instrumented build also saves its counts when the game loses focus (HOME menu): it may be closed there.
  void OnWindowFocusChanged(bool focused) override {
    if (!focused) ds2::pgo::DumpNow();
  }
  void OnShutdown() override {
    ds2::pgo::Stop();
    ds2::shot::Stop();
    ds2::guest_dump::Stop();
    ds2::swap_log::Stop();
  }

  // Without --game_data_root, use a game_root/ folder next to the executable, and on a PC build tree the
  // repository's assets/game_root (made by tools/god_extract.py). An explicit path always wins.
  void OnConfigurePaths(rex::PathConfig& paths) override {
    if (!paths.game_data_root.empty()) {
      return;
    }
    std::error_code ec;
    const auto folder = rex::filesystem::GetExecutableFolder();
    if (folder.empty()) {
      return;
    }
    for (auto candidate = folder; !candidate.empty(); candidate = candidate.parent_path()) {
      for (const auto& sub : {std::filesystem::path("game_root"), std::filesystem::path("assets") / "game_root"}) {
        // Default.xex: the name on this game's disc (the file system is case-insensitive on Windows only).
        // Or only its asset cache (game_root.nxpack + .nxidx, sdk pack_device.h), as in sa2-nx.
        auto pack = candidate / sub;
        pack += ".nxpack";
        if (std::filesystem::is_regular_file(candidate / sub / "Default.xex", ec) ||
            std::filesystem::is_regular_file(candidate / sub / "default.xex", ec) ||
            std::filesystem::is_regular_file(pack, ec)) {
          paths.game_data_root = candidate / sub;
          return;
        }
      }
      if (candidate == candidate.parent_path()) {
        break;
      }
    }
  }
};
