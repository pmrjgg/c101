# Profiling and compiler recipes

## Linux perf

```bash
perf record -F 999 --call-graph dwarf -o perf.data ./app args      # DWARF unwinding: works without frame pointers, big files
perf record -F 999 -g ./app                                          # frame-pointer stacks: build with -fno-omit-frame-pointer
perf report --stdio --no-children --percent-limit 2 | head -60       # self time per symbol
perf annotate --stdio <symbol> | head -80                            # hot instructions inside one function
perf stat -e cycles,instructions,branches,branch-misses,L1-dcache-load-misses,LLC-load-misses ./app
perf stat -r 10 ./app                                                # 10 runs, mean and variance
perf stat -I 1000 -e cycles,instructions -p <pid>                    # 1 s intervals on a live process
perf c2c record ./app && perf c2c report --stdio | head -80          # false sharing: look for HITM lines
```

Unprivileged use depends on `/proc/sys/kernel/perf_event_paranoid`; changing it needs root, so
report it as an Open doubt instead of running sudo. In containers hardware counters are often
missing: `perf stat` prints `<not supported>`. Write full reports to `.stack/out/<agent>/` and quote
only the top rows.

Reading `perf stat`: IPC = instructions / cycles; misses per element = misses / items processed.
Compare two variants with the same event list and the same input; a change that lowers time but
raises instructions usually moved work into fewer, wider instructions (vectorization) or removed
stalls.

## Intel VTune, AMD uProf

```bash
vtune -collect hotspots -r r_hot -- ./app args
vtune -collect uarch-exploration -r r_uarch -- ./app args   # top-down: front-end, bad speculation, back-end, retiring
vtune -collect memory-access -r r_mem -- ./app args
vtune -report hotspots -r r_hot -format csv > .stack/out/<agent>/hotspots.csv
vtune -report summary -r r_uarch
```

AMD uProf offers the equivalent hotspot and pipeline analyses on Zen; on Linux `perf stat --topdown`
or `perf stat -M TopdownL1` (newer perf, CPU-dependent) gives the level-1 breakdown without VTune.

## macOS: Instruments from the command line

```bash
xcrun xctrace record --template 'Time Profiler' --output run.trace --launch -- ./app args
xcrun xctrace record --template 'CPU Counters' --time-limit 60s --output cc.trace --launch -- ./app
xcrun xctrace record --template 'Allocations' --output alloc.trace --launch -- ./app
xcrun xctrace export --input run.trace --toc                      # list tables, then --xpath to export one
xcrun xctrace list templates
```

Apple silicon mixes performance and efficiency cores and has no user CPU pinning: warm up before
timing, interleave variants, and confirm with repetitions (section 1 of the main skill).

## Tracy (instrumented timeline)

```cmake
FetchContent_Declare(tracy GIT_REPOSITORY https://github.com/wolfpld/tracy.git GIT_TAG <release tag or sha>)
FetchContent_MakeAvailable(tracy)
target_link_libraries(app PRIVATE Tracy::TracyClient)
# configure with -DTRACY_ENABLE=ON (default OFF: the macros then compile to nothing)
```

```cpp
#include <tracy/Tracy.hpp>
void step(World& w) {
    ZoneScoped;                         // one zone per call, named after the function
    { ZoneScopedN("collide"); collide(w); }
    FrameMark;                          // once per frame / tick
}
```

Viewer: the Tracy profiler GUI (humans). Headless: `tracy-capture -o run.tracy` while the app runs,
then `tracy-csvexport run.tracy > .stack/out/<agent>/zones.csv`. `TRACY_ON_DEMAND` only profiles
while a client is connected; `TracyAlloc(ptr, size)` / `TracyFree(ptr)` track allocations.

## Allocation and cache tools

