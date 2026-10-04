"""Tool output as users paste it, in the shapes perf, toplev, gcc and clang print."""

PERF5 = """
 Performance counter stats for './bench':

            812.34 msec task-clock                #    0.998 CPUs utilized
                 3      context-switches          #    0.004 K/sec
                 0      cpu-migrations            #    0.000 K/sec
               104      page-faults               #    0.128 K/sec
     2,537,513,000      cycles                    #    3.124 GHz
     1,015,005,200      instructions              #    0.40  insn per cycle
       381,153,000      branches                  #  469.209 M/sec
        12,856,000      branch-misses             #    3.37% of all branches
       400,000,000      L1-dcache-loads
        40,000,000      L1-dcache-load-misses     #   10.00% of all L1-dcache accesses
     1,500,000,000      stalled-cycles-backend    #   59.11% backend cycles idle

       0.813955300 seconds time elapsed

       0.810000000 seconds user
       0.004000000 seconds sys
"""

PERF6_HYBRID = """
 Performance counter stats for './server --bench':

          1,234.56 msec task-clock:u                     #    0.998 CPUs utilized
                 0      context-switches:u               #    0.000 /sec
               123      page-faults:u                    #   99.633 /sec
     4,567,890,123      cpu_core/cycles/u                #    3.700 GHz                         (83.33%)
     <not counted>      cpu_atom/cycles/u                                                       (0.00%)
     9,876,543,210      cpu_core/instructions/u          #    2.16  insn per cycle              (83.33%)
     <not counted>      cpu_atom/instructions/u                                                 (0.00%)
     1,111,111,111      cpu_core/branches/u              #  900.000 M/sec                       (83.33%)
        12,345,678      cpu_core/branch-misses/u         #    1.11% of all branches             (83.33%)
             TopdownL1 (cpu_core)                 #     29.3 %  tma_backend_bound
                                                  #     10.1 %  tma_bad_speculation
                                                  #     20.6 %  tma_frontend_bound
                                                  #     40.0 %  tma_retiring             (83.33%)
             TopdownL1 (cpu_atom)                 #     35.0 %  tma_backend_bound
                                                  #     25.0 %  tma_frontend_bound

       1.237123456 seconds time elapsed
"""

PERF_DE_LOCALE = """
 Performance counter stats for './a.out':

     2.000.000.000      cycles
     3.000.000.000      instructions              #    1,50  insn per cycle

       1,000000000 seconds time elapsed
"""

PERF_CSV = """1234.56,msec,task-clock,1234560000,100.00,0.998,CPUs utilized
4567890123,,cycles,1234000000,100.00,3.700,GHz
9876543210,,instructions,1234000000,100.00,2.16,insn per cycle
<not supported>,,stalled-cycles-frontend,0,100.00,,
123456,,cpu/event=0x3c,umask=0x0/,1234000000,50.00,,
"""

PERF_CSV_INTERVAL = """1.000123456,1000000000,,cycles,1000000000,100.00,,
1.000123456,500000000,,instructions,1000000000,100.00,,
2.000234567,1000000000,,cycles,1000000000,100.00,,
2.000234567,700000000,,instructions,1000000000,100.00,,
"""

PERF_JSON = """{"counter-value" : "4567890123.000000", "unit" : "", "event" : "cycles", "event-runtime" : 1234000000, "pcnt-running" : 100.00, "metric-value" : "3.700000", "metric-unit" : "GHz"}
{"counter-value" : "2283945061.000000", "unit" : "", "event" : "instructions", "event-runtime" : 1234000000, "pcnt-running" : 61.50, "metric-value" : "0.500000", "metric-unit" : "insn per cycle"}
{"counter-value" : "<not counted>", "unit" : "", "event" : "LLC-load-misses", "event-runtime" : 0, "pcnt-running" : 0.00}
"""

PERF_OLD_TOPDOWN = """
 Performance counter stats for 'system wide':

                                retiring      bad speculation       frontend bound        backend bound
S0-D0-C0           2                 30.0%                 4.0%                26.0%                40.0%
S0-D0-C1           2                 32.0%                 6.0%                22.0%                40.0%

       1.001234567 seconds time elapsed
"""

PERF_AMD_PIPELINE = """
 Performance counter stats for './bench':

             PipelineL1                      #     18.5 %  frontend_bound
                                             #     45.0 %  backend_bound
                                             #      2.5 %  bad_speculation
                                             #     34.0 %  retiring

       1.000000000 seconds time elapsed
"""

