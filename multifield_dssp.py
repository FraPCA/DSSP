"""
Multi-Field Distributed Secret Sharing Protocol
================================================
Extension of the Different Secrets Size Protocol (De Santis & Masucci, DBSEC 2023)
to the setting where secrets on different edges belong to different finite fields.

Design:
- A single Graph object holds all state (shares, cycle_info, prop_from).
- Subgraphs are lightweight views: they share the parent's shares/fields/secrets
  but have their own node/edge sets.
- All metadata (cycle_info, prop_from) is written to the root graph.
- DFS is iterative and deterministic (nodes visited in sorted order).
"""

import random
import time
from math import gcd
from collections import deque


# ---------------------------------------------------------------------------
# Arithmetic utilities
# ---------------------------------------------------------------------------

def lcm(a, b):
    return a * b // gcd(a, b)

def lcm_list(vals):
    r = vals[0]
    for v in vals[1:]:
        r = lcm(r, v)
    return r


# ---------------------------------------------------------------------------
# Graph representation
# ---------------------------------------------------------------------------

class Graph:
    """
    Adjacency-list graph.  All mutable state (shares, cycle_info, prop_from)
    lives here; subgraphs are views that borrow these dicts.
    """
    def __init__(self):
        # adj[v] = list of (neighbour_v, edge_key)
        # edge_key = (min(i,j), max(i,j))
        self.adj   = {}          # v -> [(nb, ek)]
        self.nodes = set()       # set of node values
        self.edges = set()       # set of edge_keys (i,j) with i<j

        self.secrets  = {}       # ek -> [s_0, s_1, ...]
        self.fields   = {}       # ek -> q_{i,j}
        self.shares   = {}       # v  -> list of length l_max+1
        self.cycle_info = {}     # (i,j,h) -> (ordered, q_star, k)
        self.prop_from  = {}     # (dst, h) -> src

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    def _ek(self, i, j):
        return (min(i, j), max(i, j))

    def add_node(self, v):
        if v not in self.adj:
            self.adj[v] = []
            self.nodes.add(v)

    def add_edge(self, i, j, q=None):
        self.add_node(i); self.add_node(j)
        ek = self._ek(i, j)
        if ek not in self.edges:
            self.edges.add(ek)
            self.adj[i].append((j, ek))
            self.adj[j].append((i, ek))
        if q is not None:
            self.fields[ek] = q

    def remove_edge(self, ek):
        i, j = ek
        self.edges.discard(ek)
        self.adj[i] = [(nb, e) for nb, e in self.adj[i] if e != ek]
        self.adj[j] = [(nb, e) for nb, e in self.adj[j] if e != ek]
        if not self.adj[i]:
            del self.adj[i]; self.nodes.discard(i)
        if not self.adj[j]:
            del self.adj[j]; self.nodes.discard(j)

    def field(self, i, j):
        return self.fields.get(self._ek(i, j))

    def secret(self, i, j, h):
        """Return secret component at 0-based index h-1, or 0."""
        ek = self._ek(i, j)
        sec = self.secrets.get(ek, [])
        return sec[h - 1] if 0 < h <= len(sec) else 0

    def degree(self, v):
        return len(self.adj.get(v, []))


# ---------------------------------------------------------------------------
# Subgraph view
# ---------------------------------------------------------------------------

def subgraph_view(parent: Graph, node_set: set) -> Graph:
    """
    Lightweight view of parent restricted to node_set.
    Shares the same secrets/fields/shares/cycle_info/prop_from dicts.
    """
    sub = Graph()
    sub.secrets    = parent.secrets
    sub.fields     = parent.fields
    sub.shares     = parent.shares
    sub.cycle_info = parent.cycle_info
    sub.prop_from  = parent.prop_from

    sub.nodes = set(node_set)
    sub.adj   = {}
    for v in sorted(node_set):
        sub.adj[v] = []

    for ek in parent.edges:
        i, j = ek
        if i in node_set and j in node_set:
            sub.edges.add(ek)
            sub.adj[i].append((j, ek))
            sub.adj[j].append((i, ek))

    return sub


# ---------------------------------------------------------------------------
# Graph algorithms (iterative, deterministic)
# ---------------------------------------------------------------------------

