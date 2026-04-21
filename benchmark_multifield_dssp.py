"""
benchmark_multifield_dssp.py
Benchmark script for the Multi-Field DSSP implementation.

Mirrors the structure of benchmark_dssp.py (same Tables 1-5, same figures,
same CSV layout) so results are directly comparable.  Adds an optional
Table 6 that exercises the heterogeneous-field setting unique to the
multi-field extension.
"""
import random, time, statistics, csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from multifield_dssp import run_multifield_dssp

# ── graph factories (identical to the original benchmark) ────────────────────

def random_connected_graph(nv, ne):
    nodes = list(range(1, nv+1)); random.shuffle(nodes)
    edges = set()
    for k in range(1, len(nodes)):
        i = nodes[random.randint(0, k-1)]; j = nodes[k]
        edges.add((min(i,j), max(i,j)))
    att = 0
    while len(edges) < ne and att < ne*10:
        i = random.randint(1, nv); j = random.randint(1, nv)
        if i != j: edges.add((min(i,j), max(i,j)))
        att += 1
    return list(edges)

def tree_graph(nv):
    nodes = list(range(1, nv+1)); random.shuffle(nodes)
    edges = []
    for k in range(1, len(nodes)):
        i = nodes[random.randint(0, k-1)]; j = nodes[k]
        edges.append((min(i,j), max(i,j)))
    return edges

def path_graph(nv):  return [(i, i+1) for i in range(1, nv)]
def cycle_graph(nv): return [(i, i+1) for i in range(1, nv)] + [(1, nv)]
def star_graph(nl):  return [(1, i) for i in range(2, nl+2)]

# ── core run: builds (secrets, fields) and times run_multifield_dssp ─────────

def run_once(edges, l_max, equal_length=False, hetero_fields=None):
    """
    edges          : list of (i,j) tuples
    l_max          : max secret length per edge
    equal_length   : if True, every edge has exactly l_max components
    hetero_fields  : if None, use a single common q for all edges (default,
                     reproduces the original benchmark setting).
                     If given, must be a list of candidate moduli; each edge
                     samples its own q from this list (multi-field setting).
    """
    m = len(edges)
    sl = [l_max]*m if equal_length else [random.randint(1, l_max) for _ in edges]

    if hetero_fields is None:
        # single-field: same q on every edge, sized as in the old benchmark
        q = sum(sl) + 2
        q += (q % 2 == 0)        # force odd, matches original convention
        fields  = {e: q for e in edges}
        # secret components in [1, q-1] (with replacement, as in
        # multifield_dssp.test_random_* helpers)
        secrets = {e: [random.randint(1, q-1) for _ in range(sl[k])]
                   for k, e in enumerate(edges)}
    else:
        # multi-field: independent modulus per edge, secrets in [1, q_e - 1]
        fields, secrets = {}, {}
        for k, e in enumerate(edges):
            q_e = random.choice(hetero_fields)
            fields[e]  = q_e
            secrets[e] = [random.randint(1, q_e - 1) for _ in range(sl[k])]

    t0 = time.perf_counter()
    run_multifield_dssp(list(edges), secrets, fields)
    return time.perf_counter() - t0

def bench(factory, l_max, reps=10, equal_length=False, hetero_fields=None):
    times = []
    for _ in range(reps):
        try:
            times.append(run_once(factory(), l_max, equal_length, hetero_fields))
        except Exception:
            pass
    if not times: return float('nan'), float('nan')
    return statistics.mean(times), (statistics.stdev(times) if len(times) > 1 else 0)

# ── standalone Tree Protocol baseline (unchanged) ────────────────────────────

def run_tree_protocol(nv, l):
    from collections import defaultdict
    edges = tree_graph(nv); m = len(edges)
    q = m*l+3; q += q % 2 == 0
    adj = defaultdict(list)
    for (i, j) in edges:
        adj[i].append(j); adj[j].append(i)
    t0 = time.perf_counter()
    root = edges[0][0]
    parent = {root: None}; order = [root]; visited = {root}; queue = [root]
    while queue:
        cur = queue.pop(0)
        for nb in adj[cur]:
            if nb not in visited:
                visited.add(nb); parent[nb] = cur
                order.append(nb); queue.append(nb)
    Zq = list(range(1, q))
    secrets = {}
    for (i, j) in edges:
        s = [random.choice(Zq) for _ in range(l)]
        secrets[(i, j)] = s; secrets[(j, i)] = s
    r = [random.randint(1, q-1) for _ in range(l)]
    shares = {root: r}
    for node in order[1:]:
        p = parent[node]; key = (min(p, node), max(p, node))
        shares[node] = [(shares[p][k] + secrets[key][k]) % q for k in range(l)]
    return time.perf_counter() - t0

