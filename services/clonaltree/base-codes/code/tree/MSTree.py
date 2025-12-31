import numpy as np
import random
import math
from operator import xor
from ete3 import Tree
import numpy as np
import sys 

INF = float('inf') 

# Find set of vertex i or Find i parent
def find(i, parent): 
	while parent[i] != i: 
		i = parent[i] 
	return i 

# Does union of i and j. It returns 
# false if i and j are already in same 
# set. 
def union(i, j, parent): 
	a = find(i, parent) 
	b = find(j, parent) 
	parent[a] = b
	return parent


# Finds MST using Kruskal's algorithm 
def kruskalMST(cost, root, labels): 
	INF = float('inf'); error = 0
	mincost = 0 # Cost of min MST 
	V = len(cost)
	MST = np.zeros((V, V))
	# Initialize sets of disjoint sets 
	parent = [i for i in range(V)] 
	for i in range(V): 
		parent[i] = i
	
	# Include minimum weight edges one by one 
	edge_count = 0
	tree = Tree()
	tree.add_child(name=labels[root])
	includeAfter = []
	#Debug to be removed
	#for j in range(len(cost)):
	#	print(cost[0][j])
	#sys.exit()

	while edge_count < V - 1: 
		min = INF 
		a = -1
		b = -1
		#Find the pair of vertex with minimum cost		
		for i in range(V): 
			for j in range(V): 
				if find(i, parent) != find(j, parent) and cost[i][j] < min:
					#print(i, j, cost[i][j])					
					min = cost[i][j] 
					a = i 
					b = j 
		parent = union(a, b, parent) 
		#print('Edge {}:({}, {}) cost:{}'.format(edge_count, labels[a], labels[b], min)) 
		tree, tp = addNodeTree(tree, labels[a], labels[b], min)
		#print (tree)#Debug to be removed
		if tp:
			includeAfter.append(tp); error +=1
		edge_count += 1
		mincost += min
   
	#print("Minimum cost= {}".format(mincost)) 
	#ToDo: Tem que ser while, enquanto tiver nodes para incluir, e remover da lista
	if includeAfter:
		while len(includeAfter) > 0:
			for ia in includeAfter:
				#print (ia)
				a, b, cs = ia
				tree, tp = addNodeTree(tree, a, b, cs)
				if len(tp) == 0:
					error -= 1
					includeAfter.remove(ia)
				
				
	if error == 0:
		print ('ok, no warnning')
	else:
		print ('ERROR, nodes not included')
	return tree


def editTree(t1, adjMatrix, labels):
	tr = Tree()
	ardColapsed = []
	for node in t1.traverse("preorder"):
		if node.is_root():
			#print ('1')
			children = node.get_children()
			for n in children:
				tr.add_child(name=n.name)
				#print ('2', n.name)
		else:
			G = tr.search_nodes(name=node.name)
			if (G):
				children = node.get_children()
				for n in children:
					#print ('3', n.name)
					if n.name not in ardColapsed:
						colapse = colapseNodes(n.name, children, node.name, adjMatrix, labels, ardColapsed)
						#print ('==', colapse)
						if colapse:
							N = G[0].add_child(name=None) # Adds a empty branch or bifurcation
							n1 = N.add_child(name=n.name) # Adds current node
							ardColapsed.append(n.name)
							
							for c in colapse:
								#print ('col ', c)
								n2 = N.add_child(name=c)
								ardColapsed.append(c) # Adds other nodes
								#print(tr.get_ascii(show_internal=True))
						else:
							G[0].add_child(name=n.name)
	return tr
	


def colapseNodes(node, lnodes, parent, cost, labels, aldColapsed):
	colapse = []
	#print ('---> ', node, lnodes, parent, labels)
	idNode = labels.index(node); idPar = labels.index(parent)
	for i in lnodes:
		idI = labels.index(i.name)
		#print ('nodes ', node, i.name)
		if i.name != node and cost[idNode][idI] <= cost[idNode][idPar] and cost[idNode][idI] <= cost[idI][idPar]:
			#print ('cost ',node, i.name, cost[idNode][idI]);print ('cost P ',node, parent, cost[idNode][idPar])
			if i.name not in aldColapsed:
				colapse.append(i.name)
	return colapse