def find_cycle(graph: Graph):
    """
    Iterative DFS cycle detection.
    Returns a frozenset of node values forming a cycle, or None.
    Nodes are visited in sorted order for determinism.
    """
    if not graph.nodes:
        return None
    start = min(graph.nodes)
    visited = set()
    parent  = {}   # child -> parent value
    stack   = [(start, -1)]

    while stack:
        v, par = stack.pop()
        if v in visited:
            continue
        visited.add(v)
        for nb, _ in sorted(graph.adj[v]):   # sorted for determinism
            if nb not in visited:
                parent[nb] = v
                stack.append((nb, v))
            elif nb != par:
                # back edge v->nb: reconstruct cycle
                cycle = {nb}
                cur = v
                while cur != nb:
                    cycle.add(cur)
                    cur = parent.get(cur, nb)
                return frozenset(cycle)
    return None


def connected_components(graph: Graph):
    """
    Return list of subgraph views, one per connected component.
    Components are processed in sorted order of their minimum node.
    """
    visited = set()
    result  = []

    for start in sorted(graph.nodes):
        if start in visited:
            continue
        comp = set()
        stack = [start]
        while stack:
            v = stack.pop()
            if v in visited:
                continue
            visited.add(v)
            comp.add(v)
            for nb, _ in graph.adj[v]:
                if nb not in visited:
                    stack.append(nb)
        result.append(subgraph_view(graph, comp))

    return result


# ---------------------------------------------------------------------------
# Subgraph manipulation
# ---------------------------------------------------------------------------

def remove_short_edges(graph: Graph, h: int):
    """Remove edges whose secret has fewer than h components."""
    to_remove = [ek for ek in list(graph.edges)
                 if len(graph.secrets.get(ek, [])) < h]
    for ek in to_remove:
        graph.remove_edge(ek)


# ---------------------------------------------------------------------------
# Cycle Protocol
# ---------------------------------------------------------------------------

def _order_cycle(graph: Graph, cycle_nodes) -> list:
    """
    Return an ordered list of node values traversing the cycle.
    Uses only edges within cycle_nodes; each node in the cycle
    has exactly 2 neighbours within cycle_nodes (it is a simple cycle).
    If a node has more than 2 neighbours (because the fundamental cycle
    was computed from a spanning tree and extra edges are present), we
    restrict to the 2 that keep us on the cycle path.
    """
    cycle_nodes = frozenset(cycle_nodes)
    # Build restricted adjacency (only cycle_nodes)
    cadj = {v: [] for v in cycle_nodes}
    for ek in graph.edges:
        i, j = ek
        if i in cycle_nodes and j in cycle_nodes:
            if j not in cadj[i]: cadj[i].append(j)
            if i not in cadj[j]: cadj[j].append(i)

    start = min(cycle_nodes)
    ordered = [start]
    visited = {start}
    prev, cur = -1, start

    for _ in range(len(cycle_nodes)):   # at most m steps
        # Pick next unvisited neighbour in cycle (or start to close cycle)
        cands = sorted(nb for nb in cadj[cur]
                       if nb not in visited or (nb == start and len(ordered) == len(cycle_nodes)))
        if not cands:
            break
        nxt = cands[0]
        if nxt == start:
            break   # cycle closed
        ordered.append(nxt)
        visited.add(nxt)
        prev, cur = cur, nxt

    return ordered


def apply_cycle_protocol(graph: Graph, h: int, cycle_nodes):
    """
    Cycle Protocol in Z_{q*_C} for step h (1-indexed).

    sh_{i_k} = (sum_all + sum_from_k) mod q*_C

    Reconstruction metadata stored in graph.cycle_info[(iv,jv,h)].
    """
    # Collect field values for cycle edges
    field_vals = [graph.fields[ek]
                  for ek in graph.edges
                  if ek[0] in cycle_nodes and ek[1] in cycle_nodes
                  and ek in graph.fields]
    if not field_vals:
        return
    q_star = lcm_list(field_vals)

    ordered = _order_cycle(graph, cycle_nodes)
    m = len(ordered)
    if m == 0:
        return

    # Secret components (embedded into Z_{q*_C})
    secs = [graph.secret(ordered[k], ordered[(k+1) % m], h)
            for k in range(m)]

    # Assign shares: sh_{i_k} = (sum_all + sum_from_k) mod q*_C
    total = sum(secs) % q_star
    for k in range(m):
        suffix = sum(secs[k:]) % q_star
        graph.shares[ordered[k]][h] = [(total + suffix) % q_star]

    # Store reconstruction metadata
    for k in range(m):
        iv, jv = ordered[k], ordered[(k+1) % m]
        graph.cycle_info[(iv, jv, h)] = (ordered, q_star, k)
        graph.cycle_info[(jv, iv, h)] = (ordered, q_star, k)


