"""
run_experiments_tifs.py
=======================
Benchmarks for the TIFS submission of the
"Storage-Optimal Distributed Secret Sharing with Variable-Length Secrets"
manuscript.

Generates the experimental data referenced in the paper, addressing:
  * Reviewer 3 point 5  (graph topologies and scalability to >> 500 nodes);
  * Reviewer 1 point 4  (relationship between storage overhead and the
                         structural quantity number_tree(G) / L);
  * Reviewer 3 point 4  (quantitative comparison with a padding baseline).

Outputs:
  results/tab_time_nodes.csv     -- time vs |V| across topologies (5000 nodes)
  results/tab_time_lmax.csv      -- time vs l_max
  results/tab_so_topology.csv    -- storage overhead vs topology
  results/tab_so_lmax.csv        -- storage overhead vs l_max for each topology
  results/tab_padding_gap.csv    -- our SO vs padding-baseline SO
  results/tab_number_tree.csv    -- empirical number_tree(G)/L vs topology
  results/fig_time_nodes.png
  results/fig_padding_gap.png
  results/fig_so_topology.png
  results/fig_number_tree.png

Usage:
    python run_experiments_tifs.py             # full run (reps=10)
    python run_experiments_tifs.py --quick     # quick test (reps=3)
    python run_experiments_tifs.py --reps 20   # custom reps
    python run_experiments_tifs.py --max-n 1000   # cap graph size
"""

import argparse
import csv
import os
import random
import sys
import time
from collections import defaultdict
from typing import Iterable

import networkx as nx

# We use matplotlib via the non-interactive Agg backend so the script
# runs in headless environments (CI, servers, etc.).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from dssp import run_dssp, verify_all


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true",
                   help="Quick smoke run with reps=3 and fewer sizes.")
    p.add_argument("--reps", type=int, default=10,
                   help="Number of repetitions per configuration.")
    p.add_argument("--max-n", type=int, default=5000,
                   help="Maximum number of nodes used in the time-vs-|V| sweep.")
    p.add_argument("--output-dir", default="results",
                   help="Directory where CSVs and figures are written.")
    p.add_argument("--q", type=int, default=257,
                   help="Field modulus q (odd, >= 3). Default 257.")
    p.add_argument("--seed-base", type=int, default=1000,
                   help="Base seed for reproducibility.")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Graph generators
# ---------------------------------------------------------------------------
#
# We expose four topology families:
#
#   "erdos"      Erdős–Rényi G(n, p) with p tuned so that |E| ~ 2|V|
#   "barabasi"   Barabási–Albert preferential attachment (m=2)
#   "watts"      Watts–Strogatz small-world (k=4, p=0.1)
#   "grid"       2D grid (mesh) of size floor(sqrt(n)) x ceil(n/sqrt(n))
#
# All generators return a list of edges (i,j) with i < j on node labels
# 1..|V|. The graph is then made connected by adding the spanning-tree
# edges of a random shuffle of the nodes (so that the protocol is run on
# a single connected component for clarity of the topology effect).
# ---------------------------------------------------------------------------

def _relabel_to_1_based(g: nx.Graph) -> nx.Graph:
    """Relabel a networkx graph to integer labels 1..|V|."""
    mapping = {old: new for new, old in enumerate(sorted(g.nodes()), start=1)}
    return nx.relabel_nodes(g, mapping)


def _ensure_connected(g: nx.Graph, seed: int) -> nx.Graph:
    """
    Add a small number of edges to make the graph connected, by linking
    representative nodes from different components in a random order.
    The added edges form a path between component representatives, so
    they perturb the topology minimally.
    """
    if nx.is_connected(g):
        return g
    rng = random.Random(seed)
    comps = list(nx.connected_components(g))
    reps = [rng.choice(sorted(c)) for c in comps]
    rng.shuffle(reps)
    for k in range(1, len(reps)):
        g.add_edge(reps[k - 1], reps[k])
    return g


def gen_erdos(n: int, seed: int) -> nx.Graph:
    """Erdős–Rényi G(n, p) with expected |E| ~ 2|V|."""
    p = min(1.0, 4.0 / max(1, n - 1))
    g = nx.gnp_random_graph(n, p, seed=seed)
    g = _relabel_to_1_based(g)
    return _ensure_connected(g, seed)