# ── standalone Cycle Protocol baseline (unchanged) ───────────────────────────

def run_cycle_protocol(m, l):
    q = m*l+3; q += q % 2 == 0
    t0 = time.perf_counter()
    Zq = list(range(1, q))
    secrets = [[random.choice(Zq) for _ in range(l)] for _ in range(m)]
    shares = []
    for i in range(m):
        sh = [(sum(s[k] for s in secrets) +
               sum(secrets[j][k] for j in range(i, m))) % q
              for k in range(l)]
        shares.append(sh)
    return time.perf_counter() - t0

# ── configuration ────────────────────────────────────────────────────────────

REPS = 10
output_folder = Path("output_multifield")
output_folder.mkdir(exist_ok=True, parents=True)

# ── TABLE 1 ──────────────────────────────────────────────────────────────────
T1_CONFIGS = [(10,20),(25,50),(50,100),(100,200),(200,400),(300,600),(500,1000)]
print("Table 1: time vs graph size (l_max=10)")
table1 = []
for nv, ne in T1_CONFIGS:
    m, s = bench(lambda n=nv, e=ne: random_connected_graph(n, e), 10, REPS)
    table1.append((nv, ne, m, s))
    print(f"  |V|={nv:4d} |E|={ne:5d}: {m:.4f} ± {s:.4f} s")

# ── TABLE 2 ──────────────────────────────────────────────────────────────────
T2_LMAX = [1, 5, 10, 20, 30, 50]
print("\nTable 2: time vs l_max (|V|=100, |E|=200)")
table2 = []
for lmax in T2_LMAX:
    m, s = bench(lambda: random_connected_graph(100, 200), lmax, REPS)
    table2.append((lmax, m, s))
    print(f"  l_max={lmax:3d}: {m:.4f} ± {s:.4f} s")

# ── TABLE 3: DSSP vs Tree Protocol ──────────────────────────────────────────
CMP_SIZES = [10, 25, 50, 100, 200, 300, 500]
L = 10
print("\nTable 3: Multi-Field DSSP vs Tree Protocol (l=10, tree graphs)")
table3 = []
for nv in CMP_SIZES:
    md, sd = bench(lambda n=nv: tree_graph(n), L, REPS, equal_length=True)
    tt = [run_tree_protocol(nv, L) for _ in range(REPS)]
    mt = statistics.mean(tt); st = statistics.stdev(tt) if len(tt) > 1 else 0
    ratio = md/mt if mt > 0 else float('nan')
    table3.append((nv, md, sd, mt, st, ratio))
    print(f"  |V|={nv:4d}: DSSP={md:.4f}s  Tree={mt:.4f}s  ratio={ratio:.2f}x")

# ── TABLE 4: DSSP vs Cycle Protocol ─────────────────────────────────────────
print("\nTable 4: Multi-Field DSSP vs Cycle Protocol (l=10, cycle graphs)")
table4 = []
for m in CMP_SIZES:
    md, sd = bench(lambda n=m: cycle_graph(n), L, REPS, equal_length=True)
    tc = [run_cycle_protocol(m, L) for _ in range(REPS)]
    mc = statistics.mean(tc); sc = statistics.stdev(tc) if len(tc) > 1 else 0
    ratio = md/mc if mc > 0 else float('nan')
    table4.append((m, md, sd, mc, sc, ratio))
    print(f"  m={m:4d}: DSSP={md:.4f}s  Cycle={mc:.4f}s  ratio={ratio:.2f}x")

# ── TABLE 5: topology comparison ────────────────────────────────────────────
TOPO_N, TOPO_L = 100, 10
print(f"\nTable 5: time by topology (|V|={TOPO_N}, l_max={TOPO_L})")
topo_factories = {
    "Star":   lambda: star_graph(TOPO_N-1),
    "Path":   lambda: path_graph(TOPO_N),
    "Cycle":  lambda: cycle_graph(TOPO_N),
    "Tree":   lambda: tree_graph(TOPO_N),
    "Random": lambda: random_connected_graph(TOPO_N, 2*TOPO_N),
}
table5 = []
for name, factory in topo_factories.items():
    m, s = bench(factory, TOPO_L, REPS)
    table5.append((name, m, s))
    print(f"  {name:8s}: {m:.4f} ± {s:.4f} s")

