import random
import matplotlib.pyplot as pyplot
import networkx


class DSSPNode:
    def __init__(self, value: int):
        self.value = value
        self.edges: set[DSSPEdge] = set()

    def getDegree(self):
        return len(self.edges)

    def __str__(self):
        return f"Nodo {self.value}"


class DSSPEdge:
    def __init__(self, i: DSSPNode, j: DSSPNode):
        self.i = i
        self.j = j

    def __str__(self):
        return f"Edge({self.i.value}<->{self.j.value})"
    
class DSSPGraph:
    def __init__(self):
        self.nodes: dict[int, "DSSPNode"] = {}
        self.edges: set[DSSPEdge] = set()
        self.secrets: dict[tuple[int, int], list[int]] #edge.i ed edge.j sono la key, i secret sono il value
        self.shares: dict[int, list[list[int]]] = {} #valore del nodo è la key, il value è una lista di liste di share, indicizzata per numero di step.

    def __str__(self):
        nodes_str = ", ".join(str(node) for node in self.nodes.values())
        edges_str = ", ".join(str(edge) for edge in self.edges)
        secrets_str = str(self.secrets)
        shares_str = []
        for node, values in self.shares.items():
            shares_str.append(f"node {node}: ")
            stepCounter = 0
            for value in values:
                shares_str.append(f"step {stepCounter} : {value} ,")
                stepCounter += 1
        return f"DSSPGraph(nodes=[{nodes_str}], edges=[{edges_str}], secrets=[{secrets_str}], shares=[{shares_str}])"


    def get_node(self, value: int):
        if value not in self.nodes:
            self.nodes[value] = DSSPNode(value)
        return self.nodes[value]

    def add_edge(self, iValue: int, jValue: int, secrets: list[int] = []):
        i = self.get_node(iValue)
        j = self.get_node(jValue)
        edge = DSSPEdge(i, j)
        self.edges.add(edge)
        i.edges.add(edge)
        j.edges.add(edge)

    def remove_edge(self, edge: DSSPEdge):

        # O(deg)

        i = edge.i
        j = edge.j

        # Rimosso controllo con if, fatto da discard.

        i.edges.discard(edge)

        j.edges.discard(edge)

        self.edges.discard(edge)

        if not i.edges:
            # Equivalente a len(edges) == 0
            self.nodes.pop(i.value, None)

        if not j.edges:
            self.nodes.pop(j.value, None)
    
    def calculateLMax(self):
        # Versione corta che usa max, passando iterable e key.
        return max((len(secret) for secret in self.secrets.values()), default=0)
    
    def getSecrets(self):
        #O(1)
        return self.secrets

    def getSubset(self, node_values: set[int]):
        """Prende come input lista di valori dei nodi,
        restituisce il grafo che li contiene."""
        sub = DSSPGraph()
        sub.secrets = {}
        sub.shares = {}
        nodes = {}

        for v in node_values:
            old = self.nodes[v]
            nodes[v] = DSSPNode(old.value)
            sub.nodes[v] = nodes[v]

        for edge in self.edges:
            if edge.i.value in node_values and edge.j.value in node_values:
                iValue = edge.i.value
                jValue = edge.j.value
                new_edge = DSSPEdge(nodes[iValue], nodes[jValue])
                sub.edges.add(new_edge)
                nodes[iValue].edges.add(new_edge)
                nodes[jValue].edges.add(new_edge)
                sub.secrets[iValue, jValue] = self.secrets[iValue, jValue]
                sub.shares[iValue] = self.shares[iValue]
                sub.shares[jValue] = self.shares[jValue]

        #sub.secrets = self.secrets
        #sub.shares = self.shares

        return sub
    
    def initializeLeaves(self):
    # O(|E|)

     for edge in self.edges:
        if edge.j.getDegree() == 1:
            self.shares[edge.j.value][0] = (self.secrets[edge.i.value, edge.j.value])      
            # Dovrebbe corrispondere a sij allo step 0.
        # Altrimenti rimane empty assegnato al nodo i
    
    def reduce(self):
    # O(|E| * deg)
     edges_to_remove = {edge for edge in self.edges if edge.j.getDegree() == 1}

     for edge in edges_to_remove:
        self.remove_edge(edge)


    
    def visualize(self, step, subtitle=""):
        title = "Step " + str(step)
        pyplot.suptitle(title)
        pyplot.title(subtitle)
        nxGraph = networkx.Graph()
        for edge in self.edges:
            nxGraph.add_edge(edge.i.value, edge.j.value, secret="s" + str(edge.i.value) + "," + str(edge.j.value) + "\n" + str(self.secrets[(edge.i.value, edge.j.value)]))
        pos = networkx.shell_layout(nxGraph)
        networkx.draw(nxGraph, pos, with_labels=True)
        edge_labels = networkx.get_edge_attributes(nxGraph, 'secret')
        networkx.draw_networkx_edge_labels(nxGraph, pos, edge_labels=edge_labels)

        extra_labels = {n: "sh" + str(n) + "\n" + str(self.shares[n][step]) for n in nxGraph.nodes if n in self.shares}        
        vertical_offset = 0.12  

        offset_pos = { node: (x, y + vertical_offset) for node, (x, y) in pos.items() }        
        networkx.draw_networkx_labels(nxGraph,
    offset_pos,
    labels=extra_labels,
    font_color="red",
    font_size=10
)

        pyplot.show()



