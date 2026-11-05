// Stage 3 diagnostic: a scripted controller for unattended test runs (tools/win/boot_test.ps1 has no input).
// ds2_input_script lists "<second>:<button>[:<hold ms>]" steps, comma separated, e.g. "25:start,32:a,80:lsu:8000"; each
// is held for its ms (default ds2_input_hold_ms) from that second after start. Buttons: a b x y start back up down left
// right lb rb; sticks at full deflection: lsu lsd lsl lsr (left), rsu rsd rsl rsr (right).
// It is one more input driver (rex::input::InputDriver, as the SDK's NOP driver), so it adds a connected pad (after the
// SDK's own ones: usually player 2). Empty turns it off and no pad is added.

#include "ds2_input_script.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include <rex/cvar.h>
#include <rex/input/input_driver.h>
#include <rex/input/input_system.h>
#include <rex/logging.h>

REXCVAR_DEFINE_STRING(ds2_input_script, "", "DS2",
                      "Scripted pad for test runs: <second>:<button>,... (a b x y start back up down left right lb rb)");
REXCVAR_DEFINE_INT32(ds2_input_hold_ms, 200, "DS2", "How long each button of ds2_input_script is held");

namespace ds2::input_script {
namespace {

using namespace rex;
using namespace rex::input;

constexpr DeviceId kScriptDevice = static_cast<DeviceId>(0x44533250);  // 'DS2P'

struct Step {
  double at_s;
  double hold_s;  // <= 0: ds2_input_hold_ms
  uint16_t buttons;
  int16_t lx, ly, rx, ry;  // stick deflection while held (lsu/lsd/lsl/lsr, rsu/rsd/rsl/rsr)
};

int16_t AddAxis(int16_t a, int16_t b) {
  return static_cast<int16_t>(std::clamp(int(a) + int(b), -32767, 32767));
}

class ScriptInputDriver final : public InputDriver {
 public:
  explicit ScriptInputDriver(std::vector<Step> steps)
      : InputDriver(nullptr, 0), steps_(std::move(steps)), started_(std::chrono::steady_clock::now()) {}

  X_STATUS Setup() override { return X_STATUS_SUCCESS; }

  void EnumerateDevices(std::vector<DeviceInfo>& out) override {
    DeviceInfo info;
    info.id = kScriptDevice;
    info.name = "ds2 input script";
    info.synthetic = true;
    out.push_back(info);
  }

  X_RESULT GetDeviceState(DeviceId id, X_INPUT_STATE* out_state) override {
    if (id != kScriptDevice) {
      return X_ERROR_DEVICE_NOT_CONNECTED;
    }
    const double now = std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
    const double default_hold = REXCVAR_GET(ds2_input_hold_ms) / 1000.0;
    uint16_t buttons = 0;
    int16_t lx = 0, ly = 0, rx = 0, ry = 0;
    for (size_t i = 0; i < steps_.size(); ++i) {
      const Step& step = steps_[i];
      const double hold = step.hold_s > 0 ? step.hold_s : default_hold;
      if (now >= step.at_s && now < step.at_s + hold) {
        buttons |= step.buttons;
        lx = AddAxis(lx, step.lx);
        ly = AddAxis(ly, step.ly);
        rx = AddAxis(rx, step.rx);
        ry = AddAxis(ry, step.ry);
        if (!logged_[i]) {
          logged_[i] = true;
          REXLOG_INFO("[ds2] input script: buttons 0x{:04X} sticks ({},{} / {},{}) for {:.1f} s at {:.1f} s",
                      step.buttons, step.lx, step.ly, step.rx, step.ry, hold, now);
        }
      }
    }
    if (out_state) {
      std::memset(out_state, 0, sizeof(*out_state));
      const std::array<int32_t, 5> state = {buttons, lx, ly, rx, ry};
      if (state != last_state_) {  // XInput: a new packet number whenever anything changes
        ++packet_;
        last_state_ = state;
      }
      out_state->packet_number = packet_;
      out_state->gamepad.buttons = buttons;
      out_state->gamepad.thumb_lx = lx;
      out_state->gamepad.thumb_ly = ly;
      out_state->gamepad.thumb_rx = rx;
      out_state->gamepad.thumb_ry = ry;
    }
    return X_ERROR_SUCCESS;
  }

