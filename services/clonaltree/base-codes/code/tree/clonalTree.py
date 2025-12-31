
import numpy as np
from optparse import OptionParser
from scipy.spatial import distance
from MSTree import *
from BasicTree import *
from BasicSeq import *
import sys 




#Read fasta file, detect repeated sequences and germline
'''def readFasta(fastaFile):
	dico = {}
	germline = ""

	for record in SeqIO.parse(fastaFile, "fasta"):
		sequence = str(record.seq)
		if record.id == "germline":
			germline = sequence
		if sequence in dico.keys(): 
			dico[sequence] = dico[sequence] + 1
		else:
			dico[sequence] = 1
	return dico, germline

#Create array of colapsed sequences, detect root tree and generate array of sequence labels
def colapseSequences(dico, germline):
	count = 1
	root  = 0

	labels = [];  arraySeqs = [];
	
	for key in dico.keys():
		labels.append("Seq" + str(count) + "-" + str(dico[key]))
		if key == germline:
			root = count - 1
		arraySeqs.append(key)
		count = count + 1
	return labels, root, arraySeqs
'''

def makeBoolean(var):
	if var == '0':
		return True
	else:
		return False



#===================================================================================
#						Main
#===================================================================================
def main():
	usage = usage = "python clonalTree.py -i <fastaFile> -r <revision> -o <outputFile> \n"
	parser = OptionParser(usage)
	parser.add_option("-i", "--fastaFile", dest="fastaFile",  help="sequences in fasta format")
	parser.add_option("-o", "--outputFile", dest="outputFile",  help="output file")
	parser.add_option("-a", "--useAbundance", dest="useAbundance",  help="if 0 we use abundance")
	parser.add_option("-r", "--revision", dest="revision",  help="if 0 we perform revision")
	
	(options, args) = parser.parse_args()
	if len(sys.argv) < 5:
		parser.error("incorrect number of arguments")
	
	fastaFile = options.fastaFile
	outputFile = options.outputFile
	useAbundance = options.useAbundance
	revision = options.revision

	useAbundance = makeBoolean(useAbundance)
	revision = makeBoolean(revision)

	#dico, germline = readFasta(fastaFile)
	labels, root, arraySeqs, abundance =  readFastaAbundance(fastaFile)
	#print (labels)
	
	adjMatrix = createAdjMatrix(arraySeqs)

	#print(adjMatrix)
	#sys.exit()
	tree, infoTree = kruskalMST(adjMatrix, root, labels, abundance, useAbundance)
	#print (infoTree)
	
	if revision:
		tree = editTree(tree, adjMatrix, labels)
	if checkConsistence(tree, labels):
		tree.write(format=1, outfile=outputFile)
		f = open(outputFile +'.csv', 'w')
		f.write(infoTree); f.close()
		#print (tree.get_ascii(show_internal=True)) 
		#print (costTree3(tree, labels, adjMatrix))
		print ('done')
	else:
		print ('KO')
	

#===================================================================================
if __name__ == "__main__":
	main()