TOPLEV = """# 4.8-full-perf on Intel(R) Core(TM) i7-8700 CPU @ 3.20GHz [skl]
FE             Frontend_Bound                  % Slots                       12.3    [ 9.0%]
BAD            Bad_Speculation                 % Slots                        2.1  < [ 9.0%]
BE             Backend_Bound                   % Slots                       60.6    [ 9.0%]
RET            Retiring                        % Slots                       25.0  < [ 9.0%]
BE/Mem         Backend_Bound.Memory_Bound      % Slots                       45.2    [ 9.0%] <==
"""

GCC_REMARKS = """kernel.c:12:5: missed: couldn't vectorize loop
kernel.c:14:9: missed: not vectorized: complicated access pattern.
kernel.c:21:5: missed: not vectorized: possible aliasing between a and b
kernel.c:30:5: optimized: loop vectorized using 32 byte vectors
"""

CLANG_REMARKS = """kernel.c:12:5: remark: loop not vectorized [-Rpass-missed=loop-vectorize]
kernel.c:12:5: remark: loop not vectorized: cannot identify array bounds [-Rpass-analysis=loop-vectorize]
kernel.c:30:5: remark: vectorized loop (vectorization width: 8, interleaved count: 4) [-Rpass=loop-vectorize]
"""

OBJDUMP = """0000000000001139 <sum>:
    1139:	c5 fc 57 c0          	vxorps %ymm0,%ymm0,%ymm0
    113d:	c4 e2 7d 92 04 87    	vgatherdps %ymm1,(%rdi,%ymm2,4),%ymm0
    1143:	c5 fc 58 04 87       	vaddps (%rdi,%rax,4),%ymm0,%ymm0
    1148:	f0 48 0f c1 07       	lock xadd %rax,(%rdi)
    114d:	c5 f8 77             	vzeroupper
"""

PERF_ANNOTATE = """ Percent |      Source code & Disassembly of bench for cycles:u
         :      for (i = 0; i < n; i++)
   12.50 │      vmovups   (%rax,%rdx,4),%zmm0
   40.00 │      vfmadd231ps (%rcx,%rdx,4),%zmm1,%zmm0
   20.00 │      vmovups   %zmm0,(%rax,%rdx,4)
    5.00 │      add       $0x10,%rdx
"""

CODE = """#include <atomic>
#include <immintrin.h>
struct alignas(64) Counter { std::atomic<long> n; };
void bump(Counter *c) { c->n.fetch_add(1, std::memory_order_relaxed); }
void axpy(float *__restrict y, const float *x, float a, int n) {
    __m256 va = _mm256_set1_ps(a);
    for (int i = 0; i < n; i += 8) {
        _mm256_storeu_ps(y + i, _mm256_fmadd_ps(va, _mm256_loadu_ps(x + i), _mm256_loadu_ps(y + i)));
    }
}
"""

# ----- the four demo pastes: a memory-bound server, a hybrid desktop, a VM, a failed command -----

SPR_MEMORY = """
 Performance counter stats for './hashjoin --rows 200000000':

 1,079,412,630,288      TOPDOWN.SLOTS                    #     86.2 %  tma_backend_bound
                                                  #      3.1 %  tma_bad_speculation
    70,161,821,067      topdown-retiring                 #      4.2 %  tma_frontend_bound
                                                  #      6.5 %  tma_retiring
   930,453,687,308      topdown-be-bound
    33,461,791,539      topdown-bad-spec
    45,335,330,472      topdown-fe-bound
       413,206,118      INT_MISC.UOP_DROPPING
   179,902,105,048      cycles
    63,124,877,410      instructions                     #    0.35  insn per cycle
     9,517,402,331      branches
       104,691,425      branch-misses                    #    1.10% of all branches
    22,013,558,902      L1-dcache-loads
     1,893,166,066      L1-dcache-load-misses            #    8.60% of all L1-dcache accesses
       640,288,114      LLC-loads
       590,345,641      LLC-load-misses                  #   92.20% of all LL-cache accesses

      60.213487902 seconds time elapsed

      57.104322000 seconds user
       3.021870000 seconds sys

"""

