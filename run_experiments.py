"""
run_experiments.py
==================
Runs all benchmarks for the Multi-Ring DSSP paper and saves CSV files.
Must be run from the same directory as mf_dssp.py.

Usage:
    python run_experiments.py           # full run (reps=10)
    python run_experiments.py --quick   # quick test (reps=3, fewer sizes)
    python run_experiments.py --reps 20 # custom reps

Output (one CSV per table):
    tab_time_nodes.csv      Time vs |V|
    tab_time_lmax.csv       Time vs l_max
    tab_storage_trees.csv   Storage on random trees
    tab_iot_star.csv        IoT star topology
    tab_delta_cyc.csv       Cycle embedding overhead
    tab_nonuniform.csv      Share non-uniformity
"""
import os
import sys, random, time, csv
from math import log2, gcd
from collections import Counter, defaultdict
from multifield_dssp import run_multifield_dssp

# ── CLI ───────────────────────────────────────────────────────────────────

REPS  = 10
QUICK = '--quick' in sys.argv
if QUICK:
    REPS = 3
i = sys.argv.index('--reps') if '--reps' in sys.argv else -1
if i >= 0 and i + 1 < len(sys.argv):
    REPS = int(sys.argv[i + 1])

# ── Arithmetic ────────────────────────────────────────────────────────────

def lcm(a, b):  return a * b // gcd(a, b)
def lcm_list(v):
    r = v[0]
    for x in v[1:]: r = lcm(r, x)
    return r

# ── Bit counting ──────────────────────────────────────────────────────────

def count_bits(graph, fields):
    """
    Sum log2(q) over all non-empty share slots.
    q is determined by:
      - cycle_info if the node was in a cycle at that step
      - prop_from  if the share was propagated
      - max adjacent edge otherwise (root share)
    """
    bits = 0.0
    for v, share_list in graph.shares.items():
        for h, sh in enumerate(share_list):
            if not sh:
                continue
            # cycle share?
            cycle_q = None
            for (ni, nj, nh), (ordered, q_star, _) in graph.cycle_info.items():
                if nh == h and v in ordered:
                    cycle_q = q_star
                    break
            if cycle_q is not None:
                bits += log2(cycle_q)
                continue
            # propagated share?
            src = graph.prop_from.get((v, h))
            if src is not None:
                ek = (min(v, src), max(v, src))
                bits += log2(fields.get(ek, 15))
                continue
            # root share: use max modulus among adjacent edges
            adj = [fields[e] for e in fields if v in e]
            bits += log2(max(adj)) if adj else log2(15)
    return bits

# ── Graph generators ──────────────────────────────────────────────────────

def gen_graph(n_nodes, n_edges, l_max, q=15, seed=None):
    """Random graph with n_nodes nodes and n_edges edges, all q."""
    if seed is not None: random.seed(seed)
    nodes = list(range(1, n_nodes + 1)); random.shuffle(nodes)
    edges = set()
    for k in range(1, n_nodes):
        edges.add((min(nodes[k-1], nodes[k]), max(nodes[k-1], nodes[k])))
    att = 0
    while len(edges) < n_edges and att < 10000:
        a, b = random.sample(nodes, 2)
        edges.add((min(a, b), max(a, b))); att += 1
    edges = list(edges)
    fields  = {e: q for e in edges}
    secrets = {e: [random.randint(1, q - 1)
                   for _ in range(random.randint(1, l_max))]
               for e in edges}
    return edges, secrets, fields


def gen_tree_hetero(n_nodes, l_max, q_leaf=3, q_internal=15, seed=None):
    """Random tree: leaf edges in Z_{q_leaf}, internal in Z_{q_internal}."""
    if seed is not None: random.seed(seed)
    nodes = list(range(1, n_nodes + 1)); random.shuffle(nodes)
    edges = [(min(nodes[k-1], nodes[k]), max(nodes[k-1], nodes[k]))
             for k in range(1, n_nodes)]
    deg = defaultdict(int)
    for i, j in edges:
        deg[i] += 1; deg[j] += 1
    f_mr  = {e: (q_leaf if deg[e[0]] == 1 or deg[e[1]] == 1
                 else q_internal) for e in edges}
    f_dss = {e: lcm(q_leaf, q_internal) for e in edges}
    secrets = {e: [random.randint(1, f_mr[e] - 1)
                   for _ in range(random.randint(1, l_max))]
               for e in edges}
    leaf_pct = sum(1 for e in edges
                   if deg[e[0]] == 1 or deg[e[1]] == 1) / len(edges) * 100
    return edges, secrets, f_mr, f_dss, leaf_pct

# ── CSV helper ────────────────────────────────────────────────────────────

def save_csv(fname, header, rows):
    os.makedirs('output_runexperiments', exist_ok=True)
    fname = os.path.join('output_runexperiments', fname)
    with open(fname, 'w', newline='') as f:
        csv.writer(f).writerow(header)
        csv.writer(f).writerows(rows)
    print(f"  -> {fname}")

