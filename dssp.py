"""
Distributed Secret Sharing Protocol (DSSP) — single-field implementation.

Implements the Different Secrets Size Protocol and the Subgraph Share
Distribution Protocol of De Santis & Masucci, in the corrected version
that handles connected components with arbitrary cyclomatic number
(i.e. multiple independent cycles per component).

The Subgraph Share Distribution Protocol proceeds in three phases:

  1. Initialization
     - If the component contains a cycle, apply the Cycle Protocol
       to one cycle C, setting Z = (V_C, E_C).
     - Otherwise (acyclic component), pick an arbitrary edge (i,j),
       draw a uniform r in Z_q, and assign shares r and r + x_{i,j}
       to nodes i and j. Set Z = ({i,j}, {(i,j)}).

  2. Frontier expansion
     - While there exists an edge (i,j) in E_J \\ E_Z with i in V_Z
       and j not in V_Z: pick one of node i's existing shares dsh_i,
       assign dsh_i + x_{i,j} to node j, then add j to V_Z and
       (i,j) to E_Z.

  3. Cycle closure
     - While there exists an edge (i,j) in E_J \\ E_Z with both i
       and j in V_Z: pick one of node i's existing shares dsh_i,
       assign the *additional* share dsh_i + x_{i,j} to node j.
       Then add (i,j) to E_Z.

The Cycle Protocol is from De Prisco, De Santis & Palmieri (TDSC 2024).
The frontier expansion and cycle closure phases are both applications of
Construction 1 of the same paper.

API preserved for backward compatibility with run_experiments.py:
  - DSSP()             : interactive entry point
  - DSSPTestable(...)  : non-interactive entry point, returns 0 on success
  - DSSPSetVariables(...) : builds graph + secrets

New API:
  - run_dssp(access_structure, secrets, q) -> DSSPGraph
        Runs the protocol and returns the graph with shares populated.
  - reconstruct(graph, i, j, h, q) -> int
        Reconstructs s_{i,j,h} (1-indexed). Returns the value.
  - verify_all(graph, secrets, q) -> bool
        Verifies that every secret can be reconstructed correctly.
"""

import random
import matplotlib.pyplot as pyplot
import networkx
from collections import deque
from typing import Optional


# ---------------------------------------------------------------------------
# Graph data structures
# ---------------------------------------------------------------------------

def _ek(i: int, j: int) -> tuple:
    """Canonical edge key (min, max)."""
    return (min(i, j), max(i, j))