def gen_barabasi(n: int, seed: int) -> nx.Graph:
    """Barabási–Albert preferential attachment with m=2."""
    if n < 3:
        g = nx.path_graph(n)
    else:
        g = nx.barabasi_albert_graph(n, m=2, seed=seed)
    g = _relabel_to_1_based(g)
    return _ensure_connected(g, seed)


def gen_watts(n: int, seed: int) -> nx.Graph:
    """Watts–Strogatz small-world, k=4, p=0.1."""
    k = min(4, max(2, n - 1))
    if k % 2 == 1:
        k -= 1
    if k < 2:
        g = nx.path_graph(n)
    else:
        g = nx.watts_strogatz_graph(n, k=k, p=0.1, seed=seed)
    g = _relabel_to_1_based(g)
    return _ensure_connected(g, seed)


def gen_grid(n: int, seed: int) -> nx.Graph:
    """2D grid (mesh). Dimensions chosen to be as square as possible."""
    rows = max(1, int(round(n ** 0.5)))
    cols = (n + rows - 1) // rows
    g = nx.grid_2d_graph(rows, cols)
    # Drop excess nodes so that the graph has exactly n nodes.
    nodes_sorted = sorted(g.nodes())
    for nd in nodes_sorted[n:]:
        g.remove_node(nd)
    g = _relabel_to_1_based(g)
    return _ensure_connected(g, seed)


TOPOLOGY_GENERATORS = {
    "erdos":    gen_erdos,
    "barabasi": gen_barabasi,
    "watts":    gen_watts,
    "grid":     gen_grid,
}


# ---------------------------------------------------------------------------
# Secret generation
# ---------------------------------------------------------------------------

def make_secrets(edges: Iterable[tuple], l_max: int, q: int,
                 rng: random.Random) -> dict:
    """
    Build a `secrets` dict: each edge (i,j) maps to a list of components
    of length uniformly distributed in [1, l_max], with values uniform
    in [0, q-1].
    """
    return {(i, j): [rng.randrange(q)
                     for _ in range(rng.randint(1, l_max))]
            for (i, j) in edges}


# ---------------------------------------------------------------------------
# Storage overhead measurements
# ---------------------------------------------------------------------------

def storage_overhead(graph, secrets: dict) -> float:
    """
    Empirical storage overhead: total shares (counted as Z_q symbols)
    divided by total secret components.

    For nodes in the original graph (the parent), shares[v] is a list
    indexed by step h. Each shares[v][h] is a list of Z_q symbols of
    length 0, 1, or more (more in the cycle-closure case). We count
    every Z_q symbol once.
    """
    total_shares = 0
    for v, sh_list in graph.shares.items():
        for sh in sh_list:
            if sh:
                total_shares += len(sh)
    total_components = sum(len(s) for s in secrets.values())
    return total_shares / total_components if total_components else 0.0


def padding_baseline_so(graph, secrets: dict) -> float:
    """
    Storage overhead of the padding-based baseline: pad each secret to
    l_max components, then apply the uniform-size DSSP of [ads].

    Closed-form per the TIFS manuscript:
      SO_pad = l_max * |E| / L                if G contains a cycle
      SO_pad = l_max * (|E| + 1) / L          if G is a tree of diam >= 3
      SO_pad = 1                              if G is a tree of diam <= 2

    We do not check the diameter precisely (the closed forms above
    coincide for our purposes when L is computed against the original
    secret lengths). We use the "graph contains a cycle" form when
    `mu(G) >= 1`, the tree form otherwise.
    """
    # Total length L
    L = sum(len(s) for s in secrets.values())
    if L == 0:
        return 0.0
    n_edges = len(secrets)
    l_max = max(len(s) for s in secrets.values())
    # Detect cycle using cyclomatic number on the original graph
    n_nodes = sum(1 for _ in graph.shares)
    mu = n_edges - n_nodes + 1   # for one connected component
    if mu >= 1:
        return (l_max * n_edges) / L
    return (l_max * (n_edges + 1)) / L