# ── Experiment 1: Time vs |V| ─────────────────────────────────────────────

def exp_time_vs_nodes(node_counts, l_max=10, edge_ratio=2.0,
                      q=15, reps=REPS, out='tab_time_nodes.csv'):
    print(f"\n[1/6] Time vs |V|  (l_max={l_max}, q={q}, reps={reps})")
    rows = []
    for n in node_counts:
        ne = max(n - 1, int(n * edge_ratio))
        times = []
        for rep in range(reps):
            e, s, f = gen_graph(n, ne, l_max, q, seed=rep * 1000 + n)
            t0 = time.perf_counter()
            run_multifield_dssp(e, s, f)
            times.append((time.perf_counter() - t0) * 1000)
        mean = sum(times) / reps
        std  = (sum((t-mean)**2 for t in times) / reps) ** 0.5
        rows.append([n, ne, round(mean, 2), round(std, 2)])
        print(f"  |V|={n:4d}  |E|={ne:5d}  {mean:.2f} ± {std:.2f} ms")
    save_csv(out, ['V', 'E', 'mean_ms', 'std_ms'], rows)

# ── Experiment 2: Time vs l_max ───────────────────────────────────────────

def exp_time_vs_lmax(lmax_values, n_nodes=100, edge_ratio=2.0,
                     q=15, reps=REPS, out='tab_time_lmax.csv'):
    print(f"\n[2/6] Time vs l_max  (|V|={n_nodes}, q={q}, reps={reps})")
    ne = int(n_nodes * edge_ratio)
    rows = []
    for l in lmax_values:
        times = []
        for rep in range(reps):
            e, s, f = gen_graph(n_nodes, ne, l, q, seed=rep * 1000 + l)
            t0 = time.perf_counter()
            run_multifield_dssp(e, s, f)
            times.append((time.perf_counter() - t0) * 1000)
        mean = sum(times) / reps
        std  = (sum((t-mean)**2 for t in times) / reps) ** 0.5
        rows.append([l, round(mean, 2), round(std, 2)])
        print(f"  l_max={l:3d}  {mean:.2f} ± {std:.2f} ms")
    save_csv(out, ['l_max', 'mean_ms', 'std_ms'], rows)

# ── Experiment 3: Storage — random trees ─────────────────────────────────

def exp_storage_trees(node_counts, l_max=10, reps=REPS,
                      out='tab_storage_trees.csv'):
    print(f"\n[3/6] Storage on random trees  (l_max={l_max}, reps={reps})")
    rows = []
    for n in node_counts:
        mr_l, dss_l, lf_l = [], [], []
        for rep in range(reps):
            edges, secrets, f_mr, f_dss, lf = gen_tree_hetero(
                n, l_max, seed=rep * 1000 + n)
            g_mr  = run_multifield_dssp(edges, secrets, f_mr)
            g_dss = run_multifield_dssp(edges,
                        {e: list(s) for e, s in secrets.items()}, f_dss)
            mr_l.append(count_bits(g_mr, f_mr))
            dss_l.append(count_bits(g_dss, f_dss))
            lf_l.append(lf)
        mr  = round(sum(mr_l)  / reps, 1)
        dss = round(sum(dss_l) / reps, 1)
        lf  = round(sum(lf_l)  / reps, 1)
        sav = round((dss - mr) / dss * 100, 1) if dss > 0 else 0.0
        rows.append([n, mr, dss, sav, lf])
        print(f"  |V|={n:4d}  MR={mr:.1f}  DSS={dss:.1f}"
              f"  saving={sav:.1f}%  leaf={lf:.1f}%")
    save_csv(out, ['V','MR_bits','DSS_bits','saving_pct','leaf_edges_pct'], rows)

# ── Experiment 4: IoT star topology ──────────────────────────────────────

def exp_iot_star(hub_counts, sensors_per_hub=10, l_max=10,
                 reps=REPS, out='tab_iot_star.csv'):
    print(f"\n[4/6] IoT star  (sensors/hub={sensors_per_hub},"
          f" l_max={l_max}, reps={reps})")
    rows = []
    for nh in hub_counts:
        mr_l, dss_l, t_l = [], [], []
        for rep in range(reps):
            random.seed(rep * 1000 + nh * 100 + sensors_per_hub)
            hubs = list(range(1, nh + 1)); nid = nh + 1
            edges=[]; f_mr={}; f_dss={}
            for k in range(nh):
                e=(min(hubs[k],hubs[(k+1)%nh]),max(hubs[k],hubs[(k+1)%nh]))
                if e not in f_mr:
                    edges.append(e); f_mr[e]=15; f_dss[e]=15
            for hub in hubs:
                for _ in range(sensors_per_hub):
                    s=nid; nid+=1
                    e=(min(hub,s),max(hub,s))
                    edges.append(e); f_mr[e]=3; f_dss[e]=15
            secrets={e:[random.randint(1,f_mr[e]-1)
                        for _ in range(random.randint(1,l_max))]
                     for e in edges}
            t0=time.perf_counter()
            g_mr=run_multifield_dssp(edges,secrets,f_mr)
            t_l.append((time.perf_counter()-t0)*1000)
            g_dss=run_multifield_dssp(edges,
                      {e:list(s) for e,s in secrets.items()},f_dss)
            mr_l.append(count_bits(g_mr,f_mr))
            dss_l.append(count_bits(g_dss,f_dss))
        n_v=nh+nh*sensors_per_hub
        mr =round(sum(mr_l)/reps,1); dss=round(sum(dss_l)/reps,1)
        sav=round((dss-mr)/dss*100,1) if dss>0 else 0.0
        tm =round(sum(t_l)/reps,2)
        rows.append([nh,n_v,mr,dss,sav,tm])
        print(f"  hubs={nh:3d}  |V|={n_v:4d}  MR={mr:.1f}"
              f"  DSS={dss:.1f}  saving={sav:.1f}%  time={tm:.2f} ms")
    save_csv(out,['hubs','V','MR_bits','DSS_bits','saving_pct','time_ms'],rows)