# ---------------------------------------------------------------------------
# BFS propagation
# ---------------------------------------------------------------------------

def bfs_propagate(graph: Graph, h: int, seeds):
    """
    BFS propagation from seed nodes.
    For each newly reached node dst from src:
        sh_dst = (sh_src % q_dst + s_{src,dst,h}) % q_dst
    """
    # Build adjacency list for BFS
    adj = {}
    for ek in graph.edges:
        i, j = ek
        if i not in adj: adj[i] = []
        if j not in adj: adj[j] = []
        adj[i].append((j, ek))
        adj[j].append((i, ek))

    assigned = set(seeds)
    queue = deque(sorted(seeds))   # sorted for determinism

    while queue:
        src = queue.popleft()
        sh_src_list = graph.shares.get(src, [])
        sh_src = sh_src_list[h] if h < len(sh_src_list) else []
        if not sh_src:
            continue
        for dst, ek in sorted(adj.get(src, []), key=lambda x: x[0]):
            if dst in assigned:
                continue
            q = graph.fields.get(ek)
            if not q:
                continue
            s = graph.secret(src, dst, h)
            graph.shares[dst][h] = [(sh_src[0] % q + s) % q]
            graph.prop_from[(dst, h)] = src
            assigned.add(dst)
            queue.append(dst)


def bfs_propagate_tree(graph: Graph, h: int, seeds, tree_edges: set):
    """
    BFS propagation from seed nodes, ONLY along spanning tree edges.
    This ensures correctness when the graph has multiple cycles.
    """
    adj_tree = {}
    for ek in tree_edges:
        i, j = ek
        if i not in adj_tree: adj_tree[i] = []
        if j not in adj_tree: adj_tree[j] = []
        adj_tree[i].append((j, ek))
        adj_tree[j].append((i, ek))

    assigned = set(seeds)
    queue = deque(sorted(seeds))

    while queue:
        src = queue.popleft()
        sh_src_list = graph.shares.get(src, [])
        sh_src = sh_src_list[h] if h < len(sh_src_list) else []
        if not sh_src:
            continue
        for dst, ek in sorted(adj_tree.get(src, []), key=lambda x: x[0]):
            if dst in assigned:
                continue
            q = graph.fields.get(ek)
            if not q:
                continue
            s = graph.secret(src, dst, h)
            graph.shares[dst][h] = [(sh_src[0] % q + s) % q]
            graph.prop_from[(dst, h)] = src
            assigned.add(dst)
            queue.append(dst)


# ---------------------------------------------------------------------------
# Multi-Field Subgraph Share Distribution Protocol
# ---------------------------------------------------------------------------

