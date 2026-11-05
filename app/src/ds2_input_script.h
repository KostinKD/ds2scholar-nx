// Stage 3 diagnostic: a scripted controller (ds2_input_script) for unattended test runs.

#pragma once

namespace rex::system {
class IInputSystem;
}

namespace ds2::input_script {

// Adds the scripted pad to the runtime's input system when ds2_input_script lists any step.
void Install(rex::system::IInputSystem* input);

}  // namespace ds2::input_script