RPL_HYBRID_MUX = """
 Performance counter stats for 'clang++ -O2 -c huge_generated.cpp':

         47,786.42 msec task-clock                       #    0.991 CPUs utilized             
             1,147      context-switches                 #   24.003 /sec                      
                96      cpu-migrations                   #    2.009 /sec                      
         1,083,417      page-faults                      #   22.672 K/sec                     
   200,096,317,044      cpu_atom/cycles/                 #    4.187 GHz                         (11.71%)
   259,081,552,417      cpu_core/cycles/                 #    5.422 GHz                         (84.37%)
   209,320,741,508      cpu_atom/instructions/           #    1.05  insn per cycle              (15.62%)
   393,368,520,946      cpu_core/instructions/           #    1.52  insn per cycle              (84.37%)
    42,931,684,082      cpu_atom/branches/               #  898.408 M/sec                       (11.68%)
    80,522,517,331      cpu_core/branches/               #    1.685 G/sec                       (84.37%)
     1,433,918,270      cpu_atom/branch-misses/          #    3.34% of all branches             (11.76%)
     2,310,996,247      cpu_core/branch-misses/          #    2.87% of all branches             (84.37%)
             TopdownL1 (cpu_core)                 #     23.1 %  tma_backend_bound      
                                                  #     11.2 %  tma_bad_speculation    
                                                  #     41.6 %  tma_frontend_bound     
                                                  #     24.1 %  tma_retiring             (84.37%)
             TopdownL1 (cpu_atom)                 #     14.1 %  tma_bad_speculation    
                                                  #     21.9 %  tma_retiring             (11.64%)
                                                  #     25.6 %  tma_backend_bound      
                                                  #     38.4 %  tma_frontend_bound       (11.79%)

      48.211307529 seconds time elapsed

      46.571203000 seconds user
       1.208114000 seconds sys

"""

VM_CSV_INTERVALS = """1.001054218,10412873551,,cycles,585352542,58.51,,
1.001054218,6874120338,,instructions,583351678,58.31,0.66,insn per cycle
1.001054218,1398412077,,branches,581350815,58.11,,
1.001054218,21873419,,branch-misses,580350383,58.01,1.56,of all branches
1.001054218,412873144,,cache-references,584352110,58.41,,
1.001054218,118432871,,cache-misses,584352110,58.41,28.69,of all cache refs
1.001054218,2104338712,,L1-dcache-loads,582351247,58.21,,
1.001054218,187341228,,L1-dcache-load-misses,582351247,58.21,8.90,of all L1-dcache accesses
1.001054218,61843117,,LLC-loads,579349952,57.91,,
1.001054218,27183442,,LLC-load-misses,579349952,57.91,43.96,of all LL-cache accesses
1.001054218,9873214,,dTLB-load-misses,581350815,58.11,,
1.001054218,<not supported>,,stalled-cycles-frontend,0,100.00,,
2.002187431,10563019874,,cycles,582631861,58.24,,
2.002187431,6712345120,,instructions,580631065,58.04,0.64,insn per cycle
2.002187431,1371209544,,branches,578630269,57.84,,
2.002187431,22417633,,branch-misses,577629871,57.74,1.63,of all branches
2.002187431,431209877,,cache-references,581631463,58.14,,
2.002187431,126348120,,cache-misses,581631463,58.14,29.30,of all cache refs
2.002187431,2061873390,,L1-dcache-loads,579630667,57.94,,
2.002187431,193872145,,L1-dcache-load-misses,579630667,57.94,9.40,of all L1-dcache accesses
2.002187431,64417820,,LLC-loads,576629472,57.64,,
2.002187431,29076133,,LLC-load-misses,576629472,57.64,45.14,of all LL-cache accesses
2.002187431,10412776,,dTLB-load-misses,578630269,57.84,,
2.002187431,<not supported>,,stalled-cycles-frontend,0,100.00,,
3.003012875,10388412706,,cycles,586941902,58.67,,
3.003012875,6903318841,,instructions,584941077,58.47,0.66,insn per cycle
3.003012875,1405110923,,branches,582940253,58.27,,
3.003012875,21544087,,branch-misses,581939840,58.17,1.53,of all branches
3.003012875,408761320,,cache-references,585941489,58.57,,
3.003012875,115873602,,cache-misses,585941489,58.57,28.35,of all cache refs
3.003012875,2118402771,,L1-dcache-loads,583940665,58.37,,
3.003012875,184120336,,L1-dcache-load-misses,583940665,58.37,8.69,of all L1-dcache accesses
3.003012875,60318744,,LLC-loads,580939428,58.07,,
3.003012875,26412879,,LLC-load-misses,580939428,58.07,43.79,of all LL-cache accesses
3.003012875,9541087,,dTLB-load-misses,582940253,58.27,,
3.003012875,<not supported>,,stalled-cycles-frontend,0,100.00,,
"""