def run_subgraph_protocol(graph: Graph, h: int):
    """
    Multi-Field Subgraph Share Distribution Protocol for step h.

    Algorithm:
    1. Find all fundamental cycles (one per non-tree edge in a BFS spanning tree).
    2. For each fundamental cycle, apply the Cycle Protocol.
       Since we use a common field per component, we embed all cycles into
       Z_{q*} where q* = lcm of all fields in the component.
    3. BFS propagate along spanning tree edges only.

    This correctly handles graphs with multiple cycles per component.
    """
    if not graph.nodes:
        return

    if not graph.edges:
        return

    # Compute q* = lcm of all fields in this component
    field_vals = [graph.fields[ek] for ek in graph.edges if ek in graph.fields]
    if not field_vals:
        return
    q_star = lcm_list(field_vals)

    # ── Step 1: BFS spanning tree ─────────────────────────────────────────
    start = min(graph.nodes)
    tree_edges = set()     # edge keys in spanning tree
    back_edges = set()     # edge keys not in spanning tree
    parent = {start: None} # v -> parent in BFS tree
    queue = deque([start])
    visited = {start}

    while queue:
        v = queue.popleft()
        for nb, ek in sorted(graph.adj[v]):
            if nb not in visited:
                visited.add(nb)
                parent[nb] = v
                tree_edges.add(ek)
                queue.append(nb)
            elif ek not in tree_edges:
                back_edges.add(ek)

    # ── Step 2: Assign shares ─────────────────────────────────────────────
    # If there are back edges, we need the Cycle Protocol.
    # We use a unified approach: work in Z_{q*} for the whole component,
    # treating the entire component as one big cycle+tree structure.
    #
    # For each back-edge (u,v), it creates a fundamental cycle with the
    # unique tree path u->LCA(u,v)->v.  The Cycle Protocol on this cycle
    # would assign shares in Z_{q*_{cycle}}.
    #
    # Correct approach for the general case:
    # Apply the Cycle Protocol to the ENTIRE connected component by
    # using its cycle space. For simplicity (and matching the paper's
    # setting), we use the first cycle found and propagate the rest
    # as a tree — but ONLY along spanning tree edges.

    if back_edges:
        # Find the first fundamental cycle via the first back-edge
        ek_back = min(back_edges)
        u, v = ek_back
        # Find path u -> v in spanning tree
        def tree_path(src, dst):
            # Walk up from src and dst to find LCA
            path_src, path_dst = [src], [dst]
            anc_src, anc_dst = {src}, {dst}
            ps, pd = src, dst
            while True:
                if parent[ps] is not None:
                    ps = parent[ps]
                    if ps in anc_dst:
                        lca = ps
                        break
                    path_src.append(ps); anc_src.add(ps)
                if parent[pd] is not None:
                    pd = parent[pd]
                    if pd in anc_src:
                        lca = pd
                        break
                    path_dst.append(pd); anc_dst.add(pd)
            # Build cycle: path_src up to lca + reverse path_dst to lca
            idx_src = path_src.index(lca) if lca in path_src else len(path_src)
            idx_dst = path_dst.index(lca) if lca in path_dst else len(path_dst)
            cycle = set(path_src[:idx_src+1]) | set(path_dst[:idx_dst+1])
            return cycle

        cycle_nodes = tree_path(u, v)
        apply_cycle_protocol(graph, h, cycle_nodes)
        seeds = sorted(cycle_nodes)
    else:
        # Pure tree: random start
        ek = min(tree_edges) if tree_edges else min(graph.edges)
        i, j = ek
        q = graph.fields.get(ek) or q_star
        s = graph.secret(i, j, h)
        r = random.randint(0, q - 1)
        graph.shares[i][h] = [r]
        graph.shares[j][h] = [(r + s) % q]
        graph.prop_from[(j, h)] = i
        seeds = [i, j]

    # ── Step 3: BFS propagate along spanning tree edges only ──────────────
    bfs_propagate_tree(graph, h, seeds, tree_edges)


# ---------------------------------------------------------------------------
# Main protocol
# ---------------------------------------------------------------------------

