"""
Intraclonal Alignment and Root/Naive Sequence Selection
========================================================

This module performs two main functions:
1. Selects the root/naive/germline sequence for each clone
2. Aligns clonotypes within each clone to the root sequence

ROOT/NAIVE SELECTION (CURRENT IMPLEMENTATION):
-----------------------------------------------
The root sequence is currently defined as:
- The most abundant clonotype within a clone
- If multiple clonotypes have same abundance, first one is selected

The root selection happens in read_seq_info() function (line 36-46):
    major_clonotype = sorted(..., key=lambda k: len(clonotype_seq[k]), reverse=True)[0]

MODIFICATION GUIDE:
-------------------
To change root selection method, modify:
1. CONFIG.py → ROOT_SELECTION_METHOD
2. read_seq_info() function (line 24-46):
   - For 'highest_v_identity': Sort by V gene identity instead of abundance
   - For 'lowest_mutation_count': Count mutations from germline
   - For 'closest_to_germline': Calculate distance to IMGT germline

ALTERNATIVE ROOT SELECTION METHODS:
-----------------------------------
1. Highest V gene identity:
   - Sort by airr_dico[seq]['v_identity'] or similar field
   
2. Lowest mutation count:
   - Count differences from germline sequence
   
3. Closest to germline:
   - Calculate Hamming/Levenshtein distance to IMGT germline

KEY FUNCTIONS:
--------------
- read_AIRR(): Reads AIRR format annotation file
- read_seq_info(): Selects root sequence and clonotypes to analyze
- compare_clonotype_to_germline(): Aligns clonotypes to root
- write_clonotype_align(): Writes alignment output
- write_clonaltree_align(): Writes sequences for tree construction

INPUT:
------
- AIRR_IMGT_annotation_output: AIRR format file with full sequence info
- final_seq_info: Total sequence info with clone/clonotype assignments
- number_of_clonotype_to_analyze: 'all' or number (N most abundant)

OUTPUT:
-------
- {repertoire_name}_align.txt: Aligned clonotypes (V-CDR3-J format)
- {repertoire_name}_clonaltree.txt: Sequences in FASTA format for tree building
"""
import sys
from optparse import OptionParser
import operator
import collections

#####################################################################
def read_file (nomFi):
	f=open(nomFi,"r")
	lines=f.readlines()
	f.close()
	return lines
#####################################################################
def read_AIRR(lines):
	germline_seq,airr_dico = {},{}
	for l in lines:
		seq = l.split("\t")
		airr_dico[seq[0]] = {'sequence_alignment': seq[12],'np2' : seq[20] ,'v_sequence_alignment' : seq[84], 'np1' : seq[18], 'd_sequence_alignment':seq[86] ,'j_sequence_alignment' :seq[88], 'v_alignment_start' : seq[56] ,'v_alignment_end' :seq[57], 'd_alignment_start':seq[62],'d_alignment_end':seq[63],'j_alignment_start' :seq[68],'j_alignment_end':seq[69],'cdr3_start':seq[74], 'cdr3_end':seq[75],'germline_seq':seq[92]+seq[18]+seq[94]+seq[20]+seq[96] }
		#germline_seq[seq id] = v_germline_alignment + np1 + d_germline_alignment + np2 + j_germline_alignment
		germline_seq[seq[0]] = seq[92]+seq[18]+seq[94]+seq[20]+seq[96]
	#print(airr_dico['S14768'])
	return airr_dico