PERF_ERR_METRICGROUP = """Cannot find metric or group `PipelineL1'

 Usage: perf stat [<options>] [<command>]

    -M, --metrics <metric/metric group list>
                          monitor specified metrics or metric groups (separated by ,)
"""

PERF_ERR_PARANOID = """Error:
Access to performance monitoring and observability operations is limited.
Consider adjusting /proc/sys/kernel/perf_event_paranoid setting to open
access to performance monitoring and observability operations for processes
without CAP_PERFMON, CAP_SYS_PTRACE or CAP_SYS_ADMIN Linux capability.
More information can be found at 'Perf events and tool security' document:
https://www.kernel.org/doc/html/latest/admin-guide/perf-security.html
perf_event_paranoid setting is 4:
  -1: Allow use of (almost) all events by all users
      Ignore mlock limit after perf_event_mlock_kb without CAP_IPC_LOCK
>= 0: Disallow raw and ftrace function tracepoint access
>= 1: Disallow CPU event access
>= 2: Disallow kernel profiling
To make the adjusted perf_event_paranoid setting permanent preserve it
in /etc/sysctl.conf (e.g. kernel.perf_event_paranoid = <setting>)
"""

PERF_ERR_EVENTS = """event syntax error: 'cycle_activty.stalls_l3_miss'
                     \\___ unknown term 'cycle_activty.stalls_l3_miss' for pmu 'cpu'
Run 'perf list' for a list of valid events

Error:
The sys_perf_event_open() syscall returned with 95 (Operation not supported) for event (branch-misses).

 Performance counter stats for './app':

     1,234,567,890      cycles
   <not supported>      branch-misses

       0.500000000 seconds time elapsed

Some events weren't counted. Try disabling the NMI watchdog:
	echo 0 > /proc/sys/kernel/nmi_watchdog
	perf stat ...
	echo 1 > /proc/sys/kernel/nmi_watchdog
"""

PERF_TOPDOWN_L2 = """
 Performance counter stats for './sort':

    12,000,000,000      cycles
     9,000,000,000      instructions                     #    0.75  insn per cycle
             TopdownL1                 #     45.0 %  tma_backend_bound
                                       #      5.0 %  tma_bad_speculation
                                       #     10.0 %  tma_frontend_bound
                                       #     40.0 %  tma_retiring
             TopdownL2                 #     35.0 %  tma_core_bound
                                       #     10.0 %  tma_memory_bound
                                       #      4.0 %  tma_branch_mispredicts

       3.000000000 seconds time elapsed
"""

ARM_NEOVERSE = """
 Performance counter stats for './kernel':

       2,000.00 msec task-clock                       #    1.000 CPUs utilized
  6,000,000,000      armv8_pmuv3_0/cpu_cycles/        #    3.000 GHz
  9,000,000,000      armv8_pmuv3_0/inst_retired/      #    1.50  insn per cycle
  1,200,000,000      armv8_pmuv3_0/stall_backend/
             TopdownL1                 #     20.0 %  bad_speculation
                                       #     30.0 %  frontend_bound
                                       #     20.0 %  backend_bound
                                       #     30.0 %  retiring

       2.000000000 seconds time elapsed
"""

AMD_EVENTS = """
 Performance counter stats for './db':

     5,000,000,000      cycles
     4,000,000,000      instructions                     #    0.80  insn per cycle
       300,000,000      ls_dispatch.ld_dispatch
        50,000,000      ls_any_fills_from_sys.dram_io_all

       2.000000000 seconds time elapsed
"""