```bash
heaptrack ./app args                                     # writes heaptrack.app.<pid>.zst
heaptrack_print heaptrack.app.*.zst > .stack/out/<agent>/heaptrack.txt   # read MOST CALLS, PEAK MEMORY
valgrind --tool=massif ./app && ms_print massif.out.<pid> | head -60     # heap over time
valgrind --tool=cachegrind ./app && cg_annotate cachegrind.out.<pid> | head -60
```

`heaptrack_gui` and KCachegrind are for humans; agents read the text output.

## A minimal timing harness (when Google Benchmark is unavailable)

This is the structure behind the worked example's numbers: warm-up, interleaved variants, median
of N per round, best median over rounds.

```cpp
template <class F> double median_ns_per_item(F&& f, std::size_t items, int reps) {
    std::vector<double> t;
    for (int r = 0; r < reps; ++r) {
        const auto a = std::chrono::steady_clock::now();
        f();
        const auto b = std::chrono::steady_clock::now();
        t.push_back(std::chrono::duration<double, std::nano>(b - a).count() / double(items));
    }
    std::sort(t.begin(), t.end());
    return t[t.size() / 2];
}
// main: run the kernel for 500 ms first, then 3 rounds of {variant A, B, C}, keep min of medians;
// print a checksum of the outputs so the work cannot be optimized away.
```

## Profile-guided and post-link optimization pipelines

| Step | Clang (IR PGO) | GCC |
|---|---|---|
| instrument | `-fprofile-generate` | `-fprofile-generate` (`-fprofile-update=atomic` with threads) |
| train | run representative inputs; `LLVM_PROFILE_FILE=prof/%p-%m.profraw` | run; `.gcda` files land next to objects (`-fprofile-dir=`) |
| merge | `llvm-profdata merge -output=app.profdata prof/*.profraw` | automatic |
| optimize | `-fprofile-use=app.profdata` | `-fprofile-use` (`-fprofile-partial-training`) |

`LLVM_PROFILE_FILE` patterns: `%p` process id, `%h` host name, `%m` binary signature (processes
of the same binary merge at dump time), `%b` build id, `%c` continuous mode.

AutoFDO (sampling, no instrumented build): `perf record -b -e cycles:u -- ./app` (LBR), then
`create_llvm_prof --binary=./app --profile=perf.data --out=app.prof` (google/autofdo; add
`--use_lbr=false` for non-LBR data) or `llvm-profgen`, then build with `-fprofile-sample-use=app.prof`
plus `-fdebug-info-for-profiling -funique-internal-linkage-names`, keeping the same debug options.

BOLT (after PGO and LTO, ELF x86-64/AArch64): link with `-Wl,--emit-relocs`; `perf record -e
cycles:u -j any,u -o perf.data -- ./app`; `perf2bolt -p perf.data -o perf.fdata ./app` (add `-ba`
when the profile has no branch stacks); `llvm-bolt ./app -o app.bolt -data=perf.fdata
-reorder-blocks=ext-tsp -reorder-functions=cdsort -split-functions -split-all-cold -split-eh
-dyno-stats`. Benchmark `app.bolt` against `app` with the same harness.

LTO in CMake: `include(CheckIPOSupported)`, `check_ipo_supported(RESULT ok OUTPUT msg)`, then
`set_property(TARGET app PROPERTY INTERPROCEDURAL_OPTIMIZATION ON)` or the
`CMAKE_INTERPROCEDURAL_OPTIMIZATION` cache variable in a release preset (CMake uses `-flto=thin`
for Clang 3.9+ and `-flto=auto` for GCC 10.1+). Static libraries built with LTO contain bitcode or
GIMPLE: link them with the same compiler family and use `gcc-ar`/`llvm-ar` when archiving by hand.

## Compile-time profiling

`clang++ -ftime-trace` writes a JSON per TU next to the object; open it in Perfetto or
chrome://tracing, or aggregate many with ClangBuildAnalyzer. Usual fixes: precompiled headers,
forward declarations, `extern template` for common instantiations, splitting heavy headers,
C++20 modules for leaf libraries.