# ── TABLE 6: heterogeneous fields (multi-field specific) ────────────────────
# Compare single-field (all edges share one q) vs multi-field (each edge picks
# its own q from a small set of moduli). This is the regime that the original
# DSSP could not handle.
HETERO_POOL = [5, 7, 11, 13, 15]
print(f"\nTable 6: single-field vs multi-field "
      f"(|V|=100, |E|=200, l_max=10, fields ∈ {HETERO_POOL})")
table6 = []
for label, hf in [("single-field", None), ("multi-field", HETERO_POOL)]:
    m, s = bench(lambda: random_connected_graph(100, 200),
                 10, REPS, hetero_fields=hf)
    table6.append((label, m, s))
    print(f"  {label:13s}: {m:.4f} ± {s:.4f} s")

# ── FIGURES ─────────────────────────────────────────────────────────────────
print("\nGenerating figures...")

# Fig 1: time vs nodes, several l_max
FIG1_LMAX = [5, 10, 20, 50]
fig1_data = {}
for lmax in FIG1_LMAX:
    rows = []
    for nv, ne in T1_CONFIGS:
        m, s = bench(lambda n=nv, e=ne: random_connected_graph(n, e), lmax, REPS)
        rows.append((nv, m, s))
    fig1_data[lmax] = rows

fig, ax = plt.subplots(figsize=(6, 4))
markers = ["o", "s", "^", "D"]
for idx, lmax in enumerate(FIG1_LMAX):
    xs   = [r[0] for r in fig1_data[lmax]]
    ys   = [r[1] for r in fig1_data[lmax]]
    errs = [r[2] for r in fig1_data[lmax]]
    ax.errorbar(xs, ys, yerr=errs, label=f"$\\ell_{{\\max}}={lmax}$",
                marker=markers[idx], capsize=3)
ax.set_xlabel("Number of nodes $|V|$"); ax.set_ylabel("Execution time (s)")
ax.set_title("Execution time vs.~number of nodes ($|E|=2|V|$)")
ax.legend(); ax.grid(True, linestyle="--", alpha=0.5)
fig.tight_layout()
fig.savefig(output_folder/"fig_time_vs_nodes.pdf")
fig.savefig(output_folder/"fig_time_vs_nodes.png")

# Fig 2: time vs l_max
fig, ax = plt.subplots(figsize=(5, 4))
ax.errorbar([r[0] for r in table2], [r[1] for r in table2],
            yerr=[r[2] for r in table2], marker="o", capsize=3, color="steelblue")
ax.set_xlabel("$\\ell_{\\max}$"); ax.set_ylabel("Execution time (s)")
ax.set_title("Execution time vs.~$\\ell_{\\max}$ ($|V|=100$, $|E|=200$)")
ax.grid(True, linestyle="--", alpha=0.5)
fig.tight_layout()
fig.savefig(output_folder/"fig_time_vs_lmax.pdf")
fig.savefig(output_folder/"fig_time_vs_lmax.png")

# Fig 3: theoretical SO vs m (unchanged: same theoretical curve)
m_vals = list(range(1, 201)); so_vals = [1 + 1/mm for mm in m_vals]
fig, ax = plt.subplots(figsize=(5, 4))
ax.plot(m_vals, so_vals, color="steelblue", linewidth=1.8, label="$SO=1+1/m$")
ax.axhline(y=1, color="gray", linestyle="--", linewidth=1.2, label="Lower bound $SO=1$")
ax.set_xlabel("Number of secrets $m$"); ax.set_ylabel("Storage overhead $SO$")
ax.set_title("Theoretical $SO$ for tree-based structures\n(equal-length secrets)")
ax.legend(); ax.set_ylim(0.95, 2.1); ax.grid(True, linestyle="--", alpha=0.5)
fig.tight_layout()
fig.savefig(output_folder/"fig_so_vs_m.pdf")
fig.savefig(output_folder/"fig_so_vs_m.png")

# Fig 4: comparison vs Tree / Cycle baselines
fig, axes = plt.subplots(1, 2, figsize=(10, 4))
ax = axes[0]
ax.errorbar([r[0] for r in table3], [r[1] for r in table3],
            yerr=[r[2] for r in table3], marker="o", capsize=3,
            label="Multi-Field DSSP", color="steelblue")