class DSSPGraph:
    """
    Distributed Secret Sharing graph.

    Attributes
    ----------
    nodes        : set[int]
    edges        : set[tuple[int,int]]    -- canonical (min,max) keys
    adj          : dict[int, set[int]]    -- adjacency as sets of neighbours
    secrets      : dict[(i,j), list[int]] -- s_{i,j} as a list of length l_{i,j}
    shares       : dict[v, list[list[int]]]
                       shares[v][0] is the share at Step 0 (leaf init, possibly empty)
                       shares[v][h] is the list of shares at step h (1..l_max).
                       The list is empty if v received nothing at step h.
                       It may contain MORE than one element if v received
                       additional shares during cycle closure.
    cycle_info   : dict[(i,j,h), (ordered_cycle, k)]
                       reconstruction metadata for edges processed by the
                       Cycle Protocol at step h: ordered_cycle is the list
                       of nodes traversing the cycle, and k is the index
                       of edge (i,j) along the cycle. Stored symmetrically
                       for (i,j,h) and (j,i,h).
    prop_from    : dict[(j,h), i]
                       for an edge (i,j) assigned by frontier expansion at
                       step h: j is the new endpoint, i is the existing one,
                       and the single share of j at step h is dsh_i + x_{i,j}.
    closure_share: dict[(i,j,h), (src, share_index, dst, dst_share_index)]
                       for an edge (i,j) assigned by cycle closure at step h:
                       src and dst identify which endpoint received the
                       additional share, share_index points into shares[src][h]
                       to identify the dsh_src used, dst_share_index points
                       into shares[dst][h] to identify the new additional share.
    """

    def __init__(self):
        self.nodes: set = set()
        self.edges: set = set()
        self.adj: dict = {}                # v -> set of neighbours
        self.secrets: dict = {}            # (i,j) -> list[int]
        self.shares: dict = {}             # v -> list of lists; shares[v][h] = list[int]
        self.cycle_info: dict = {}         # (i,j,h) -> (ordered, k)
        self.prop_from: dict = {}          # (j,h) -> i
        self.closure_share: dict = {}      # (i,j,h) -> (src, src_idx, dst, dst_idx)

    def __str__(self) -> str:
            return "Nodes: " + str(self.nodes) + "\nEdges: " + str(self.edges) + "\nAdj: " + str(self.adj) + "\nSecrets: " + str(self.secrets) + "\nShares: " + str(self.shares) + "\nCycle_info: " + str(self.cycle_info) + "\nProp_from: " + str(self.prop_from) + "\nClosure_share: " + str(self.closure_share)

    # --- construction --------------------------------------------------

    def add_node(self, v: int) -> None:
        if v not in self.nodes:
            self.nodes.add(v)
            self.adj[v] = set()

    def add_edge(self, i: int, j: int) -> None:
        self.add_node(i)
        self.add_node(j)
        e = _ek(i, j)
        if e not in self.edges:
            self.edges.add(e)
            self.adj[i].add(j)
            self.adj[j].add(i)

    def remove_edge(self, e: tuple) -> None:
        i, j = e
        self.edges.discard(e)
        self.adj[i].discard(j)
        self.adj[j].discard(i)
        # Nodes are kept even if isolated; only callers may drop them.

    def degree(self, v: int) -> int:
        return len(self.adj.get(v, ()))

    def has_edge(self, i: int, j: int) -> bool:
        return _ek(i, j) in self.edges

    def secret_component(self, i: int, j: int, h: int) -> int:
        """Component h (1-indexed) of secret s_{i,j}, or 0 if absent."""
        sec = self.secrets.get(_ek(i, j), [])
        return sec[h - 1] if 1 <= h <= len(sec) else 0

    # --- subgraph view --------------------------------------------------

    def subgraph(self, node_set: set) -> "DSSPGraph":
        """
        Return a new DSSPGraph that shares the same `secrets`, `shares`,
        `cycle_info`, `prop_from`, and `closure_share` dicts as self, but
        whose `nodes` / `edges` / `adj` are restricted to node_set.

        The shared dicts mean: writes made by the subgraph (e.g. assigning
        shares) are visible on the parent.
        """
        sub = DSSPGraph()
        sub.secrets = self.secrets
        sub.shares = self.shares
        sub.cycle_info = self.cycle_info
        sub.prop_from = self.prop_from
        sub.closure_share = self.closure_share

        sub.nodes = set(node_set)
        sub.adj = {v: set() for v in node_set}
        for (i, j) in self.edges:
            if i in node_set and j in node_set:
                sub.edges.add((i, j))
                sub.adj[i].add(j)
                sub.adj[j].add(i)
        return sub
    
    # --- graphic representation of the graph during each step --------------------------------------------------

    def visualize_step(self, step: int, subtitle: str) -> None:

        """
        This function is responsible for creating and updating a window which shows a visual representation of the
        graph, during step `step`. Nodes, edges, secrets and shares are shown by the representation, which is
        updated through clicks or key presses. 
        `subtitle` is passed to this function in order to provide a title for the graph, which usually contextualizes
        the most recent operation that was executed on it.
        """


        pyplot.clf()                          
        ax = pyplot.gca()                     
        fig = pyplot.gcf()                    
        fig.patch.set_facecolor("#1a1a2e")
        ax.set_facecolor("#1a1a2e")
        
        nxGraph = networkx.Graph()
        nxGraph.add_nodes_from(self.nodes)
        for edge in self.edges:
            i, j = edge
            history = self.secrets.get((i, j), [])
            label = f"s{i},{j}\n{history}"
            nxGraph.add_edge(i, j, secret=label)

        pos = networkx.kamada_kawai_layout(nxGraph)

        networkx.draw_networkx_nodes(
            nxGraph, pos, ax=ax,
            node_color="#e94560",
            node_size=800,
            linewidths=2,
            edgecolors="#ffffff",
        )

        networkx.draw_networkx_labels(
            nxGraph, pos, ax=ax,
            font_color="white",
            font_size=11,
            font_weight="bold",
        )

        networkx.draw_networkx_edges(
            nxGraph, pos, ax=ax,
            edge_color="#4a90d9",
            width=2,
            alpha=0.7,
            style="solid",
        )

        edge_labels = networkx.get_edge_attributes(nxGraph, "secret")
        networkx.draw_networkx_edge_labels(
            nxGraph, pos, edge_labels=edge_labels, ax=ax,
            font_color="#f0c040",
            font_size=8,
            bbox=dict(boxstyle="round,pad=0.3", fc="#16213e", ec="#4a90d9", alpha=0.85),
        )

        extra_labels = {
            n: str([vals for h, vals in enumerate(self.shares[n]) if h <= step])
            for n in nxGraph.nodes() if n in self.shares
        }
        vertical_offset = 0.15
        offset_pos = {node: (x, y + vertical_offset) for node, (x, y) in pos.items()}
        networkx.draw_networkx_labels(
            nxGraph, offset_pos, labels=extra_labels, ax=ax,
            font_color="#00e5ff",
            font_size=9,
            font_weight="bold",
        )

        fig.suptitle(
            f"Step {step}",
            color="white", fontsize=16, fontweight="bold", y=0.98,
        )
        ax.set_title(
            subtitle,
            color="#aaaacc", fontsize=11, pad=8,
        )

        ax.set_xlim(-1.5, 1.5)
        ax.set_ylim(-1.5, 1.5)
        ax.axis("off")

        pyplot.tight_layout()
        pyplot.draw()                  
        pyplot.waitforbuttonpress() 
        


