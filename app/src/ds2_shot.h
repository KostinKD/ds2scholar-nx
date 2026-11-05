// Stage 3 diagnostic: still images of the presented output at the seconds listed in ds2_shot_s.

#pragma once

#include <functional>

namespace rex::ui {
class Presenter;
}

namespace ds2::shot {

// Starts the capture thread when ds2_shot_s lists any second.
void Start(std::function<rex::ui::Presenter*()> get_presenter);

// Stops and joins it.
void Stop();

}  // namespace ds2::shot
