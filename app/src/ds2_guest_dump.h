// Diagnostic: copies a range of guest physical memory to a file at a given time (ds2_diag_guest_dump).
#pragma once

namespace rex::memory {
class Memory;
}

namespace ds2::guest_dump {

void Start(rex::memory::Memory* memory);
void Stop();

}  // namespace ds2::guest_dump
