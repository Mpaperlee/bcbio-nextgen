"""
run the pizzly fusion caller for RNA-seq
https://github.com/pmelsted/pizzly
http://www.biorxiv.org/content/early/2017/07/20/166322
"""
from __future__ import print_function

import os

from bcbio import utils
import bcbio.pipeline.datadict as dd
from bcbio.pipeline import config_utils
from bcbio.distributed.transaction import file_transaction
from bcbio.rnaseq import kallisto, sailfish, gtf
from bcbio.provenance import do
from bcbio.utils import file_exists, safe_makedir

h5py = utils.LazyImport("h5py")
import numpy as np

def get_fragment_length(data):
    """
    lifted from
    https://github.com/pmelsted/pizzly/scripts/pizzly_get_fragment_length.py
    """
    h5 = kallisto.get_kallisto_h5(data)
    cutoff = 0.95
    with h5py.File(h5) as f:
        x = np.asarray(f['aux']['fld'], dtype='float64')
    y = np.cumsum(x)/np.sum(x)
    fraglen = np.argmax(y > cutoff)
    return(fraglen)

def run_pizzly(data):
    work_dir = dd.get_work_dir(data)
    pizzlydir = os.path.join(work_dir, "pizzly")
    samplename = dd.get_sample_name(data)
    gtf = dd.get_gtf_file(data)
    if dd.get_transcriptome_fasta(data):
        gtf_fa = dd.get_transcriptome_fasta(data)
    else:
        gtf_fa = sailfish.create_combined_fasta(data)
    fraglength = get_fragment_length(data)
    cachefile = os.path.join(pizzlydir, "pizzly.cache")
    fusions = kallisto.get_kallisto_fusions(data)
    pizzlypath = config_utils.get_program("pizzly", dd.get_config(data))
    outdir = pizzly(pizzlypath, gtf, gtf_fa, fraglength, cachefile, pizzlydir,
                    fusions, samplename)
    return outdir

def pizzly(pizzly_path, gtf, gtf_fa, fraglength, cachefile, pizzlydir, fusions,
           samplename):
    outdir = os.path.join(pizzlydir, samplename)
    pizzly_gtf = make_pizzly_gtf(gtf, os.path.join(pizzlydir, "pizzly.gtf"))
    with file_transaction(outdir) as tx_out_dir:
        safe_makedir(tx_out_dir)
        out_stem = os.path.join(tx_out_dir, "pizzly")
        cmd = ("{pizzly_path} -k 31 --gtf {pizzly_gtf} --cache {cachefile} "
            "--align-score 2 --insert-size {fraglength} --fasta {gtf_fa} "
            "--output {out_stem} {fusions}")
        message = ("Running pizzly on %s." % fusions)
        do.run(cmd.format(**locals()), message)
    return outdir

def make_pizzly_gtf(gtf_file, out_file):
    """
    pizzly needs the GTF to be in gene -> transcript -> exon order for each
    gene. it also wants the gene biotype set as the source
    """
    if file_exists(out_file):
        return out_file
    db = gtf.get_gtf_db(gtf_file)
    with file_transaction(out_file) as tx_out_file:
        with open(tx_out_file, "w") as out_handle:
            for gene in db.features_of_type("gene"):
                children = [x for x in db.children(id=gene)]
                for child in children:
                    if child.attributes.get("gene_biotype", None):
                        gene_biotype = child.attributes.get("gene_biotype")
                gene.attributes['gene_biotype'] = gene_biotype
                gene.source = gene_biotype[0]
                print(gene, file=out_handle)
                for child in children:
                    child.source = gene_biotype[0]
                    # gffread produces a version-less FASTA file
                    child.attributes.pop("transcript_version", None)
                    print(child, file=out_handle)
    return out_file
