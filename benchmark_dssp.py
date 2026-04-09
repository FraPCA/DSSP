"""
benchmark_dssp.py
-----------------
Benchmark script for the DSSP protocol (FraPCA/DSSP).

Run this script from the same folder as dssp.py:
    python benchmark_dssp.py

It generates:
  - Table 1: execution time vs graph size (|V|, |E| = 2|V|, l_max = 10)
  - Table 2: execution time vs l_max    (|V| = 100, |E| = 200)
  - Figure 1: time vs nodes             (fig_time_vs_nodes.pdf)
  - Figure 2: time vs l_max             (fig_time_vs_lmax.pdf)
  - Figure 3: storage overhead SO       (fig_so_vs_m.pdf)

All results are also saved to benchmark_results.csv.
"""

import time
import random
import statistics
import csv
import matplotlib
matplotlib.use("Agg")          # non-interactive backend, no display needed
from matplotlib import pyplot as plt
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the protocol.  We call DSSPTestable() which skips the visualize()
# calls (no GUI needed during benchmarks).
# ---------------------------------------------------------------------------
from dssp import DSSPTestable, DSSPSetVariables, altGenerateGraph

# ---------------------------------------------------------------------------
# Helper: build a random connected graph with |V| nodes and |E| edges
# ---------------------------------------------------------------------------

def random_connected_graph(num_nodes: int, num_edges: int):
    """
    Returns (access_structure, secret_lengths) for a random connected graph.
    access_structure: list of [i, j] edges (1-indexed nodes)
    secret_lengths:   list of secret lengths, one per edge
    l_max is fixed externally.
    """
    assert num_edges >= num_nodes - 1, "Need at least n-1 edges for connectivity"

    # Build a random spanning tree first
    nodes = list(range(1, num_nodes + 1))
    random.shuffle(nodes)
    edges = set()
    for k in range(1, len(nodes)):
        i = nodes[random.randint(0, k - 1)]
        j = nodes[k]
        edges.add((min(i, j), max(i, j)))

    # Add random extra edges
    attempts = 0
    while len(edges) < num_edges and attempts < num_edges * 10:
        i = random.randint(1, num_nodes)
        j = random.randint(1, num_nodes)
        if i != j:
            edges.add((min(i, j), max(i, j)))
        attempts += 1

    return list(edges)


def make_inputs(edges, l_max: int):
    """
    Given a list of (i,j) edge tuples and l_max, return the inputs
    needed by DSSPTestable / DSSPSetVariables.
    """
    m = len(edges)
    # Assign random secret lengths uniformly in [1, l_max]
    secret_lengths = [random.randint(1, l_max) for _ in edges]
    n = max(max(e) for e in edges)   # number of nodes = max node index
    sum_lengths = sum(secret_lengths)
    # q must be odd, >= 3, and > sum_lengths
    q = sum_lengths + 1
    if q < 3:
        q = 3
    if q % 2 == 0:
        q += 1
    access_structure = [list(e) for e in edges]
    return m, secret_lengths, n, q, access_structure


def run_once(edges, l_max: int):
    """Run the protocol once and return elapsed time in seconds."""
    m, secret_lengths, n, q, access_structure = make_inputs(edges, l_max)
    t0 = time.perf_counter()
    ret = DSSPTestable(m, secret_lengths, n, q, access_structure)
    t1 = time.perf_counter()
    if ret != 0:
        raise RuntimeError(f"DSSPTestable returned error code {ret}")
    return t1 - t0


def benchmark(edges_list_factory, l_max: int, repetitions: int = 10):
    """
    edges_list_factory: callable () -> list of (i,j) edges
    Returns (mean, std) in seconds.
    """
    times = []
    for _ in range(repetitions):
        edges = edges_list_factory()
        try:
            t = run_once(edges, l_max)
            times.append(t)
        except Exception as e:
            print(f"  Warning: run failed ({e}), skipping.")
    if not times:
        return float("nan"), float("nan")
    mean = statistics.mean(times)
    std  = statistics.stdev(times) if len(times) > 1 else 0.0
    return mean, std


output_folder = Path("output")
output_folder.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Table 1: time vs graph size
# ---------------------------------------------------------------------------

TABLE1_CONFIGS = [
    (10,   20),
    (25,   50),
    (50,  100),
    (100, 200),
    (200, 400),
    (300, 600),
    (500, 1000),
]
TABLE1_LMAX = 10
REPETITIONS = 10

print("=" * 60)
print("Table 1: execution time vs graph size")
print(f"  l_max = {TABLE1_LMAX}, repetitions = {REPETITIONS}")
print("=" * 60)
print(f"{'|V|':>6}  {'|E|':>6}  {'mean (s)':>12}  {'std (s)':>10}")
print("-" * 40)

table1_rows = []
for num_nodes, num_edges in TABLE1_CONFIGS:
    factory = lambda nv=num_nodes, ne=num_edges: random_connected_graph(nv, ne)
    mean, std = benchmark(factory, TABLE1_LMAX, REPETITIONS)
    table1_rows.append((num_nodes, num_edges, mean, std))
    print(f"{num_nodes:>6}  {num_edges:>6}  {mean:>12.4f}  {std:>10.4f}")

# ---------------------------------------------------------------------------
# Table 2: time vs l_max
# ---------------------------------------------------------------------------

TABLE2_LMAX_VALUES = [1, 5, 10, 20, 30, 50]
TABLE2_NODES = 100
TABLE2_EDGES = 200

print()
print("=" * 60)
print("Table 2: execution time vs l_max")
print(f"  |V| = {TABLE2_NODES}, |E| = {TABLE2_EDGES}, repetitions = {REPETITIONS}")
print("=" * 60)
print(f"{'l_max':>8}  {'mean (s)':>12}  {'std (s)':>10}")
print("-" * 35)

