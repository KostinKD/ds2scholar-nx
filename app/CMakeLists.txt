# Dark Souls II (Xbox 360, title 465307E4): static recompilation host application.
#
# The game code is not in this repository: run the code generator first (tools/codegen.ps1), which writes generated/
# from your own Default.xex together with the CMake glue (generated/rexglue.cmake, made by `rexglue codegen`).
#
# Stage 3, Windows PC, emulated GPU:
#   cmake --preset win-pc && cmake --build --preset win-pc        (from app/, inside tools\win\env.ps1)
#
# Started from the project `rexglue init` writes (sdk/resources/templates/init), not from sa2-nx's app: none of
# sa2's natives, hooks or renderer are used yet. app/src/me/ (sa2's renderer sources copied with the repository) is
# not part of this build.

cmake_minimum_required(VERSION 3.25)
project(ds2 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The SDK is built from source in this repository unless another tree is given.
set(REXSDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../sdk" CACHE PATH "Path to the ReXGlue SDK source tree")

# ds2scholar-nx (2026-10-25, as prototype2-nx WORKLOG #107): the presenter's FSR 1 (EASU + RCAS) and CAS paths
# (present_effect = fsr / cas) only need their SPIR-V, which the SDK ships built. The macro also gates members of
# rex/ui/presenter.h, so it is set for every target (one class layout). present_effect stays "bilinear" by default.
add_compile_definitions(REX_HAS_FIDELITYFX_SDK=1)

if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/generated/rexglue.cmake")
    message(FATAL_ERROR "app/generated/rexglue.cmake is missing: run tools/codegen.ps1 first")
endif()
include(generated/rexglue.cmake)

# The build re-runs the generator by itself whenever an input in codegen.d changes (manifest, toml, xex, the generator
# binary). That rewrites app/generated and would drop the codegen flavour's post-codegen steps: they are appended to
# the same command, as in sa2-nx.
if(TARGET ds2_codegen)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    add_custom_command(OUTPUT "${CMAKE_CURRENT_SOURCE_DIR}/generated/default/codegen.build.stamp" APPEND
        COMMAND "${CMAKE_COMMAND}" -E env "REXSDK_DIR=${REXSDK_DIR}"
                "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/../tools/post_codegen.py")
endif()

set(DS2_SOURCES
    src/main.cpp
    # Stage 3 diagnostic: VdSwap count in the log every ds2_swap_log_s seconds.
    src/ds2_swap_log.cpp
    src/ds2_guest_dump.cpp
    # Stage 3 diagnostic: still images of the presented output at the seconds of ds2_shot_s.
    src/ds2_shot.cpp
    # Stage 3 diagnostic: a scripted pad for unattended test runs (ds2_input_script).
    src/ds2_input_script.cpp
    # Stage 5: PGO profile collection of the instrumented Switch build (DS2_PGO=generate; empty otherwise).
    src/ds2_pgo.cpp
    # Stage 4, step 1: call counters on the Direct3D functions found by signature (ds2_d3d_census_s).
    src/ds2_d3d_census.cpp
    # Stage 4: the native renderer (src/me, sa2-nx's PM4-ring Vulkan renderer, unchanged). It replaces the emulated
    # Xenos GPU with sa2_renderer_native = true; off by default. Not built: sa2's native Direct3D layer
    # (src/me/sa2_api_*.cpp, sa2_d3d_api.cpp) and its hooks (sa2_me_hooks.cpp), all on sa2's addresses.
    src/me/me_native_system.cpp
    src/me/me_ring_wait.cpp
    # Stage 5, busy-waits: the game's D3D GPU wait sleeps on ring progress (ds2_cpu_gpu_wait_sleep, off by default).
    src/cpu/ds2_gpu_wait.cpp
    # Stage 5: the XDK's unaligned vector memcpy in native code (ds2_native_unaligned_memcpy, off by default).
    src/cpu/ds2_native_memcpy.cpp
    src/me/me_renderdoc.cpp
    src/me/native/sa2_native_draws.cpp
    src/me/native/sa2_deferred_recording.cpp
    src/me/native/sa2_native_targets.cpp
    src/me/native/sa2_native_shaders.cpp
    src/me/native/sa2_native_textures_pool.cpp
    src/me/native/sa2_shader_library.cpp
    src/me/native/sa2_native_glue.cpp
    src/me/sa2_render_mode.cpp
    # ds2's hooks for the renderer (docs/analysis/d3d.md addresses) and stubs for sa2's native Direct3D layer.
    src/ds2_me_hooks.cpp
    src/ds2_me_stubs.cpp
    src/ds2_gpu_boost.cpp
    # Stage 5: 30 fps with even pacing at raised clocks (ds2_frame_cap_30, off by default).
    src/ds2_frame_cap.cpp
    # The renderer's switchable enhancement keys (sa2-nx's src/cpu/sa2_enhancements, unchanged).
    src/cpu/sa2_enhancements.cpp
)
if(NOT REXGLUE_PLATFORM_SWITCH)
    # Switch profiler counters the native renderer calls (no-ops on PC).
    list(APPEND DS2_SOURCES src/me/me_pc_stubs.cpp)
endif()
# The codegen flavour (tools/codegen.ps1 -Flavor) names the build in the first "[enh]" log line (from sa2-nx; ds2-nx
# had it fixed to "classic codegen" until CPU step 1, 2026-10-17).
set(DS2_FLAVOR_FILE "${CMAKE_CURRENT_SOURCE_DIR}/generated/codegen_flavor.txt")
set(DS2_BUILD_FLAVOR "classic codegen")
if(EXISTS "${DS2_FLAVOR_FILE}")
    file(READ "${DS2_FLAVOR_FILE}" DS2_BUILD_FLAVOR)
    string(STRIP "${DS2_BUILD_FLAVOR}" DS2_BUILD_FLAVOR)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${DS2_FLAVOR_FILE}")
endif()
set_source_files_properties(src/cpu/sa2_enhancements.cpp PROPERTIES
    COMPILE_DEFINITIONS "SA2_BUILD_FLAVOR=\"${DS2_BUILD_FLAVOR}\"")

if(WIN32)
    add_executable(ds2 WIN32 ${DS2_SOURCES})
else()
    add_executable(ds2 ${DS2_SOURCES})
endif()

# GPU_PLUGINS xenos stages rexgpu-xenos*.dll next to ds2.exe (ds2.toml gpu_plugin = "xenos"; second boot 2026-10-16:
# "GPU plugin 'xenos' not found at out/pc/rexgpu-xenosrd.dll").
rexglue_setup_target(ds2 GPU_PLUGINS xenos)

# The native renderer's EDRAM transfer / utility shaders (src/me/native/shaders) as SPIR-V initializers, compiled on
# the host with glslangValidator (tools/win/build_glslang.ps1 builds it into out/glslang). As in sa2-nx's CMakeLists.
set(DS2_GLSLANG_VALIDATOR "${CMAKE_CURRENT_SOURCE_DIR}/../out/glslang/StandAlone/glslangValidator${CMAKE_EXECUTABLE_SUFFIX}"
    CACHE FILEPATH "Host glslangValidator")
set(DS2_GENERATED_SHADER_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated-shaders")
set(DS2_EDRAM_SHADER_INCLUDES)
foreach(_shader sa2_edram_7e3_to_rgba8 sa2_edram_rgba8_to_7e3 sa2_edram_16f_to_16f me_resolve_exp_bias me_resolve_exp_bias_rgba8 ds2_resolve_7e3_as_unorm10 me_edram_depth_to_rgba8 me_edram_depth_to_16f me_edram_import me_edram_color_to_depth me_edram_depth_to_depth me_edram_depth_to_stencil me_edram_color_to_stencil me_edram_depth_to_depth_msaa2 me_edram_depth_msaa2_to_depth_1x me_edram_depth_to_stencil_msaa2 me_edram_depth_msaa2_to_stencil_1x me_edram_raw64_to_rgba8 me_edram_rgba8_to_raw64 me_edram_raw64_to_16f me_edram_16f_to_raw64 me_edram_raw64_to_raw64 me_edram_depth_to_raw64 me_edram_raw64_to_depth me_depth_resolve_guestspace me_depth_resolve_guestspace_msaa2 me_edram_stencil_to_buffer me_edram_stencil_msaa2_to_buffer me_edram_color_stencil_to_buffer me_edram_color_to_color me_edram_r64_to_r64 sa2_resolve_copy sa2_depth_resolve_ms)
    set(_extension comp)
    if(_shader STREQUAL "me_edram_import")
        set(_extension vert)
    elseif(_shader MATCHES "^me_edram_(color_to_depth|depth_to_depth|depth_to_stencil|color_to_stencil|depth_to_depth_msaa2|depth_msaa2_to_depth_1x|depth_to_stencil_msaa2|depth_msaa2_to_stencil_1x|raw64_to_depth|color_to_color|r64_to_r64)$" OR _shader STREQUAL "sa2_resolve_copy" OR
           _shader STREQUAL "sa2_depth_resolve_ms")
        set(_extension frag)
    endif()
    set(_source "${CMAKE_CURRENT_SOURCE_DIR}/src/me/native/shaders/${_shader}.${_extension}")
    set(_output "${DS2_GENERATED_SHADER_DIR}/${_shader}.inc")
    set(_target_flags)
    if(_shader MATCHES "^me_edram_(stencil_to_buffer|color_stencil_to_buffer|stencil_msaa2_to_buffer|depth_to_depth_msaa2|depth_msaa2_to_depth_1x|depth_to_stencil_msaa2|depth_msaa2_to_stencil_1x)$" OR _shader STREQUAL "me_depth_resolve_guestspace_msaa2")
        set(_target_flags --target-env vulkan1.2)
        set(_output "${DS2_GENERATED_SHADER_DIR}/${_shader}_generated.inc")
    endif()
    add_custom_command(OUTPUT "${_output}"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${DS2_GENERATED_SHADER_DIR}"
        COMMAND "${DS2_GLSLANG_VALIDATOR}" -V ${_target_flags} -x -o "${_output}" "${_source}"
        DEPENDS "${_source}" VERBATIM)
    list(APPEND DS2_EDRAM_SHADER_INCLUDES "${_output}")
endforeach()
# ds2scholar-nx (ds2_7e3_r11g11b10): variants of the transfer / resolve shaders whose 7e3 side is a B10G11R11_UFLOAT image
# (storage format r11f_g11f_b10f). Name, source shader, defines.
set(DS2_R11_VARIANTS
    "sa2_edram_7e3_to_rgba8_r11|sa2_edram_7e3_to_rgba8|-DSRC_FMT=r11f_g11f_b10f"
    "sa2_edram_rgba8_to_7e3_r11|sa2_edram_rgba8_to_7e3|-DDST_FMT=r11f_g11f_b10f"
    "me_resolve_exp_bias_r11|me_resolve_exp_bias|-DSRC_FMT=r11f_g11f_b10f"
    "me_resolve_exp_bias_rgba8_r11|me_resolve_exp_bias_rgba8|-DSRC_FMT=r11f_g11f_b10f"
    "ds2_resolve_7e3_as_unorm10_r11|ds2_resolve_7e3_as_unorm10|-DSRC_FMT=r11f_g11f_b10f"
    "sa2_edram_16f_to_16f_r11src|sa2_edram_16f_to_16f|-DSRC_FMT=r11f_g11f_b10f"
    "sa2_edram_16f_to_16f_r11dst|sa2_edram_16f_to_16f|-DDST_FMT=r11f_g11f_b10f"
    "sa2_edram_16f_to_16f_r11both|sa2_edram_16f_to_16f|-DSRC_FMT=r11f_g11f_b10f,-DDST_FMT=r11f_g11f_b10f"
    "me_edram_16f_to_raw64_r11|me_edram_16f_to_raw64|-DSRC_FMT=r11f_g11f_b10f"
    "me_edram_raw64_to_16f_r11|me_edram_raw64_to_16f|-DDST_FMT=r11f_g11f_b10f"
    "me_edram_depth_to_16f_r11|me_edram_depth_to_16f|-DDST_FMT=r11f_g11f_b10f")
foreach(_variant ${DS2_R11_VARIANTS})
    string(REPLACE "|" ";" _parts "${_variant}")
    list(GET _parts 0 _name)
    list(GET _parts 1 _base)
    list(GET _parts 2 _defines)
    string(REPLACE "," " " _defines_text "${_defines}")
    separate_arguments(_define_args UNIX_COMMAND "${_defines_text}")
    set(_source "${CMAKE_CURRENT_SOURCE_DIR}/src/me/native/shaders/${_base}.comp")
    set(_output "${DS2_GENERATED_SHADER_DIR}/${_name}.inc")
    add_custom_command(OUTPUT "${_output}"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${DS2_GENERATED_SHADER_DIR}"
        COMMAND "${DS2_GLSLANG_VALIDATOR}" -V ${_define_args} -x -o "${_output}" "${_source}"
        DEPENDS "${_source}" VERBATIM)
    list(APPEND DS2_EDRAM_SHADER_INCLUDES "${_output}")
endforeach()
add_custom_target(ds2_edram_shaders DEPENDS ${DS2_EDRAM_SHADER_INCLUDES})
add_dependencies(ds2 ds2_edram_shaders)
target_include_directories(ds2 PRIVATE
    "${DS2_GENERATED_SHADER_DIR}"
    src
    src/me
    src/me/native
    src/me/native/shaders
    "${REXSDK_DIR}/src/core"
    # Precompiled SPIR-V of the SDK presenter (vulkan_spirv/guest_output_*): the renderer draws into its output.
    "${REXSDK_DIR}/src/ui/shaders")

# CPU-only SDK sources the native renderer reuses (draw-extent estimation, shader microcode interpretation): the GPU
# plugin's private symbols cannot satisfy application-side use. As in sa2-nx.
target_sources(ds2 PRIVATE
    "${REXSDK_DIR}/src/graphics/register_file.cpp"
    "${REXSDK_DIR}/src/graphics/format/ucode.cpp"
    "${REXSDK_DIR}/src/graphics/pipeline/shader/interpreter.cpp")

# The renderer includes xxhash.h and renderdoc_app.h directly; with the SDK built from source they are private to its
# libraries.
foreach(_dep xxhash renderdoc)
    if(TARGET ${_dep})
        target_include_directories(ds2 PRIVATE $<TARGET_PROPERTY:${_dep},INTERFACE_INCLUDE_DIRECTORIES>)
    endif()
endforeach()

# Settings template next to the executable, only when there is none yet (the copy there is the user's to edit).
if(NOT REXGLUE_PLATFORM_SWITCH)
    add_custom_command(TARGET ds2 POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -DSRC=${CMAKE_CURRENT_SOURCE_DIR}/ds2.toml -DDST=$<TARGET_FILE_DIR:ds2>/ds2.toml
                -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/copy_if_missing.cmake"
        VERBATIM)
endif()

# Stage 5 (2026-10-17): the generated game code is built in this directory, so the SDK's own flags do not reach it.
# GCC's default for GNU C++ is -ffp-contract=fast: it fused separate PPC fmul/fadd into FMA (the first NRO had 36065
# vector fmla/fmls in 2564 recompiled functions, tools/check_switch_build.py) and results drift from the Xbox 360;
# strict aliasing is unsafe for recompiled code. As in sa2-nx (for its tinted characters). Clang (the PC build) gets
# them too, so the PC rounds like the console.
option(DS2_EXACT_FP "-ffp-contract=off -fno-strict-aliasing on the targets with generated game code" ON)
if(DS2_EXACT_FP AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    foreach(target ds2 ds2_recomp)
        if(TARGET ${target})
            target_compile_options(${target} PRIVATE -ffp-contract=off -fno-strict-aliasing)
        endif()
    endforeach()
endif()

# Stage 5, CPU step 2 bisect (2026-10-18): the step 2 NRO (1c907ad5) breaks the image on the console (models gone,
# chaos, HUD fine; 96 unidentified pixel shaders instead of 13, switch_logs ds2_021) while the PC build of the same
# generated code is clean (bonfire shot, 13). ON puts volatile back into the guest loads/stores (tools/pch_no_volatile.py
# leaves REX_GUEST_VOLATILE overridable) without a new codegen, so the NRO is step 2 minus no_volatile.
option(DS2_GUEST_VOLATILE "-DREX_GUEST_VOLATILE=volatile on the targets with generated game code" OFF)
if(DS2_GUEST_VOLATILE)
    foreach(target ds2 ds2_recomp)
        if(TARGET ${target})
            target_compile_definitions(${target} PRIVATE REX_GUEST_VOLATILE=volatile)
        endif()
    endforeach()
endif()

# Stage 5, Switch (2026-10-17): the first NRO, as in sa2-nx's app/CMakeLists.txt minus its optimisation rounds (LTO,
# hot function order, CPU switches, PGO), which come one at a time after the NRO starts (docs/progress.md).
#   tools\win\build_switch.ps1 -> out\nx\ds2.nro
if(REXGLUE_PLATFORM_SWITCH)
    option(DS2_SWITCH_OMIT_FRAME_POINTER "Game code without the x29 frame chain (Switch)" OFF)
    if(DS2_SWITCH_OMIT_FRAME_POINTER)
        target_compile_options(ds2_recomp PRIVATE -fomit-frame-pointer)
    endif()
    message(STATUS "ds2: game code omit frame pointer ${DS2_SWITCH_OMIT_FRAME_POINTER}")
    # ds2_register.cpp is one generated function of ~30,000 SetFunction calls run once at start-up; sa2-nx measured
    # 771-927 s of GCC -O3 on its own (the critical path of the build). -O0 changes a few microseconds of start-up.
    set(_ds2_register "${CMAKE_CURRENT_SOURCE_DIR}/generated/default/ds2_register.cpp")
    if(EXISTS "${_ds2_register}")
        set_property(SOURCE "${_ds2_register}" APPEND PROPERTY COMPILE_OPTIONS -O0)
    endif()
    # Stage 5, CPU (2026-10-18, docs/progress.md entry 50): link-time optimisation, as in sa2-nx's app/CMakeLists.txt
    # (SA2_SWITCH_LTO, from nfsmw-nx / UnleashedRecomp-NX): the game code (ds2_recomp) and the app (ds2) are compiled to
    # GIMPLE (-flto -fno-fat-lto-objects) and optimised as one program at the link (-flto=N -flto-partition=balanced,
    # N parallel LTRANS jobs, low for the build machine's memory). The link repeats -ffp-contract=off and
    # -fno-strict-aliasing (the LTRANS stage must not fuse what the compile stage kept apart). xxHash with
    # XXH_FORCE_MEMORY_ACCESS=0: nfsmw-nx's LTO builds hit its default (a strict-aliasing violation) once inlined.
    # The SDK libraries stay out. Without sa2-nx's -fipa-pta (its own key, later). Prerequisite: sub_82997E24 in native
    # code (ds2_native_unaligned_memcpy, entry 49): GCC 16.1.0 miscompiles the recompiled one whenever its code moves.
    # SotFS (2026-10-22, docs/progress.md): on by default after the console A/B of optimised + LTO against classic
    # (30 fps held, CPU 211-215 % against 224-268 %; picture checked by the owner).
    option(DS2_SWITCH_LTO "Link-time optimisation of the game code and the app (Switch)" ON)
    set(DS2_SWITCH_LTO_JOBS "2" CACHE STRING "Parallel LTRANS jobs of the Switch LTO link")
    # Entry 52 (2026-10-18): -fipa-pta (UnleashedRecomp-NX, sa2-nx's SA2_SWITCH_IPA_PTA): interprocedural points-to
    # analysis at the LTO link. Its own key, after LTO + direct_calls were measured (entry 51).
    option(DS2_SWITCH_IPA_PTA "-fipa-pta at the Switch LTO link" OFF)
    if(DS2_SWITCH_LTO)
        set(_ds2_lto_compile -flto -fno-fat-lto-objects)
        set(_ds2_lto_link -flto=${DS2_SWITCH_LTO_JOBS} -flto-partition=balanced -ffp-contract=off -fno-strict-aliasing)
        if(DS2_SWITCH_IPA_PTA)
            list(APPEND _ds2_lto_compile -fipa-pta)
            list(APPEND _ds2_lto_link -fipa-pta)
        endif()
        target_compile_definitions(ds2 PRIVATE XXH_FORCE_MEMORY_ACCESS=0)
        foreach(target ds2_recomp ds2)
            if(TARGET ${target})
                target_compile_options(${target} PRIVATE ${_ds2_lto_compile})
            endif()
        endforeach()
        target_link_options(ds2 PRIVATE ${_ds2_lto_link})
        message(STATUS "ds2: Switch LTO on (${DS2_SWITCH_LTO_JOBS} LTRANS jobs, -fipa-pta ${DS2_SWITCH_IPA_PTA})")
    endif()
    # Entry 53 (2026-10-18): hot functions first in .text (sa2-nx's SA2_SWITCH_HOT_ORDER, nfsmw-nx's
    # orden_funciones.ld): app/hot_functions.ld from a console stack profile (tools/hot_order.py; the profile and the
    # ELF it was recorded on are kept in out/nx/keep/profiles). Only placement changes: every function has its own
    # section (-ffunction-sections, also on the LTO link). The file starts with KEEP(*(.crt0)): the start-up code must
    # stay at address 0 (tools/check_switch_build.py checks it).
    option(DS2_SWITCH_HOT_ORDER "Hot functions first in .text (app/hot_functions.ld)" OFF)
    if(DS2_SWITCH_HOT_ORDER AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/hot_functions.ld")
        target_link_options(ds2 PRIVATE "-Wl,--section-ordering-file,${CMAKE_CURRENT_SOURCE_DIR}/hot_functions.ld")
        set_property(TARGET ds2 APPEND PROPERTY LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/hot_functions.ld")
        message(STATUS "ds2: hot function order on (app/hot_functions.ld)")
    endif()
    # Entry 54 (2026-10-19): profile-guided optimisation, as sa2-nx's SA2_PGO (game code and app, like LTO):
    #   DS2_PGO=generate  an instrumented NRO that writes its branch counts to pgo/ next to the NRO (src/ds2_pgo.cpp;
    #                     registered in a section, -fprofile-info-section=gcov_info: libgcov's exit-time files do not
    #                     fit the Switch). Value profiling off: its shared lists are not safe without atomic updates.
    #   DS2_PGO=use       the counts merged on the PC (tools/win/pgo_merge.ps1 <folder with the .stream files>).
    #                     Code the sessions did not run is compiled as without a profile (-fprofile-partial-training);
    #                     functions changed since the instrumented build keep no profile (-Wno-coverage-mismatch).
    # The profile is pgo/ at the root of the repository (DS2_PGO_DIR): one .gcda per object, named by its path in the
    # build folder (-fprofile-prefix-path, the build folder written the Windows way, as GCC sees it).
    set(DS2_PGO "" CACHE STRING "Profile-guided optimisation of the Switch build: empty, generate or use")
    set_property(CACHE DS2_PGO PROPERTY STRINGS "" generate use)
    set(DS2_PGO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../pgo" CACHE PATH "Folder of the PGO profile (.gcda files)")
    get_filename_component(_ds2_pgo_dir "${DS2_PGO_DIR}" ABSOLUTE)
    file(TO_NATIVE_PATH "${_ds2_pgo_dir}" _ds2_pgo_dir)
    file(TO_NATIVE_PATH "${CMAKE_BINARY_DIR}" _ds2_pgo_prefix)
    if(DS2_PGO STREQUAL "generate")
        set(_ds2_pgo "-fprofile-generate=${_ds2_pgo_dir}" "-fprofile-prefix-path=${_ds2_pgo_prefix}"
                     -fno-profile-values -fprofile-update=single -fprofile-info-section=gcov_info)
        target_compile_definitions(ds2 PRIVATE DS2_PGO_GENERATE=1)
    elseif(DS2_PGO STREQUAL "use")
        if(NOT EXISTS "${DS2_PGO_DIR}")
            message(FATAL_ERROR "DS2_PGO=use: no profile in ${DS2_PGO_DIR}")
        endif()
        # -fprofile-correction: counts taken without atomic updates while several game threads ran the same code.
        set(_ds2_pgo "-fprofile-use=${_ds2_pgo_dir}" "-fprofile-prefix-path=${_ds2_pgo_prefix}" -fprofile-correction
                     -fno-profile-values -fprofile-partial-training -Wno-missing-profile -Wno-coverage-mismatch)
    elseif(DS2_PGO)
        message(FATAL_ERROR "DS2_PGO must be empty, generate or use (got ${DS2_PGO})")
    endif()
    if(DS2_PGO)
        foreach(target ds2_recomp ds2)
            if(TARGET ${target})
                target_compile_options(${target} PRIVATE ${_ds2_pgo})
            endif()
        endforeach()
        target_link_options(ds2 PRIVATE ${_ds2_pgo})
        message(STATUS "ds2: PGO ${DS2_PGO}")
    endif()
    # Inliner limits of the game code with a profile (sa2-nx's SA2_SWITCH_INLINE_AUTO / _UNIT_GROWTH, its
    # docs/cpu-rounds.md: 64/12 there cut executed calls 41 %). Compile options of ds2_recomp: GCC keeps its parameters
    # per function and the LTO inliner asks the caller's. They do not touch the recorded profile. Empty: the compiler's
    # (30 / 40 %), the verified build. DS2_SWITCH_LTO_DUMP: -fdump-ipa-inline and out/nx/ds2.map for
    # tools/lto_inline_report.py; the code is the same with and without.
    set(DS2_SWITCH_INLINE_AUTO "" CACHE STRING "max-inline-insns-auto of the game code with a profile (empty: GCC's)")
    set(DS2_SWITCH_INLINE_UNIT_GROWTH "" CACHE STRING "inline-unit-growth of the game code with a profile (empty: GCC's)")
    option(DS2_SWITCH_LTO_DUMP "The inliner's decisions of the Switch LTO link as a dump file and a link map" OFF)
    set(_ds2_inline_options "")
    if(DS2_PGO STREQUAL "use")
        if(DS2_SWITCH_INLINE_AUTO)
            list(APPEND _ds2_inline_options --param=max-inline-insns-auto=${DS2_SWITCH_INLINE_AUTO})
        endif()
        if(DS2_SWITCH_INLINE_UNIT_GROWTH)
            list(APPEND _ds2_inline_options --param=inline-unit-growth=${DS2_SWITCH_INLINE_UNIT_GROWTH})
        endif()
    endif()
    if(_ds2_inline_options)
        target_compile_options(ds2_recomp PRIVATE ${_ds2_inline_options})
    endif()
    message(STATUS "ds2: game code inliner options '${_ds2_inline_options}'")
    if(DS2_SWITCH_LTO_DUMP)
        target_link_options(ds2 PRIVATE -fdump-ipa-inline "-Wl,-Map,${CMAKE_CURRENT_BINARY_DIR}/ds2.map")
    endif()
    # The homebrew menu entry. No icon of our own yet: libnx's default one.
    rexglue_switch_add_nro(ds2
        NAME "Dark Souls II: Scholar of the First Sin (ds2scholar-nx)"
        AUTHOR "ds2scholar-nx"
        VERSION "1.10.0-access1")
endif()
