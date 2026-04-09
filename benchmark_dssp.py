"""
benchmark_fixed.py
Benchmark script for DSSP with fixed cycleProtocol.
"""
import random, time, statistics, csv, math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from dssp import DSSPSetVariables, getConnectedComponents, getReducedGraphBasedOnLen

# ── fixed protocol ────────────────────────────────────────────────────────────

def cycleCheckWithDFS_fixed(node, parent_val, visited, nodesInCycle):
    visited.add(node.value)
    for edge in node.edges:
        nb = edge.j if edge.i == node else edge.i
        if nb.value not in visited:
            nodesInCycle[nb.value] = node.value
            cycle = cycleCheckWithDFS_fixed(nb, node.value, visited, nodesInCycle)
            if cycle:
                return cycle
        elif nb.value != parent_val:
            cycle = set()
            cur = node.value
            cycle.add(nb.value)
            while cur != nb.value:
                cycle.add(cur)
                cur = nodesInCycle[cur]
            return cycle
    return None

def runSubgraphProtocol_fixed(graph, step, Zq):
    h_idx = step - 1
    start_node = next(iter(graph.nodes.values()))
    cycle = cycleCheckWithDFS_fixed(start_node, -1, set(), {})

    if cycle:
        from collections import defaultdict
        adj = defaultdict(list)
        for e in graph.edges:
            iv, jv = e.i.value, e.j.value
            if iv in cycle and jv in cycle:
                key = (min(iv,jv), max(iv,jv))
                adj[iv].append((jv, key))
                adj[jv].append((iv, key))
        start = min(cycle)
        ordered_nodes, ordered_secrets = [start], []
        visited_c, cur = {start}, start
        while True:
            moved = False
            for nb, key in adj[cur]:
                if nb not in visited_c:
                    s = graph.secrets[key]
                    ordered_secrets.append(s[h_idx] if h_idx < len(s) else 0)
                    ordered_nodes.append(nb); visited_c.add(nb); cur = nb
                    moved = True; break
            if not moved:
                for nb, key in adj[cur]:
                    if nb == start:
                        s = graph.secrets[key]
                        ordered_secrets.append(s[h_idx] if h_idx < len(s) else 0)
                    break
                break
        m = len(ordered_secrets)
        total = sum(ordered_secrets)
        graph.shares[ordered_nodes[m-1]][h_idx] = [total + ordered_secrets[m-1]]
        for i in range(m-1, 0, -1):
            graph.shares[ordered_nodes[i-1]][h_idx] = [
                graph.shares[ordered_nodes[i]][h_idx][0] + ordered_secrets[i-1]]
        graphZ_node_set = set(cycle)
    else:
        arb_edge = random.choice(list(graph.edges))
        if not Zq: return
        shareR = random.choice(Zq); Zq.remove(shareR)
        iv, jv = arb_edge.i.value, arb_edge.j.value
        key = (min(iv,jv), max(iv,jv))
        s = graph.secrets[key]
        sv = s[h_idx] if h_idx < len(s) else 0
        graph.shares[iv][h_idx] = [shareR]
        graph.shares[jv][h_idx] = [shareR + sv]
        graphZ_node_set = {iv, jv}

    changed = True
    while changed:
        changed = False
        for edge in graph.edges:
            iv, jv = edge.i.value, edge.j.value
            key = (min(iv,jv), max(iv,jv))
            s = graph.secrets.get(key, [])
            sv = s[h_idx] if h_idx < len(s) else 0
            if iv in graphZ_node_set and jv not in graphZ_node_set and graph.shares[iv][h_idx]:
                graph.shares[jv][h_idx] = [graph.shares[iv][h_idx][0] + sv]
                graphZ_node_set.add(jv); changed = True; break
            elif jv in graphZ_node_set and iv not in graphZ_node_set and graph.shares[jv][h_idx]:
                graph.shares[iv][h_idx] = [graph.shares[jv][h_idx][0] + sv]
                graphZ_node_set.add(iv); changed = True; break

# ── helpers ───────────────────────────────────────────────────────────────────

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