# ---------------------------------------------------------------------------
# Graph algorithms (deterministic)
# ---------------------------------------------------------------------------

def find_cycle(graph: DSSPGraph) -> Optional[list]:
    """
    Iterative DFS cycle detection. Returns an *ordered* list of node values
    that traverse a simple cycle, or None if the graph is acyclic.
    Nodes are visited in sorted order for determinism.
    """
    if not graph.nodes:
        return None
    visited: set = set()

    for start in sorted(graph.nodes):
        if start in visited:
            continue
        # Iterative DFS keeping parent info to detect a back-edge
        parent = {start: None}
        # Stack contains (node, iterator over sorted neighbours)
        stack = [(start, iter(sorted(graph.adj[start])))]
        while stack:
            v, it = stack[-1]
            try:
                nb = next(it)
            except StopIteration:
                stack.pop()
                continue
            if nb == parent[v]:
                continue
            if nb in parent:
                # Back-edge v -> nb: reconstruct the cycle by walking up the
                # parent chain from v back to nb, then reverse for correct order.
                cycle = []
                cur = v
                while cur != nb:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.append(nb)  # close the cycle back at the starting node
                cycle.reverse()   # parent chain is built leaf-to-root; reverse it
                return cycle
            parent[nb] = v
            stack.append((nb, iter(sorted(graph.adj[nb]))))
        visited.update(parent.keys())
    return None


def connected_components(graph: DSSPGraph) -> list:
    """Return list of subgraph views, one per connected component."""
    visited: set = set()
    comps = []
    for start in sorted(graph.nodes):
        if start in visited:
            continue
        comp: set = set()
        stack = [start]
        while stack:
            v = stack.pop()
            if v in visited:
                continue
            visited.add(v)
            comp.add(v)
            for nb in graph.adj[v]:
                if nb not in visited:
                    stack.append(nb)
        comps.append(graph.subgraph(comp))
    return comps


def remove_short_edges(graph: DSSPGraph, h: int) -> None:
    """Remove edges whose secret has fewer than h components."""
    to_remove = [e for e in list(graph.edges)
                 if len(graph.secrets.get(e, [])) < h]
    for e in to_remove:
        graph.remove_edge(e)
    # Drop isolated nodes
    for v in list(graph.nodes):
        if not graph.adj.get(v):
            graph.nodes.discard(v)
            graph.adj.pop(v, None)


# ---------------------------------------------------------------------------
# Cycle Protocol (De Prisco, De Santis & Palmieri)
# ---------------------------------------------------------------------------