table2_rows = []
for lmax in TABLE2_LMAX_VALUES:
    factory = lambda nv=TABLE2_NODES, ne=TABLE2_EDGES: random_connected_graph(nv, ne)
    mean, std = benchmark(factory, lmax, REPETITIONS)
    table2_rows.append((lmax, mean, std))
    print(f"{lmax:>8}  {mean:>12.4f}  {std:>10.4f}")

# ---------------------------------------------------------------------------
# Figure 1: time vs nodes (multiple l_max curves)
# ---------------------------------------------------------------------------

FIG1_LMAX_VALUES = [5, 10, 20, 50]
FIG1_NODE_COUNTS = [10, 25, 50, 100, 200, 300, 500]

print()
print("Generating Figure 1: time vs nodes ...")

fig1_data = {}   # l_max -> list of (nodes, mean, std)
for lmax in FIG1_LMAX_VALUES:
    rows = []
    for nv in FIG1_NODE_COUNTS:
        ne = 2 * nv
        factory = lambda n=nv, e=ne: random_connected_graph(n, e)
        mean, std = benchmark(factory, lmax, REPETITIONS)
        rows.append((nv, mean, std))
        print(f"  l_max={lmax}, |V|={nv}: {mean:.4f} ± {std:.4f} s")
    fig1_data[lmax] = rows

fig, ax = plt.subplots(figsize=(6, 4))
markers = ["o", "s", "^", "D"]
for idx, lmax in enumerate(FIG1_LMAX_VALUES):
    rows = fig1_data[lmax]
    xs   = [r[0] for r in rows]
    ys   = [r[1] for r in rows]
    errs = [r[2] for r in rows]
    ax.errorbar(xs, ys, yerr=errs, label=f"$\\ell_{{\\max}}={lmax}$",
                marker=markers[idx], capsize=3)
ax.set_xlabel("Number of nodes $|V|$")
ax.set_ylabel("Execution time (s)")
ax.set_title("Execution time vs.~number of nodes ($|E|=2|V|$)")
ax.legend()
ax.grid(True, linestyle="--", alpha=0.5)
fig.tight_layout()
fig.savefig(output_folder/"fig_time_vs_nodes.pdf")
print("  Saved fig_time_vs_nodes.pdf")

# ---------------------------------------------------------------------------
# Figure 2: time vs l_max
# ---------------------------------------------------------------------------

print()
print("Generating Figure 2: time vs l_max ...")

fig2_lmax = [1, 5, 10, 20, 30, 50]
fig2_rows = []
for lmax in fig2_lmax:
    factory = lambda nv=TABLE2_NODES, ne=TABLE2_EDGES: random_connected_graph(nv, ne)
    mean, std = benchmark(factory, lmax, REPETITIONS)
    fig2_rows.append((lmax, mean, std))
    print(f"  l_max={lmax}: {mean:.4f} ± {std:.4f} s")

fig, ax = plt.subplots(figsize=(5, 4))
xs   = [r[0] for r in fig2_rows]
ys   = [r[1] for r in fig2_rows]
errs = [r[2] for r in fig2_rows]
ax.errorbar(xs, ys, yerr=errs, marker="o", capsize=3, color="steelblue")
ax.set_xlabel("Maximum secret length $\\ell_{\\max}$")
ax.set_ylabel("Execution time (s)")
ax.set_title(f"Execution time vs.~$\\ell_{{\\max}}$ ($|V|={TABLE2_NODES}$, $|E|={TABLE2_EDGES}$)")
ax.grid(True, linestyle="--", alpha=0.5)
fig.tight_layout()
fig.savefig(output_folder/"fig_time_vs_lmax.pdf")
print("  Saved fig_time_vs_lmax.pdf")

# ---------------------------------------------------------------------------
# Figure 3: storage overhead SO = 1 + 1/m (theoretical, tree with equal lengths)
# ---------------------------------------------------------------------------

print()
print("Generating Figure 3: storage overhead SO vs m ...")

m_values = list(range(1, 201))
so_values = [1.0 + 1.0 / m for m in m_values]

fig, ax = plt.subplots(figsize=(5, 4))
ax.plot(m_values, so_values, color="steelblue", linewidth=1.8,
        label="$SO = 1 + 1/m$")
ax.axhline(y=1.0, color="gray", linestyle="--", linewidth=1.2,
           label="Lower bound $SO = 1$")
ax.set_xlabel("Number of secrets $m$")
ax.set_ylabel("Storage overhead $SO$")
ax.set_title("Theoretical $SO$ for tree-based access structures\n(equal-length secrets)")
ax.legend()
ax.set_ylim(0.95, 2.1)
ax.grid(True, linestyle="--", alpha=0.5)
fig.tight_layout()
fig.savefig(output_folder/"fig_so_vs_m.pdf")
print("  Saved fig_so_vs_m.pdf")

# ---------------------------------------------------------------------------
# Save all numeric results to CSV
# ---------------------------------------------------------------------------

print()
print("Saving results to benchmark_results.csv ...")

with open(output_folder/"benchmark_results.csv", "w", newline="") as f:
    writer = csv.writer(f)

    writer.writerow(["TABLE 1: time vs graph size", f"l_max={TABLE1_LMAX}", f"reps={REPETITIONS}"])
    writer.writerow(["|V|", "|E|", "mean_time_s", "std_time_s"])
    for row in table1_rows:
        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["TABLE 2: time vs l_max", f"|V|={TABLE2_NODES}", f"|E|={TABLE2_EDGES}", f"reps={REPETITIONS}"])
    writer.writerow(["l_max", "mean_time_s", "std_time_s"])
    for row in table2_rows:
        writer.writerow(row)

print("  Saved benchmark_results.csv")
print()
print("All done.")