def run_once(edges, l_max, equal_length=False):
    m = len(edges)
    sl = [l_max]*m if equal_length else [random.randint(1, l_max) for _ in edges]
    n = max(max(e) for e in edges)
    q = sum(sl)+2; q += q%2==0
    t0 = time.perf_counter()
    graph, _, _, Zq = DSSPSetVariables(m, n, q, sl, [list(e) for e in edges])
    graph.initializeLeaves(); graph.reduce()
    for h in range(graph.calculateLMax()):
        getReducedGraphBasedOnLen(graph, h+1)
        for j in getConnectedComponents(graph):
            runSubgraphProtocol_fixed(j, h+1, Zq)
    return time.perf_counter() - t0

def bench(factory, l_max, reps=10, equal_length=False):
    times = []
    for _ in range(reps):
        try: times.append(run_once(factory(), l_max, equal_length))
        except: pass
    if not times: return float('nan'), float('nan')
    return statistics.mean(times), (statistics.stdev(times) if len(times)>1 else 0)

# ── standalone Tree Protocol ──────────────────────────────────────────────────

def run_tree_protocol(nv, l):
    from collections import defaultdict
    edges = tree_graph(nv); m = len(edges)
    q = m*l+3; q += q%2==0
    adj = defaultdict(list)
    for (i,j) in edges: adj[i].append(j); adj[j].append(i)
    t0 = time.perf_counter()
    root = edges[0][0]; parent = {root: None}; order = [root]; visited = {root}; queue = [root]
    while queue:
        cur = queue.pop(0)
        for nb in adj[cur]:
            if nb not in visited:
                visited.add(nb); parent[nb]=cur; order.append(nb); queue.append(nb)
    Zq = list(range(1, q))
    secrets = {}
    for (i,j) in edges:
        s = [random.choice(Zq) for _ in range(l)]
        secrets[(i,j)] = s; secrets[(j,i)] = s
    r = [random.randint(1, q-1) for _ in range(l)]
    shares = {root: r}
    for node in order[1:]:
        p = parent[node]; key = (min(p,node), max(p,node))
        shares[node] = [(shares[p][k]+secrets[key][k])%q for k in range(l)]
    return time.perf_counter() - t0

# ── standalone Cycle Protocol ─────────────────────────────────────────────────

def run_cycle_protocol(m, l):
    q = m*l+3; q += q%2==0
    t0 = time.perf_counter()
    Zq = list(range(1, q))
    secrets = [[random.choice(Zq) for _ in range(l)] for _ in range(m)]
    shares = []
    for i in range(m):
        sh = [(sum(s[k] for s in secrets) + sum(secrets[j][k] for j in range(i,m)))%q for k in range(l)]
        shares.append(sh)
    return time.perf_counter() - t0

REPS = 10
output_folder = Path("output")
output_folder.mkdir(exist_ok=True, parents=True)

# ── TABLE 1 ───────────────────────────────────────────────────────────────────
T1_CONFIGS = [(10,20),(25,50),(50,100),(100,200),(200,400),(300,600),(500,1000)]
print("Table 1: time vs graph size (l_max=10)")
table1 = []
for nv,ne in T1_CONFIGS:
    m,s = bench(lambda n=nv,e=ne: random_connected_graph(n,e), 10, REPS)
    table1.append((nv,ne,m,s))
    print(f"  |V|={nv:4d} |E|={ne:5d}: {m:.4f} ± {s:.4f} s")

# ── TABLE 2 ───────────────────────────────────────────────────────────────────
T2_LMAX = [1,5,10,20,30,50]
print("\nTable 2: time vs l_max (|V|=100, |E|=200)")
table2 = []
for lmax in T2_LMAX:
    m,s = bench(lambda: random_connected_graph(100,200), lmax, REPS)
    table2.append((lmax,m,s))
    print(f"  l_max={lmax:3d}: {m:.4f} ± {s:.4f} s")

