import numpy as np
import random
import random
from ete3 import Tree
import numpy as np
import sys 


#------------------------------------------------------
def pathToRoot(nodeName, tree):
	D = tree&nodeName
	# Get the path from B to the root
	node = D
	path = []
	while node.up:
		nn = node.name
		if node.name == '' or node.name.isdigit():
			nn = 'none'
		path.append(nn)
		node = node.up
	if path and path[len(path)-1] == 'none':
		path[len(path)-1] = 'germline'
	return path
#------------------------------------------------------
def readNKTree(fileName, root=False):
	with open(fileName, 'r') as file:
		data = file.read().replace('\n', '')
	file.close()
	tree = Tree(str(data),  format=1)
	if root:
		rootedTree = Tree()
		A = rootedTree.add_child(name="germline")
		A.add_child(tree)
		return rootedTree
	return tree
#------------------------------------------------------
def costTree(tree):
	ctotal = 0
	for node in tree.traverse("preorder"):
		parent = node.up
		if parent:
			print (node.name, parent.name, node.get_distance(parent))
			ctotal = ctotal + node.dist
	return ctotal

#------------------------------------------------------
def costTree3(tree, labels, adjMatrix):
	ctotal = 0; count = 0
	for node in tree.traverse("preorder"):

		parent = node.up
		if parent:
			path = pathToRoot(node.name, tree)
			if path:
				i = 1; #print(path)
				pn = path[len(path)-1]
				while (i< len(path)):
					if path[i] in labels:
						pn = path[i]
						i = len(path)
					i+=1									

				if pn in labels and node.name in labels:
					cost = adjMatrix[labels.index(node.name)][labels.index(pn)]
					#print (node.name, pn, cost)
					ctotal = ctotal + cost
					count +=1
				#else:
				#	print (pn, node.name)
	if count != len(labels):
		print ('ERROR missing nodes', count,  len(labels))
	return ctotal
#------------------------------------------------------
def costTree2(tree, labels, adjMatrix):
	ctotal = 0; count = 0
	for node in tree.traverse("preorder"):
		parent = node.up
		if parent:
			print ('parentNode=' ,parent.name, 'node=', node.name); 
			print(pathToRoot(node.name, tree))
			pn = parent.name
			if pn == '':
				pn = 'germline'
			n = parent
			while pn not in labels:
				print ('pn=', pn)
				n = n.up
				pn = n.name
			
			if pn in labels and node.name in labels:
				cost = adjMatrix[labels.index(node.name)][labels.index(pn)]
				print (node.name, pn, cost)
				ctotal = ctotal + cost
				count +=1
			else:
				print (pn, node.name)
	print ('Nb nodes', count)
	return ctotal

#===================================================================================
def getCommonAncestorPath(tree, node):
	path = pathToRoot(node, tree)
	#print (path)
	return path[1]

#===================================================================================
def getCommonAncestorPaths(pathA, pathB):
	for i in pathA:
		if i !='none' and i in pathB:
			return i
	return 'germline'

#===================================================================================
def findCommonAncestorLeaves(tree, labels):
	coupleNodes = {}
	for i in range(len(labels)):	  
		for j in range(i+1, len(labels)):
			#print (labels[i], labels[j])
			pathi = pathToRoot(labels[i], tree)
			pathj = pathToRoot(labels[j], tree)
			#print (pathi);	print (pathj)
			if 	labels[i] in pathj:
				ancestor = labels[i]
			elif labels[j] in pathi:
				ancestor = labels[j]
			else:
				ancestor = getCommonAncestorPaths(pathi, pathj)
			#print (labels[i]+ '-'+ labels[j], ancestor)
			coupleNodes[labels[i]+ '-'+ labels[j]] = ancestor
	return coupleNodes


#===================================================================================
def findCommonAncestorLeavesOLD(tree, labels):
	coupleNodes = {}
	for i in range(len(labels)):	  
		for j in range(i+1, len(labels)):
			print (labels[i], labels[j])
			ancestor = tree.get_common_ancestor(labels[i], labels[j])
			aname = ancestor.name
			if aname == '':
				aname = 'germline'
			#fazer um methodo pra retornar o pai comun comparando os paths
			while aname not in labels:
				aa = getCommonAncestorPath(tree, aname)
				aname = aa; print ("entrou", aname)
			coupleNodes[labels[i]+ '-'+ labels[j]] = aname
	return coupleNodes

#===================================================================================
def checkConsistence(tree, labels):
	seen = {}
	for node in tree.traverse("preorder"):
		if node.name not in seen.keys():
			if node.name in labels:
				seen[node.name] = True
			elif node.name != '':
				print ("ERROR ", node.name, " not in labels")
		else:
			print ("ERROR ", node.name, " several times")
	print (len(seen),len(labels))
	return len(seen)==len(labels)

