import numpy as np
import random
import sys 
from Bio import SeqIO


#---------------------------------------------------------------------------
def readFastaAbundance(fastaFile):
	dico = {}
	germline = ""; SEP="@"
	labels = [];  arraySeqs = []; Abundance = {}
	count = 0; root  = 0

	for record in SeqIO.parse(fastaFile, "fasta"):
		#print (record.id)
		if SEP in record.id:
			ID = record.id.split(SEP)[0]
			abund = int(record.id.split(SEP)[1])
		else:
			ID = record.id
			abund = 1
		#print ("ID=", ID, "ab=", abund)
		if ID not in dico.keys(): 
			dico[ID] = str(record.seq)
			labels.append(ID)
			arraySeqs.append(str(record.seq))
			if ID == 'germline':
				root = count
			count = count + 1
		if ID in Abundance.keys():
			Abundance[ID] += abund
		else:
			Abundance[ID] = abund
		
	return labels, root, arraySeqs, Abundance
#---------------------------------------------------------------------------
def readFasta(fastaFile):
	dico = {}
	germline = ""
	labels = [];  arraySeqs = [];
	count = 0; root  = 0

	for record in SeqIO.parse(fastaFile, "fasta"):
		if record.id not in dico.keys(): 
			dico[record.id] = str(record.seq)
			labels.append(record.id)
			arraySeqs.append(str(record.seq))
			if record.id == 'germline':
				root = count
			count = count + 1
		
	return labels, root, arraySeqs

#---------------------------------------------------------------------------
def readFasta2(fastaFile):
	dico = {}
	germline = ""
	labels = [];  arraySeqs = [];
	count = 1; root  = 0

	for record in SeqIO.parse(fastaFile, "fasta"):
		if record.id not in dico.keys(): 
			dico[record.id] = str(record.seq)
			labels.append(record.id)
			arraySeqs.append(str(record.seq))
			count = count + 1
		
	return labels, dico

#---------------------------------------------------------------------------
def hamming_distance(chaine1, chaine2):
	return sum(c1 != c2 for c1, c2 in zip(chaine1, chaine2))

#---------------------------------------------------------------------------
#create adjacent matrix from colpased sequences by using hamming distance
def createAdjMatrix(arraySeqs):
	adjMatrix = np.zeros((len(arraySeqs), len(arraySeqs)))

	for i in range(len(arraySeqs)):
		#for j in range(i+1, len(arraySeqs)):
		for j in range(0, len(arraySeqs)):
			adjMatrix[i][j] = hamming_distance(arraySeqs[i], arraySeqs[j])
	return adjMatrix



