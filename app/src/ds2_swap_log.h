// Stage 3 diagnostic: the count of presented frames (VdSwap) in the log every ds2_swap_log_s seconds.

#pragma once

namespace ds2::swap_log {

// Starts the logging thread when ds2_swap_log_s > 0.
void Start();

// Stops and joins it.
void Stop();

}  // namespace ds2::swap_log