# ── TABLE 3: DSSP vs Tree Protocol ───────────────────────────────────────────
CMP_SIZES = [10,25,50,100,200,300,500]
L = 10
print("\nTable 3: DSSP vs Tree Protocol (l=10, tree graphs)")
table3 = []
for nv in CMP_SIZES:
    md,sd = bench(lambda n=nv: tree_graph(n), L, REPS, equal_length=True)
    tt = [run_tree_protocol(nv,L) for _ in range(REPS)]
    mt = statistics.mean(tt); st = statistics.stdev(tt) if len(tt)>1 else 0
    ratio = md/mt if mt>0 else float('nan')
    table3.append((nv,md,sd,mt,st,ratio))
    print(f"  |V|={nv:4d}: DSSP={md:.4f}s  Tree={mt:.4f}s  ratio={ratio:.2f}x")

# ── TABLE 4: DSSP vs Cycle Protocol ──────────────────────────────────────────
print("\nTable 4: DSSP vs Cycle Protocol (l=10, cycle graphs)")
table4 = []
for m in CMP_SIZES:
    md,sd = bench(lambda n=m: cycle_graph(n), L, REPS, equal_length=True)
    tc = [run_cycle_protocol(m,L) for _ in range(REPS)]
    mc = statistics.mean(tc); sc = statistics.stdev(tc) if len(tc)>1 else 0
    ratio = md/mc if mc>0 else float('nan')
    table4.append((m,md,sd,mc,sc,ratio))
    print(f"  m={m:4d}: DSSP={md:.4f}s  Cycle={mc:.4f}s  ratio={ratio:.2f}x")

# ── TABLE 5: topology comparison ─────────────────────────────────────────────
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
    m,s = bench(factory, TOPO_L, REPS)
    table5.append((name,m,s))
    print(f"  {name:8s}: {m:.4f} ± {s:.4f} s")

# ── FIGURES ───────────────────────────────────────────────────────────────────
print("\nGenerating figures...")

# Fig 1: time vs nodes
FIG1_LMAX = [5,10,20,50]
fig1_data = {}
for lmax in FIG1_LMAX:
    rows = []
    for nv,ne in T1_CONFIGS:
        m,s = bench(lambda n=nv,e=ne: random_connected_graph(n,e), lmax, REPS)
        rows.append((nv,m,s))
    fig1_data[lmax] = rows

fig,ax = plt.subplots(figsize=(6,4))
markers = ["o","s","^","D"]
for idx,lmax in enumerate(FIG1_LMAX):
    xs=[r[0] for r in fig1_data[lmax]]; ys=[r[1] for r in fig1_data[lmax]]; errs=[r[2] for r in fig1_data[lmax]]
    ax.errorbar(xs,ys,yerr=errs,label=f"$\\ell_{{\\max}}={lmax}$",marker=markers[idx],capsize=3)
ax.set_xlabel("Number of nodes $|V|$"); ax.set_ylabel("Execution time (s)")
ax.set_title("Execution time vs.~number of nodes ($|E|=2|V|$)"); ax.legend(); ax.grid(True,linestyle="--",alpha=0.5)
fig.tight_layout(); fig.savefig(output_folder/"fig_time_vs_nodes.pdf"); fig.savefig(output_folder/"fig_time_vs_nodes.png")

# Fig 2: time vs l_max
fig,ax = plt.subplots(figsize=(5,4))
ax.errorbar([r[0] for r in table2],[r[1] for r in table2],yerr=[r[2] for r in table2],marker="o",capsize=3,color="steelblue")
ax.set_xlabel("$\\ell_{\\max}$"); ax.set_ylabel("Execution time (s)")
ax.set_title(f"Execution time vs.~$\\ell_{{\\max}}$ ($|V|=100$, $|E|=200$)"); ax.grid(True,linestyle="--",alpha=0.5)
fig.tight_layout(); fig.savefig(output_folder/"fig_time_vs_lmax.pdf"); fig.savefig(output_folder/"fig_time_vs_lmax.png")

# Fig 3: SO vs m
m_vals = list(range(1,201)); so_vals = [1+1/m for m in m_vals]
fig,ax = plt.subplots(figsize=(5,4))
ax.plot(m_vals,so_vals,color="steelblue",linewidth=1.8,label="$SO=1+1/m$")
ax.axhline(y=1,color="gray",linestyle="--",linewidth=1.2,label="Lower bound $SO=1$")
ax.set_xlabel("Number of secrets $m$"); ax.set_ylabel("Storage overhead $SO$")
ax.set_title("Theoretical $SO$ for tree-based structures\n(equal-length secrets)")
ax.legend(); ax.set_ylim(0.95,2.1); ax.grid(True,linestyle="--",alpha=0.5)
fig.tight_layout(); fig.savefig(output_folder/"fig_so_vs_m.pdf"); fig.savefig(output_folder/"fig_so_vs_m.png")