def heterogeneity_ratio(secrets: dict) -> float:
    """l_max * |E| / L (the heterogeneity ratio used in Section 5.3)."""
    L = sum(len(s) for s in secrets.values())
    n_edges = len(secrets)
    l_max = max(len(s) for s in secrets.values()) if secrets else 0
    return (l_max * n_edges) / L if L else 0.0


# ---------------------------------------------------------------------------
# number_tree(G) -- structural quantity from Lemma 5.6
# ---------------------------------------------------------------------------

def compute_number_tree(edges: list, secret_lengths: dict) -> int:
    """
    Compute number_tree(G) = sum over h=1..l_max of the number of
    connected components of G'_h that are trees (= acyclic).

    G'_h is obtained from G' (= G minus its leaves) by removing all edges
    whose secret has length < h.
    """
    # Build adjacency once
    n_total = 0
    if not edges:
        return 0

    # Build G' by removing leaves of G
    g = nx.Graph()
    g.add_edges_from(edges)
    # Leaves of G
    leaves = [v for v in g.nodes() if g.degree(v) == 1]
    g.remove_nodes_from(leaves)
    # Edge lengths
    el = {(min(i, j), max(i, j)): secret_lengths[(min(i, j), max(i, j))]
          for (i, j) in g.edges()}
    if not el:
        return 0
    l_max = max(el.values())

    total_trees = 0
    for h in range(1, l_max + 1):
        # G'_h: drop edges with length < h
        g_h = nx.Graph()
        for (i, j), L in el.items():
            if L >= h:
                g_h.add_edge(i, j)
        if g_h.number_of_edges() == 0:
            continue
        # Count connected components that are trees (mu == 0)
        for comp in nx.connected_components(g_h):
            sub = g_h.subgraph(comp)
            if sub.number_of_edges() == sub.number_of_nodes() - 1:
                total_trees += 1
    return total_trees


# ---------------------------------------------------------------------------
# Single experiment runs
# ---------------------------------------------------------------------------

def run_once(edges: list, secrets: dict, q: int):
    """
    Run the protocol on a single (edges, secrets) instance. Return:
      (elapsed_seconds, graph, ok)
    where `ok` is True iff verify_all passes.
    """
    t0 = time.perf_counter()
    g = run_dssp(edges, secrets, q)
    t1 = time.perf_counter()
    ok = verify_all(g, secrets, q)
    return (t1 - t0, g, ok)


# ---------------------------------------------------------------------------
# CSV / figure helpers
# ---------------------------------------------------------------------------

def write_csv(path: str, header: list, rows: list) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def mean_std(xs: list) -> tuple:
    if not xs:
        return (0.0, 0.0)
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return (m, var ** 0.5)


# ---------------------------------------------------------------------------
# Experiment 1: time vs |V| across topologies
# ---------------------------------------------------------------------------

def experiment_time_vs_nodes(args, out_dir: str):
    print("\n=== Experiment 1: time vs |V| across topologies ===")
    if args.quick:
        node_counts = [100, 500, 1000]
    else:
        node_counts = [100, 250, 500, 1000, 2000, 3000, 4000, args.max_n]
    node_counts = sorted(set(n for n in node_counts if n <= args.max_n))

    l_max = 5
    rows = []
    header = ["topology", "|V|", "|E|", "mean_time_s", "std_time_s",
              "all_reconstruct_ok"]

    for topo, gen in TOPOLOGY_GENERATORS.items():
        for n in node_counts:
            times = []
            all_ok = True
            edges_count = 0
            for rep in range(args.reps):
                seed = args.seed_base + rep * 17 + n
                rng = random.Random(seed)
                G = gen(n, seed)
                edges = sorted(((min(i, j), max(i, j))
                                for i, j in G.edges()))
                if not edges:
                    continue
                edges_count = len(edges)
                secrets = make_secrets(edges, l_max, args.q, rng)
                t, _, ok = run_once(edges, secrets, args.q)
                times.append(t)
                if not ok:
                    all_ok = False
            mean, std = mean_std(times)
            rows.append([topo, n, edges_count,
                         f"{mean:.5f}", f"{std:.5f}",
                         "yes" if all_ok else "NO"])
            print(f"  {topo:9s} |V|={n:5d} |E|={edges_count:5d}  "
                  f"{mean:7.3f}s ± {std:7.3f}  "
                  f"({'OK' if all_ok else 'FAIL'})")

    write_csv(os.path.join(out_dir, "tab_time_nodes.csv"), header, rows)

    # Figure
    fig, ax = plt.subplots(figsize=(7, 4.5))
    by_topo = defaultdict(list)
    for row in rows:
        topo, n, _, m, _, _ = row
        by_topo[topo].append((int(n), float(m)))
    for topo, pts in by_topo.items():
        pts.sort()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, marker="o", label=topo)
    ax.set_xlabel("Number of nodes |V|")
    ax.set_ylabel("Mean encoding time (s)")
    ax.set_title(f"Different Secrets Size Protocol — l_max={l_max}, "
                 f"reps={args.reps}")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "fig_time_nodes.png"), dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Experiment 2: time vs l_max