  X_RESULT GetDeviceCapabilities(DeviceId id, uint32_t, X_INPUT_CAPABILITIES* out_caps) override {
    if (id != kScriptDevice) {
      return X_ERROR_DEVICE_NOT_CONNECTED;
    }
    if (out_caps) {
      std::memset(out_caps, 0, sizeof(*out_caps));
      out_caps->type = 0x01;      // XINPUT_DEVTYPE_GAMEPAD
      out_caps->sub_type = 0x01;  // XINPUT_DEVSUBTYPE_GAMEPAD
      out_caps->gamepad.buttons = 0xFFFF;
      out_caps->gamepad.left_trigger = 0xFF;
      out_caps->gamepad.right_trigger = 0xFF;
      out_caps->gamepad.thumb_lx = static_cast<int16_t>(0x7FFF);
      out_caps->gamepad.thumb_ly = static_cast<int16_t>(0x7FFF);
      out_caps->gamepad.thumb_rx = static_cast<int16_t>(0x7FFF);
      out_caps->gamepad.thumb_ry = static_cast<int16_t>(0x7FFF);
    }
    return X_ERROR_SUCCESS;
  }

  X_RESULT SetDeviceVibration(DeviceId id, X_INPUT_VIBRATION*) override {
    return id == kScriptDevice ? X_ERROR_SUCCESS : X_ERROR_DEVICE_NOT_CONNECTED;
  }

  X_RESULT GetDeviceKeystroke(DeviceId id, uint32_t, X_INPUT_KEYSTROKE*) override {
    return id == kScriptDevice ? X_ERROR_EMPTY : X_ERROR_DEVICE_NOT_CONNECTED;
  }

 private:
  std::vector<Step> steps_;
  std::vector<bool> logged_ = std::vector<bool>(steps_.size(), false);
  std::chrono::steady_clock::time_point started_;
  uint32_t packet_ = 1;
  std::array<int32_t, 5> last_state_ = {};
};

std::vector<Step> Parse(const std::string& script) {
  static const std::map<std::string, uint16_t> kButtons = {
      {"a", X_INPUT_GAMEPAD_A},       {"b", X_INPUT_GAMEPAD_B},
      {"x", X_INPUT_GAMEPAD_X},       {"y", X_INPUT_GAMEPAD_Y},
      {"start", X_INPUT_GAMEPAD_START}, {"back", X_INPUT_GAMEPAD_BACK},
      {"up", X_INPUT_GAMEPAD_DPAD_UP},  {"down", X_INPUT_GAMEPAD_DPAD_DOWN},
      {"left", X_INPUT_GAMEPAD_DPAD_LEFT}, {"right", X_INPUT_GAMEPAD_DPAD_RIGHT},
      {"lb", X_INPUT_GAMEPAD_LEFT_SHOULDER}, {"rb", X_INPUT_GAMEPAD_RIGHT_SHOULDER}};
  constexpr int16_t kFull = 32767;
  struct Stick {
    int16_t lx, ly, rx, ry;
  };
  static const std::map<std::string, Stick> kSticks = {
      {"lsu", {0, kFull, 0, 0}}, {"lsd", {0, -kFull, 0, 0}}, {"lsl", {-kFull, 0, 0, 0}}, {"lsr", {kFull, 0, 0, 0}},
      {"rsu", {0, 0, 0, kFull}}, {"rsd", {0, 0, 0, -kFull}}, {"rsl", {0, 0, -kFull, 0}}, {"rsr", {0, 0, kFull, 0}}};
  std::vector<Step> steps;
  std::stringstream list(script);
  for (std::string item; std::getline(list, item, ',');) {
    // <second>:<button or stick>[:<hold ms>]
    const auto colon = item.find(':');
    if (colon == std::string::npos) {
      REXLOG_WARN("[ds2] input script: '{}' is not <second>:<button>[:<ms>], skipped", item);
      continue;
    }
    std::string name = item.substr(colon + 1);
    double hold_s = 0;
    if (const auto second = name.find(':'); second != std::string::npos) {
      hold_s = std::stod(name.substr(second + 1)) / 1000.0;
      name = name.substr(0, second);
    }
    Step step{std::stod(item.substr(0, colon)), hold_s, 0, 0, 0, 0, 0};
    if (const auto b = kButtons.find(name); b != kButtons.end()) {
      step.buttons = b->second;
    } else if (const auto s = kSticks.find(name); s != kSticks.end()) {
      step.lx = s->second.lx;
      step.ly = s->second.ly;
      step.rx = s->second.rx;
      step.ry = s->second.ry;
    } else {
      REXLOG_WARN("[ds2] input script: unknown button or stick in '{}', skipped", item);
      continue;
    }
    steps.push_back(step);
  }
  return steps;
}

}  // namespace

void Install(rex::system::IInputSystem* input) {
  auto steps = Parse(REXCVAR_GET(ds2_input_script));
  auto* system = dynamic_cast<rex::input::InputSystem*>(input);
  if (steps.empty() || !system) {
    return;
  }
  REXLOG_INFO("[ds2] input script: {} steps on an extra pad", steps.size());
  system->AddDriver(std::make_unique<ScriptInputDriver>(std::move(steps)));
}

}  // namespace ds2::input_script