def cycleProtocol(graph: DSSPGraph, h: int, secrets):
    # Assegna shares in grafo a ciclo
    # O(|secrets|)

    h = h - 1  # H parte da 1, ma i segreti sono indicizzati da 0.
    print("Valore h: " + str(h))

    print(secrets)
    sum = 0
    m = len(secrets)
    shares = [int] * len(secrets)
    for i in range(m):
        # parte da 0 per via dell'indicizzazione degli array su python
        print("Calcolo somma per il segreto " + str(i))
        sum = sum + secrets[i][h]
        # sum is now s1 + s2 + . . . + sm
    sharem = sum + secrets[m - 1][h]
    graph.shares[m][h] = [sharem]
    print("Inserito share in posizione: " + str(m))
    print(sharem)
    for i in range(m - 1, 0, -1):
        print("Inserisco share " + str(i))
        sharei = graph.shares[i + 1][h][0] + secrets[i - 1][h]
        print("Valore: " + str(sharei))
        graph.shares[i][h] = [sharei]
    print("Stampo lista degli share:\n" + str(shares))
    return shares

def altGenerateGraph(
        accessStructure, secrets: dict[tuple[int, int], list[int]], numSteps:int
): # Crea grafo a partire da Access Structure e secrets

    graph = DSSPGraph()
    for edge in accessStructure:
        i, j = edge
        graph.add_edge(i, j, secrets[(i,j)])
    graph.secrets = secrets
    for node in graph.nodes.items():
        graph.shares[node[0]] = [[] for _ in range(numSteps)]
    # print(graph)
    return graph

def cycleCheckWithDFS(
    node: DSSPNode,
    parent: DSSPNode,
    visited: set[int],
    nodesInCycle: dict[int, DSSPNode],
):
    # O(|V| + |E|)
    visited.add(node.value)
    for edge in node.edges:
        neighbor = edge.j if edge.i == node else edge.i
        if neighbor.value not in visited:
            nodesInCycle[neighbor.value] = node
            cycle = cycleCheckWithDFS(neighbor, node, visited, nodesInCycle)
            if cycle:
                return cycle
        elif neighbor.value != parent.value:
            # Individuato ciclo, va ripercorso
            cycle = set()
            cur = node
            cycle.add(neighbor.value)
            while cur.value != neighbor.value:
                cycle.add(cur.value)
                cur = nodesInCycle[cur.value]

            return cycle

    return None


def depthFirstSearch(node: DSSPNode, visited: set[int], component: set[int]):
    # O(|V| + |E|)
    visited.add(node.value)
    component.add(node.value)
    for edge in node.edges:
        neighbor = edge.j if edge.i == node else edge.i
        if neighbor.value not in visited:
            depthFirstSearch(neighbor, visited, component)


def getConnectedComponents(graph: DSSPGraph):
    # O(|V| + |E|)
    visited = set()
    components = []
    for node in graph.nodes.values():
        if node.value not in visited:
            component = set()
            depthFirstSearch(node, visited, component)
            subgraph = DSSPGraph()
            subgraph.secrets = {}
            subgraph.shares = {}
            # Ottimizzazione per evitare di visitare nuovamente archi
            visited_edges = set()
            for edge in graph.edges:
                if edge not in visited_edges:
                    if edge.i.value in component and edge.j.value in component:
                        subgraph.add_edge(edge.i.value, edge.j.value)
                        subgraph.secrets[edge.i.value, edge.j.value] = graph.secrets[edge.i.value, edge.j.value]
                        subgraph.shares[edge.i.value] = graph.shares[edge.i.value]
                        subgraph.shares[edge.j.value] = graph.shares[edge.j.value]
                    visited_edges.add(edge)
            

            #subgraph.secrets = graph.secrets
            #subgraph.shares = graph.shares

            components.append(subgraph)
    print("Stampo componenti")
    for component in components:
        print(component)

    return components