def read_seq_info(lines,airr_dico,nb_clonotype):
#the seq of each clonotypes
#the most abundant seq ===> germline 
	clonotype_seq = {}
	list_selected_clonotype = []
	for l in lines:
		#print (l)
		seq = l.split("\t")
		clonotype = seq[0].split("_")[1]
		if clonotype in clonotype_seq.keys():
			clonotype_seq[clonotype].append(seq[1])
		else: 
			clonotype_seq[clonotype] = [seq[1]]
	#the most abundant clonotype ===> germline 
	major_clonotype = (sorted(clonotype_seq, key=lambda k: len(clonotype_seq[k]), reverse=True)[0])
	germline = [airr_dico[clonotype_seq[major_clonotype][0]]['germline_seq'],airr_dico[clonotype_seq[major_clonotype][0]]['cdr3_start'],airr_dico[clonotype_seq[major_clonotype][0]]['cdr3_end']]
	if nb_clonotype == 'all':
		list_selected_clonotype = list((sorted(clonotype_seq, key=lambda k: len(clonotype_seq[k]), reverse=True)))
	else :
		list_selected_clonotype = list((sorted(clonotype_seq, key=lambda k: len(clonotype_seq[k]), reverse=True)[0:int(nb_clonotype)]))
	#print(airr_dico[clonotype_seq[major_clonotype][0]]['germline_seq'])
	#print (clonotype_seq)
	return clonotype_seq,germline,list_selected_clonotype

def compare_clonotype_to_germline(airr_dico,clonotype_seq,germline,list_selected_clonotype):
	clonotype_align = {}
	for key in list_selected_clonotype:
		representative_seq_id =clonotype_seq[key][0]
		seq = airr_dico[representative_seq_id]['sequence_alignment']
		#print (len(seq),seq,len(germline[0]),germline[0])
		aligned_seq = ''
		if len(seq) == len(germline[0]):
			for nt in range(len(germline[0])):
				if germline[0][nt] == seq[nt]:
					aligned_seq+='-'
				else :
					aligned_seq+= seq[nt]
		
			"""
			for nt in range(len(seq[0])):
				if germline[0][nt] == seq[nt]:
					aligned_seq+='-'
				else :
					aligned_seq+= seq[nt]
			"""
		#V,np1,d,np2,J,CDR3
			V = aligned_seq[int(airr_dico[representative_seq_id]['v_alignment_start'])-1:int(airr_dico[representative_seq_id]['v_alignment_end'])-1]
			np1 = airr_dico[representative_seq_id]['np1']
			np2 = airr_dico[representative_seq_id]['np2']
			cdr3_start = int(airr_dico[representative_seq_id]['cdr3_start'])
			cdr3_end = int(airr_dico[representative_seq_id]['cdr3_end'])
			if airr_dico[representative_seq_id]['d_alignment_start']!= '' and airr_dico[representative_seq_id]['d_alignment_end'] != '':
				D = aligned_seq[int(airr_dico[representative_seq_id]['d_alignment_start'])-1:int(airr_dico[representative_seq_id]['d_alignment_end'])-1]

				J = aligned_seq[int(airr_dico[representative_seq_id]['j_alignment_start'])-1:int(airr_dico[representative_seq_id]['j_alignment_end'])-1]
				whole_seq = V+np1+D+np2+J
				#print (whole_seq)
				#print(whole_seq[0:cdr3_start],whole_seq[cdr3_start:cdr3_end],whole_seq[cdr3_end:-1])
				#clonotype_align[key] = [V,np1,D,np2,J,cdr3_start,cdr3_end]
				clonotype_align[key] =[whole_seq[0:cdr3_start],whole_seq[cdr3_start:cdr3_end],whole_seq[cdr3_end:-1]]
		else:
			print ("here",key,"seq",len(seq),"Ger",len(germline[0]))
	return clonotype_align