def apply_cycle_protocol(graph: DSSPGraph, cycle_ordered: list, h: int, q: int) -> None:
    """
    Cycle Protocol over Z_q at step h (1-indexed), on the ordered cycle.

    Secrets are taken as x_k = s_{c_k, c_{k+1 mod m}, h} for k=0..m-1.
    Shares are assigned as:
        sh_{c_k} = (sum_all_secrets + sum_from_k) mod q
    and stored as the (unique) share at step h for each cycle node.

    Stores reconstruction metadata in graph.cycle_info[(c_k, c_{k+1}, h)].
    """
    m = len(cycle_ordered)
    secs = [graph.secret_component(cycle_ordered[k],
                                   cycle_ordered[(k + 1) % m], h)
            for k in range(m)]
    total = sum(secs) % q
    for k in range(m):
        suffix = sum(secs[k:]) % q
        graph.shares[cycle_ordered[k]][h] = [(total + suffix) % q]
    # Symmetric metadata
    for k in range(m):
        a, b = cycle_ordered[k], cycle_ordered[(k + 1) % m]
        graph.cycle_info[(a, b, h)] = (cycle_ordered, k)
        graph.cycle_info[(b, a, h)] = (cycle_ordered, k)


# ---------------------------------------------------------------------------
# Subgraph Share Distribution Protocol  (Algorithm 2, corrected version)
# ---------------------------------------------------------------------------

def run_subgraph_protocol(component: DSSPGraph, h: int, q: int) -> None:
    """
    Apply the Subgraph Share Distribution Protocol on a connected component
    `component` at step h (1-indexed), with arithmetic in Z_q.

    Three phases: initialization, frontier expansion, cycle closure.

    `component` is a subgraph view: writes to its `shares`, `cycle_info`,
    `prop_from`, `closure_share` are visible on the parent graph.
    """
    if not component.nodes or not component.edges:
        return
    
    # ---- Phase 1: initialization ----------------------------------------
    VZ: set = set()
    EZ: set = set()

    cycle = find_cycle(component)
    if cycle is not None:
        apply_cycle_protocol(component, cycle, h, q)
        VZ.update(cycle)
        m = len(cycle)
        for k in range(m):
            EZ.add(_ek(cycle[k], cycle[(k + 1) % m]))

    else:
        # Acyclic component: pick an arbitrary edge (deterministic: minimum)
        e0 = min(component.edges)
        i0, j0 = e0
        r = random.randrange(q)
        x = component.secret_component(i0, j0, h)
        component.shares[i0][h] = [r]
        component.shares[j0][h] = [(r + x) % q]
        component.prop_from[(j0, h)] = i0
        VZ.update([i0, j0])
        EZ.add(e0)

    # ---- Phase 2: frontier expansion ------------------------------------
    # BFS-style frontier queue: when a node joins V_Z, scan its incident
    # edges and (a) propagate to neighbours not in V_Z (adding the new
    # edge to E_Z), (b) record neighbours already in V_Z (with edge not
    # yet in E_Z) as residual cycle-closure edges to be processed in
    # Phase 3. This yields O(|V_J| + |E_J|) overall.
    queue = deque(sorted(VZ))
    residual_edges = []     # edges to be processed by cycle closure
    seen_residual: set = set()
    while queue:
        src = queue.popleft()
        for dst in sorted(component.adj.get(src, ())):
            e = _ek(src, dst)
            if e in EZ:
                continue
            if dst in VZ:
                if e not in seen_residual:
                    seen_residual.add(e)
                    residual_edges.append(e)
                continue
            dsh_src = component.shares[src][h][0]
            x = component.secret_component(src, dst, h)
            component.shares[dst][h] = [(dsh_src + x) % q]
            component.prop_from[(dst, h)] = src
            VZ.add(dst)
            EZ.add(e)
            queue.append(dst)

    # ---- Phase 3: cycle closure -----------------------------------------
    # For every residual edge (i,j) in E_J \ E_Z (necessarily with i,j in V_Z),
    # assign an *additional* share dsh_src + x_{src,dst} to node dst.
    # Deterministic choice: src = min(i,j), dst = max(i,j).
    for e in sorted(residual_edges):
        i, j = e
        src, dst = i, j  # i < j by construction
        dsh_src = component.shares[src][h][0]
        x = component.secret_component(src, dst, h)
        new_share = (dsh_src + x) % q
        component.shares[dst][h].append(new_share)
        src_idx = 0
        dst_idx = len(component.shares[dst][h]) - 1
        component.closure_share[(src, dst, h)] = (src, src_idx, dst, dst_idx)
        component.closure_share[(dst, src, h)] = (src, src_idx, dst, dst_idx)
        EZ.add(e)