def getReducedGraphBasedOnLen(graph: DSSPGraph, h: int):
    # O(|E| * deg)
    edges_to_remove = []

    for edge in list(graph.edges):
        key = (edge.i.value, edge.j.value)
        #h - 1 siccome array parte da 0, h da 1

        if len(graph.secrets[key]) < h:
            edges_to_remove.append(edge)

    for edge in edges_to_remove:
        #print("EDGE DA RIMUOVERE: " + str(edge))
        graph.remove_edge(edge)

def runSubgraphProtocol(graph: DSSPGraph, step: int, Zq):
    # O(|V| + |E| + |secrets|)
    print("Entrato nel SubgraphShareDistributionProtocol")
    # Controlla l'esistenza di un ciclo
    cycle = cycleCheckWithDFS(graph.get_node(1), DSSPNode(-1), set(), {})
    """ Parte da root siccome grafo è connesso,
    valore di parent è -1 in quanto non la root non ha parent."""
    if cycle:
        graphZ = graph.getSubset(cycle)

        # Applica cycle protocol
        cycleProtocol(graphZ, step, list(graphZ.secrets.values()))
        # print(graphZ)

    else:
        print("Nessun ciclo trovato")
        # Applica caso else
        # O(m), però non c'è modo diverso di farlo.
        arbEdge = random.choice(list(graph.edges))
        if len(Zq) < 1:
            print("Errore, terminati valori usabili nel campo Zq.")
            exit()
        shareR = random.choice(Zq)
        Zq.remove(shareR)
        print("Valore r scelto a caso: " + str(shareR))
        graph.shares[arbEdge.i.value][step - 1] = [shareR]        
        graph.shares[arbEdge.j.value][step - 1] = [shareR + graph.secrets[(arbEdge.i.value, arbEdge.j.value)][step - 1]]
        # print("Assegnati share ai nodi di un edge casuale")
        graphZ = graph.getSubset(set([arbEdge.i.value, arbEdge.j.value]))
        # print(graphZ)

    existsEdgeInDisjunct = True
    while existsEdgeInDisjunct:
        existsEdgeInDisjunct = False
        for edge in graph.edges:
            if (
                edge not in graphZ.edges
                and edge.i in graphZ.nodes
                and edge.j not in graphZ.nodes
            ):
                #Assign the share dshi + xi,j to node j
                dshi = graph.shares[edge.i.value][step - 1][0]
                graphZ.add_edge(edge.i.value, edge.j.value)
                graph.shares[edge.j.value][step - 1] = [dshi + graph.secrets[(arbEdge.i.value, arbEdge.j.value)][step - 1]]
                existsEdgeInDisjunct = True
                print("DEBUG: edge case found")
                break

    print("Terminata iterazione del SubgraphShareDistributionProtocol")
    print("Grafo risultante: " + str(graphZ))
    #graphZ.visualize()


def DSSPSetVariables(
    m: int, n: int, q: int, secretsLengths: list, accessStructure: list[list]
):  # Imposta variabili per il grafo DSSP di tipo TDSC

    secrets = dict() #key è edge, value sono i secret associati
    Zq = list(range(1, q))

    clientCounter = 0
    for edge in accessStructure:
        """Genera un segreto casualmente ed indipendentemente per ogni utente,
        ed ottieni i suoi share."""
        secret = list()
        for _ in range(secretsLengths[clientCounter]):
            choice = random.choice(Zq)
            Zq.remove(choice)
            secret.append(choice)
        clientCounter = clientCounter + 1
        print(
            "Segreto generato casualmente per il client "
            + str(clientCounter)
            + ":"
            + str(secret)
        )
        secrets[tuple(edge)] = secret


    numSteps = max(secretsLengths)
    graph = altGenerateGraph(accessStructure, secrets, numSteps)
    userShares = {}

    return graph, userShares, secrets, Zq