def write_clonotype_align(clonotype_align,repertoire_name,germline):
	file_name = repertoire_name+"_align.txt"
	filetowrite=open(file_name,"w")
	#print (int(germline[1]))
	G = "germline"+ "\t" +germline[0][0:int(germline[1])]+"\t"+  germline[0][int(germline[1]):int(germline[2])] + "\t" + germline[0][int(germline[2]):-1]+ "\n"
	filetowrite.write(G)
	for clonotype in clonotype_align.keys():
		#clonotype_info = str(clonotype) + "\t" + str(clonotype_align[clonotype][0]) + "\t" +str(clonotype_align[clonotype][1]) + "\t" + str(clonotype_align[clonotype][2]) + "\t" + str(clonotype_align[clonotype][3]) +"\t" +str(clonotype_align[clonotype][4])+"\t" +str(clonotype_align[clonotype][5])+"\t" +str(clonotype_align[clonotype][6])+ "\n"
		clonotype_info = str(clonotype) + "\t" + str(clonotype_align[clonotype][0]) + "\t" +str(clonotype_align[clonotype][1]) + "\t" + str(clonotype_align[clonotype][2])+ "\n"
		filetowrite.write(clonotype_info)
	filetowrite.close()
	return 0
def write_clonaltree_align(clonotype_align,clonotype_seq,airr_dico,repertoire_name,germline):
	#print (clonotype_align)
	file_name = repertoire_name+"_clonaltree.txt"
	filetowrite=open(file_name,"w")
	#print (int(germline[1]))
	G = ">germline"+ "\n" +germline[0][0:int(germline[1])]+  germline[0][int(germline[1]):int(germline[2])] + germline[0][int(germline[2]):-1]+ "\n"
	filetowrite.write(G)
	for clonotype in clonotype_align.keys():
		#clonotype_info = str(clonotype) + "\t" + str(clonotype_align[clonotype][0]) + "\t" +str(clonotype_align[clonotype][1]) + "\t" + str(clonotype_align[clonotype][2]) + "\t" + str(clonotype_align[clonotype][3]) +"\t" +str(clonotype_align[clonotype][4])+"\t" +str(clonotype_align[clonotype][5])+"\t" +str(clonotype_align[clonotype][6])+ "\n"
		clonotype_info = ">"+str(clonotype) + "\n" + airr_dico[clonotype_seq[clonotype][0]]['sequence_alignment']+ "\n"
		filetowrite.write(clonotype_info)
	filetowrite.close()
	return 0
#####################################################################
def main():
	usage = "usage: alignment_intraconal.py -a AIRR_IMGT_annotation_output -f final_seq_info -n repertoire_name -s number_of_clonotype_to_analyze"
	parser = OptionParser(usage)
	parser.add_option("-a", "--AIRR_IMGT_annotation_output", dest="IMGT_seq_info",
	      help="read data from AIRR_IMGT_annotation_output")
	parser.add_option("-f", "--final_seq_info",dest="final_seq_info",
	      help="read data from final_seq_info")
	parser.add_option("-n", "--repertoire_name",dest="repertoire_name",
	      help="repertoire_name")
	parser.add_option("-s", "--number_of_clonotype_to_analyze",dest="number_of_clonotype_to_analyze",
	      help="the number of clonotype to analyze, if use all, there will be no selection for the analyzing clonotypes otherwise choose the number of n most abondant clonotype ")
	(options, args) = parser.parse_args()
	if len(sys.argv) != 9:
		parser.error("incorrect number of arguments")
	
	IMGT_seq_info = options.IMGT_seq_info
	final_seq_info = options.final_seq_info
	repertoire_name = options.repertoire_name
	nb_clonotype =  options.number_of_clonotype_to_analyze

	lines_airr = read_file (IMGT_seq_info)
	airr_dico = read_AIRR(lines_airr)
	lines_clonotype_seq = read_file (final_seq_info)
	clonotype_seq,germline,list_selected_clonotype = read_seq_info(lines_clonotype_seq,airr_dico,nb_clonotype)

	
	clonotype_align = compare_clonotype_to_germline(airr_dico,clonotype_seq,germline,list_selected_clonotype)

	write_clonotype_align(clonotype_align,repertoire_name,germline)
	write_clonaltree_align(clonotype_align,clonotype_seq,airr_dico,repertoire_name,germline)

#####################################################################
if __name__ == "__main__":
	main()