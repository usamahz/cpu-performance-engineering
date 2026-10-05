# CPU Performance Engineering

![](misc/banner-pinnacle-ridge.avif)

[![Links](https://github.com/usamahz/cpu-performance-engineering/actions/workflows/links.yml/badge.svg)](https://github.com/usamahz/cpu-performance-engineering/actions/workflows/links.yml) [![Quality](https://github.com/usamahz/cpu-performance-engineering/actions/workflows/quality.yml/badge.svg)](https://github.com/usamahz/cpu-performance-engineering/actions/workflows/quality.yml) [![Entries](https://img.shields.io/badge/entries-304-1f6feb)](#contents) [![Benchmarks](https://img.shields.io/badge/benchmarks-14%20runnable-1f6feb)](misc/benchmarks/README.md) [![MCP](https://img.shields.io/badge/MCP-server-1f6feb)](misc/mcp/README.md) [![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE) [![Stars](https://img.shields.io/github/stars/usamahz/cpu-performance-engineering?style=flat&color=555)](https://github.com/usamahz/cpu-performance-engineering/stargazers)

Making a program fast on a modern CPU means knowing what the core does with
each instruction, where the time actually goes, and how to prove a change
helped. This is the reading that gets you there, in the order that makes the
next piece legible.

**Scope.** x86 and Arm server parts, from one instruction through to serving
a model on CPU. Not language runtimes, database internals, or anything above
the socket.

**Evidence.** Primary sources only: the paper, the specification, the vendor
manual, the repository, or a report by the person who did the work. Any
number, anywhere in this repository, carries all seven fields set out in
[What earns a place](#what-earns-a-place), or it is not quoted.

**Proof.** Fourteen of the sections end in a benchmark under
[misc/benchmarks/](misc/benchmarks/README.md): C source, the build line, the
machine, the raw numbers and the analysis, all committed. Run them yourself.

**Plug it in.** The MCP server in [misc/mcp/](misc/mcp/README.md) turns
this list into a CPU performance brain inside any AI client: the reading
order, every rejected candidate with the rule it failed, every benchmark,
and an index of the linked sources built on the reader's own machine. Point
it at real work and the answers quote those sources and cite them. With
[uv](https://docs.astral.sh/uv/) installed, one command adds it.

**Claude Code**

```sh
claude mcp add --scope user cpu-perf -- uvx cpu-perf
```

**Codex**

```sh
codex mcp add cpu-perf -- uvx cpu-perf
```

Claude Desktop, Cursor and VS Code take a few lines of config, given in
[Connect it](misc/mcp/README.md#connect-it).

Section 1 is a path through the rest; read it top to bottom before using the
numbered sections as a reference.

## Contents

- [1. Start here](#1-start-here)
- [2. One instruction, end to end](#2-one-instruction-end-to-end)
  - [Fetch and decode](#fetch-and-decode)
  - [Rename and issue](#rename-and-issue)
  - [Execute](#execute)
  - [Memory access and retire](#memory-access-and-retire)
- [3. Microarchitecture](#3-microarchitecture)
  - [Limits of ILP and SMT](#limits-of-ilp-and-smt)
  - [Branch prediction and speculation](#branch-prediction-and-speculation)
  - [Vendor estimates and measured tables](#vendor-estimates-and-measured-tables)
  - [What the manuals leave out](#what-the-manuals-leave-out)
- [4. Memory hierarchy](#4-memory-hierarchy)
  - [Cache geometry, replacement and misses in flight](#cache-geometry-replacement-and-misses-in-flight)
  - [TLBs, page walks and prefetchers](#tlbs-page-walks-and-prefetchers)
  - [Store buffers, ordering and cache-line contention](#store-buffers-ordering-and-cache-line-contention)
  - [Struct layout, software prefetch and page size](#struct-layout-software-prefetch-and-page-size)
- [5. Measurement](#5-measurement)
  - [Method and the whole-system view](#method-and-the-whole-system-view)
  - [Counters, events and precise sampling](#counters-events-and-precise-sampling)
  - [CPU profilers and flame graphs](#cpu-profilers-and-flame-graphs)
  - [Microbenchmarks that lie](#microbenchmarks-that-lie)
- [6. Models](#6-models)
  - [Roofline and the execution-cache-memory model](#roofline-and-the-execution-cache-memory-model)
  - [Top-down analysis](#top-down-analysis)
  - [Scaling laws](#scaling-laws)
  - [Queueing](#queueing)
- [7. Single-thread optimisation](#7-single-thread-optimisation)
  - [Data layout and loop transforms](#data-layout-and-loop-transforms)
  - [SIMD instruction sets](#simd-instruction-sets)
  - [SIMD libraries and measured kernels](#simd-libraries-and-measured-kernels)
  - [Branchless code and bit manipulation](#branchless-code-and-bit-manipulation)
- [8. Compilers and codegen](#8-compilers-and-codegen)
  - [Reading emitted code](#reading-emitted-code)
  - [Optimisation levels, inlining and link time](#optimisation-levels-inlining-and-link-time)
  - [Target flags and auto-vectorisation](#target-flags-and-auto-vectorisation)
  - [Profile-guided and post-link optimisation](#profile-guided-and-post-link-optimisation)
- [9. Concurrency](#9-concurrency)
  - [Memory models and atomics](#memory-models-and-atomics)
  - [Locks, contention and allocators](#locks-contention-and-allocators)
  - [Lock-free structures and RCU](#lock-free-structures-and-rcu)
  - [Thread pools and work stealing](#thread-pools-and-work-stealing)
- [10. NUMA and multi-socket](#10-numa-and-multi-socket)
  - [NUMA and Linux memory placement](#numa-and-linux-memory-placement)
  - [Topology and interconnects](#topology-and-interconnects)
  - [Migration, balancing and measured effects](#migration-balancing-and-measured-effects)
- [11. OS and I/O](#11-os-and-io)
  - [Syscalls and asynchronous I/O](#syscalls-and-asynchronous-io)
  - [Scheduling, affinity and isolation](#scheduling-affinity-and-isolation)
  - [Interrupts and kernel bypass](#interrupts-and-kernel-bypass)
  - [Cache and bandwidth partitioning](#cache-and-bandwidth-partitioning)
- [12. Tail latency and production systems](#12-tail-latency-and-production-systems)
  - [Measuring the tail](#measuring-the-tail)
  - [Where jitter comes from](#where-jitter-comes-from)
  - [Load generation and production workloads](#load-generation-and-production-workloads)
  - [Mechanical sympathy](#mechanical-sympathy)
- [13. Inference on CPU](#13-inference-on-cpu)
  - [GEMM and BLAS](#gemm-and-blas)
  - [Runtimes](#runtimes)
  - [Quantization](#quantization)
  - [Matrix extensions](#matrix-extensions)
  - [Threading for inference](#threading-for-inference)
  - [When CPU beats GPU](#when-cpu-beats-gpu)
- [14. Hardware generations](#14-hardware-generations)
  - [Intel Xeon](#intel-xeon)
  - [AMD EPYC](#amd-epyc)
  - [Arm Neoverse server parts](#arm-neoverse-server-parts)
  - [Independent measurement across vendors](#independent-measurement-across-vendors)
- [15. Benchmarks](#15-benchmarks)
  - [Standard suites](#standard-suites)
  - [Microbenchmark suites](#microbenchmark-suites)
  - [Methodology and what suites miss](#methodology-and-what-suites-miss)
- [16. Watchlist](#16-watchlist)
  - [ISA extensions without a shipped server part](#isa-extensions-without-a-shipped-server-part)
  - [Parts without a public measurement](#parts-without-a-public-measurement)
  - [Memory and interconnect](#memory-and-interconnect)
  - [Kernel paths and generated code](#kernel-paths-and-generated-code)
- [What earns a place](#what-earns-a-place)

## 1. Start here

Each entry assumes only the ones before it. The first and sixth are paid books; the third is a manual to open at the chapters its reason names.

1. [Computer Architecture: A Quantitative Approach, 7th Edition](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-443-15406-5) - Its pipelining appendix and memory chapters define the hazard, speculation and cache vocabulary the list assumes.
2. [Optimizing software in C++](https://www.agner.org/optimize/optimizing_cpp.pdf) - Maps C++ onto pipeline mechanisms and shows why a loop-carried dependency chain, not instruction count, paces a loop.
3. [Intel Optimization Reference Manual](https://www.intel.com/content/www/us/en/content-details/671488/intel-64-and-ia-32-architectures-optimization-reference-manual-volume-1.html) - Its opening chapters show how a shipping x86 core implements the textbook pipeline, each rule tied to a mechanism.
4. [What Every Programmer Should Know About Memory](https://www.akkadia.org/drepper/cpumemory.pdf) - Measures the step in cost per access at each cache boundary and the gap a prefetcher hides.
5. [Memory Barriers: a Hardware View for Software Hackers](http://www.rdrop.com/users/paulmck/scalability/paper/whymb.2010.07.23a.pdf) - Explains why a second core makes loads and stores reorder and what a barrier drains.
6. [Systems Performance: Enterprise and the Cloud, 2nd Edition](https://www.brendangregg.com/systems-performance-2nd-edition-book.html) - Puts the method before the tools: what to measure, in what order, and how benchmarks mislead.
7. [Roofline: An Insightful Visual Performance Model for Multicore Architectures](https://cacm.acm.org/research/roofline-an-insightful-visual-performance-model-for-multicore-architectures/) - Places a loop from a byte count and a datasheet bandwidth alone, before any counter is read.
8. [A Top-Down Method for Performance Analysis and Counters Architecture](https://sites.google.com/site/analysismethods/yasin-pubs) - Defines the split of pipeline slots into front end, bad speculation, back end and retiring, the tree profilers report.
9. [Performance Analysis and Tuning on Modern CPUs](https://github.com/dendibakh/perf-book) - Walks from a noisy timing to counters to a named bottleneck, applying roofline and top-down to whole programs.
10. [What Has My Compiler Done for Me Lately? Unbolting the Compiler's Lid](https://www.youtube.com/watch?v=bSkpMdDe4g4) - Shows how to read emitted assembly against its source, so each mechanism is checked in a listing, not assumed.

Work the exercises in [Performance Ninja](https://github.com/dendibakh/perf-ninja) alongside them; reading alone will not build the instinct.

Reproduce it: [misc/benchmarks/04-cache-latency](misc/benchmarks/04-cache-latency/README.md), the cost per dependent load stepping up at each cache boundary, the curve the fourth entry measures.

## 2. One instruction, end to end

Vendors name the same structures differently (Intel's decoded ICache is AMD's op cache, and AMD's macro-op is Arm's MOP), so the stage names below are generic.

### Fetch and decode

- [Fetch Directed Instruction Prefetching](https://cseweb.ucsd.edu/~calder/papers/MICRO-99-FDP.pdf) - The origin of the decoupled front end, where the predictor runs ahead of fetch and drives instruction prefetch.
- [Micro-Operation Cache: A Power Aware Frontend for Variable Instruction Length ISA](https://ieeexplore.ieee.org/document/945363) - Introduces the decoded micro-op cache and its power case, the structure both x86 vendors later built.
- [Software Optimization Guide for the AMD Zen5 Microarchitecture](https://docs.amd.com/v/u/en-US/58455_1.00) - Where AMD states when the op cache feeds micro-ops, and the fusion and alignment rules for hot loops.
- [The microarchitecture of Intel, AMD, and VIA CPUs](https://www.agner.org/optimize/microarchitecture.pdf) - Measures rather than quotes each x86 core's misprediction penalty, micro-op cache and loop buffer behaviour.
- [Intel Mitigations for Jump Conditional Code Erratum](https://www.intel.com/content/www/us/en/content-details/841076/intel-mitigations-for-jump-conditional-code-erratum.html) - States what a microcode fix evicts from the decoded cache and which counters show the fall back to legacy decode.
- [Composite Instruction Prefetching](https://doi.org/10.1109/ICCD56317.2022.00076) - Establishes how complementary instruction prefetchers can be combined rather than selecting a single design.

Reproduce it: [misc/benchmarks/02-branch-misprediction](misc/benchmarks/02-branch-misprediction/README.md), the cost of a mispredicted branch, sorted against unsorted against branchless.

### Rename and issue

- [An Efficient Algorithm for Exploiting Multiple Arithmetic Units](https://ieeexplore.ieee.org/document/5392028) - The origin of tag-based renaming and reservation stations, from which every out-of-order issue queue descends.
- [Optimizing subroutines in assembly language](https://www.agner.org/optimize/optimizing_assembly.pdf) - Shows which chains renaming cannot break, from partial registers to flags, and the zero-cost idioms that do.
- [Measuring Reorder Buffer Capacity](https://blog.stuffedcow.net/2013/05/measuring-rob-capacity/) - Sets the user-space method that measures the window and register files, and which idioms take no physical register.

### Execute

- [Focusing Processor Policies via Critical-Path Prediction](https://dl.acm.org/doi/10.1145/379240.379253) - Defines the dependence graph of an out-of-order core and the critical path through it that sets run time.
- [Instruction tables: latencies, throughputs and micro-operation breakdowns](https://www.agner.org/optimize/instruction_tables.pdf) - Measures latency, reciprocal throughput and port assignment per instruction, the weights a dependence graph needs.
- [Arm Neoverse V2 Core Software Optimization Guide](https://support.arm.com/documentation/109898/latest/) - States every stage of one Arm core from fetch to issue, then per-instruction latency, throughput and pipe assignment.
- [Entropy Decoding in Oodle Data: x86-64 3-Stream Huffman Decoders](https://fgiesen.wordpress.com/2022/09/05/entropy-decoding-in-oodle-data-x86-64-3-stream-huffman-decoders/) - Predicts a real decoder loop's cycle count from its carried chain and issue slots, then measures the prediction.
- [Faster zlib/DEFLATE decompression on the Apple M1 (and x86)](https://dougallj.wordpress.com/2022/08/20/faster-zlib-deflate-decompression-on-the-apple-m1-and-x86/) - Predicts a decoder's refill chain from Arm core latencies, fits extra work under it, and measures the gain.

### Memory access and retire

- [Memory Dependence Prediction using Store Sets](https://people.csail.mit.edu/emer/media/papers/1990s/1998/1998.06.isca.storesets.pdf) - The origin of memory dependence prediction, which lets a load pass older stores and flushes on a wrong guess.
- [Store-to-Load Forwarding and Memory Disambiguation in x86 Processors](https://blog.stuffedcow.net/2014/01/x86-memory-disambiguation/) - Measures which store and load size and offset pairs forward or stall, and which cores predict memory dependences.
- [Microarchitecture Optimizations for Exploiting Memory-Level Parallelism](https://ieeexplore.ieee.org/document/1310765) - Defines memory-level parallelism as the misses one window overlaps, and shows which core limits cap it.
- [Implementing Precise Interrupts in Pipelined Processors](https://ieeexplore.ieee.org/document/4607) - Introduces the reorder buffer and defines a precise exception as in-order commit of out-of-order results.
- [Where Do Interrupts Happen?](https://travisdowns.github.io/blog/2019/08/20/interrupts.html) - Measures that an interrupt lands on the oldest unretired instruction, which decides what a sampling profiler blames.

## 3. Microarchitecture

Where a design paper, the vendor manual and a measurement disagree about a core, the measurement is the one to trust and re-run.

### Limits of ILP and SMT

- [The MIPS R10000 Superscalar Microprocessor](https://ieeexplore.ieee.org/document/491460) - Shows rename, the active list and precise branch recovery fitted together in one shipped out-of-order core.
- [Limits of Instruction-Level Parallelism (WRL Research Report 93/6)](https://davidwall.info/papers/WRL-TR-93.6.pdf) - Separates perfect from realistic prediction, renaming and aliasing, and shows how little ILP survives the real ones.
- [Complexity-Effective Superscalar Processors](https://ftp.cs.wisc.edu/sohi/papers/1997/isca.complexity.pdf) - Puts circuit delay on wakeup, select and bypass, capping issue width and window size before ILP runs out.
- [Simultaneous Multithreading: Maximizing On-Chip Parallelism](https://cseweb.ucsd.edu/~tullsen/isca95.pdf) - The origin of SMT, where another thread fills one thread's idle issue slots at a cost to both.
- [A Mechanistic Performance Model for Superscalar Out-of-Order Processors](https://users.elis.ugent.be/~leeckhou/papers/tocs09.pdf) - Turns window size, issue width and miss events into cycles lost, making an ILP limit a cycle count.

### Branch prediction and speculation

- [A Case for (Partially) TAgged GEometric History Length Branch Prediction](https://jilp.org/vol8/v8paper1.pdf) - Defines the tagged geometric-history predictor shipped designs converge on, and the limit of what it can learn.
- [A 64-Kbytes ITTAGE indirect branch predictor](https://jilp.org/jwac-2/program/cbp3_07_seznec.pdf) - Carries the tagged geometric scheme to indirect jumps and calls, where interpreters and virtual dispatch stall.
- [Characterizing the Branch Misprediction Penalty](https://users.elis.ugent.be/~leeckhou/papers/ispass06-eyerman.pdf) - Defines the penalty as pipeline refill plus window drain, so it exceeds pipeline depth and is not constant.
- [Spectre Attacks: Exploiting Speculative Execution](https://arxiv.org/abs/1801.01203) - Establishes that predictor state is shared and trainable across contexts, the root of every mitigation and its cost.
- [Speculative Execution Side Channel Mitigations](https://www.intel.com/content/www/us/en/developer/articles/technical/software-security-guidance/technical-documentation/speculative-execution-side-channel-mitigations.html) - Defines the indirect-branch and store-bypass controls (IBRS, STIBP, IBPB, SSBD) and states which carry a large cost.

### Vendor estimates and measured tables

- [Software Optimization Guide for the AMD Zen5 Microarchitecture](https://docs.amd.com/v/u/en-US/58455_1.00) - Calls its own latency spreadsheet an estimate and lists its assumptions, the vendor claim the measured tables check.
- [The microarchitecture of Intel, AMD, and VIA CPUs](https://www.agner.org/optimize/microarchitecture.pdf) - States where measured predictor, op cache and port findings disagree with the vendor's account of an x86 core.
- [Instruction tables: latencies, throughputs and micro-operation breakdowns](https://www.agner.org/optimize/instruction_tables.pdf) - States why its measured figures differ from the vendor's and names which latencies cannot be measured accurately.
- [uops.info](https://uops.info/) - Where each latency, throughput and port entry links to its microbenchmark, so any value can be re-run.
- [applecpu: Firestorm Overview](https://dougallj.github.io/applecpu/firestorm.html) - Measured per-instruction tables for an Apple AArch64 core, each entry linked to the counter experiment behind it.

### What the manuals leave out

- [Performance Speed Limits](https://travisdowns.github.io/blog/2019/06/11/speed-limits.html) - Sets the method for finding which hard bound binds a loop, testing its cycles against each in turn.
- [uiCA: Accurate Throughput Prediction of Basic Blocks on Recent Intel Microarchitectures](https://arxiv.org/abs/2107.14210) - Models the predecoder, decoders, micro-op cache and loop buffer closely enough to predict front-end bound loops.
- [Gathering Intel on Intel AVX-512 Transitions](https://travisdowns.github.io/blog/2020/01/17/avxfreq1.html) - Measures what the vendor leaves untimed in an AVX-512 licence change, a throttled phase then a frequency step.
- [Hardware Store Elimination](https://travisdowns.github.io/blog/2020/05/13/intel-zero-opt.html) - Finds an undocumented optimisation by its counter signature and bandwidth, and sets the method for what manuals omit.

Reproduce it: [misc/benchmarks/03-latency-vs-throughput](misc/benchmarks/03-latency-vs-throughput/README.md), one dependency chain against eight independent accumulators.

## 4. Memory hierarchy

Line size and page size are machine parameters, not constants, so every padding and alignment rule below is applied against the target's own values.

### Cache geometry, replacement and misses in flight

- [What Every Programmer Should Know About Memory](https://www.akkadia.org/drepper/cpumemory.pdf) - One measured account of DRAM timing, cache geometry, TLBs and prefetchers that sets the padding and prefetch rules.
- [Measuring Cache and TLB Performance and Their Effect on Benchmark Run Times](https://www2.eecs.berkeley.edu/Pubs/TechRpts/1993/Archive/CSD-93-767.pdf) - The origin of the strided-loop method that recovers cache and TLB size, line size, associativity and miss cost.
- [Achieving Non-Inclusive Cache Performance with Inclusive Caches](https://www.jaleels.org/ajaleel/publications/micro2010-tla.pdf) - Names inclusion victims as the cost of an inclusive last-level cache, the case for non-inclusive and victim designs.
- [Adaptive Insertion Policies for High Performance Caching](https://dl.acm.org/doi/10.1145/1250662.1250709) - The origin of set duelling and bimodal insertion, the adaptive replacement that survives a streaming pass.
- [Lockup-Free Instruction Fetch/Prefetch Cache Organization](https://dl.acm.org/doi/10.1145/285930.285979) - Origin of the lockup-free cache, whose miss-status registers keep misses in flight, so a stream beats a chase.
- [Dynamic Set Stealing to Improve Cache Performance](https://doi.org/10.1109/SBAC-PAD55451.2022.00017) - Introduces dynamic set stealing as a cache-management mechanism beyond insertion and replacement within a fixed set.

Reproduce it: [misc/benchmarks/04-cache-latency](misc/benchmarks/04-cache-latency/README.md), dependent-load latency from L1 to DRAM, with and without TLB pressure.

### TLBs, page walks and prefetchers

- [Intel SDM Volume 3A: System Programming Guide, Part 1](https://www.intel.com/content/www/us/en/content-details/671190/intel-64-and-ia-32-architectures-software-developer-s-manual-volume-3a-system-programming-guide-part-1.html) - Fixes the paging walk, the page-walk caches, the TLB invalidation rules and what each memory type permits.
- [Translation Caching: Skip, Don't Walk (the Page Table)](https://www.cs.rice.edu/CS/Architecture/docs/barr-isca10.pdf) - Defines the page-walk cache design space and shows why cached partial translations let a walk skip page-table levels.
- [Improving Direct-Mapped Cache Performance](https://ieeexplore.ieee.org/document/134547) - The origin of the stream buffer that every vendor stream prefetcher descends from, and of the victim cache.
- [Intel Optimization Reference Manual Volume 1](https://www.intel.com/content/www/us/en/content-details/671488/intel-64-and-ia-32-architectures-optimization-reference-manual-volume-1.html) - Names each prefetcher and what trains it, and which stop at a page boundary and which cross it.
- [Arm Neoverse V2 Core Technical Reference Manual](https://support.arm.com/documentation/102375/latest/) - Names an Arm server core's load-side and store-side prefetchers, its TLB levels and the bits that disable them.
- [CHiRP: Control-Flow History Reuse Prediction](https://people.engr.tamu.edu/djimenez/pdfs/CHiRP_MICRO2020_CameraReady.pdf) - Uses control-flow history to predict translation reuse and guide replacement in the TLB.

### Store buffers, ordering and cache-line contention

- [Memory Barriers: a Hardware View for Software Hackers](http://www.rdrop.com/users/paulmck/scalability/paper/whymb.2010.07.23a.pdf) - Derives store buffers and invalidate queues from the cost of coherence, the reason reordering exists at all.
- [x86-TSO: A Rigorous and Usable Programmer's Model for x86 Multiprocessors](https://www.cl.cam.ac.uk/~pes20/weakmemory/cacm.pdf) - The store-buffer model of Intel and AMD ordering, tested on hardware, fixing which reorderings a fence pays for.
- [Simplifying ARM Concurrency: Multicopy-Atomic Axiomatic and Operational Models for ARMv8](https://www.cl.cam.ac.uk/~pes20/armv8-mca/) - The formal model Arm adopted into its architecture, and the record of why the non-multicopy-atomic option was dropped.
- [Everything You Always Wanted to Know About Synchronization but Were Afraid to Ask](https://sigops.org/s/conferences/sosp/2013/papers/p33-david.pdf) - Measures line-transfer cost between cores by coherence state and distance, the figure behind every contention rule.
- [C2C - False Sharing Detection in Linux Perf](https://joemario.github.io/blog/2016/09/01/c2c-blog/) - The implementers' account of perf c2c, whose worked example reads contended lines, offsets and callers off the report.

### Struct layout, software prefetch and page size

- [Cache-Conscious Structure Definition](https://www.microsoft.com/en-us/research/publication/cache-conscious-structure-definition-2/) - Introduces and measures structure splitting and field reordering on real programs, the origin of hot-cold layout rules.
- [CppCon 2014: Data-Oriented Design and C++](https://www.youtube.com/watch?v=rX0ItVEVjHc) - Argues from cache-line utilisation arithmetic that layout must follow the access pattern, the case behind structure of arrays.
- [dwarves (pahole)](https://github.com/acmel/dwarves) - Prints a struct's holes, padding and cache-line boundaries from DWARF, so a layout is seen rather than guessed.
- [When Prefetching Works, When It Doesn't, and Why](https://faculty.cc.gatech.edu/~hyesoon/lee_taco12.pdf) - Sorts software prefetch into the cases where it helps and hurts, and shows how it mistrains hardware prefetchers.
- [Transparent Hugepage Support](https://docs.kernel.org/admin-guide/mm/transhuge.html) - The kernel's statement of THP: the enabled and defrag knobs, khugepaged, and the counters showing what was obtained.
- [Coordinated and Efficient Huge Page Management with Ingens](https://www.usenix.org/conference/osdi16/technical-sessions/presentation/kwon) - Measures the fault latency, memory bloat and unfairness that eager THP promotion causes, and shows what removes them.

## 5. Measurement

Cloud instances often virtualise the hardware counters away and macOS runs no Linux perf, so perf stat has to show a non-zero cycles count before any counter entry below is trusted.

### Method and the whole-system view

- [The USE Method](https://www.brendangregg.com/usemethod.html) - Sets the checklist that finds the saturated resource before any profiler is opened.
- [Performance Analysis and Tuning on Modern CPUs](https://github.com/dendibakh/perf-book) - Draws the line between counting, sampling, instrumentation and tracing, so a question is matched to its tool.
- [BPF Performance Tools](https://www.brendangregg.com/bpf-performance-tools-book.html) - The reference for time a CPU sampler cannot see, off-CPU, scheduler and I/O waits, traced at bounded cost.
- [bpftrace](https://github.com/bpftrace/bpftrace) - Makes a tracing hypothesis a one-line experiment over kprobes, uprobes, tracepoints and PMU events.
- [Google-Wide Profiling: A Continuous Profiling Infrastructure for Data Centers](https://research.google/pubs/google-wide-profiling-a-continuous-profiling-infrastructure-for-data-centers/) - The design continuous profilers descend from, always-on sampling across a fleet, cheap enough to leave running.

### Counters, events and precise sampling

- [perf_event_open(2)](https://man7.org/linux/man-pages/man2/perf_event_open.2.html) - Defines the counting and sampling modes every Linux profiler uses, and the sample record fields, branch stack included.
- [Instruction-Based Sampling: A New Performance Analysis Technique](https://www.amd.com/content/dam/amd/en/documents/archived-tech-docs/white-papers/AMD_IBS_paper_EN.pdf) - Defines skid, why a sample lands after the culprit, and how tagging one op through the pipeline removes it.
- [Intel Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) - Defines the architectural counters, what a PEBS sample captures, and why rdtsc counts time, not cycles, under DVFS.
- [Processor Programming Reference for AMD Family 1Ah Model 02h](https://docs.amd.com/v/u/en-US/57238) - Defines the event encodings and IBS registers for one Zen core, the tables perf's AMD events are derived from.
- [perf-arm-spe(1)](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/tools/perf/Documentation/perf-arm-spe.txt) - Defines Arm SPE as perf drives it, one sampled op in flight, the filters, and what a record holds.

### CPU profilers and flame graphs

- [Linux perf wiki: Tutorial](https://perfwiki.github.io/main/tutorial/) - The maintainers' walk from perf stat to perf record to perf annotate, with the sample fields each flag sets.
- [Intel VTune Profiler Documentation](https://www.intel.com/content/www/us/en/developer/tools/oneapi/vtune-profiler-documentation.html) - Home of the user guide and cookbook, where each hardware analysis is defined by the events behind it.
- [AMD uProf User Guide](https://docs.amd.com/r/en-US/57368-uProf-user-guide) - The vendor's reference for IBS-driven profiling on Zen, with metric presets defined per core generation.
- [The Flame Graph](https://queue.acm.org/detail.cfm?id=2927301) - Records the design decisions, width as sample share and alphabetical rather than time order, behind its reading rules.
- [Coz: Finding Code that Counts with Causal Profiling](https://arxiv.org/abs/1608.03676) - Proves a hot function need not be worth optimising, by measuring what speeding up a line does to end-to-end time.

### Microbenchmarks that lie

- [Producing Wrong Data Without Doing Anything Obviously Wrong!](https://sape.inf.usi.ch/publications/asplos09) - The origin of measurement bias as a term, link order and environment size alone flipping a compiler flag comparison.
- [Non-Determinism and Overcount on Modern Hardware Performance Counter Implementations](https://web.eece.maine.edu/~vweaver/projects/deterministic/ispass2013_deterministic.pdf) - Traces run-to-run variation in x86 retired-instruction counts to one extra count per interrupt and per fault.
- [clock_gettime(2)](https://man7.org/linux/man-pages/man2/clock_gettime.2.html) - Defines what each clock counts, NTP-slewed or raw monotonic time, or CPU time, and the resolution call.
- [Benchmarking tips (LLVM)](https://llvm.org/docs/Benchmarking.html) - The compiler project's recipe for a quiet Linux host, governor, boost, SMT siblings, ASLR, a cpuset and tmpfs.
- [Google Benchmark User Guide](https://github.com/google/benchmark/blob/main/docs/user_guide.md) - Documents the barriers that keep the optimiser from deleting the work under test, and repetition statistics.

Reproduce it: [misc/benchmarks/05-measurement-pitfalls](misc/benchmarks/05-measurement-pitfalls/README.md), dead-code elimination, run-to-run spread, cold against warm.

## 6. Models

A roofline is a bound built from measured roofs and counted bytes, so a point above a roof means a wrong roof or a wrong byte count, not fast code.

### Roofline and the execution-cache-memory model

- [Roofline: An Insightful Visual Performance Model for Multicore Architectures](https://cacm.acm.org/research/roofline-an-insightful-visual-performance-model-for-multicore-architectures/) - Defines operational intensity as traffic past the caches, and the ceilings that say which optimisation can pay.
- [Applying the Roofline Model](https://spiral.ece.cmu.edu/pub-spiral/pubfile/ispass-2013_177.pdf) - States the counter set and method that put a measured point on the plot in place of a hand-counted intensity.
- [LIKWID](https://github.com/RRZE-HPC/likwid) - Measures the roofs with likwid-bench and the point from likwid-perfctr groups on Intel, AMD and Arm server cores.
- [Cache-aware Roofline model: Upgrading the loft](https://ieeexplore.ieee.org/document/6506838) - Adds a roof per cache level against traffic at the core, so a kernel that hits in cache is not plotted as DRAM bound.
- [Performance bottlenecks of stencil computations using the Execution-Cache-Memory model](https://arxiv.org/abs/1410.5010) - Times each level's transfer with overlap rules, predicting a core's rate and the core count where bandwidth saturates.

Reproduce it: [misc/benchmarks/06-roofline](misc/benchmarks/06-roofline/README.md), measured roofs and three kernels of rising arithmetic intensity.

### Top-down analysis

- [A Top-Down Method for Performance Analysis and Counters Architecture](https://sites.google.com/site/analysismethods/yasin-pubs) - Defines the slot accounting that turns raw counters into a weighted tree of bottlenecks, and why the unit is a slot.
- [TMA_Metrics-full.xlsx (intel/perfmon)](https://github.com/intel/perfmon/blob/main/TMA_Metrics-full.xlsx) - The official home of every TMA formula, event, threshold and level per microarchitecture, from which toplev derives.
- [pmu-tools](https://github.com/andikleen/pmu-tools) - Runs the TMA tree on Linux from the spreadsheet and states why multiplexed levels mislead on short or varied workloads.
- [pipeline.json (perf pmu-events, amdzen4)](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/tools/perf/pmu-events/arch/x86/amdzen4/pipeline.json) - States the AMD top-down formulas in events for both levels, the metric groups perf stat runs on Zen with no vendor tool.
- [Arm CPU Telemetry Solution Topdown Methodology Specification](https://support.arm.com/documentation/109542/latest/) - Defines Arm's top-down as staged stall accounting, first locating the bottleneck and then measuring its resource.

### Scaling laws

- [Validity of the single processor approach to achieving large scale computing capabilities](https://dl.acm.org/doi/10.1145/1465482.1465560) - States the serial-fraction bound on speedup, the argument every later scaling law is written against.
- [Reevaluating Amdahl's Law](http://www.johngustafson.net/pubs/pub13/amdahl.htm) - Defines scaled speedup, the bound that holds when the problem grows with the processor count instead of staying fixed.
- [Amdahl's Law in the Multicore Era](https://research.cs.wisc.edu/multifacet/papers/ieeecomputer08_amdahl_multicore.pdf) - Extends the bound to chips of unequal cores under a fixed area budget, the arithmetic behind big and little cores.
- [A Simple Capacity Model of Massively Parallel Transaction Systems](https://www.perfdynamics.com/Papers/njgCMG93.pdf) - The origin of the coherency term that makes throughput fall, not merely flatten, as processors are added.
- [Guerrilla Capacity Planning](https://www.perfdynamics.com/iBook/gcap.html) - Derives the universal scalability law and states the procedure that fits its coefficients to measured throughput.

### Queueing

- [A Proof for the Queuing Formula: L = λW](https://pubsonline.informs.org/doi/10.1287/opre.9.3.383) - Proves occupancy equals arrival rate times time in system with no assumption on arrivals or service.
- [Quantitative System Performance](https://homes.cs.washington.edu/~lazowska/qsp/) - Origin of the bound-and-bottleneck analysis roofline names as its ancestor, and of the asymptotic bounds on throughput.
- [Performance Modeling and Design of Computer Systems](https://www.cs.cmu.edu/~harchol/PerformanceModeling/book.html) - Proves why open and closed systems answer a load question differently, and when scheduling, not capacity, sets latency.
- [Stochastic Processes Occurring in the Theory of Queues](https://projecteuclid.org/journals/annals-of-mathematical-statistics/volume-24/issue-3/Stochastic-Processes-Occurring-in-the-Theory-of-Queues-and-their-Analysis-by-the/10.1214/aoms/1177728975.full) - Origin of the A/S/c notation, and of the embedded chain that solves a queue with non-memoryless arrivals or service.
- [The single server queue in heavy traffic](https://www.cambridge.org/core/journals/mathematical-proceedings-of-the-cambridge-philosophical-society/article/abs/single-server-queue-in-heavy-traffic/81C55BC00A68FE6D5385638AA0B0AF37) - Derives the wait near saturation from utilisation and arrival and service variance, the formula behind the latency knee.

## 7. Single-thread optimisation

A loop the compiler reports as vectorised can still run at scalar speed: a float reduction stays one serial chain until reassociation is permitted.

### Data layout and loop transforms

- [Intel Optimization Reference Manual](https://www.intel.com/content/www/us/en/content-details/671488/intel-64-and-ia-32-architectures-optimization-reference-manual-volume-1.html) - Where Intel states when a structure of arrays beats an array of structures, strided and hybrid cases included.
- [ispc: A SPMD Compiler for High-Performance CPU Programming](https://pharr.org/matt/assets/ispc.pdf) - Measures one kernel in both layouts and traces the gain to the gathers the array-of-structures form forces.
- [A Data Locality Optimizing Algorithm](https://dl.acm.org/doi/10.1145/113445.113449) - Defines interchange, skewing, reversal and tiling as one family and proves when each keeps a loop nest legal.
- [The Cache Performance and Optimizations of Blocked Algorithms](https://dl.acm.org/doi/10.1145/106972.106981) - Traces the drops in a blocked loop's speed curve to self-interference misses, and shows when copying a tile pays.
- [Auto-Vectorization in LLVM](https://llvm.org/docs/Vectorizers.html) - Where LLVM lists what its loop and SLP vectorisers accept: interleaving, reductions, if-conversion and runtime checks.

Reproduce it: [misc/benchmarks/07-aos-vs-soa-simd](misc/benchmarks/07-aos-vs-soa-simd/README.md), array of structs against structure of arrays, scalar against NEON.

### SIMD instruction sets

- [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html) - Maps each intrinsic to its instruction and CPUID flag, with the vendor's latency and throughput per microarchitecture.
- [Intel Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) - The normative semantics of every Intel vector instruction, with the masking, rounding and fault rules intrinsics hide.
- [Introduction to SVE](https://support.arm.com/documentation/102476/latest/) - Where Arm explains vector-length-agnostic loops and predication, the model that removes remainder loops entirely.
- [Arm C Language Extensions](https://arm-software.github.io/acle/) - The specification the NEON and SVE intrinsics come from, so it settles what a compiler must accept and what is a bug.
- [Arm Architecture Reference Manual for A-profile architecture](https://support.arm.com/documentation/ddi0487/latest/) - The normative definition of NEON, SVE and SVE2 instructions and of the scalable vector and predicate register model.

### SIMD libraries and measured kernels

- [Highway](https://github.com/google/highway) - Defines sizeless vector types with run-time dispatch, so one source serves SVE and every fixed-width ISA.
- [xsimd](https://github.com/xtensor-stack/xsimd) - Fixes a batch type per ISA and width, the compile-time vector length model, and still reaches NEON and SVE.
- [Faster Base64 Encoding and Decoding Using AVX2 Instructions](https://arxiv.org/abs/1704.00605) - Where shuffle-based lookup replacing a byte loop is worked through step by step, with the measurement method spelt out.
- [Parsing Gigabytes of JSON per Second](https://arxiv.org/abs/1902.08318) - Shows branch-free structural indexing with carry-less multiply and shuffles, measured against conventional parsers.
- [simdjson](https://github.com/simdjson/simdjson) - Where that technique ships, with a kernel per ISA and the harness that keeps its published comparisons reproducible.
- [Hyperscan: A Fast Multi-pattern Regex Matcher for Modern CPUs](https://www.usenix.org/conference/nsdi19/presentation/wang-xiang) - Decomposes regexes into string and automaton pieces so both run on SIMD, the design inside the matcher Snort embeds.

### Branchless code and bit manipulation

- [Branch Prediction and the Performance of Interpreters](https://inria.hal.science/hal-01100647) - Counter evidence that current predictors absorb interpreter dispatch, so a branch removal must be measured, not assumed.
- [Hacker's Delight, 2nd Edition](https://www.informit.com/store/hackers-delight-9780321842688) - Derives the branch-free integer tricks, division by a constant among them, with proofs rather than as a catalogue.
- [Faster sorted array unions by reducing branches](https://lemire.me/blog/2021/07/14/faster-sorted-array-unions-by-reducing-branches/) - A worked branchless merge with code whose gain vanishes when the compiler emits no conditional move.
- [Array Layouts for Comparison-Based Searching](https://arxiv.org/abs/1509.05053) - Measures branch-free search over sorted, Eytzinger and B-tree layouts, the winner changing with size and prefetch.
- [Faster Population Counts Using AVX2 Instructions](https://arxiv.org/abs/1611.07612) - Shows a carry-save adder tree in vector registers beating the dedicated instruction, timed as the minimum of many runs.

## 8. Compilers and codegen

No -O level changes the target instruction set: without -march or -mcpu, every instruction emitted belongs to the default target ISA, so target flags come before any judgement of codegen.

### Reading emitted code

- [Compiler Explorer](https://godbolt.org/) - Shows how a source change alters the emitted instructions across compilers, versions and flags, with nothing installed.
- [What Every C Programmer Should Know About Undefined Behavior](https://blog.llvm.org/2011/05/what-every-c-programmer-should-know.html) - Explains how the signed-overflow and aliasing rules let a trip count be known and a store loop become memset.
- [llvm-objdump](https://llvm.org/docs/CommandGuide/llvm-objdump.html) - Reads the binary that shipped, with source lines and symbolised branch targets, rather than a recompiled snippet.
- [llvm-mca](https://llvm.org/docs/CommandGuide/llvm-mca.html) - Predicts loop throughput and port pressure from the scheduling model, and states it models neither front end nor caches.
- [llvm-exegesis](https://llvm.org/docs/CommandGuide/llvm-exegesis.html) - Measures instruction latency and throughput with counters, so the model llvm-mca predicts from is checked, not trusted.

### Optimisation levels, inlining and link time

- [Options That Control Optimization (GCC)](https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html) - Lists what each -O level turns on, the inlining limits, and that -Ofast admits transforms invalid for conforming code.
- [There Are No Zero-cost Abstractions (CppCon 2019)](https://www.youtube.com/watch?v=rHIkrotSwcc) - Shows with real codegen that an abstraction is free only when inlining and the ABI allow it, and the cost when either refuses.
- [Itanium C++ ABI](https://itanium-cxx-abi.github.io/cxx-abi/abi.html) - Fixes the rule that a non-trivial class goes by reference to a caller-made temporary, the cost a wrapped pointer pays.
- [How To Write Shared Libraries](https://www.akkadia.org/drepper/dsohowto.pdf) - States what PLT calls and interposition cost, and the visibility controls a library needs to inline its own exports.
- [LTO Overview (GCC Internals)](https://gcc.gnu.org/onlinedocs/gccint/LTO-Overview.html) - Defines whole-program LTO against partitioned WHOPR, and the LGEN, WPA and LTRANS stages that run -flto in parallel.
- [ThinLTO](https://clang.llvm.org/docs/ThinLTO.html) - Defines the thin link, summaries analysed whole-program then parallel backends, and the cache for incremental rebuilds.

### Target flags and auto-vectorisation

- [x86 Options (GCC)](https://gcc.gnu.org/onlinedocs/gcc/x86-Options.html) - Defines -march against -mtune, the psABI levels, and -mprefer-vector-width, the switch for full-width AVX-512 code.
- [Function Multiversioning (GCC)](https://gcc.gnu.org/onlinedocs/gcc/Function-Multiversioning.html) - Defines target_clones, one function per ISA behind a resolver the dynamic linker runs, so a generic build ships AVX-512.
- [Controlling Floating Point Behavior (Clang)](https://clang.llvm.org/docs/UsersManual.html#controlling-floating-point-behavior) - Lists what -ffast-math implies, of which -fassociative-math alone frees a float reduction, and -ffp-contract for FMA.
- [Auto-Vectorization in LLVM](https://llvm.org/docs/Vectorizers.html) - States what the vectorisers need, aliasing disproved or checked at run time, and where a float reduction stays in order.
- [Options to Emit Optimization Reports (Clang)](https://clang.llvm.org/docs/UsersManual.html#options-to-emit-optimization-reports) - Defines the remarks that make the compiler say which loop it left scalar and why, so the fix targets the real blocker.

Reproduce it: [misc/benchmarks/08-autovectorization-aliasing](misc/benchmarks/08-autovectorization-aliasing/README.md), the vectoriser with and without restrict.

### Profile-guided and post-link optimisation

- [Profile Guided Optimization (Clang)](https://clang.llvm.org/docs/UsersManual.html#profile-guided-optimization) - Defines the instrumented and sampled workflows, why their profiles cannot mix, and the cost of a wrong training input.
- [AutoFDO: Automatic Feedback-Directed Optimization for Warehouse-Scale Applications](https://research.google/pubs/autofdo-automatic-feedback-directed-optimization-for-warehouse-scale-applications/) - Defines the address-to-source mapping with discriminators that lets a stale production profile still drive FDO.
- [BOLT: A Practical Binary Optimizer for Data Centers and Beyond](https://arxiv.org/abs/1807.06735) - States why a profile applied to the final binary beats one mapped to source, and the layout passes accuracy enables.
- [BOLT (llvm-project/bolt)](https://github.com/llvm/llvm-project/tree/main/bolt) - States what full effect needs, relocations kept at link time and a branch-stack sample profile, neither on by default.
- [RFC: Propeller: A frame work for Post Link Optimizations](https://lists.llvm.org/pipermail/llvm-dev/2019-September/135393.html) - States the design, not a result: basic-block sections and a relink, no binary rewrite, so layout needs no disassembly.

## 9. Concurrency

Every cost below is a cache line moving between cores, so the ordering models and the measured line-transfer cost in the memory hierarchy section come first.

### Memory models and atomics

- [Foundations of the C++ Concurrency Memory Model](https://rsim.cs.illinois.edu/Pubs/08PLDI.pdf) - Defines the data-race-free contract, sequential consistency for race-free programs and no meaning for a race.
- [Atomic operations, C++ working draft](https://eel.is/c++draft/atomics) - The normative wording for every memory order, fence and read-modify-write, the text a compiler is checked against.
- [C/C++11 mappings to processors](https://www.cl.cam.ac.uk/~pes20/cpp/cpp0xmappings.html) - The table that turns each memory order into x86 and Arm instructions, so what an order costs is read off the page.
- [Linux kernel memory-barriers.txt](https://www.kernel.org/doc/Documentation/memory-barriers.txt) - States what the kernel assumes any CPU may reorder and what each barrier and access primitive guarantees.
- [herdtools7](https://github.com/herd/herdtools7) - Where herd7, litmus7 and klitmus7 live, the tools that run a litmus test against the x86, Arm and kernel models.

### Locks, contention and allocators

- [Is Parallel Programming Hard, And, If So, What Can You Do About It?](https://mirrors.edge.kernel.org/pub/linux/kernel/people/paulmck/perfbook/perfbook.html) - Derives counting, partitioning, locking and deferral with code that runs, the textbook the section assumes.
- [Algorithms for Scalable Synchronization on Shared-Memory Multiprocessors](https://www.cs.rochester.edu/u/scott/papers/1991_TOCS_synch.pdf) - The origin of the queue lock, each waiter spinning on its own line, measured against ticket and test-and-set locks.
- [Futexes Are Tricky](https://www.akkadia.org/drepper/futex.pdf) - Derives a correct user-space mutex from futex and shows the lost wakeups and extra kernel entries naive versions pay.
- [Hoard: A Scalable Memory Allocator for Multithreaded Applications](https://people.cs.umass.edu/~emery/pubs/berger-asplos2000.pdf) - Defines blowup and allocator-induced false sharing, which per-processor heaps under a bounded global heap avoid.
- [TCMalloc: Thread-Caching Malloc](https://google.github.io/tcmalloc/design.html) - The design statement for per-CPU caches built on restartable sequences and a hugepage-aware back end for TLB reach.

Reproduce it: [misc/benchmarks/09-false-sharing](misc/benchmarks/09-false-sharing/README.md), adjacent counters against padded counters across threads.

### Lock-free structures and RCU

- [The Art of Multiprocessor Programming](https://shop.elsevier.com/books/the-art-of-multiprocessor-programming/herlihy/978-0-12-415950-1) - States linearizability and the consensus hierarchy and builds both into working stacks, queues, lists and hash tables.
- [Simple, Fast, and Practical Non-Blocking and Blocking Concurrent Queue Algorithms](https://www.cs.rochester.edu/u/scott/papers/1996_PODC_queues.pdf) - The lock-free queue later libraries copy, with the counted pointer against ABA and a two-lock queue beside it.
- [Hazard Pointers for C++26](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2023/p2530r3.pdf) - The standard-track form of safe reclamation, fixing when a retired node may be freed while a reader still holds it.
- [What is RCU?](https://docs.kernel.org/RCU/whatisRCU.html) - The kernel's own statement of RCU as publish, wait for readers and keep old versions, with a free read side.
- [User-Level Implementations of Read-Copy Update](https://www.efficios.com/pub/rcu/urcu-main.pdf) - Defines liburcu's quiescent-state, signal-based and general RCU flavours and measures each read side against locks.

### Thread pools and work stealing

- [Cilk: An Efficient Multithreaded Runtime System](https://publications.csail.mit.edu/lcs/pubs/pdf/MIT-LCS-TM-548.pdf) - Defines work and critical path, proves the work-stealing bound, and shows they alone predict a runtime's speedup.
- [The Implementation of the Cilk-5 Multithreaded Language](https://www.fftw.org/~athena/papers/cilk5.ps.gz) - States the work-first principle, that overhead belongs on the rare steal path and not on every spawn.
- [Correct and Efficient Work-Stealing for Weak Memory Models](https://inria.hal.science/hal-00802885) - Gives the work-stealing deque a proven atomics form and derives which fence push, take and steal need on Arm and x86.
- [OpenMP Specifications](https://www.openmp.org/specifications/) - Fixes fork-join and tasking semantics, and the wait and binding controls deciding if idle workers spin, sleep or move.
- [oneTBB](https://github.com/uxlfoundation/oneTBB) - The shipping work-stealing runtime, arenas and task groups over a deque, the home of grain size and spin-before-sleep.

## 10. NUMA and multi-socket

A page's node is decided at first touch, not when memory is allocated or a policy is set, and every vendor table below depends on the BIOS node mode of the machine it ran on.

### NUMA and Linux memory placement

- [NUMA (Non-Uniform Memory Access): An Overview](https://queue.acm.org/doi/10.1145/2508834.2513149) - The one account tying first touch, policy scope, zone reclaim and page movement together from the implementer's side.
- [What is NUMA?](https://docs.kernel.org/mm/numa.html) - Defines nodes, zonelists and the distance-ordered fallback that places an allocation once local memory runs out.
- [NUMA Memory Policy](https://docs.kernel.org/admin-guide/mm/numa_memory_policy.html) - The normative statement of policy scopes, every mode including weighted interleave, and the cpuset intersection rule.
- [Numa policy hit/miss statistics](https://docs.kernel.org/admin-guide/numastat.html) - Defines numa_hit, numa_miss and numa_foreign, the counters that show whether a policy put pages where it said.
- [numactl](https://github.com/numactl/numactl) - Reference implementation of the policy API, prints the distance table and binds a binary that cannot be rebuilt.

Reproduce it: [misc/benchmarks/10-first-touch](misc/benchmarks/10-first-touch/README.md), first touch of fresh pages against the second pass.

### Topology and interconnects

- [NUMA Memory Performance](https://docs.kernel.org/admin-guide/mm/numaperf.html) - Explains the firmware-rated latency and bandwidth per initiator and target, and memory-side caches, that rank nodes.
- [Intel Xeon Processor Scalable Family Technical Overview](https://www.intel.com/content/www/us/en/developer/articles/technical/xeon-processor-scalable-family-technical-overview.html) - Where Intel names the mesh, UPI socket links, the directory-running home agent, and how SNC splits the cache.
- [Intel Xeon 6 with P-cores Configuration and Tuning Guide for HPC Applications](https://www.intel.com/content/www/us/en/content-details/858491/intel-xeon-6-with-p-cores-configuration-and-tuning-guide-for-hpc-applications.html) - Defines SNC on current parts as one node per compute die, and fixes the numactl and numastat checks of placement.
- [BIOS and Workload Tuning Guide for AMD EPYC 9004 Series Processors](https://docs.amd.com/v/u/en-US/58011-epyc-9004-tg-bios-and-workload) - Discloses the I/O die, GMI and xGMI links, the NPS modes with their interleave widths, and the cache-as-NUMA override.
- [Arm Neoverse CMN-700 Coherent Mesh Network Technical Reference Manual](https://support.arm.com/documentation/102308/latest/) - Defines the mesh, the home nodes holding the system cache and snoop filter, and the gateways joining sockets or CXL.

### Migration, balancing and measured effects

- [move_pages(2)](https://man7.org/linux/man-pages/man2/move_pages.2.html) - Defines per-page migration of a running process, and a query reporting each page's node, the direct test of first touch.
- [sysctl kernel numa_balancing](https://docs.kernel.org/admin-guide/sysctl/kernel.html#numa-balancing) - Defines the hinting-fault sampling behind automatic balancing and tiering, and warns the overhead may not pay off.
- [Traffic Management: A Holistic Approach to Memory Placement on NUMA Systems](https://people.ece.ubc.ca/sasha/papers/asplos284-dashti.pdf) - Proves against the kernel balancer that controller and link congestion, not remote latency, is what placement manages.
- [Intel Memory Latency Checker](https://www.intel.com/content/www/us/en/developer/articles/tool/intelr-memory-latency-checker.html) - Measures the node-to-node latency and bandwidth matrix and loaded latency on the x86 at hand, which no datasheet states.
- [High Performance Computing Tuning Guide for AMD EPYC 9004 Series Processors](https://docs.amd.com/v/u/en-US/58002_amd-epyc-9004-tg-hpc) - Tabulates measured bandwidth by NPS mode, cores per die, boost and SMT, so the NPS trade-off is shown, not asserted.

## 11. OS and I/O

A syscall's cost depends on the mitigation state, the governor and the idle state the core was in, three sysfs settings that change after boot, so each is recorded beside any number below.

### Syscalls and asynchronous I/O

- [vdso(7)](https://man7.org/linux/man-pages/man7/vdso.7.html) - Defines the calls the kernel answers without a mode switch, and the clocksource condition for skipping the trap.
- [FlexSC: Flexible System Call Scheduling with Exception-Less System Calls](https://www.usenix.org/conference/osdi10/flexsc-flexible-system-call-scheduling-exception-less-system-calls) - Separates a syscall's trap cost from its cache and TLB pollution, and shows the pollution can dominate.
- [An Analysis of Performance Evolution of Linux's Core Operations](https://www.eecg.toronto.edu/~stumm/Papers/Ren-sosp-19.pdf) - Measures syscall and context switch cost across kernel releases and traces each slowdown to a named mitigation.
- [Efficient IO with io_uring](https://www.kernel.dk/io_uring.pdf) - States the goals aio failed, and which io_uring features remove a syscall and which remove a copy.
- [Understanding Modern Storage APIs: A systematic study of libaio, SPDK, and io_uring](https://atlarge-research.com/pdfs/2022-systor-apis.pdf) - Measures io_uring's polling modes against libaio and SPDK, and shows the kernel poller needs its own core.

Reproduce it: [misc/benchmarks/11-syscall-cost](misc/benchmarks/11-syscall-cost/README.md), the fixed cost of a kernel crossing across request sizes.

### Scheduling, affinity and isolation

- [EEVDF Scheduler](https://docs.kernel.org/scheduler/sched-eevdf.html) - Defines lag and virtual deadline, which the default class schedules by, and the slice request in sched_setattr.
- [The Linux Scheduler: a Decade of Wasted Cores](https://people.ece.ubc.ca/sasha/papers/eurosys16-final29.pdf) - Proves cores sit idle while runnable threads queue, and gives the invariant checker that found the load-balancer bugs.
- [Control Group v2](https://docs.kernel.org/admin-guide/cgroup-v2.html) - Defines cpu.max throttling, cpu.weight and the cpusets that bound affinity, the controls behind every container limit.
- [CPU Performance Scaling](https://docs.kernel.org/admin-guide/pm/cpufreq.html) - Defines the governors, driver and boost switch that set a core's frequency, the sysfs state a measurement records.
- [CPU Isolation](https://docs.kernel.org/admin-guide/cpu-isolation.html) - Ties isolcpus, nohz_full, IRQ affinity, RCU offload and cpusets into one recipe, and lists the jitter it leaves.

### Interrupts and kernel bypass

- [NAPI](https://docs.kernel.org/networking/napi.html) - Defines the polling, software coalescing, busy polling and IRQ suspension knobs that trade interrupts against latency.
- [DPDK Programmer's Guide](https://doc.dpdk.org/guides/prog_guide/) - Defines the full bypass model, pinned poll-mode cores with no interrupts, that every kernel path is measured against.
- [The eXpress Data Path](https://github.com/tohojo/xdp-paper) - Measures an in-kernel programmable path against DPDK and the stack per core, with the full configuration published.
- [Kernel vs. User-Level Networking: Don't Throw Out the Stack with the Interrupts](https://cs.uwaterloo.ca/~mkarsten/papers/sigmetrics2024.html) - Separates direct and indirect NIC interrupt cost, measures the stack against bypass, and is where IRQ suspension began.
- [AF_XDP](https://docs.kernel.org/networking/af_xdp.html) - Defines the socket and UMEM rings handing XDP frames to user space, and the zero-copy and need-wakeup modes.

### Cache and bandwidth partitioning

- [Intel Resource Director Technology Architecture Specification](https://www.intel.com/content/www/us/en/content-details/789566/intel-resource-director-technology-intel-rdt-architecture-specification.html) - Defines classes of service, cache masks, bandwidth allocation and monitoring IDs, the model resctrl exposes.
- [User Interface for Resource Control feature (resctrl)](https://docs.kernel.org/filesystems/resctrl.html) - Defines the filesystem through which Linux exposes Intel, AMD and Arm partitioning, and the schemata format.
- [MPAM](https://docs.kernel.org/arch/arm64/mpam.html) - Maps Arm's cache portion and bandwidth controls onto resctrl's schemata, and states which platform limits apply.
- [CPI2: CPU performance isolation for shared compute clusters](https://john.e-wilkes.com/papers/2013-EuroSys-CPI2.pdf) - Shows at fleet scale that cycles per instruction alone finds an interfering neighbour and the one to throttle.
- [Heracles: Improving Resource Efficiency at Scale](https://csl.stanford.edu/~christos/publications/2015.heracles.isca.pdf) - Shows cache ways, cores, bandwidth and power must be partitioned together, or batch work reaches the tail.

## 12. Tail latency and production systems

A latency figure means nothing without its percentile, its load model and the way it was recorded.

### Measuring the tail

- [The Tail at Scale](https://www.barroso.org/publications/TheTailAtScale.pdf) - Shows why fan-out makes a rare slow server a common slow request, and names the techniques that tolerate variance.
- [Attack of the Killer Microseconds](https://www.barroso.org/publications/AttackoftheKillerMicroseconds.pdf) - Defines the stall band that out-of-order hardware cannot hide and a context switch cannot amortise.
- [How NOT to Measure Latency](https://www.youtube.com/watch?v=lJ8ydIuPFeU) - Shows that a summary without a max discards the samples that define the tail, and closed-loop load never records them.
- [Coordinated Omission](https://groups.google.com/g/mechanical-sympathy/c/icNZJejUHfE) - The original definition of the recording error, with arithmetic for how far a reported percentile sits from the truth.
- [HdrHistogram](https://github.com/HdrHistogram/HdrHistogram) - Keeps the whole distribution at fixed relative precision in constant time, so the far percentiles and max survive.

Reproduce it: [misc/benchmarks/12-coordinated-omission](misc/benchmarks/12-coordinated-omission/README.md), closed-loop against open-loop p99 under the same stalls.

### Where jitter comes from

- [rt-tests](https://git.kernel.org/pub/scm/utils/rt-tests/rt-tests.git/) - The reference wakeup-latency measurement for Linux, whose README states that an unloaded run proves nothing.
- [osnoise tracer](https://docs.kernel.org/trace/osnoise-tracer.html) - Counts the noise a spinning thread suffers and attributes each event to NMI, IRQ, softirq, thread or hardware.
- [Tales of the Tail](https://syslab.cs.washington.edu/papers/latency-socc14.pdf) - Derives the queueing-ideal tail and attributes the excess to scheduling, interrupt placement, power saving and NUMA.
- [Latency Implications of Virtual Memory](https://rigtorp.se/virtual-memory/) - Measures with code the page-fault, TLB-shootdown and writeback stalls that memory mapping hides from the caller.
- [The KVM halt polling system](https://docs.kernel.org/virt/kvm/halt-polling.html) - Defines the host-side polling after a vCPU halt that trades idle host CPU for guest wakeup time, unseen by the guest.

### Load generation and production workloads

- [Open Versus Closed: A Cautionary Tale](https://www.usenix.org/conference/nsdi-06/open-versus-closed-cautionary-tale) - Shows that open and closed load models disagree on response time and scheduling gains, with rules for choosing one.
- [wrk2](https://github.com/giltene/wrk2) - Issues requests on a fixed schedule and times each from when it was due, so server stalls reach the percentiles.
- [Reconciling High Server Utilization and Sub-millisecond Quality-of-Service](https://csl.stanford.edu/~christos/publications/2014.mutilate.eurosys.pdf) - Shows the tail, not throughput, caps a latency-critical server's utilisation, and how far co-located work lowers it.
- [TailBench](https://tailbench.csail.mit.edu/) - Pairs latency-critical services with an open-loop harness that records sojourn against service time per request.
- [Workload Analysis of a Large-Scale Key-Value Store](https://jiangs.utasites.cloud/pubs/papers/atikoglu12-memcached.pdf) - Measures the key, value and inter-arrival distributions of live key-value traffic, the shape load generators imitate.

### Mechanical sympathy

- [Inter Thread Latency](https://mechanical-sympathy.blogspot.com/2011/08/inter-thread-latency.html) - Measures with code the floor for handing a cache line between cores, which every queue and lock is built on.
- [Single Writer Principle](https://mechanical-sympathy.blogspot.com/2011/09/single-writer-principle.html) - States the design rule that removes write contention outright, using a contended increment's cost as the argument.
- [Optimizing a Ring Buffer for Throughput](https://rigtorp.se/ringbuffer/) - Adds cached indices to a single-producer single-consumer ring and shows with counters the coherence traffic removed.
- [LMAX Disruptor](https://lmax-exchange.github.io/disruptor/disruptor.html) - Applies the single writer rule and cache-line padding to a ring buffer, with the queue comparison that motivated it.
- [Aeron](https://github.com/aeron-io/aeron) - Carries the single writer and batching rules through a whole transport, the reference beyond one in-process queue.

## 13. Inference on CPU

A decode step at batch one reads every weight once for a few flops, so it runs at the memory system's rate, and a CPU figure compares with a GPU figure only at the same batch and precision.

### GEMM and BLAS

- [Anatomy of High-Performance Matrix Multiplication](https://www.cs.utexas.edu/~flame/pubs/GotoTOMS_revision.pdf) - Derives the cache blocking every fast CPU GEMM still uses by refining a memory model until the packed kernel falls out.
- [BLIS: A Framework for Rapidly Instantiating BLAS Functionality](https://www.cs.utexas.edu/~flame/pubs/blis1_toms_rev3.pdf) - Reduces a BLAS to one register-tile micro-kernel per architecture and states which loop owns which level of cache.
- [LLaMA Now Goes Faster on CPUs](http://justine.lol/matmul/) - Builds a register-tile kernel step by step and shows where outer-loop unrolling wins and where a vendor BLAS still does.
- [OpenBLAS](https://github.com/OpenMathLib/OpenBLAS) - Sets run-time dispatch for a BLAS, one kernel table per microarchitecture chosen as a DYNAMIC_ARCH build loads.
- [oneDNN Matrix Multiplication Primitive](https://uxlfoundation.github.io/oneDNN/dev_guide_matmul.html) - Fixes the data-type table, packed weight format and fused post-ops a CPU GEMM must expose to an inference graph.
- [Scaled Dot-Product Attention (oneDNN Graph)](https://uxlfoundation.github.io/oneDNN/dev_guide_graph_sdpa.html) - Fixes the fused attention pattern, f32 accumulation under bf16 inputs and the shapes the fast CPU path accepts.

Reproduce it: [misc/benchmarks/13-sgemm-naive-vs-blas](misc/benchmarks/13-sgemm-naive-vs-blas/README.md), naive GEMM, a hand microkernel and the vendor BLAS, plus int8 against float32 dot products.

### Runtimes

- [oneDNN](https://github.com/uxlfoundation/oneDNN) - Generates VNNI and AMX kernels at run time under PyTorch, TensorFlow and OpenVINO, and calls Compute Library on Arm.
- [ggml](https://github.com/ggml-org/ggml) - Defines the quantized block formats and the per-ISA dot-product kernels over them that every llama.cpp type rests on.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) - Where new quantization types, kernels and thread pools land first, each with the perplexity and speed table behind it.
- [ONNX Runtime MLAS](https://github.com/microsoft/onnxruntime/tree/main/onnxruntime/core/mlas) - Holds the CPU provider's GEMM, int8 and int4 MatMul kernels, dispatched per ISA at run time from SSE to AMX and SME.
- [OpenVINO CPU Device](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/cpu-device.html) - States precision defaults per ISA, the int8 path through oneDNN and the streams model that turns cores into throughput.

### Quantization

- [Quantization and Training of Neural Networks for Efficient Integer-Arithmetic-Only Inference](https://arxiv.org/abs/1712.05877) - Defines the affine scale and zero-point scheme with integer accumulation that every int8 CPU runtime still implements.
- [Nuances of int8 Computations](https://uxlfoundation.github.io/oneDNN/dev_guide_int8_computations.html) - States where int8 saturates on pre-VNNI x86, the compensation that makes signed by signed work, and what VNNI removes.
- [Quantize ONNX models](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html) - Defines the QDQ form against QOperator and dynamic against static, and which sign choices are safe on which CPUs.
- [k-quants](https://github.com/ggml-org/llama.cpp/pull/1684) - Defines super-block formats with quantized scales and the perplexity against size curve behind mixing types per tensor.
- [T-MAC: CPU Renaissance via Table Lookup for Low-Bit LLM Deployment on Edge](https://arxiv.org/abs/2407.00088) - Replaces unpacking and multiplying low-bit weights with bit-sliced lookups, so a narrower weight costs less to apply.

### Matrix extensions

- [Intel Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) - Defines AMX tiles, tile configuration and TMUL, the VNNI and bf16 dot products, and the XSAVE state a tile load needs.
- [Using XSTATE features in user space applications](https://docs.kernel.org/arch/x86/xstate.html) - Defines the arch_prctl permission Linux requires for AMX tile data and the trap a tile instruction takes until granted.
- [Add Intel Advanced Matrix Extensions (AMX) support to ggml](https://github.com/ggml-org/llama.cpp/pull/7707) - Holds the design report for the ggml AMX path, whose double buffering hides applying scales between tile products.
- [Arm Architecture Reference Manual for A-profile architecture](https://support.arm.com/documentation/ddi0487/latest/) - Defines streaming SVE mode, the ZA tile array and SME2 multi-vector instructions, with pseudocode a kernel must match.
- [SME Programmer's Guide](https://support.arm.com/documentation/109246/latest/) - Walks through SME2 int8 and f32 matmul and gemv kernels and a lookup-table path, on a unit so far only in client parts.

### Threading for inference

- [Thread management](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) - Sets the physical-core default, the affinity it implies and the spin-wait controls that trade idle CPU for latency.
- [Performance Hints and Thread Scheduling](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/cpu-device/performance-hint-and-thread-scheduling.html) - States the vendor defaults, one thread per core, SMT siblings off, core type by precision and one socket for latency.
- [Threadpool: take 2](https://github.com/ggml-org/llama.cpp/pull/8672) - Defines the explicit thread pool with CPU masks, strict placement, priority and polling that ggml runs without OpenMP.
- [llama-bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md) - Defines the prompt and generation tests, repetitions and mean with deviation behind any comparable llama.cpp number.
- [Dual Epyc Genoa/Turin token generation performance bottlenecks](https://github.com/ggml-org/llama.cpp/discussions/11733) - Traces poor decode scaling across sockets to remote NUMA access from weight placement, with numatop counts as evidence.

### When CPU beats GPU

- [gpt-j example README (ggml)](https://github.com/ggml-org/ggml/blob/master/examples/gpt-j/README.md) - Origin of ggml's bandwidth argument, NEON threads saturate a laptop's memory bus, so a GPU on that bus gains nothing.
- [llama.cpp Performance Testing](https://johannesgaessler.github.io/llamacpp_performance) - Holds the memory clock sweep with all else fixed, the token rate following it and flattening after a few threads.
- [SparAMX: Accelerating Compressed LLMs Token Generation on AMX-powered CPUs](https://arxiv.org/abs/2502.12444) - Measures decode kernels on a Xeon as DRAM-bound, so AMX pays at batch one only once bytes per token shrink, with code.
- [MLPerf Inference v6.0 Results](https://github.com/mlcommons/inference_results_v6.0) - Holds CPU-only entries whose logs show the batched Offline case lost to GPU entries at the same accuracy floor.

## 14. Hardware generations

The measurement articles below state no compiler, flags or run count, so each is kept for the structure it exposes and no figure from it is repeated.

### Intel Xeon

- [Technical Overview of the 4th Gen Intel Xeon Scalable Processor Family](https://www.intel.com/content/www/us/en/developer/articles/technical/fourth-generation-xeon-scalable-family-overview.html) - Where Intel states what Sapphire Rapids added: larger L2 and L3, DDR5, CXL, AMX and on-die accelerators.
- [Sapphire Rapids: Golden Cove Hits Servers](https://chipsandcheese.com/p/a-peek-at-sapphire-rapids) - Measures L3 and memory latency across the tiled mesh and the slow clock ramp the vendor overview omits.
- [Emerald Rapids: 5th-Generation Intel Xeon Scalable Processors](https://ieeexplore.ieee.org/document/10454434) - The designers' statement of what changed: fewer, larger dies, a bigger shared L3, faster DDR5 and socket links.
- [A Look into Intel Xeon 6's Memory Subsystem](https://chipsandcheese.com/p/a-look-into-intel-xeon-6s-memory) - Measures per-die L3 under sub-NUMA clustering and the die-crossing cost on Granite Rapids beside Turin.
- [Benchmarking the Evolution of Performance and Energy Efficiency Across Recent Generations](https://real.mtak.hu/215594/) - Bandwidth-bound codes on Sapphire, Emerald and Granite Rapids and Sierra Forest with clocks, SMT and compiler stated.

### AMD EPYC

- [AMD Next-Generation Zen 4 Core and 4th Gen AMD EPYC Server CPUs](https://ieeexplore.ieee.org/document/10466769) - The designers' account of the Zen 4 core and how it yields Genoa, Genoa-X, Bergamo and Siena.
- [Testing AMD's Bergamo: Zen 4c Spam](https://chipsandcheese.com/p/testing-amds-bergamo-zen-4c-spam) - Tests the same-core claim for Zen 4c: cache latency, clock ceiling and core-to-core paths beside clock-matched Zen 4.
- [Software Optimization Guide for the AMD Zen5 Microarchitecture](https://docs.amd.com/v/u/en-US/58455_1.00) - Where AMD states what Zen 5 changed in front end, vector datapath and caches, the core Turin carries.
- [AMD EPYC 9005 Processor Architecture Overview](https://docs.amd.com/v/u/en-US/58462_amd-epyc-9005-tg-architecture-overview) - Defines Turin: Zen 5 or Zen 5c dies, which parts double die-to-IO links, NUMA modes and full-width AVX-512.
- [AMD's Turin: 5th Gen EPYC Launched](https://chipsandcheese.com/p/amds-turin-5th-gen-epyc-launched) - Measures what wider die-to-IO links and faster DDR5 do for Turin bandwidth, and where latency rose over Genoa.

### Arm Neoverse server parts

- [AWS Graviton Getting Started](https://github.com/aws/aws-graviton-getting-started) - Where AWS states which Neoverse core, ISA revision, mesh, caches and compiler flag each Graviton generation carries.
- [Arm Neoverse V2 Core Software Optimization Guide](https://support.arm.com/documentation/109898/latest/) - Sets the pipeline widths and instruction timings of the core Graviton 4, Grace and Axion share.
- [NVIDIA Grace Performance Tuning Guide](https://docs.nvidia.com/dccpu/grace-perf-tuning-guide/index.html) - States the coherency fabric, LPDDR5X fit and MPAM cache and memory partitioning on Grace.
- [Arm Neoverse N2 Core Software Optimization Guide](https://support.arm.com/documentation/109914/latest/) - States the timings and fusion rules of the narrower N line core in Cobalt 100 and Yitian.
- [Ampere Altra Rev A1 64-Bit Multi-Core Processor Datasheet](https://amperecomputing.com/assets/Altra_Rev_A1_DS_v1_50_20240130_3375c3dec5_1c5d4604fa.pdf) - Where Ampere states the N1 part: private L2 per core, shared system cache, mesh and DDR4 fit.

### Independent measurement across vendors

- [Microarchitectural Comparison and In-core Modeling of State-of-the-art CPUs](https://arxiv.org/abs/2409.08108) - Measures Neoverse V2, Golden Cove and Zen 4 in-core at fixed clock, and each socket's clock under vector load.
- [On the Performance of Cloud-based ARM SVE for Zero-Knowledge Proving Systems](https://arxiv.org/abs/2506.09505) - One SVE workload run on Graviton 3, Graviton 4, Yitian and Axion with compiler, runs and spread stated.
- [Arm's Neoverse V2, in AWS's Graviton 4](https://chipsandcheese.com/p/arms-neoverse-v2-in-awss-graviton-4) - Measures a sustained rename width below the stated one, cache latencies, mesh behaviour and cross-socket cost on V2.
- [ARM's Neoverse N2: Cortex A710 for Servers](https://chipsandcheese.com/p/arms-neoverse-n2-cortex-a710-for-servers) - Measures structure sizes, cache latencies and mesh behaviour of N2 on Yitian, the core Cobalt 100 carries.
- [AmpereOne at Hot Chips 2024: Maximizing Density](https://chipsandcheese.com/p/ampereone-at-hot-chips-2024-maximizing-density) - Puts vendor slides beside measurements of the predictor, small instruction cache, private L2 and long memory latency.

Reproduce it: [misc/benchmarks/14-pcore-vs-ecore](misc/benchmarks/14-pcore-vs-ecore/README.md), the same three kernels on a performance core and an efficiency core.

## 15. Benchmarks

A score means what its suite's run rules say it means, so the rules come before the number.

### Standard suites

- [SPEC CPU 2026 Run and Reporting Rules](https://www.spec.org/cpu2026/Docs/runrules.html) - Defines base against peak, rate against speed, the threading models a speed run may use and an Arm reference machine.
- [SPEC CPU: The Next Generation](https://arxiv.org/abs/2605.01575) - Where the committee states how workloads were chosen and hardened, and defines the rolling round-robin rate.
- [SPEC CPU2026: Characterization, Representativeness, and Cross-Suite Comparison](https://arxiv.org/abs/2605.03713) - Measures with counters what each workload stresses on x86 and Arm server parts, beside data-centre and inference suites.
- [MLPerf Inference Rules](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc) - Fixes model, accuracy floor and query pattern per scenario, so a Server score is throughput under a latency bound.
- [DCPerf: An Open-Source, Battle-Tested Performance Benchmark Suite for Datacenter Workloads](https://aisystemcodesign.github.io/papers/DCPerf-ISCA25.pdf) - Shows standard suites misproject data-centre servers, and states the fleet-matching method the suite is built by.

### Microbenchmark suites

- [Memory Bandwidth and Machine Balance in Current High Performance Computers](https://www.cs.virginia.edu/~mccalpin/papers/balance/) - Defines sustainable bandwidth as what unit-stride loops get, not bus peak, and machine balance as flops per access.
- [STREAM Benchmark Reference Information](https://www.cs.virginia.edu/stream/ref.html) - Sets the array size rule, timing over repeated trials, and counting bytes a loop asks for, not what the cache moved.
- [lmbench: Portable Tools for Performance Analysis](https://www.usenix.org/legacy/publications/library/proceedings/sd96/mcvoy.html) - Origin of the one-mechanism-per-test method for memory, system call, pipe and socket latency, and what each leaves out.
- [uarch-bench](https://github.com/travisdowns/uarch-bench) - Isolates memory-level parallelism from load latency as separate tests, with DVFS held off before timing, x86 Linux only.
- [nanoBench: A Low-Overhead Tool for Running Microbenchmarks on x86 Systems](https://arxiv.org/abs/1911.03282) - Shows why kernel mode with interrupts off matters, removes harness overhead, then recovers cache replacement policies.

Reproduce it: [misc/benchmarks/15-stream-bandwidth](misc/benchmarks/15-stream-bandwidth/README.md), triad bandwidth by thread count against the vendor figure.

### Methodology and what suites miss

- [How Not to Lie with Statistics: The Correct Way to Summarize Benchmark Results](https://dl.acm.org/doi/10.1145/5666.5673) - Origin of the rule that normalised results take the geometric mean, which a SPEC ratio and the crimes list rest on.
- [Systems Benchmarking Crimes](https://gernot-heiser.org/benchmarking-crimes.html) - Checklist of evaluation faults from sub-setting and improper baselines to arithmetic means of ratios, each with a fix.
- [Scientific Benchmarking of Parallel Computing Systems](https://htor.inf.ethz.ch/publications/img/hoefler-scientific-benchmarking.pdf) - Sets which mean fits costs, rates and ratios, when confidence intervals are owed, and the absolute base a speedup needs.
- [Rigorous Benchmarking in Reasonable Time](https://kar.kent.ac.uk/33611/) - Decides how many builds, runs and iterations an experiment needs by measuring at which level the variation arises.
- [Profiling a warehouse-scale computer](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/44271.pdf) - Fleet counter profile showing services stall on instruction fetch and burn cycles in shared routines, which SPEC lacks.

## 16. Watchlist

Everything below is real but unproven: no item yet has all three of a written specification, a part you can buy, and a public measurement stating every one of the seven fields. Each line says what would promote it. Vendor multiples never qualify. Last checked **2026-09-15**.

### ISA extensions without a shipped server part

- [Intel AVX10.2 Architecture Specification](https://www.intel.com/content/www/us/en/content-details/828965/intel-advanced-vector-extensions-10-2-intel-avx10-2-architecture-specification.html) - Folds the AVX-512 subsets into one versioned level and adds BF16 and FP8 forms, pending a shipped part and a run.
- [Intel Architecture Instruction Set Extensions Programming Reference](https://www.intel.com/content/www/us/en/content-details/671368/intel-architecture-instruction-set-extensions-programming-reference.html) - Ties APX, with doubled x86 registers, AVX10.2 and AMX FP8 tiles to Diamond Rapids, pending silicon and a public run.
- SME in a Neoverse core, so far shipped only in client parts, pending a server core that carries it and a public run.
- [RISC-V Vector Extension, Version 1.0](https://docs.riscv.org/reference/isa/unpriv/v-st-ext.html) - The ratified vector ISA, shipped only as IP and chiplets, pending a socketed server part and a run against Arm or x86.

### Parts without a public measurement

- [6th Gen AMD EPYC Server CPUs](https://newsroom.amd.com/news/aai-2026-6th-gen-epyc/) - The Zen 6 server family, so far a press release with no shipped part, pending shipment and a public run against Zen 5.
- [Intel Xeon 6+ Processors](https://www.intel.com/content/www/us/en/products/details/processors/xeon/6-plus-series.html) - The E-core-only sockets after Sierra Forest, shipped with vendor multiples footnoted off the page, pending a public run.
- [NVIDIA Vera CPU](https://www.nvidia.com/en-us/data-center/vera-cpu/) - Custom Arm cores with statically partitioned SMT and no architecture document, pending a specification and a public run.
- [Arm Neoverse V3 Core Software Optimization Guide](https://support.arm.com/documentation/109678/latest/) - Vendor timing tables for the core shipped in Graviton 5 and previewed in Cobalt 200, pending a public run on the core.

### Memory and interconnect

- [CXL Specification](https://computeexpresslink.org/cxl-specification/) - Defines memory pooled across hosts on a coherent link, with latency so far estimated, pending a run on a shipped pool.
- [Demystifying CXL Memory with Genuine CXL-Ready Systems and Devices](https://arxiv.org/abs/2303.15375) - Measures expansion devices with frequency and SMT fixed, the nearest run to every field, pending compiler and flags.
- [DDR5MDB02 Multiplexed Rank Data Buffer, JESD82-552](https://www.jedec.org/standards-documents/docs/jesd82-552) - Defines the data buffer behind MRDIMMs, whose vendor bandwidth claims name no method, pending a run against RDIMMs.

### Kernel paths and generated code

- [Extensible Scheduler Class](https://docs.kernel.org/scheduler/sched-ext.html) - Lets a BPF program schedule at run time with safe fallback, once a run against the default scheduler states every field.
- [io_uring zero copy Rx](https://docs.kernel.org/networking/iou-zcrx.html) - Lands payloads straight in user memory on header-splitting NICs, pending the implementer's epoll run naming every field.
- [T-MAC](https://github.com/microsoft/T-MAC) - Table-lookup kernels for low-bit weights, with a baseline stated but no frequency, compiler or flags, pending those.
- [Faster sorting algorithms discovered using deep reinforcement learning](https://www.nature.com/articles/s41586-023-06004-9) - Generated small sorts shipped in libc++, timed by CPU family with no model, compiler or flags stated, pending those.

## What earns a place

Seven fields, and a number without all of them does not appear here:

| | |
|---|---|
| 1 | CPU model and microarchitecture |
| 2 | core count used |
| 3 | frequency, with turbo and SMT state |
| 4 | compiler and flags |
| 5 | workload |
| 6 | baseline |
| 7 | measurement method |

Miss one and the number is dropped; if the entry rests on that number, it
moves to the watchlist or goes.

An entry itself has to be the thing, not writing about the thing: the paper
that first described a mechanism, the specification or manual that defines
it, the repository the implementation lives in, or a report from whoever did
the work with code and reproducible measurements. Summaries, tutorials,
surveys, marketing pages, mirrors and repackagings do not qualify. Every URL
points at the live canonical copy, and `misc/scripts/check_links.py` and
`misc/scripts/check_format.py` prove it on every push and again weekly.

[CONTRIBUTING.md](CONTRIBUTING.md) has the rules in full.

## License

MIT. Maintained by [@usamahz](https://github.com/usamahz).

Format inspired by the GPU-side list at [wafer-ai/gpu-perf-engineering-resources](https://github.com/wafer-ai/gpu-perf-engineering-resources).