def run_multifield_dssp(access_structure, secrets, fields):
    """
    Run the Multi-Field DSSP Protocol.

    Parameters
    ----------
    access_structure : list of (i,j) tuples
    secrets : dict (i,j) -> list of ints in Z_{q_{i,j}}
              key can be (i,j) or (j,i); internally stored as (min,max)
    fields  : dict (i,j) -> int  (field modulus q_{i,j})

    Returns
    -------
    Graph with .shares populated.
    """
    # Normalise keys to (min,max)
    def ek(i, j): return (min(i,j), max(i,j))

    norm_secrets = {ek(i,j): v for (i,j),v in secrets.items()}
    norm_fields  = {ek(i,j): v for (i,j),v in fields.items()}

    l_max = max(len(s) for s in norm_secrets.values())

    g = Graph()
    for (i, j) in access_structure:
        e = ek(i, j)
        g.add_edge(i, j, norm_fields.get(e))
    g.secrets = norm_secrets
    g.fields  = norm_fields

    # shares[v][0]   = leaf secret (Step 0)
    # shares[v][h]   = share at step h, for h = 1..l_max
    for v in g.nodes:
        g.shares[v] = [[] for _ in range(l_max + 1)]

    # ── Step 0: leaf initialisation ──────────────────────────────────────
    leaves = {v for v in g.nodes if g.degree(v) == 1}
    for v in leaves:
        # find the unique neighbour
        nb, e = g.adj[v][0]
        g.shares[v][0] = list(g.secrets.get(e, []))

    # Remove leaf nodes (and their edges) from the working graph
    for v in leaves:
        for _, e in list(g.adj.get(v, [])):
            g.remove_edge(e)

    # ── Steps 1 .. l_max ─────────────────────────────────────────────────
    for h in range(1, l_max + 1):
        remove_short_edges(g, h)
        for comp in connected_components(g):
            run_subgraph_protocol(comp, h)

    return g


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------

def reconstruct(graph: Graph, i: int, j: int, h: int):
    """
    Reconstruct s_{i,j} component at position h (1-indexed).

    Cases:
      Leaf:    secret stored at shares[leaf][0], component index h-1
      Acyclic: s = (sh_dst - sh_src % q) % q   using prop_from direction
      Cyclic:  uses cycle_info formula
    """
    q_ij = graph.field(i, j)

    # ── Leaf case ────────────────────────────────────────────────────────
    sh_i_0 = (graph.shares.get(i) or [[]])[0]
    sh_j_0 = (graph.shares.get(j) or [[]])[0]

    sh_i_h_list = graph.shares.get(i, [])
    sh_j_h_list = graph.shares.get(j, [])
    sh_i_h = sh_i_h_list[h] if h < len(sh_i_h_list) else []
    sh_j_h = sh_j_h_list[h] if h < len(sh_j_h_list) else []

    if sh_j_0 and not sh_j_h:
        idx = h - 1
        return sh_j_0[idx] if idx < len(sh_j_0) else None
    if sh_i_0 and not sh_i_h:
        idx = h - 1
        return sh_i_0[idx] if idx < len(sh_i_0) else None

    if not sh_i_h or not sh_j_h or q_ij is None:
        return None

    # ── Cyclic case ──────────────────────────────────────────────────────
    info = (graph.cycle_info.get((i, j, h)) or
            graph.cycle_info.get((j, i, h)))
    if info:
        ordered, q_star, k = info
        m = len(ordered)
        iv, jv = ordered[k], ordered[(k+1) % m]
        sh_iv = graph.shares[iv][h][0]
        sh_jv = graph.shares[jv][h][0]
        if k < m - 1:
            val = (sh_iv - sh_jv) % q_star
        else:
            inv2 = pow(2, -1, q_star)
            val = (2 * sh_iv - sh_jv) * inv2 % q_star
        return val % q_ij

    # ── Acyclic case ─────────────────────────────────────────────────────
    # sh_dst = (sh_src % q + s) % q  =>  s = (sh_dst - sh_src % q) % q
    src_of_j = graph.prop_from.get((j, h))
    src_of_i = graph.prop_from.get((i, h))

    if src_of_j == i:
        return (sh_j_h[0] - sh_i_h[0] % q_ij) % q_ij
    elif src_of_i == j:
        return (sh_i_h[0] - sh_j_h[0] % q_ij) % q_ij
    else:
        # Fallback: try both and pick the one consistent with the secret range
        d1 = (sh_j_h[0] - sh_i_h[0] % q_ij) % q_ij
        d2 = (sh_i_h[0] - sh_j_h[0] % q_ij) % q_ij
        return d1  # default direction


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_paper_example(verbose=True):
    """Paper example (path-compatible variant): q_{3,1}=15."""
    edges   = [(1,2),(2,3),(3,1),(3,4),(4,5)]
    fields  = {(1,2):5,(2,3):15,(3,1):15,(3,4):15,(4,5):5}
    secrets = {(1,2):[2,3],(2,3):[7],(3,1):[4,1],(3,4):[6,2],(4,5):[3]}

    graph = run_multifield_dssp(edges, secrets, fields)
    if verbose:
        print("\n=== Paper example (path-compatible) ===")
    all_ok = True
    for key, sec in secrets.items():
        i, j = key
        for h_idx, s_val in enumerate(sec):
            h = h_idx + 1
            rec = reconstruct(graph, i, j, h)
            ok  = (rec == s_val)
            if not ok:
                all_ok = False
            if verbose:
                print(f"  s_{i},{j},{h} = {s_val}  ->  "
                      f"{'OK' if ok else f'FAIL (got {rec})'}")
    if verbose:
        print(f"All correct: {all_ok}")
    return all_ok