def addNodeTree(t, a, b, min, infoCost):

	tp = ()
	G = t.search_nodes(name=a)
	
	if (G):
		G[0].add_child(name=b, dist=min) 
		infoCost += a + "\t" + b + "\t" + str(min) + "\n"
	else:
		G = t.search_nodes(name=b)
		if (G):
			G[0].add_child(name=a, dist=min)
			infoCost += a + "\t" + b + "\t" + str(min) + "\n"
		else:
			print ("Warnning nodes do not exists: ", a, b)
	return t, infoCost

def takeRandomNode(included, labels,  D):
	#print ("LEN INC", len(included))
	random.seed(30)
	i = random.randint(0, D-1)
	while (labels[i] in included):
		i = random.randint(0, D-1)
	return i


def chooseBestNode(minsI, minsJ, visitedNodes, adjMatrix, labels, abundance):

	maxAb = -INF; nodeA = 0; nodeB = 0
	#print ('len(mins)', len(minsI))
	for i in range(len(minsI)):
		a = minsI[i]; b = minsJ[i];
		#print ('mins ', a, b, labels[a], labels[b])
		if (labels[a]!=labels[b]) and (xor(a in visitedNodes, b in visitedNodes)):
			#print (labels[a], labels[b], adjMatrix[a][b])
			ab = abundance[labels[a]] + abundance[labels[b]]
			#print (labels[a], abundance[labels[a]], labels[b], abundance[labels[b]])
			if  ab > maxAb:
				maxAb = ab
				nodeA = a
				nodeB = b
	if nodeA==0 and nodeB ==0:
		print ("ERROR: Disconnected Tree", len(visitedNodes))
		sys.exit()
	return nodeA, nodeB


def aminIndex(matrix, indices):
	minV = INF
	mins = []; minI = []; minJ = []
	#Find the minimal value in the matrix constrainted by indices
	for i in indices:
		m = np.amin(matrix[i]) #take the min value
		if m < minV:
			minV = m
	#print ('MinV', minV)
	#Find the j indices with minimal value
	for i in indices:
		for j in range(len(matrix[i])):
			if matrix[i][j] == minV:
				minI.append(i)
				minJ.append(j)
	return minI, minJ

def aminIndexFirstFound(matrix, indices):
	minV = INF
	mins = []; minI = []; minJ = []
	#Find the minimal value in the matrix constrainted by indices
	for i in indices:
		m = np.amin(matrix[i]) #take the min value
		j = np.argmin(matrix[i]) #take the index of the min value
		if m < minV:
			minV = m
			minJ = j
			minI = i
	return [minI], [minJ]


def correctMatrix(adjMatrixNP, visitedNodes):
   
	for i in range(len(adjMatrixNP)):
		for j in range(i, len(adjMatrixNP[i])):
			#print (' i, j ', i,j)
			if i in visitedNodes and j in visitedNodes:
				adjMatrixNP[i][j] = INF; adjMatrixNP[j][i] = INF
	return adjMatrixNP


def kruskalMST(cost, root, labels, abundance, useAb=True): 
	infoTree = ""
	tree = Tree()
	tree.add_child(name=labels[root])
	adjMatrixNP = np.array(cost); np.fill_diagonal(adjMatrixNP, INF)
	visitedNodes = [root]
	it = 0
	while len(visitedNodes) < len(labels):
		if useAb:
			minsI, minsJ =  aminIndex(adjMatrixNP, visitedNodes)
		else:
			minsI, minsJ =  aminIndexFirstFound(adjMatrixNP, visitedNodes)
		#print (adjMatrixNP); print (minsI); print (minsJ)
		nodeA, nodeB = chooseBestNode(minsI, minsJ, visitedNodes, adjMatrixNP, labels, abundance)
		minV = adjMatrixNP[nodeA][nodeB]
		adjMatrixNP[nodeA][nodeB] = INF; adjMatrixNP[nodeB][nodeA] = INF
		#print ('==>', labels[nodeA], labels[nodeB], adjMatrixNP[nodeB][nodeA])
		#print (adjMatrixNP)
		tree, infoTree = addNodeTree(tree, labels[nodeA], labels[nodeB], minV, infoTree)
		if nodeA not in visitedNodes:
			visitedNodes.append(nodeA)
		if nodeB not in visitedNodes:
			visitedNodes.append(nodeB)
		#print (nodeA, nodeB)
		#print (tree.get_ascii(show_internal=True))
		#if it == 100:
		#	print (tree.get_ascii(show_internal=True))
		#	print (len(visitedNodes))
		#	sys.exit()
		it +=1
		#print ('it ', it)
		adjMatrixNP = correctMatrix(adjMatrixNP, visitedNodes)
	#print (adjMatrixNP)
	return tree, infoTree