# gcc 13.3 -O3 -march=native on Emerald Rapids, objdump -d --no-show-raw-insn: the vector loop of a
# float dot product compiled without -ffast-math (vmulps, then the eight lanes added in order)
OBJDUMP_NO_BYTES = """0000000000000000 <dot>:
   0:	endbr64
  26:	vxorps %xmm0,%xmm0,%xmm0
  38:	vmovups (%rax,%rsi,1),%ymm4
  3d:	vmulps (%rcx,%rsi,1),%ymm4,%ymm1
  42:	add    $0x20,%rsi
  46:	vaddss %xmm1,%xmm0,%xmm0
  4a:	vshufps $0x55,%xmm1,%xmm1,%xmm3
  54:	vaddss %xmm3,%xmm0,%xmm0
  58:	vunpckhps %xmm1,%xmm1,%xmm3
  5c:	vaddss %xmm3,%xmm0,%xmm0
  60:	vaddss %xmm2,%xmm0,%xmm0
  6b:	vaddss %xmm2,%xmm0,%xmm0
  76:	vaddss %xmm2,%xmm0,%xmm0
  88:	vaddss %xmm2,%xmm0,%xmm0
  8c:	vaddss %xmm1,%xmm0,%xmm0
  90:	cmp    %rsi,%rdi
  93:	jne    38 <dot+0x38>
"""

GDB_DISASSEMBLE = """Dump of assembler code for function sum:
   0x0000000000001139 <+0>:	endbr64
   0x000000000000113d <+4>:	vxorps %xmm0,%xmm0,%xmm0
=> 0x0000000000001141 <+8>:	vaddps (%rdi,%rax,4),%ymm0,%ymm0
   0x0000000000001146 <+13>:	add    $0x8,%rax
   0x000000000000114a <+17>:	cmp    %rax,%rsi
End of assembler dump.
"""

DSP_CODE = """/* dsp.c: inner loops of a small audio mixer. */
#include <stddef.h>

float dot(const float *a, const float *b, size_t n)
{
    float s = 0.0f;
    for (size_t i = 0; i < n; i++)
        s += a[i] * b[i];
    return s;
}

size_t first_clip(const float *x, size_t n, float limit)
{
    for (size_t i = 0; i < n; i++)
        if (x[i] > limit || x[i] < -limit)
            return i;
    return n;
}
"""

# gcc 13.3 -O3 -march=native -fopt-info-vec-all on DSP_CODE plus a mix() loop, as printed
GCC_DSP_REMARKS = """dsp.c:7:26: optimized: loop vectorized using 32 byte vectors
dsp.c:7:26: optimized: loop vectorized using 16 byte vectors
dsp.c:4:7: note: vectorized 1 loops in function.
dsp.c:4:7: note: ***** Analysis failed with vector mode V8SF
dsp.c:16:26: optimized: loop vectorized using 32 byte vectors
dsp.c:16:26: optimized:  loop versioned for vectorization because of possible aliasing
dsp.c:16:26: optimized: loop vectorized using 16 byte vectors
dsp.c:14:6: note: vectorized 1 loops in function.
dsp.c:24:14: missed: couldn't vectorize loop
dsp.c:24:14: missed: not vectorized: control flow in loop.
dsp.c:21:8: note: vectorized 0 loops in function.
"""

# clang -O3 -march=native -Rpass=loop-vectorize -Rpass-missed=loop-vectorize -Rpass-analysis=loop-vectorize
CLANG_DSP_REMARKS = """dsp.c:8:11: remark: loop not vectorized: cannot prove it is safe to reorder floating-point operations; allow reordering by specifying '#pragma clang loop vectorize(enable)' before the loop or by providing the compiler option '-ffast-math'. [-Rpass-analysis=loop-vectorize]
    8 |         s += a[i] * b[i];
      |           ^
dsp.c:7:5: remark: loop not vectorized [-Rpass-missed=loop-vectorize]
    7 |     for (size_t i = 0; i < n; i++)
      |     ^
dsp.c:16:5: remark: vectorized loop (vectorization width: 8, interleaved count: 4) [-Rpass=loop-vectorize]
dsp.c:23:5: remark: loop not vectorized: could not determine number of loop iterations [-Rpass-analysis=loop-vectorize]
dsp.c:23:5: remark: loop not vectorized [-Rpass-missed=loop-vectorize]
"""

# a struct and its hot loop, pasted with a note whose commas once read as perf stat -x
ORDER_BOOK = """struct order { uint64_t id; char symbol[16]; char client[48]; double price; uint64_t ts_created; uint64_t ts_updated; char notes[56]; uint32_t qty; uint32_t flags; }; // sizeof 160, price at offset 72, qty at offset 152
double notional(const struct order *o, size_t n){ double s=0; for(size_t i=0;i<n;i++) s+=o[i].price*o[i].qty; return s; }
N=2,000,000 orders (320 MB), ~26 ms, ~13 ns per order, best of 20
"""