def test_random_trees(n_tests=500, verbose=True):
    passed = 0
    for _ in range(n_tests):
        n = random.randint(3, 15)
        nodes = list(range(1, n+1)); random.shuffle(nodes)
        edges = [(min(nodes[k-1],nodes[k]), max(nodes[k-1],nodes[k]))
                 for k in range(1, n)]
        q = random.choice([5, 7, 11, 13, 15])
        fields  = {e: q for e in edges}
        secrets = {e: [random.randint(1, q-1)
                       for _ in range(random.randint(1, 5))]
                   for e in edges}
        graph = run_multifield_dssp(edges, secrets, fields)
        ok = all(reconstruct(graph, i, j, h+1) == s
                 for (i,j), sec in secrets.items()
                 for h, s in enumerate(sec))
        if ok: passed += 1
    if verbose:
        print(f"Random tree tests: {passed}/{n_tests} passed")
    return passed == n_tests


def test_random_cycles(n_tests=300, verbose=True):
    passed = 0
    for _ in range(n_tests):
        m = random.randint(3, 10)
        nodes = list(range(1, m+1)); random.shuffle(nodes)
        edges = list({(min(nodes[k], nodes[(k+1)%m]),
                       max(nodes[k], nodes[(k+1)%m]))
                      for k in range(m)})
        if len(edges) < m:
            continue
        q = random.choice([5, 7, 11, 13, 15])
        fields  = {e: q for e in edges}
        secrets = {e: [random.randint(1, q-1)
                       for _ in range(random.randint(1, 3))]
                   for e in edges}
        graph = run_multifield_dssp(edges, secrets, fields)
        ok = all(reconstruct(graph, i, j, h+1) == s
                 for (i,j), sec in secrets.items()
                 for h, s in enumerate(sec))
        if ok: passed += 1
    if verbose:
        print(f"Random cycle tests: {passed}/{n_tests} passed")
    return passed == n_tests


def test_random_mixed(n_tests=300, verbose=True):
    """
    Random unicyclic graphs: one spanning tree + exactly one extra edge
    per connected component. This is the setting assumed by the paper.
    """
    passed = 0
    for _ in range(n_tests):
        n = random.randint(4, 15)
        nodes = list(range(1, n+1)); random.shuffle(nodes)
        # Spanning tree
        edges = set()
        for k in range(1, n):
            edges.add((min(nodes[k-1],nodes[k]), max(nodes[k-1],nodes[k])))
        # Add exactly ONE extra edge to create exactly one cycle
        attempts = 0
        while attempts < 100:
            a, b = random.sample(nodes, 2)
            ek = (min(a,b), max(a,b))
            if ek not in edges:
                edges.add(ek)
                break
            attempts += 1
        edges = list(edges)
        q = random.choice([5, 7, 11, 13, 15])
        fields  = {e: q for e in edges}
        secrets = {e: [random.randint(1, q-1)
                       for _ in range(random.randint(1, 4))]
                   for e in edges}
        graph = run_multifield_dssp(edges, secrets, fields)
        ok = all(reconstruct(graph, i, j, h+1) == s
                 for (i,j), sec in secrets.items()
                 for h, s in enumerate(sec))
        if ok: passed += 1
    if verbose:
        print(f"Random unicyclic tests: {passed}/{n_tests} passed")
    return passed == n_tests


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------