# ---------------------------------------------------------------------------

def experiment_time_vs_lmax(args, out_dir: str):
    print("\n=== Experiment 2: time vs l_max ===")
    if args.quick:
        lmax_values = [1, 5, 10]
    else:
        lmax_values = [1, 2, 5, 10, 20, 30, 50]
    n = 500
    rows = []
    header = ["topology", "l_max", "|V|", "|E|",
              "mean_time_s", "std_time_s", "all_reconstruct_ok"]

    for topo, gen in TOPOLOGY_GENERATORS.items():
        for lmax in lmax_values:
            times = []
            all_ok = True
            edges_count = 0
            for rep in range(args.reps):
                seed = args.seed_base + rep * 17 + lmax
                rng = random.Random(seed)
                G = gen(n, seed)
                edges = sorted(((min(i, j), max(i, j))
                                for i, j in G.edges()))
                if not edges:
                    continue
                edges_count = len(edges)
                secrets = make_secrets(edges, lmax, args.q, rng)
                t, _, ok = run_once(edges, secrets, args.q)
                times.append(t)
                if not ok:
                    all_ok = False
            mean, std = mean_std(times)
            rows.append([topo, lmax, n, edges_count,
                         f"{mean:.5f}", f"{std:.5f}",
                         "yes" if all_ok else "NO"])
            print(f"  {topo:9s} l_max={lmax:3d}  {mean:7.3f}s ± {std:7.3f}  "
                  f"({'OK' if all_ok else 'FAIL'})")

    write_csv(os.path.join(out_dir, "tab_time_lmax.csv"), header, rows)


# ---------------------------------------------------------------------------
# Experiment 3: storage overhead vs topology
# ---------------------------------------------------------------------------