# ── Experiment 5: Delta_cyc ───────────────────────────────────────────────

def exp_delta_cyc(test_cases, l_max=3, reps=30, out='tab_delta_cyc.csv'):
    print(f"\n[5/6] Delta_cyc  (l_max={l_max}, reps={reps})")
    rows = []
    for cf in test_cases:
        m=len(cf); nodes=list(range(1,m+1))
        raw=[(nodes[k],nodes[(k+1)%m]) for k in range(m)]
        seen=set(); edges=[]
        for a,b in raw:
            e=(min(a,b),max(a,b))
            if e not in seen: edges.append(e); seen.add(e)
        if len(edges)<m: continue
        f_mf={edges[k]:cf[k] for k in range(len(edges))}
        q_star=lcm_list(cf); q_min=min(cf)
        delta_th=(log2(q_star)-log2(q_min))*m
        delta_l=[]
        for rep in range(reps):
            random.seed(rep*1000+sum(cf))
            secrets={e:[random.randint(1,f_mf[e]-1)
                        for _ in range(random.randint(1,l_max))]
                     for e in edges}
            g=run_multifield_dssp(edges,secrets,f_mf)
            bits_mf=count_bits(g,f_mf)
            bits_nat=sum(log2(f_mf[e])*len(s) for e,s in secrets.items())
            delta_l.append(bits_mf-bits_nat)
        de=round(sum(delta_l)/reps,2)
        rows.append([','.join(map(str,cf)),m,q_star,round(delta_th,2),de])
        print(f"  {str(cf):22s}  q*={q_star}  th={round(delta_th,2):.2f}"
              f"  emp={de:.2f}")
    save_csv(out,['moduli','cycle_len','q_star','delta_th_per_step','delta_emp'],rows)

# ── Experiment 6: Share non-uniformity ───────────────────────────────────

def exp_nonuniformity(n_samples=100000, out='tab_nonuniform.csv'):
    print(f"\n[6/6] Share non-uniformity  (n_samples={n_samples})")
    rows=[]
    for q1,q2,label in [(5,3,'Z5->Z3 (incompatible)'),(15,3,'Z15->Z3 (compatible)')]:
        counts=Counter()
        for _ in range(n_samples):
            r=random.randint(0,q1-1); s=random.randint(0,q1-1)
            counts[((r+s)%q1)%q2]+=1
        total=sum(counts.values())
        probs=[round(counts[c]/total,4) for c in range(q2)]
        rows.append([label]+probs)
        print(f"  {label:32s}  P={probs}")
    save_csv(out,['case','P_c0','P_c1','P_c2'],rows)

# ── Main ──────────────────────────────────────────────────────────────────

if __name__=='__main__':
    if QUICK:
        NODE_COUNTS=[10,50,100,200]; LMAX_VALUES=[1,5,10,20]
        HUB_COUNTS=[2,4,8,10];      DELTA_REPS=10
    else:
        NODE_COUNTS=[10,25,50,100,200,300,500]; LMAX_VALUES=[1,5,10,20,30,50]
        HUB_COUNTS=[2,4,6,8,10,20];             DELTA_REPS=30

    DELTA_CASES=[[3,5,15],[5,5,15],[3,15,15],[3,5,5,15],[3,3,5,15]]

    print(f"Multi-Ring DSSP — experiments (reps={REPS}"
          + (" QUICK" if QUICK else "") + ")")
    t0=time.perf_counter()

    exp_time_vs_nodes(NODE_COUNTS,  l_max=10, reps=REPS)
    exp_time_vs_lmax(LMAX_VALUES,              reps=REPS)
    exp_storage_trees(NODE_COUNTS,  l_max=10, reps=REPS)
    exp_iot_star(HUB_COUNTS,        l_max=10, reps=REPS)
    exp_delta_cyc(DELTA_CASES,      l_max=3,  reps=DELTA_REPS)
    exp_nonuniformity(n_samples=100000)

    print(f"\nDone in {time.perf_counter()-t0:.1f}s."
          " CSV files written to current directory.")