def run_subgraph_protocol_visual(component: DSSPGraph, h: int, q: int) -> None:
    """
    Apply the Subgraph Share Distribution Protocol on a connected component
    `component` at step h (1-indexed), with arithmetic in Z_q.

    Three phases: initialization, frontier expansion, cycle closure.
    In this version, each phase shows the resulting graph visually.

    `component` is a subgraph view: writes to its `shares`, `cycle_info`,
    `prop_from`, `closure_share` are visible on the parent graph.
    """
    if not component.nodes or not component.edges:
        return
    
    # ---- Phase 1: initialization ----------------------------------------
    VZ: set = set()
    EZ: set = set()

    cycle = find_cycle(component)
    if cycle is not None:
        apply_cycle_protocol(component, cycle, h, q)
        VZ.update(cycle)
        m = len(cycle)
        for k in range(m):
            EZ.add(_ek(cycle[k], cycle[(k + 1) % m]))

        component.visualize_step(h, "Subgraph Share Distribution Protocol: After Cycle Protocol")

    else:
        # Acyclic component: pick an arbitrary edge (deterministic: minimum)
        e0 = min(component.edges)
        i0, j0 = e0
        r = random.randrange(q)
        x = component.secret_component(i0, j0, h)
        component.shares[i0][h] = [r]
        component.shares[j0][h] = [(r + x) % q]
        component.prop_from[(j0, h)] = i0
        VZ.update([i0, j0])
        EZ.add(e0)

        component.visualize_step(h, "Subgraph Share Distribution Protocol: After arbitrary edge")


    # ---- Phase 2: frontier expansion ------------------------------------
    # BFS-style frontier queue: when a node joins V_Z, scan its incident
    # edges and (a) propagate to neighbours not in V_Z (adding the new
    # edge to E_Z), (b) record neighbours already in V_Z (with edge not
    # yet in E_Z) as residual cycle-closure edges to be processed in
    # Phase 3. This yields O(|V_J| + |E_J|) overall.
    queue = deque(sorted(VZ))
    residual_edges = []     # edges to be processed by cycle closure
    seen_residual: set = set()
    while queue:
        src = queue.popleft()
        for dst in sorted(component.adj.get(src, ())):
            e = _ek(src, dst)
            if e in EZ:
                continue
            if dst in VZ:
                if e not in seen_residual:
                    seen_residual.add(e)
                    residual_edges.append(e)
                continue
            dsh_src = component.shares[src][h][0]
            x = component.secret_component(src, dst, h)
            component.shares[dst][h] = [(dsh_src + x) % q]
            component.prop_from[(dst, h)] = src
            VZ.add(dst)
            EZ.add(e)
            queue.append(dst)

    component.visualize_step(h, "Subgraph Share Distribution Protocol: After frontier expansion")


    # ---- Phase 3: cycle closure -----------------------------------------
    # For every residual edge (i,j) in E_J \ E_Z (necessarily with i,j in V_Z),
    # assign an *additional* share dsh_src + x_{src,dst} to node dst.
    # Deterministic choice: src = min(i,j), dst = max(i,j).
    for e in sorted(residual_edges):
        i, j = e
        src, dst = i, j  # i < j by construction
        dsh_src = component.shares[src][h][0]
        x = component.secret_component(src, dst, h)
        new_share = (dsh_src + x) % q
        component.shares[dst][h].append(new_share)
        src_idx = 0
        dst_idx = len(component.shares[dst][h]) - 1
        component.closure_share[(src, dst, h)] = (src, src_idx, dst, dst_idx)
        component.closure_share[(dst, src, h)] = (src, src_idx, dst, dst_idx)
        EZ.add(e)

    component.visualize_step(h, "Subgraph Share Distribution Protocol: After cycle closure")