# Fig 4: comparison
fig,axes = plt.subplots(1,2,figsize=(10,4))
ax=axes[0]
ax.errorbar([r[0] for r in table3],[r[1] for r in table3],yerr=[r[2] for r in table3],marker="o",capsize=3,label="DSSP",color="steelblue")
ax.errorbar([r[0] for r in table3],[r[3] for r in table3],yerr=[r[4] for r in table3],marker="s",capsize=3,label="Tree Protocol",color="darkorange",linestyle="--")
ax.set_xlabel("$|V|$"); ax.set_ylabel("Time (s)"); ax.set_title(f"Tree graphs ($\\ell={L}$)"); ax.legend(fontsize=8); ax.grid(True,linestyle="--",alpha=0.5)
ax=axes[1]
ax.errorbar([r[0] for r in table4],[r[1] for r in table4],yerr=[r[2] for r in table4],marker="o",capsize=3,label="DSSP",color="steelblue")
ax.errorbar([r[0] for r in table4],[r[3] for r in table4],yerr=[r[4] for r in table4],marker="s",capsize=3,label="Cycle Protocol",color="darkorange",linestyle="--")
ax.set_xlabel("$m$"); ax.set_ylabel("Time (s)"); ax.set_title(f"Cycle graphs ($\\ell={L}$)"); ax.legend(fontsize=8); ax.grid(True,linestyle="--",alpha=0.5)
fig.suptitle("DSSP vs.~baseline protocols (homogeneous secrets)",fontsize=11); fig.tight_layout()
fig.savefig(output_folder/"fig_comparison.pdf"); fig.savefig(output_folder/"fig_comparison.png")

# Fig 5: topology
fig,ax = plt.subplots(figsize=(6,4))
names=[r[0] for r in table5]; means=[r[1] for r in table5]; stds=[r[2] for r in table5]
colors=["#4C72B0","#DD8452","#55A868","#C44E52","#8172B3"]
ax.bar(names,means,yerr=stds,capsize=5,color=colors,edgecolor="white")
ax.set_xlabel("Topology"); ax.set_ylabel("Time (s)")
ax.set_title(f"Execution time by topology ($|V|={TOPO_N}$, $\\ell_{{\\max}}={TOPO_L}$)"); ax.grid(True,axis="y",linestyle="--",alpha=0.5)
fig.tight_layout(); fig.savefig(output_folder/"fig_topology.pdf"); fig.savefig(output_folder/"fig_topology.png")

# ── CSV ───────────────────────────────────────────────────────────────────────
with open(output_folder/"benchmark_results.csv","w",newline="") as f:
    w = csv.writer(f)
    w.writerow(["TABLE 1","l_max=10",f"reps={REPS}"]); w.writerow(["|V|","|E|","mean_s","std_s"])
    for r in table1: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 2","|V|=100","|E|=200",f"reps={REPS}"]); w.writerow(["l_max","mean_s","std_s"])
    for r in table2: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 3 DSSP vs Tree",f"l={L}",f"reps={REPS}"]); w.writerow(["|V|","DSSP_mean","DSSP_std","Tree_mean","Tree_std","ratio"])
    for r in table3: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 4 DSSP vs Cycle",f"l={L}",f"reps={REPS}"]); w.writerow(["m","DSSP_mean","DSSP_std","Cycle_mean","Cycle_std","ratio"])
    for r in table4: w.writerow(r)
    w.writerow([]); w.writerow(["TABLE 5 by topology",f"|V|={TOPO_N}",f"l_max={TOPO_L}",f"reps={REPS}"]); w.writerow(["Topology","mean_s","std_s"])
    for r in table5: w.writerow(r)

print("Done. Files: benchmark_results.csv + 5 figures (pdf+png)")