def DSSP():

    m = int(input("Inserisci il numero di utenti\n"))
    while m <= 0:
        m = int(
            input(
                "Errore, il numero di utenti non può essere minore o uguale a"
                " 0. Reinserirlo.\n"
            )
        )
    secretsLengths = list()
    sumOfSecretsLengths = 0
    accessStructure = []
    for secretNumber in range(m):
        accessStructure.append(list(map(int, input("Inserire i numeri dei nodi che costituiscono l'arco numero " + str(secretNumber + 1) + ", separati da uno spazio\n").split())))
        secretLen = int(
            input("Inserisci lunghezza del segreto " + str(secretNumber + 1) + "\n")
        )
        while secretLen <= 0:
            secretLen = int(
                input(
                    "Errore: lunghezza del segreto deve essere maggiore di"
                    " 0. Reinserirla.\n"
                )
            )
        secretsLengths.append(secretLen)
        sumOfSecretsLengths += secretLen
    n = int(input("Inserisci il numero di dischi\n"))
    q = int(input("Inserisci il valore di q per il campo Zq\n"))
    qValid = False
    while not qValid:
        if q >= 3 or q % 2 != 0:
            if q > sumOfSecretsLengths:
                qValid = True
            else:
                q = int(
                    input(
                        "Errore: lo spazio Zq non è abbastanza grande per la"
                        "selezione dei segreti in base alle lunghezze "
                        "impostate degli stessi. Reinserire q.\n"
                    )
                )
        else:
            q = int(input("Errore: q <= 3 e/o pari. Reinserire q.\n"))

    graph, userShares, secrets, Zq = DSSPSetVariables(m, n, q, secretsLengths, accessStructure)

    print("Segreti: " + str(secrets))

    # print(graph)

    # Step 0
    graph.initializeLeaves()
    graph.visualize(0, "Leaves initialized")
    # print(graph)
    # Ottiene G'
    graph.reduce()
    lMax = graph.calculateLMax()
    print("Calcolata lMax: " + str(lMax))

    for h in range(lMax):  # H parte da 0, ma così si comporta come se fosse 1.
        print("Stampo il valore di h corrente: " + str(h + 1))
        getReducedGraphBasedOnLen(graph, h + 1)
        print("Grafo ridotto: " + str(graph))
        graph.visualize(h, "Reduced Graph")
        connectedComponents = getConnectedComponents(graph)
        subtitleCounter = 1 # Usato per aggiungere contesto della componente connessa al grafo
        for j in connectedComponents:
            print("Subgraph generato: " + str(j))
            j.visualize(h, "Connected Component # " + str(subtitleCounter))
            runSubgraphProtocol(j, h + 1, Zq)  
            j.visualize(h, "Connected Component # " + str(subtitleCounter) + " - After Subgraph Protocol")
            subtitleCounter += 1


    print("Terminata elaborazione del grafo secondo DSSP.")
    #print("DEBUG: Grafo finale: ")
    print("Segreti allocati: \n" + str(graph.secrets))
    print("Share allocati: \n" + str(graph.shares))


def checkCorrectInput(m: int, secretLengths: list[int], n: int, q: int):
    if m <= 0:
        print("Errore, il numero di utenti non può essere <= di 0.")
        return 1
    sumOfSecretsLengths = 0
    for length in secretLengths:

        if length <= 0:
            print(
                "Errore, il segreto numero: "
                + str(length + 1)
                + "ha lunghezza >= di 0."
            )
            return 2
        sumOfSecretsLengths += length
    if n <= 0:
        print("Errore, il numero di dischi non può essere <= di 0.")
        return 3
    if q >= 3 or q % 2 != 0:
        if q <= sumOfSecretsLengths:
            print(
                "Errore: lo spazio Zq non è abbastanza grande per la"
                "selezione dei segreti in base alle lunghezze "
                "impostate degli stessi."
            )
            return 4
        return 0 
        #Input corretti
    else:
        print("Errore: q <= 3 e/o pari.")
        return 5

def DSSPTestable(m: int, secretsLengths: list[int], n: int, q: int, accessStructure: list[list]):
    checkValue = checkCorrectInput(m, secretsLengths, n, q)
    if checkValue != 0:
        return checkValue
    graph, userShares, secrets, Zq = DSSPSetVariables(m, n, q, secretsLengths, accessStructure)

    # print(graph)

    # Step 0
    graph.initializeLeaves
    # print(graph)
    # Ottiene G'
    graph.reduce()
    lMax = graph.calculateLMax()
    print("Calcolata lMax: " + str(lMax))

    for h in range(lMax):  # H parte da 0, ma così si comporta come se fosse 1.
        print("Stampo il valore di h corrente: " + str(h + 1))
        getReducedGraphBasedOnLen(graph, h + 1)
        print("Grafo ridotto: " + str(graph))
        connectedComponents = getConnectedComponents(graph)
        for j in connectedComponents:
            print("Subgraph generato: " + str(j))
            runSubgraphProtocol(
                j, h + 1, Zq
            )

    return 0


def main():
    DSSP()


if __name__ == "__main__":
    """Invoca la funzione main quando il programma
    viene invocato da riga di comando."""
    main()