# ---------------------------------------------------------------------------
# Top-level: Different Secrets Size Protocol  (Algorithm 1)
# ---------------------------------------------------------------------------

def run_dssp(access_structure, secrets, q: int) -> DSSPGraph:
    """
    Run the Different Secrets Size Protocol over an access structure.

    Parameters
    ----------
    access_structure : iterable of (i,j) pairs
    secrets          : dict (i,j) -> list[int]   (component values in [0, q-1])
                       Key (i,j) may also appear as (j,i); normalised internally.
    q                : odd integer >= 3, the size of the finite field Z_q.

    Returns
    -------
    A DSSPGraph with .shares populated.
    """

    # Normalise secret keys to canonical (min,max) form
    norm_secrets = {_ek(i, j): list(v) for (i, j), v in secrets.items()}

    # Build the graph
    g = DSSPGraph()
    for (i, j) in access_structure:
        g.add_edge(i, j)
    g.secrets = norm_secrets

    if not g.edges:
        return g

    l_max = max(len(v) for v in norm_secrets.values())

    # shares[v] has length l_max + 1; index 0 = Step 0; indices 1..l_max = step h
    for v in g.nodes:
        g.shares[v] = [[] for _ in range(l_max + 1)]

    # --- Step 0: leaf initialisation ------------------------------------
    # For every edge (i,j) such that at least one endpoint is a leaf,
    # assign the whole secret to the leaf node, and nothing to the other.
    # If both endpoints are leaves (an "isolated edge" component), the
    # secret is deterministically assigned to the endpoint with the
    # larger label.
    leaves = {v for v in g.nodes if g.degree(v) == 1}
    leaf_edges = []          # list of (leaf_node, edge_key) pairs
    for e in list(g.edges):
        i, j = e
        i_is_leaf = (i in leaves)
        j_is_leaf = (j in leaves)
        if not (i_is_leaf or j_is_leaf):
            continue
        # Pick the leaf endpoint deterministically
        if i_is_leaf and j_is_leaf:
            leaf = max(i, j)
        elif i_is_leaf:
            leaf = i
        else:
            leaf = j
        g.shares[leaf][0] = list(g.secrets.get(e, []))
        leaf_edges.append((leaf, e))

    # Remove the processed leaf edges, then drop nodes that become isolated.
    for (_leaf, e) in leaf_edges:
        g.remove_edge(e)
    for v in list(g.nodes):
        if not g.adj.get(v):
            g.nodes.discard(v)
            g.adj.pop(v, None)

    # --- Steps 1 .. l_max ----------------------------------------------
    for h in range(1, l_max + 1):
        remove_short_edges(g, h)
        for comp in connected_components(g):
            run_subgraph_protocol(comp, h, q)

    return g

