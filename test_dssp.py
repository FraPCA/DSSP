"""
Tests for dssp.py.

Includes:
  - The original benchmark test (preserved for backward compatibility).
  - Regression tests for the multi-cycle handling (figure-eight, K_n,
    dense random graphs). These are the cases that the previous
    version of the protocol failed on.
"""

import random
import gc

import pytest

from dssp import DSSPTestable, run_dssp, verify_all

gc.disable()


# ---------------------------------------------------------------------------
# Original benchmark
# ---------------------------------------------------------------------------

def test_benchmark_DSSPTestable_1(benchmark):
    result = benchmark(
        DSSPTestable, 5, [2, 3, 2, 3, 2], 5, 21,
        [[1, 2], [2, 3], [3, 4], [1, 4], [4, 5]],
    )
    assert result == 0


# ---------------------------------------------------------------------------
# Regression tests for the multi-cycle fix
# ---------------------------------------------------------------------------

def test_figure_eight():
    """
    Figure-eight: two triangles 1-2-3 and 3-4-5 sharing vertex 3.
    Cyclomatic number 2.  This case used to silently fail under the
    previous (single-cycle-only) protocol.
    """
    edges = [(1, 2), (2, 3), (1, 3), (3, 4), (4, 5), (3, 5)]
    secrets = {
        (1, 2): [3], (2, 3): [5], (1, 3): [2],
        (3, 4): [4], (4, 5): [6], (3, 5): [1],
    }
    q = 7
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


@pytest.mark.parametrize("n", [3, 4, 5, 6, 7])
def test_complete_graph_K_n(n):
    """
    Complete graph K_n.  Cyclomatic number = (n choose 2) - n + 1
    grows quickly with n.
    """
    nodes = list(range(1, n + 1))
    edges = [(i, j) for i in nodes for j in nodes if i < j]
    q = 17
    secrets = {e: [(e[0] * 13 + e[1]) % q] for e in edges}
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


@pytest.mark.parametrize("seed", range(20))
def test_random_dense_graphs(seed):
    """
    Random dense graphs (|E| ~ 4|V|) with l_max=3.
    These configurations exercise cycle closure heavily.
    """
    random.seed(seed)
    n = 30
    target_edges = 4 * n
    nodes = list(range(1, n + 1))
    random.shuffle(nodes)
    edges = set()
    for k in range(1, n):
        a, b = nodes[k - 1], nodes[k]
        edges.add((min(a, b), max(a, b)))
    while len(edges) < target_edges:
        a, b = random.sample(nodes, 2)
        edges.add((min(a, b), max(a, b)))
    edges = list(edges)
    q = 17
    secrets = {e: [random.randrange(q)
                   for _ in range(random.randint(1, 3))]
               for e in edges}
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


@pytest.mark.parametrize("seed", range(20))
def test_random_unicyclic(seed):
    """
    Random unicyclic graphs (spanning tree + 1 extra edge).
    This is the case the original protocol already handled.
    """
    random.seed(seed)
    n = 15
    nodes = list(range(1, n + 1))
    random.shuffle(nodes)
    edges = set()
    for k in range(1, n):
        a, b = nodes[k - 1], nodes[k]
        edges.add((min(a, b), max(a, b)))
    for _ in range(100):
        a, b = random.sample(nodes, 2)
        e = (min(a, b), max(a, b))
        if e not in edges:
            edges.add(e)
            break
    edges = list(edges)
    q = 13
    secrets = {e: [random.randrange(q)
                   for _ in range(random.randint(1, 4))]
               for e in edges}
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


@pytest.mark.parametrize("seed", range(20))
def test_random_trees(seed):
    """Pure trees, l_max up to 5."""
    random.seed(seed)
    n = 20
    nodes = list(range(1, n + 1))
    random.shuffle(nodes)
    edges = [(min(nodes[k - 1], nodes[k]),
              max(nodes[k - 1], nodes[k]))
             for k in range(1, n)]
    q = 11
    secrets = {e: [random.randrange(q)
                   for _ in range(random.randint(1, 5))]
               for e in edges}
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


# ---------------------------------------------------------------------------
# Leaf handling (Step 0)
# ---------------------------------------------------------------------------

def test_pure_star():
    """
    Star graph: a single internal node connected to several leaves.
    All edges are leaf edges, handled by Step 0 alone.
    """
    edges = [(1, k) for k in range(2, 8)]
    q = 11
    secrets = {e: [(e[1] * 3) % q, (e[1] * 5) % q] for e in edges}
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


def test_mixed_leaves_and_cycle():
    """
    Tree-shaped pendants attached to a cycle.  Step 0 handles the
    leaves, then Step h handles the remaining cycle.
    """
    edges = [(1, 2), (2, 3), (3, 4), (1, 4), (2, 5), (4, 6)]
    q = 13
    random.seed(0)
    secrets = {e: [random.randrange(q) for _ in range(2)] for e in edges}
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


def test_isolated_edge():
    """
    A single edge whose both endpoints are leaves. Step 0 must assign
    the secret to one endpoint only (deterministically, the larger
    label), and reconstruct must succeed.
    """
    edges = [(1, 2)]
    secrets = {(1, 2): [3, 7, 5]}
    q = 11
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


def test_isolated_edge_plus_cycle():
    """
    Two disconnected components: one isolated edge and one triangle.
    Exercises Step 0 across disconnected components.
    """
    edges = [(1, 2), (3, 4), (4, 5), (3, 5)]
    secrets = {(1, 2): [10], (3, 4): [3], (4, 5): [5], (3, 5): [7]}
    q = 11
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


@pytest.mark.parametrize("seed", range(10))
def test_disconnected_erdos_renyi(seed):
    """
    Sparse Erdős–Rényi at p slightly above the connectivity threshold,
    typically producing several connected components including some
    isolated edges. Regression test for the original
    erdos-n=5000-seed=42 failure.
    """
    import networkx as nx
    random.seed(seed)
    n = 100
    # p such that |E| ~ 2|V| but with several small components
    p = 4.0 / (n - 1)
    G = nx.gnp_random_graph(n, p, seed=seed)
    G = nx.relabel_nodes(G, {old: new
                             for new, old in enumerate(sorted(G.nodes()), 1)})
    edges = sorted(((min(i, j), max(i, j)) for i, j in G.edges()))
    if not edges:
        pytest.skip("graph has no edges")
    q = 17
    secrets = {e: [random.randrange(q)
                   for _ in range(random.randint(1, 3))]
               for e in edges}
    g = run_dssp(edges, secrets, q)
    assert verify_all(g, secrets, q)


gc.enable()