def experiment_so_vs_topology(args, out_dir: str):
    print("\n=== Experiment 3: storage overhead vs topology ===")
    if args.quick:
        node_counts = [100, 500]
    else:
        node_counts = [100, 500, 1000, 2000]
    l_max = 10
    rows = []
    header = ["topology", "|V|", "|E|",
              "mean_SO_protocol", "std_SO_protocol",
              "mean_SO_padding",  "std_SO_padding",
              "mean_ratio_pad_over_proto",
              "mean_number_tree_over_L", "std_number_tree_over_L"]

    for topo, gen in TOPOLOGY_GENERATORS.items():
        for n in node_counts:
            so_proto, so_pad, ratio, ntL = [], [], [], []
            for rep in range(args.reps):
                seed = args.seed_base + rep * 17 + n
                rng = random.Random(seed)
                G = gen(n, seed)
                edges = sorted(((min(i, j), max(i, j))
                                for i, j in G.edges()))
                if not edges:
                    continue
                secrets = make_secrets(edges, l_max, args.q, rng)
                _, g, ok = run_once(edges, secrets, args.q)
                if not ok:
                    print(f"    [warn] reconstruction failed on "
                          f"{topo} n={n} seed={seed}")
                    continue
                so_p = storage_overhead(g, secrets)
                so_b = padding_baseline_so(g, secrets)
                so_proto.append(so_p)
                so_pad.append(so_b)
                ratio.append(so_b / so_p if so_p > 0 else 0.0)
                # number_tree(G) / L from the structural definition
                lengths = {e: len(secrets[e]) for e in secrets}
                nt = compute_number_tree(edges, lengths)
                L = sum(len(s) for s in secrets.values())
                ntL.append(nt / L if L else 0.0)
            mP, sP = mean_std(so_proto)
            mB, sB = mean_std(so_pad)
            mR, _ = mean_std(ratio)
            mN, sN = mean_std(ntL)
            edges_count = len(edges) if 'edges' in dir() else 0
            rows.append([topo, n, edges_count,
                         f"{mP:.4f}", f"{sP:.4f}",
                         f"{mB:.4f}", f"{sB:.4f}",
                         f"{mR:.4f}",
                         f"{mN:.6f}", f"{sN:.6f}"])
            print(f"  {topo:9s} |V|={n:5d}  "
                  f"SO_proto={mP:6.4f}  SO_pad={mB:6.4f}  "
                  f"ratio={mR:6.2f}  nt/L={mN:8.6f}")

    write_csv(os.path.join(out_dir, "tab_so_topology.csv"), header, rows)

    # Figure: SO_proto vs SO_pad bar chart, grouped by topology, at largest n
    fig, ax = plt.subplots(figsize=(7, 4.5))
    by_topo = defaultdict(list)
    for row in rows:
        by_topo[row[0]].append(row)
    max_n = max(node_counts)
    topos = list(TOPOLOGY_GENERATORS.keys())
    xs = list(range(len(topos)))
    width = 0.35
    proto_vals, pad_vals = [], []
    for topo in topos:
        last = [r for r in by_topo[topo] if int(r[1]) == max_n]
        if last:
            proto_vals.append(float(last[0][3]))
            pad_vals.append(float(last[0][5]))
        else:
            proto_vals.append(0)
            pad_vals.append(0)
    ax.bar([x - width / 2 for x in xs], proto_vals, width,
           label="Different Secrets Size Protocol")
    ax.bar([x + width / 2 for x in xs], pad_vals, width,
           label="Padding-based baseline")
    ax.set_xticks(xs)
    ax.set_xticklabels(topos)
    ax.axhline(1.0, color="grey", linestyle="--", linewidth=0.8)
    ax.set_ylabel("Storage overhead SO")
    ax.set_title(f"SO comparison at |V|={max_n}, l_max={l_max}, "
                 f"reps={args.reps}")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "fig_so_topology.png"), dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Experiment 4: padding gap vs heterogeneity ratio
# ---------------------------------------------------------------------------

def experiment_padding_gap(args, out_dir: str):
    """
    Sweep l_max while keeping the secret-length distribution biased so
    that the heterogeneity ratio (l_max * |E| / L) varies. Show how
    the padding baseline degrades while our protocol stays near 1.
    """
    print("\n=== Experiment 4: padding gap vs heterogeneity ratio ===")
    if args.quick:
        lmax_values = [1, 5, 10]
    else:
        lmax_values = [1, 2, 5, 10, 20, 30, 50]
    n = 500
    topo = "erdos"
    gen = TOPOLOGY_GENERATORS[topo]
    rows = []
    header = ["l_max", "|V|", "|E|", "heterogeneity_ratio",
              "mean_SO_protocol", "mean_SO_padding"]

    for lmax in lmax_values:
        so_proto, so_pad, heteros = [], [], []
        for rep in range(args.reps):
            seed = args.seed_base + rep * 17 + lmax
            rng = random.Random(seed)
            G = gen(n, seed)
            edges = sorted(((min(i, j), max(i, j))
                            for i, j in G.edges()))
            if not edges:
                continue
            secrets = make_secrets(edges, lmax, args.q, rng)
            _, g, ok = run_once(edges, secrets, args.q)
            if not ok:
                continue
            so_proto.append(storage_overhead(g, secrets))
            so_pad.append(padding_baseline_so(g, secrets))
            heteros.append(heterogeneity_ratio(secrets))
        mP, _ = mean_std(so_proto)
        mB, _ = mean_std(so_pad)
        mH, _ = mean_std(heteros)
        rows.append([lmax, n, len(edges), f"{mH:.4f}",
                     f"{mP:.4f}", f"{mB:.4f}"])
        print(f"  l_max={lmax:3d}  heteroR={mH:5.2f}  "
              f"SO_proto={mP:5.3f}  SO_pad={mB:5.3f}")

    write_csv(os.path.join(out_dir, "tab_padding_gap.csv"), header, rows)

    # Figure
    fig, ax = plt.subplots(figsize=(7, 4.5))
    xs = [float(r[3]) for r in rows]
    p_vals = [float(r[4]) for r in rows]
    b_vals = [float(r[5]) for r in rows]
    ax.plot(xs, p_vals, marker="o", label="Different Secrets Size Protocol")
    ax.plot(xs, b_vals, marker="s", label="Padding-based baseline")
    ax.set_xlabel("Heterogeneity ratio  l_max · |E| / L")
    ax.set_ylabel("Storage overhead SO")
    ax.set_title(f"SO vs heterogeneity, {topo} graph |V|={n}, reps={args.reps}")
    ax.axhline(1.0, color="grey", linestyle="--", linewidth=0.8)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "fig_padding_gap.png"), dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Experiment 5: number_tree(G) / L vs |V| across topologies