def run_dssp_visual(access_structure, secrets, q: int) -> DSSPGraph:
    """
    Run the Different Secrets Size Protocol over an access structure, generating a clickable window that shows the state of the graph at each step.

    Parameters
    ----------
    access_structure : iterable of (i,j) pairs
    secrets          : dict (i,j) -> list[int]   (component values in [0, q-1])
                       Key (i,j) may also appear as (j,i); normalised internally.
    q                : odd integer >= 3, the size of the finite field Z_q.

    Returns
    -------
    A DSSPGraph with .shares populated.
    """

    # Centers the window before generating it for the first time, in a rendering backend-agnostic way (Tk, QT, etc.)
    manager = pyplot.get_current_fig_manager()
    if manager is not None:
        manager.resize(800, 600)

    # Normalise secret keys to canonical (min,max) form
    norm_secrets = {_ek(i, j): list(v) for (i, j), v in secrets.items()}

    # Build the graph
    g = DSSPGraph()
    for (i, j) in access_structure:
        g.add_edge(i, j)
    g.secrets = norm_secrets

    if not g.edges:
        return g

    l_max = max(len(v) for v in norm_secrets.values())

    # shares[v] has length l_max + 1; index 0 = Step 0; indices 1..l_max = step h
    for v in g.nodes:
        g.shares[v] = [[] for _ in range(l_max + 1)]

    # --- Step 0: leaf initialisation ------------------------------------
    # For every edge (i,j) such that at least one endpoint is a leaf,
    # assign the whole secret to the leaf node, and nothing to the other.
    # If both endpoints are leaves (an "isolated edge" component), the
    # secret is deterministically assigned to the endpoint with the
    # larger label.
    leaves = {v for v in g.nodes if g.degree(v) == 1}
    leaf_edges = []          # list of (leaf_node, edge_key) pairs
    for e in list(g.edges):
        i, j = e
        i_is_leaf = (i in leaves)
        j_is_leaf = (j in leaves)
        if not (i_is_leaf or j_is_leaf):
            continue
        # Pick the leaf endpoint deterministically
        if i_is_leaf and j_is_leaf:
            leaf = max(i, j)
        elif i_is_leaf:
            leaf = i
        else:
            leaf = j
        g.shares[leaf][0] = list(g.secrets.get(e, []))
        leaf_edges.append((leaf, e))

    g.visualize_step(0, "Leaves initialized")

    # Remove the processed leaf edges, then drop nodes that become isolated.
    for (_leaf, e) in leaf_edges:
        g.remove_edge(e)
    for v in list(g.nodes):
        if not g.adj.get(v):
            g.nodes.discard(v)
            g.adj.pop(v, None)

    g.visualize_step(0, "Reduced graph")


    # --- Steps 1 .. l_max ----------------------------------------------
    for h in range(1, l_max + 1):
        remove_short_edges(g, h)
        g.visualize_step(h, "Subgraph built")
        comp_counter = 0
        for comp in connected_components(g):
            comp_counter += 1
            comp.visualize_step(h, "Connected component " + str(comp_counter))
            run_subgraph_protocol_visual(comp, h, q)

    return g



# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------

def reconstruct(graph: DSSPGraph, i: int, j: int, h: int, q: int) -> Optional[int]:
    """
    Reconstruct the h-th component (1-indexed) of secret s_{i,j}.

    Strategy:
      - Leaf case: one endpoint received the entire secret at Step 0;
        return component (h-1).
      - Cycle Protocol case: edge processed by the Cycle Protocol at
        step h. Use cycle_info to compute the value.
      - Cycle closure case: edge processed during phase 3.
        x = (additional_share_at_dst - dsh_src) mod q.
      - Frontier expansion case: edge processed during phase 2.
        x = (sh_dst - dsh_src) mod q.
    """
    # ---- Leaf case ----------------------------------------------------
    sh_i_0 = graph.shares.get(i, [[]])[0]
    sh_j_0 = graph.shares.get(j, [[]])[0]
    if sh_i_0 and not sh_j_0:
        idx = h - 1
        return sh_i_0[idx] if 0 <= idx < len(sh_i_0) else None
    if sh_j_0 and not sh_i_0:
        idx = h - 1
        return sh_j_0[idx] if 0 <= idx < len(sh_j_0) else None

    # ---- Cycle Protocol case -----------------------------------------
    info = graph.cycle_info.get((i, j, h)) or graph.cycle_info.get((j, i, h))
    if info is not None:
        ordered, k = info
        m = len(ordered)
        a, b = ordered[k], ordered[(k + 1) % m]
        sh_a = graph.shares[a][h][0]
        sh_b = graph.shares[b][h][0]
        if k < m - 1:
            return (sh_a - sh_b) % q
        else:
            inv2 = pow(2, -1, q)
            return ((2 * sh_a - sh_b) * inv2) % q

    # ---- Cycle closure case ------------------------------------------
    cl = graph.closure_share.get((i, j, h)) or graph.closure_share.get((j, i, h))
    if cl is not None:
        src, src_idx, dst, dst_idx = cl
        dsh_src = graph.shares[src][h][src_idx]
        add_share = graph.shares[dst][h][dst_idx]
        return (add_share - dsh_src) % q

    # ---- Frontier expansion case --------------------------------------
    src_of_j = graph.prop_from.get((j, h))
    src_of_i = graph.prop_from.get((i, h))
    sh_i_h = graph.shares.get(i, [])
    sh_j_h = graph.shares.get(j, [])
    if not (h < len(sh_i_h) and sh_i_h[h]):
        return None
    if not (h < len(sh_j_h) and sh_j_h[h]):
        return None

    if src_of_j == i:
        return (sh_j_h[h][0] - sh_i_h[h][0]) % q
    if src_of_i == j:
        return (sh_i_h[h][0] - sh_j_h[h][0]) % q

    return None