ax.errorbar([r[0] for r in table3], [r[3] for r in table3],
            yerr=[r[4] for r in table3], marker="s", capsize=3,
            label="Tree Protocol", color="darkorange", linestyle="--")
ax.set_xlabel("$|V|$"); ax.set_ylabel("Time (s)")
ax.set_title(f"Tree graphs ($\\ell={L}$)")
ax.legend(fontsize=8); ax.grid(True, linestyle="--", alpha=0.5)
ax = axes[1]
ax.errorbar([r[0] for r in table4], [r[1] for r in table4],
            yerr=[r[2] for r in table4], marker="o", capsize=3,
            label="Multi-Field DSSP", color="steelblue")
ax.errorbar([r[0] for r in table4], [r[3] for r in table4],
            yerr=[r[4] for r in table4], marker="s", capsize=3,
            label="Cycle Protocol", color="darkorange", linestyle="--")
ax.set_xlabel("$m$"); ax.set_ylabel("Time (s)")
ax.set_title(f"Cycle graphs ($\\ell={L}$)")
ax.legend(fontsize=8); ax.grid(True, linestyle="--", alpha=0.5)
fig.suptitle("Multi-Field DSSP vs.~baseline protocols (homogeneous secrets)",
             fontsize=11)
fig.tight_layout()
fig.savefig(output_folder/"fig_comparison.pdf")
fig.savefig(output_folder/"fig_comparison.png")

# Fig 5: topology bars
fig, ax = plt.subplots(figsize=(6, 4))
names = [r[0] for r in table5]
means = [r[1] for r in table5]
stds  = [r[2] for r in table5]
colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"]
ax.bar(names, means, yerr=stds, capsize=5, color=colors, edgecolor="white")
ax.set_xlabel("Topology"); ax.set_ylabel("Time (s)")
ax.set_title(f"Execution time by topology "
             f"($|V|={TOPO_N}$, $\\ell_{{\\max}}={TOPO_L}$)")
ax.grid(True, axis="y", linestyle="--", alpha=0.5)
fig.tight_layout()
fig.savefig(output_folder/"fig_topology.pdf")
fig.savefig(output_folder/"fig_topology.png")

# Fig 6: single-field vs multi-field bars
fig, ax = plt.subplots(figsize=(5, 4))
labels = [r[0] for r in table6]
means  = [r[1] for r in table6]
stds   = [r[2] for r in table6]
ax.bar(labels, means, yerr=stds, capsize=5,
       color=["#4C72B0", "#C44E52"], edgecolor="white")
ax.set_ylabel("Time (s)")
ax.set_title(f"Single-field vs multi-field\n"
             f"($|V|=100$, $|E|=200$, $\\ell_{{\\max}}=10$)")
ax.grid(True, axis="y", linestyle="--", alpha=0.5)
fig.tight_layout()
fig.savefig(output_folder/"fig_single_vs_multi.pdf")
fig.savefig(output_folder/"fig_single_vs_multi.png")

# ── CSV ─────────────────────────────────────────────────────────────────────
with open(output_folder/"benchmark_results.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["TABLE 1", "l_max=10", f"reps={REPS}"])
    w.writerow(["|V|", "|E|", "mean_s", "std_s"])
    for r in table1: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 2", "|V|=100", "|E|=200", f"reps={REPS}"])
    w.writerow(["l_max", "mean_s", "std_s"])
    for r in table2: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 3 DSSP vs Tree", f"l={L}", f"reps={REPS}"])
    w.writerow(["|V|", "DSSP_mean", "DSSP_std", "Tree_mean", "Tree_std", "ratio"])
    for r in table3: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 4 DSSP vs Cycle", f"l={L}", f"reps={REPS}"])
    w.writerow(["m", "DSSP_mean", "DSSP_std", "Cycle_mean", "Cycle_std", "ratio"])
    for r in table4: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 5 by topology", f"|V|={TOPO_N}",
                                f"l_max={TOPO_L}", f"reps={REPS}"])
    w.writerow(["Topology", "mean_s", "std_s"])
    for r in table5: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 6 single-field vs multi-field",
                                f"|V|=100", f"|E|=200", f"l_max=10",
                                f"pool={HETERO_POOL}", f"reps={REPS}"])
    w.writerow(["setting", "mean_s", "std_s"])
    for r in table6: w.writerow(r)

print("Done. Files: benchmark_results.csv + 6 figures (pdf+png)")