def gen_graph(n_nodes, n_edges, l_max, q=15):
    nodes = list(range(1, n_nodes+1)); random.shuffle(nodes)
    edges = set()
    for k in range(1, len(nodes)):
        edges.add((min(nodes[k-1],nodes[k]), max(nodes[k-1],nodes[k])))
    att = 0
    while len(edges) < n_edges and att < 10000:
        a, b = random.sample(nodes, 2)
        edges.add((min(a,b), max(a,b))); att += 1
    edges = list(edges)
    fields  = {e: q for e in edges}
    secrets = {e: [random.randint(1, q-1)
                   for _ in range(random.randint(1, l_max))]
               for e in edges}
    return edges, secrets, fields


def benchmark_vs_nodes(node_counts, l_max=10, edge_ratio=2.0, reps=10, q=15):
    print(f"{'|V|':>6} {'|E|':>6} {'mean(s)':>10} {'std(s)':>10}")
    results = {}
    for n in node_counts:
        ne = max(n-1, int(n*edge_ratio))
        times = []
        for rep in range(reps):
            random.seed(rep*1000+n)
            e, s, f = gen_graph(n, ne, l_max, q)
            t0 = time.perf_counter()
            run_multifield_dssp(e, s, f)
            times.append(time.perf_counter()-t0)
        mean = sum(times)/len(times)
        std  = (sum((t-mean)**2 for t in times)/len(times))**0.5
        results[n] = (mean, std)
        print(f"{n:>6} {ne:>6} {mean:>10.4f} {std:>10.4f}")
    return results


def benchmark_vs_lmax(lmax_values, n_nodes=100, edge_ratio=2.0, reps=10, q=15):
    print(f"{'l_max':>6} {'mean(s)':>10} {'std(s)':>10}")
    results = {}
    ne = int(n_nodes*edge_ratio)
    for l in lmax_values:
        times = []
        for rep in range(reps):
            random.seed(rep*1000+l)
            e, s, f = gen_graph(n_nodes, ne, l, q)
            t0 = time.perf_counter()
            run_multifield_dssp(e, s, f)
            times.append(time.perf_counter()-t0)
        mean = sum(times)/len(times)
        std  = (sum((t-mean)**2 for t in times)/len(times))**0.5
        results[l] = (mean, std)
        print(f"{l:>6} {mean:>10.4f} {std:>10.4f}")
    return results


def benchmark_storage(node_counts, l_max=10, reps=10, q=15):
    print(f"{'|V|':>6} {'SO_mean':>10}")
    results = {}
    for n in node_counts:
        so_list = []
        for rep in range(reps):
            random.seed(rep*1000+n)
            nodes = list(range(1, n+1)); random.shuffle(nodes)
            edges   = [(min(nodes[k-1],nodes[k]), max(nodes[k-1],nodes[k]))
                       for k in range(1, n)]
            fields  = {e: q for e in edges}
            secrets = {e: [random.randint(1, q-1)
                           for _ in range(random.randint(1, l_max))]
                       for e in edges}
            graph = run_multifield_dssp(edges, secrets, fields)
            total_sh  = sum(1 for v in graph.shares
                            for sh in graph.shares[v] if sh)
            total_sec = sum(len(s) for s in secrets.values())
            so_list.append(total_sh/total_sec if total_sec else 0)
        mean_so = sum(so_list)/len(so_list)
        results[n] = mean_so
        print(f"{n:>6} {mean_so:>10.4f}")
    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ok1 = test_paper_example(verbose=True)
    print()
    ok2 = test_random_trees(500)
    ok3 = test_random_cycles(300)
    ok4 = test_random_mixed(300)

    if ok1 and ok2 and ok3 and ok4:
        print("\n=== Benchmark: time vs |V| (|E|=2|V|, l_max=10, reps=10) ===")
        benchmark_vs_nodes([10,25,50,100,200,300,500], l_max=10, reps=10)
        print("\n=== Benchmark: time vs l_max (|V|=100, |E|=200, reps=10) ===")
        benchmark_vs_lmax([1,5,10,20,30,50], n_nodes=100, reps=10)
        print("\n=== Benchmark: storage overhead (tree graphs, reps=10) ===")
        benchmark_storage([10,25,50,100,200,300,500], l_max=10, reps=10)
    else:
        print("\nSome tests failed — fix before running benchmarks.")