def verify_all(graph: DSSPGraph, secrets: dict, q: int) -> bool:
    """
    Verify that every secret in `secrets` is correctly reconstructible.

    `secrets` may use either (i,j) or (j,i) keys.
    Returns True iff all reconstructions match.
    """
    norm = {_ek(i, j): list(v) for (i, j), v in secrets.items()}
    for (i, j), sec in norm.items():
        for h_idx, expected in enumerate(sec):
            h = h_idx + 1
            got = reconstruct(graph, i, j, h, q)
            if got != expected:
                return False
    return True


# ---------------------------------------------------------------------------
# Backward-compatible API
# ---------------------------------------------------------------------------

def DSSPSetVariables(m: int, n: int, q: int,
                     secretsLengths: list, accessStructure: list):
    """
    Build a graph + random secrets matching the supplied lengths.

    Backward-compatible with the original signature; the `n` and `m`
    parameters are kept for API compatibility but only used for input
    validation in the interactive script.
    """
    if len(secretsLengths) != len(accessStructure):
        raise ValueError("len(secretsLengths) must equal len(accessStructure)")

    secrets = {}
    for idx, edge in enumerate(accessStructure):
        i, j = edge[0], edge[1]
        secrets[(i, j)] = [random.randrange(q)
                           for _ in range(secretsLengths[idx])]
    Zq = list(range(q))
    return None, None, secrets, Zq


def DSSPTestable(should_show: str, m: int, secretsLengths: list, n: int, q: int,
                 accessStructure: list) -> int:
    """
    Non-interactive entry point used by the benchmarks. Builds random
    secrets, runs the protocol, verifies the reconstruction, and returns
    0 on success.

    Returns a non-zero error code if the inputs are invalid or if
    reconstruction fails.
    """
    err = _check_inputs(should_show, m, secretsLengths, n, q)
    if err != 0:
        return err

    _, _, secrets, _ = DSSPSetVariables(m, n, q, secretsLengths, accessStructure)
    graph = run_dssp(accessStructure, secrets, q)
    if not verify_all(graph, secrets, q):
        return 99
    return 0


def _check_inputs(should_show: str, m: int, secretLengths: list, n: int, q: int) -> int:
    if should_show not in ("Y", "y", "N", "n"):
        return 1
    if m <= 0:
        return 2
    for length in secretLengths:
        if length <= 0:
            return 3
    if n <= 0:
        return 4
    if q < 3 or q % 2 == 0:
        return 6
    return 0


def DSSP() -> None:
    """Interactive entry point (kept for backward compatibility)."""
    should_show = str(input("Should the generated graphs be shown visually, with user interaction? This will result in a slight performance hit. (Y, N)\n"))
    m = int(input("Please input the number of users\n"))
    secretsLengths = []
    accessStructure = []
    for k in range(m):
        edge = list(map(int, input(
            f"Please input the two nodes that constitute the edge {k+1}, with a space separating them\n"
        ).split()))
        accessStructure.append(edge)
        secretsLengths.append(
            int(input(f"Please input the length of secret {k+1}\n"))
        )
    n = int(input("Please input the number of disks\n"))
    q = int(input("Please input the value of q for the field Zq\n"))

    err = _check_inputs(should_show, m, secretsLengths, n, q)
    if err != 0:
        print(f"Input error (code {err})")
        return

    _, _, secrets, _ = DSSPSetVariables(m, n, q, secretsLengths, accessStructure)
    if should_show in ("Y", "y"):
        graph = run_dssp_visual(accessStructure, secrets, q)
    else:
        graph = run_dssp(accessStructure, secrets, q)
    ok = verify_all(graph, secrets, q)
    print(f"Reconstruction {'OK' if ok else 'FAILED'}.")


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DSSP()
