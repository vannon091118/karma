# Performance Domain — Snake2D V71.63

---
verified_against: "SyxCraft/src/ + pom.xml"
verified_at: "2026-07-16"
staleness_risk: "low"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.

> **Responsibility:** Tick budget, memory management, GC optimization, profiling, JVM tuning
> **Owner:** Performance Domain Agent

---

## Tick Budget (V71.63)

### Targets

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Total mod tick | < 2.0 ms | > 3.0 ms |
| Engine API queries | < 0.5 ms | > 1.0 ms |
| Manager updates | < 1.0 ms | > 2.0 ms |
| Save serialization | < 2.0 ms | N/A (on-demand) |
| Memory allocation/tick | < 100 KB | > 500 KB |
| GC pause (young) | < 5 ms | > 20 ms |
| Heap usage (steady) | < 500 MB | > 1 GB |

---

## JVM Configuration (Recommended)

```bash
# Launch arguments for modded game
-Xms1G -Xmx2G \
-XX:+UseG1GC \
-XX:MaxGCPauseMillis=10 \
-XX:G1HeapRegionSize=8M \
-XX:+UnlockExperimentalVMOptions \
-XX:+UseStringDeduplication \
-XX:+ParallelRefProcEnabled \
-XX:-UseCompressedOops \
-Dsun.java2d.opengl=true
```

### G1GC Tuning Rationale

| Flag | Purpose |
|------|---------|
| `-XX:+UseG1GC` | Low-latency collector |
| `-XX:MaxGCPauseMillis=10` | Target < 10ms pauses |
| `-XX:G1HeapRegionSize=8M` | Better for modded heaps |
| `-XX:+UseStringDeduplication` | Reduces string memory |
| `-XX:+ParallelRefProcEnabled` | Faster reference processing |

---

## Memory Management

### Allocation Patterns (Do/Don't)

| Pattern | Verdict | Alternative |
|---------|---------|-------------|
| `new ArrayList<>()` per tick | ❌ GC pressure | Reuse static buffers |
| `String.format()` per tick | ❌ Allocation | `StringBuilder` reuse |
| `new Object()` in loop | ❌ GC pressure | Object pool |
| Primitive arrays | ✅ Low overhead | — |
| Reused `FilePutter`/`FileGetter` | ✅ | — |

### Object Pools

```java
public class TickBufferPool {
    private static final int POOL_SIZE = 16;
    private static final Queue<int[]> intPool = new ArrayDeque<>();
    private static final Queue<float[]> floatPool = new ArrayDeque<>();
    
    static {
        for (int i = 0; i < POOL_SIZE; i++) {
            intPool.offer(new int[1024]);
            floatPool.offer(new float[1024]);
        }
    }
    
    public static int[] acquireInt(int size) {
        int[] arr = intPool.poll();
        if (arr == null || arr.length < size) return new int[size];
        return arr;
    }
    
    public static void releaseInt(int[] arr) {
        if (arr != null) intPool.offer(arr);
    }
    
    // Similar for float[], StringBuilder, etc.
}
```

---

## Profiling Tools

### In-Game (Runtime)

```java
// Per-tick timing
long start = System.nanoTime();
// ... tick logic ...
long elapsedMs = (System.nanoTime() - start) / 1_000_000;

if (elapsedMs > 5) {
    System.err.println("[SYXCRAFT-PERF] Slow tick: " + elapsedMs + "ms");
}

// Allocation tracking
if (System.currentTimeMillis() - lastAllocCheck > 10000) {
    long allocated = ManagementFactory.getMemoryMXBean().getHeapMemoryUsage().getUsed();
    System.out.println("[SYXCRAFT-PERF] Heap: " + (allocated / 1024 / 1024) + " MB");
    lastAllocCheck = System.currentTimeMillis();
}
```

### External Profiling

```bash
# Java Flight Recorder (JFR)
-XX:StartFlightRecording=duration=60s,filename=syxcraft.jfr

# Async Profiler
./profiler.sh -d 60 -f flamegraph.html -e cpu,alloc <pid>

# VisualVM / JConsole for live monitoring
```

---

## GC Monitoring

### Key Metrics

| Metric | Healthy | Warning | Action |
|--------|---------|---------|--------|
| Young GC frequency | 1-5/sec | > 10/sec | Increase heap, reduce allocation |
| Young GC pause | < 5ms | > 20ms | Tune G1, reduce object rate |
| Old GC frequency | < 1/hour | > 1/10min | Check for memory leaks |
| Old GC pause | < 50ms | > 200ms | Increase `-Xmx`, tune G1 |
| Heap after GC | < 50% | > 80% | Increase `-Xmx` |

### Memory Leak Detection

```java
public class LeakDetector {
    private static final Map<Class<?>, AtomicLong> instanceCounts = new ConcurrentHashMap<>();
    
    public static void track(Object obj) {
        instanceCounts.computeIfAbsent(obj.getClass(), k -> new AtomicLong()).incrementAndGet();
    }
    
    public static void report() {
        instanceCounts.forEach((cls, count) -> 
            System.out.println("[LEAK] " + cls.getSimpleName() + ": " + count.get()));
    }
}
```

---

## Optimization Checklist

- [ ] Reuse collections/Object pools for per-tick allocations
- [ ] No `String.format()` in hot paths
- [ ] Reflection calls < 50/tick
- [ ] Object allocation < 100 KB/tick
- [ ] Young GC < 5ms, < 1% CPU
- [ ] No full GC during gameplay
- [ ] Heap stable after 1 hour
- [ ] Tick time P99 < 3ms
- [ ] JFR recording captured for 60+ seconds
- [ ] No steady-state heap growth over 1 hour

---

*Performance Domain — Tick Budget Authority*