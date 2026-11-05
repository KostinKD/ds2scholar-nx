// Stubs for the parts of sa2-nx's native renderer that ds2 does not build: sa2's native Direct3D layer
// (src/me/sa2_api_*.cpp, docs/api-renderer.md in sa2-nx), written against sa2's Direct3D addresses. Every entry point
// answers "does not apply" (false), so callers take their ordinary path; Report has nothing to report.

#include <cstdint>
#include <string>

#include <rex/ppc.h>

#include "me/sa2_api.h"

namespace sa2::api {

bool DrawVertices(PPCContext&, uint8_t*) { return false; }
bool BeginVertices(PPCContext&, uint8_t*) { return false; }
bool DrawVerticesUP(PPCContext&, uint8_t*) { return false; }
bool ShadowInlineAlloc(PPCContext&, uint8_t*) { return false; }
bool Clear(PPCContext&, uint8_t*) { return false; }
bool Resolve(PPCContext&, uint8_t*) { return false; }
std::string ResolveReport() { return {}; }
bool WindowScissor(PPCContext&, uint8_t*) { return false; }
void Report() {}

}  // namespace sa2::api

// sa2-nx's src/cpu/sa2_codegen_checks.cpp and sa2_forms_selfcheck.cpp: self-checks of sa2's optimised codegen flavour
// and its processor-specific helpers, which ds2 (classic codegen) does not have. Called by src/cpu/sa2_enhancements.cpp.
#include "cpu/sa2_enhancements.h"

#include <rex/cvar.h>

// Ds2App::OnPreSetup (src/ds2_app.h): run sa2::enh::Resolve() as sa2-nx's SA2App does.
REXCVAR_DEFINE_BOOL(ds2_enhancements_resolve, true, "DS2",
                    "Resolve sa2-nx's switchable enhancements at start-up (sa2_cpu_enhancements / "
                    "sa2_noncpu_enhancements and each own key; the keys sa2 turns on). false = all inactive, as "
                    "before 2026-10-17");

namespace sa2::enh {

void CodegenChecksInit() {}
void CodegenChecksReport(int) {}
void FormsSelfCheck() {}

}  // namespace sa2::enh