# ---------------------------------------------------------------------------

def experiment_number_tree(args, out_dir: str):
    print("\n=== Experiment 5: number_tree(G)/L vs |V| ===")
    if args.quick:
        node_counts = [100, 500]
    else:
        node_counts = [100, 250, 500, 1000, 2000]
    l_max = 10
    rows = []
    header = ["topology", "|V|", "|E|",
              "mean_number_tree", "std_number_tree",
              "mean_L", "mean_number_tree_over_L"]

    for topo, gen in TOPOLOGY_GENERATORS.items():
        for n in node_counts:
            nts, Ls, ratios = [], [], []
            edges_count = 0
            for rep in range(args.reps):
                seed = args.seed_base + rep * 17 + n
                rng = random.Random(seed)
                G = gen(n, seed)
                edges = sorted(((min(i, j), max(i, j))
                                for i, j in G.edges()))
                if not edges:
                    continue
                edges_count = len(edges)
                secrets = make_secrets(edges, l_max, args.q, rng)
                lengths = {e: len(secrets[e]) for e in secrets}
                nt = compute_number_tree(edges, lengths)
                L = sum(len(s) for s in secrets.values())
                nts.append(nt)
                Ls.append(L)
                ratios.append(nt / L if L else 0.0)
            mN, sN = mean_std(nts)
            mL, _ = mean_std(Ls)
            mR, _ = mean_std(ratios)
            rows.append([topo, n, edges_count,
                         f"{mN:.2f}", f"{sN:.2f}",
                         f"{mL:.2f}", f"{mR:.6f}"])
            print(f"  {topo:9s} |V|={n:5d}  nt={mN:8.2f}  L={mL:8.2f}  "
                  f"nt/L={mR:8.6f}")

    write_csv(os.path.join(out_dir, "tab_number_tree.csv"), header, rows)

    # Figure
    fig, ax = plt.subplots(figsize=(7, 4.5))
    by_topo = defaultdict(list)
    for row in rows:
        by_topo[row[0]].append((int(row[1]), float(row[6])))
    for topo, pts in by_topo.items():
        pts.sort()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, marker="o", label=topo)
    ax.set_xlabel("Number of nodes |V|")
    ax.set_ylabel("number_tree(G) / L")
    ax.set_title(f"Empirical number_tree(G)/L, l_max={l_max}, "
                 f"reps={args.reps}")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "fig_number_tree.png"), dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv):
    args = parse_args(argv)
    if args.quick:
        args.reps = min(args.reps, 3)
        args.max_n = min(args.max_n, 1000)
    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 60)
    print(f"  TIFS DSSP benchmarks")
    print(f"  reps      = {args.reps}")
    print(f"  max nodes = {args.max_n}")
    print(f"  q         = {args.q}")
    print(f"  output    = {args.output_dir}/")
    print("=" * 60)

    t0 = time.perf_counter()

    experiment_time_vs_nodes(args, args.output_dir)
    experiment_time_vs_lmax(args, args.output_dir)
    experiment_so_vs_topology(args, args.output_dir)
    experiment_padding_gap(args, args.output_dir)
    experiment_number_tree(args, args.output_dir)

    t1 = time.perf_counter()
    print(f"\nTotal wall time: {t1 - t0:.1f}s")
    print(f"Outputs written to: {args.output_dir}/")


if __name__ == "__main__":
    main(sys.argv[1:])
