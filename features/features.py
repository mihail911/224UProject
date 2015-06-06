__author__ = 'chrisbillovits/mihaileric/chrisguthrie'

import os
import sys
import re

"""Add root directory path"""
root_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(root_dir)

from collections import Counter
from framenet.fn_tools import is_super_frame
from framenet import frame
import itertools
import nltk
import csv
from util.utils import *
import numpy as np

from nltk import word_tokenize, pos_tag
from nltk.corpus import wordnet as wn
from nltk.stem import WordNetLemmatizer
from util.colors import color, prettyPrint
from util.distributedwordreps import build, cosine

lemmatizer = WordNetLemmatizer()

GLOVE_MAT, GLOVE_VOCAB = np.zeros(1), np.zeros(1)

def glvvec(w):

    """Return the GloVe vector for w."""

    if not GLOVE_MAT.any():
        init_glv()
    i = GLOVE_VOCAB.index(w)
    return GLOVE_MAT[i]

def init_glv():
    
    global GLOVE_MAT
    if GLOVE_MAT.any():
        return
    ''' Lazily initializes GloVe vectors if they don't already exist '''
    prettyPrint("Building GloVe vectors: ", color.CYAN)
    GLOVE_MAT, GLOVE_VOCAB, _ = build(root_dir + '/nli-data/glove.6B.50d.txt', delimiter=' ', header=False, quoting=csv.QUOTE_NONE)
    prettyPrint("Loaded vectors, dimension {0} ".format(np.shape(GLOVE_MAT)[1]), color.CYAN)

def weighted_glv(tree):
    ''' Weigh the vector importance on compositionality.
        Leaves that are lower in the constituency parse
        are more so the "basis of meaning" for the sentence
        so we weigh it more.  
    '''

    init_glv()
    words = []      # (word, height in tree)
    depthSize = {}  # L1 norm of tree depths
    depthSize['count'] = 0

    def extract_words(subtree, n):

        for phrase in subtree:
            if isinstance(phrase,tuple):
                extract_words(phrase, n+1)
            else:
                words.append((phrase, n))
                depthSize['count'] += n

    extract_words(tree, 1)
    
    word_leaves = [ 1.0 * w[1] / depthSize['count'] * glvvec(w[0]) for w in words if w[0] in GLOVE_VOCAB]
    return word_leaves

def compare_glv_trees(t1, t2):
    ''' Emits a vector of features for the difference of words, discriminated on POS tag.'''
    features = {}
    leaves1 = weighted_glv(t1)
    leaves2 = weighted_glv(t2)
    diff = np.mean(leaves1) - np.mean(leaves2)
    print np.shape(diff)
    for i in range(np.shape(diff)[0]):
        features['glv_dim_diff'] = diff[i]
    return features

def word_overlap_features(t1, t2):
    overlap = [w1 for w1 in leaves(t1) if w1 in leaves(t2)]
    feat = Counter(overlap)
    feat['overlap_length'] = len(overlap)
    feat['one_not_two_length'] = len([w1 for w1 in leaves(t1) if w1 not in leaves(t2)])
    feat['two_not_one_length'] = len([w2 for w2 in leaves(t2) if w2 not in leaves(t1)])
    return feat

def word_cross_product_features(t1, t2):
    return Counter([(w1, w2) for w1, w2 in itertools.product(leaves(t1), leaves(t2))])

def gen_ngrams(s, n = 2):
    ''' Generator function for ngrams in a sentence represented as a list
        of words.'''
    for i in range(0, len(s)):
        yield ' '.join(s[i:i+n])


def gram_overlap(t1, t2, n = 2):
   
    s1, s2 = leaves(t1), leaves(t2)
    gram_overlap = [g1 for g1 in gen_ngrams(s1, n)
                    for g2 in gen_ngrams(s2, n) if g1 == g2]
    return Counter(gram_overlap) 
    
       
def gram_cross_product(t1, t2, n = 2):
    s1, s2 = leaves(t1), leaves(t2)
    return Counter([(g1, g2) for g1, g2 in itertools.product(gen_ngrams(s1, n),
                                                              gen_ngrams(s2, n))])

def tree2sent(t1, t2):
    return ' '.join(leaves(t1)), ' '.join(leaves(t2))

def length_features(t1, t2):
    feat = {}
    feat['length_1'] = len(leaves(t1))
    feat['length_2'] = len(leaves(t2))
    return feat

def tree_depth(t):
    curr_depth = 0
    max_depth = 0
    for ch in str(t):
        if ch == '(':
            curr_depth += 1
        if ch == ')':
            curr_depth -= 1
        if curr_depth > max_depth:
            max_depth = curr_depth
    return max_depth

def word_depth(word, t):
    ''' Returns the depth of a word in the tree.  -1 if it does not exist '''
    tokens = leaves(t)
    structured_sent = str(t)
    if word not in tokens:
        return -1
    
    depth = 0
    word_ind = structured_sent.index('\'' + word + '\'')
    for c in structured_sent[:word_ind]:
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
    return depth
        
def all_word_depth(t):
    ''' List of depths of words in the tree'''
    depth = 0
    depth_list = []
    counter = 0
    for ch in str(t):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '\'':
            if counter:
                depth_list.append(depth)
                counter = 0
            else:
                counter = 1
        
    return depth_list
          

def tree_depth_features(t1, t2):
    feat = {}
    feat['depth_1'] = tree_depth(t1)
    feat['depth_2'] = tree_depth(t2)
    feat['depth_similarity'] = 1 - abs((feat['depth_1'] - feat['depth_2'])/(feat['depth_1'] + feat['depth_2']))
    return feat

def penn2wn(tag):
    """ Given a Penn Treebank tag, returns the appropriate 
        WordNet tag, if possible.  Otherwise returns ''. """

    if tag[0] in 'JVNR':
        ind = 'JVNR'.index(tag[0]) # Starts with (AD)J, V(ERB), N(OUN), (ADVE)R(B)
        return 'avnr'[ind]
    return ''

def extract_nouns(sent):
    """Extracts nouns in a given sentence."""
    tokens = word_tokenize(sent)
    pos_tagged = pos_tag(tokens)
    return [word[0] for word in pos_tagged if word[1] == 'NN' or word[1] == 'NNS']

def extract_nouns_lemma(sent):
    """Extracts lemmatized nouns in a given sentence."""
    tokens = word_tokenize(sent)
    pos_tagged = pos_tag(tokens)
    return [lemmatizer.lemmatize(word[0]) for word in pos_tagged if word[1] == 'NN' or word[1] == 'NNS']

def extract_noun_synsets(sent):
    """Return list of all noun synsets for a given sentence."""
    synsets = []
    all_nouns = extract_nouns(sent)
    for noun in all_nouns:
        synsets.extend(wn.synsets(noun, pos=wn.NOUN))
    return synsets

def extract_nouns_and_synsets(sent):
    """Extracts pair of both nouns and synsets for those nouns in a given sent."""
    synsets = []
    all_nouns = extract_nouns(sent)
    for noun in all_nouns:
        synsets.extend(wn.synsets(noun, pos=wn.NOUN))
    return (all_nouns, synsets)

def extract_synsets (sent):
    ''' Extracts the synsets of all the words in the sentence with matching
        POS tag.  '''
    synsets = []
    tagged = pos_tag(sent.split())
    
    for word, pos in tagged:
        synsets.extend(wn.synsets(word, pos=penn2wn(pos)))
    return synsets

def noun_synset_dict(sent):
    synsets = {}
    all_nouns = extract_nouns(sent)
    for noun in all_nouns:
        synsets[noun] = wn.synsets(noun, pos=wn.NOUN)
    return synsets

def extract_adj_lemmas(sent):
    """Extracts all adjectives in a given sentence"""
    lemmas = []
    tokens = word_tokenize(sent)
    pos_tagged = pos_tag(tokens)
    for word in pos_tagged:
        if word[1] in ['JJ', 'JJR', 'JJS']:
            lemmas.extend(wn.lemmas(word[0], wn.ADJ))
    return lemmas

def extract_adj_antonyms(sent):
    """Return list of all antonym lemmas for nouns in a given sentence"""
    antonyms = []
    all_adj_lemmas = extract_adj_lemmas(sent)
    for lemma in all_adj_lemmas:
        antonyms.extend(lemma.antonyms())
    return antonyms

def synset_overlap_features(t1, t2):
    """Returns counter for all mutual synsets between two sentences."""
    sent1, sent2 = tree2sent(t1, t2)
    sent1_synsets = extract_noun_synsets(sent1)
    sent2_synsets = extract_noun_synsets(sent2)
    overlap_synsets = [str(syn) for syn in sent1_synsets if syn in sent2_synsets]
    return Counter(overlap_synsets)

def synset_exclusive_first_features(t1, t2):
    """Returns counter for all nouns in first sentence with no possible synonyms in second"""
    sent1, sent2 = tree2sent(t1, t2)
    sent1_synset_dict = noun_synset_dict(sent1)
    sent2_synsets = extract_noun_synsets(sent2)
    firstonly_nouns = [str(noun) for noun in sent1_synset_dict if not len(set(sent1_synset_dict[noun]) & set(sent2_synsets))]
    return Counter(firstonly_nouns)

def synset_exclusive_second_features(t1, t2):
    """Returns counter for all nouns in second sentence with no possible synonyms in first"""
    sent1, sent2 = tree2sent(t1, t2)
    sent1_synsets = extract_noun_synsets(sent1)
    sent2_synset_dict = noun_synset_dict(sent2)
    secondonly_nouns = [str(noun) for noun in sent2_synset_dict if not len(set(sent2_synset_dict[noun]) & set(sent1_synsets))]
    return Counter(secondonly_nouns)

def subphrase_generator(tree):
    ''' Given a tree, returns all of the subphrases '''
    phrases = [tree]
    def extract_subphrases(subtree):
        if isinstance(subtree, tuple):
            for sp in subtree:
                phrases.append(sp)
                extract_subphrases(sp)
                
    extract_subphrases(tree)
    return phrases

# When a phrase in t2 contains a phrase in t1, count it.
# TODO: Compare this to a phrase share feature that implements selective
# deletion of subphrases as a form of the dialogue heuristic.  
def phrase_share_feature(t1, t2):
    p1, p2 = subphrase_generator(t1), subphrase_generator(t2)
    shared = [str((v, w)) for v in p1 for w in p2 if v == w]
    
    return Counter(shared)

def phrase_dialogue_feature(t1, t2):
    p1, p2 = subphrase_generator(t1), subphrase_generator(t2)
    p_leaves, q_leaves = [leaves(p) for p in p1], [leaves(q) for q in p2]
    for i in range(len(p_leaves)):
        ptree = p1[i]
        for j in range(len(q_leaves)):
            # TODO: selective subphrase deletion.  If the nouns or verbs are
            # similar enough (i.e. synset overlap), then look for
            # same-level deletion subphrases and mark them as a feature.
            qtree = p2[j]
            pass
            
common_hyp_counter = 0
def phrase_common_hyp(t1, t2):
    ''' Checks for lowest common ancestor between two words in a phrase. '''
    global common_hyp_counter
    syns_cache = {}
    lv_1, lv_2 = leaves(t1), leaves(t2)
    def have_common_hyp(v, w):
        ''' If two word senses have a common hypernym that
            is not a superset / subset relationship, then returns true
            else false. '''
        if v in lv_2 or w in lv_1:
            return False
        for syn_v in syns_cache[v]:
            for syn_w in syns_cache[w]:
                common_hyp = lch(syn_v, syn_w)
                for h in common_hyp:
                    h_name = h.name().partition('.')[0]
                    if h_name not in lv_1 and h_name not in lv_2:
                        return True
                    else:
                        continue
        return False
    ''' ------------------------------------ '''
    
    hyp_cache = set()
    
    # for each word product, if some synset of the words has a common
    # hypernym, then features[phrase : phrase] += 1
    syn1 = extract_synsets(' '.join(lv_1))
    syn2 = extract_synsets(' '.join(lv_2))

    ''' Tabulate synsets for each word in each sentence ''' 
    for word in lv_1:
        syns_cache[word] = [syn for syn in syn1 if syn.name().partition('.')[0] == word]  
    for word in lv_2:
        syns_cache[word] = [syn for syn in syn2 if syn.name().partition('.')[0] == word]

    ''' Note which words have common hypernyms '''
    for v in lv_1:
        for w in lv_2:
            if have_common_hyp(v, w):
                 hyp_cache.add((v, w))
           
    ''' Use a subphrase generator on the sentence.
        Enforce phrase length > 1 '''
    p1, p2 = subphrase_generator(t1), subphrase_generator(t2)
    
    p1 = [leaves(p) for p in p1 if len(str(p).split(' ')) > 1]
    p2 = [leaves(p) for p in p2 if len(str(p).split(' ')) > 1]

    features = {}
        
    ''' Count the phrases in which each overlapping word exists.  '''
    for v, w in hyp_cache:
        common_phrases = [(p, q) for p in p1 for q in p2 if v in p and w in q]
        for p, q in common_phrases:
            features["com_hyp: {0} {1}".format(p, q)] = 1.0
            common_hyp_counter += 1
    
    return features
    
def general_hypernym(t1, t2):   
    ''' Calculates hypernyms of sentence 1 and sentence 2 using matching POS tags. 
        Also permits self-hypernyms '''
    s1_leaves, s2_leaves = leaves(t1), leaves(t2)
    sent1, sent2 = ' '.join(s1_leaves), ' '.join(s2_leaves)
    
    hsyns = extract_synsets(sent1)
    syns = extract_synsets(sent2)

    all_hyper_synsets = set(extract_synsets(sent1))

    # Counts the number of synsets of a word in the sentence with the 
    # same POS tag as parsed 
    s1_len = len(set(s for s in hsyns if s.name().partition('.')[0] in sent1))
    s2_len = len(set(s for s in syns if s.name().partition('.')[0] in sent2))
                            
    for h in hsyns:
        all_hyper_synsets.update(set([i for i in h.closure(lambda s:s.hypernyms())]))
    overlap = all_hyper_synsets & set(syns)

    feature_string = "hypernyms {0} {1} {2}".format(s1_len, s2_len, len(overlap))
    return Counter({feature_string : 1})


_lch_cache = {}
def lch(syn1, syn2):
    ''' Utility function to memoize common hypernym relation calls'''
    global _lch_cache
    if (syn1, syn2) not in _lch_cache:
        _lch_cache[(syn1, syn2)] = syn1.lowest_common_hypernyms(syn2)
        _lch_cache[(syn2, syn1)] = _lch_cache[(syn1, syn2)]
    return _lch_cache[(syn1, syn2)]



def hypernym_features(t1, t2):
    """ Calculate hypernyms of sent1 and check if synsets of sent2 contained in
    hypernyms of sent1. Trying to capture patterns of the form
    'A dog is jumping.' entails 'An animal is being active.'
    Returns an indicator feature of form 'contains_hypernyms: True/False'
    """
    sent1 = ' '.join(leaves(t1))
    sent2 = ' '.join(leaves(t2))
    s1_nouns, s1_syns = extract_nouns_and_synsets(sent1)

    
    s2_nouns, s2_syns  = extract_nouns_and_synsets(sent2)
    all_hyper_synsets = set(s1_syns) #Stores the hypernym synsets of the nouns in the first sentence
    s1_len, s2_len = len(s1_nouns), len(s2_nouns)

    for syn in s1_syns:
        all_hyper_synsets.update(set([i for i in syn.closure(lambda s:s.hypernyms())]))
    synset_overlap = all_hyper_synsets & set(s2_syns) # Stores intersection of sent2 synsets and hypernyms of sent1
    
    # Discretize into smaller buckets based on the number of nouns in each sentence,
    # and the size of the synset overlap.
    feature_string = 'hypernyms {0} {1} {2}'.format(s1_len, s2_len, len(synset_overlap))

    return Counter({feature_string : 1})

def antonym_features(t1, t2):

    """Use antonyms between sentences to recognize contradiction patterns. TODO: Extract antonyms from nouns and other syntactic families as well!"""

    sent1 = ' '.join(leaves(t1))
    sent2 = ' '.join(leaves(t2))
    sent2_lemmas = extract_adj_lemmas(sent2)
    sent1_antonyms = extract_adj_antonyms(sent1)
    antonyms = [str(lem) for lem in sent1_antonyms if lem in sent2_lemmas]
    return Counter(antonyms)

def word_cross_product_features(t1, t2):
    return Counter([(w1, w2) for w1, w2 in itertools.product(leaves(t1), leaves(t2))])


def word_cross_product_nv(t1, t2):
    nv1 = [w[0] for w in pos_tag(leaves(t1)) if penn2wn(w[1]) in 'nv']
    nv2 = [w[0] for w in pos_tag(leaves(t2)) if penn2wn(w[1]) in 'nv']

def frame_overlap_features(t1, t2, sf1, sf2):
    frame_names1 = [f1.name for f1 in sf1]
    frame_names2 = [f2.name for f2 in sf2]
    overlap = ['frame_' + fn1 for fn1 in frame_names1 if fn1 in frame_names2]
    feat = Counter(overlap)
    feat['first_frames'] = len(sf1)
    feat['second_frames'] = len(sf2)
    feat['overlap_frames'] = len(overlap)
    return feat

def frame_cross_product_features(t1, t2, sf1, sf2):
    frame_names1 = [f1.name for f1 in sf1]
    frame_names2 = [f2.name for f2 in sf2]
    return Counter([(f1, f2) for f1, f2 in itertools.product(frame_names1, frame_names2)])

def super_overlap(sf1, sf2):
    return [(f1, f2) for f1 in sf1 for f2 in sf2 if is_super_frame(f1, f2)]

def frame_entailment_features(t1, t2, sf1, sf2):
    super_overlap_strings = ['entailed_frame_' + f1.name for (f1, f2) in super_overlap(sf1, sf2)]
    feat = Counter(super_overlap_strings)
    feat['first_frames'] = len(sf1)
    feat['second_frames'] = len(sf2)
    feat['entailed_frames'] = len(super_overlap_strings)
    return feat


def frame_similarity_features(t1, t2, sf1, sf2):
    overlap = [(f1, f2) for f1 in sf1 for f2 in sf2 if f1.name == f2.name]
    overlap.extend(super_overlap(sf1, sf2))
    feat = {}
    total_sim = 0.0
    worst_sim = 1.0
    for f1, f2 in overlap:
        sim = frame.frame_similarity(f1, f2)
        total_sim += sim
        if sim < worst_sim:
            worst_sim = sim
        feat['frame_similarity_' + f1.name] = sim
    if len(overlap):
        feat['average_frame_similarity'] = total_sim/len(overlap)
        feat['worst_frame_similarity'] = worst_sim
    return feat

def negation_features(t1, t2):
    feat = {}
    s1, s2 = leaves(t1), leaves(t2)
    for word in ['no', 'not', 'none', "n't", 'nobody']:
        if (word in s1 and word not in s2) or (word in s2 and word not in s1):
            feat['{0}_negation'.format(word)] = 1.0

    return feat

grammar = """ \
            NN-PHRASE: {<DT.*> <NN> <RB>}
                      { <JJ> <NN>}
                      {<NN> <IN> <NN>}
                      {<RB> <JJ> <NN>}
                      { <NNS> <RB>}
                      { <JJ> <NNS>}
                      {<NNS> <IN> <NNS>}
                      {<RB> <JJ> <NNS>}
                      { <NNP> <RB>}
                      { <JJ> <NNP>}
                      {<NNP> <IN> <NNP>}
                      {<RB> <JJ> <NNP>}
                      { <NNPS> <RB>}
                      {<DT.*> <JJ> <NNPS>}
                      {<NNPS> <IN> <NNP>}
                      {<RB> <JJ> <NNPS>}
                      {<NN> <VBZ> <VBG>}
                      {<NNS> <VBZ> <VBG>}
                      {<NN> <VBP> <VBG>}
                      {<NNS> <VBP> <VBG>}

            VB-PHRASE : {<RB> <VB>}
                        {<RB> <VBD>}
                        {<RB> <VBG>}
                        {<RB> <VBN>}
                        {<RB> <VBP>}
                        {<RB> <VBZ>}
                        {<RBR> <VB>}
                        {<RBR> <VBD>}
                        {<RBR> <VBG>}
                        {<RBR> <VBN>}
                        {<RBR> <VBP>}
                        {<RBR> <VBZ>}
                        {<RBS> <VB>}
                        {<RBS> <VBD>}
                        {<RBS> <VBG>}
                        {<RBS> <VBN>}
                        {<RBS> <VBP>}
                        {<RBS> <VBZ>}
                        {<VBG> <IN> <DT> <NN>}
                        {<VBG> <IN> <DT> <NNS>}

          """
cp = nltk.RegexpParser(grammar)

def get_noun_phrase_labeled(t1,t2):
    """Gets noun phrases for given trees as lists with
    labeled POS tags."""
    sent1 = leaves(t1)
    sent2 = leaves(t2)

    tree1 = cp.parse(nltk.pos_tag(sent1))
    tree2 = cp.parse(nltk.pos_tag(sent2))

    #List of noun phrases with tokens and POS tags
    np1 = [subtree1.leaves() for subtree1 in tree1.subtrees() if subtree1.label() == 'NN-PHRASE']
    np2 = [subtree2.leaves() for subtree2 in tree2.subtrees() if subtree2.label() == 'NN-PHRASE']

    return np1, np2

def get_noun_phrase_words(nps_labeled):
    """Gets the words of a noun phrase."""
    all_np_words = []
    for np in nps_labeled:
        all_np_words += [" ".join([pair[0].lower() for pair in np])]
    return all_np_words

def get_noun_phrase_mapping(np1, np2):
    """Gets noun phrase mapping from noun phrase text to labeled list."""
    np1_token_mapping = {" ".join([pair[0].lower() for pair in np]): np for np in np1}
    np2_token_mapping = {" ".join([pair[0].lower() for pair in np]): np for np in np2}

    return np1_token_mapping, np2_token_mapping

npm_counter = 0
def noun_phrase_modifier_features(t1, t2):
    """Extracts noun phrases within sentences and identifies
    whether a noun phrase in second sentence is subsumed by first."""
    feat = []
    global npm_counter
    np1, np2 = get_noun_phrase_labeled(t1, t2)
    # TODO: get compositionality statistics, and see if they are sparse or not.
    np1_token_mapping, np2_token_mapping = get_noun_phrase_mapping(np1, np2)

    for tok1 in np1_token_mapping.keys():
        for tok2 in np2_token_mapping.keys():
            if set(tok2).issubset(set(tok1)):
                sent1_entities = np1_token_mapping[tok1]
                sent2_entities = np2_token_mapping[tok2]
                np1_pos = [tok[1] for tok in sent1_entities]
                np2_pos = [tok[1] for tok in sent2_entities]
                feature_key = ",".join(np1_pos) + ":" + ",".join(np2_pos)
                feat += [feature_key]
                npm_counter += 1
                
    print npm_counter
    return Counter(feat)

def get_noun_phrase_vector(noun_phrase):
    """Generate an aggregate distributed word vector
    for a given noun phrase."""
    all_word_vecs = [glvvec(w) for w in noun_phrase if w in GLOVE_VOCAB] #How often are the words not in glove vocab?
    return np.sum(all_word_vecs, axis=0)

def noun_phrase_word_vec_features(t1, t2):
    """Produces features for the similarity between
    pairwise noun phrase word vectors across the two sentences."""
    feat = {}
    np1, np2 = get_noun_phrase_labeled(t1, t2)

    np1_token_mapping, np2_token_mapping = get_noun_phrase_mapping(np1, np2)

    np1_words = get_noun_phrase_words(np1)
    np2_words = get_noun_phrase_words(np2)

    for n1 in np1_words:
        for n2 in np2_words:
            sent1_entities = np1_token_mapping[n1]
            sent2_entities = np2_token_mapping[n2]
            np1_pos = [tok[1] for tok in sent1_entities]
            np2_pos = [tok[1] for tok in sent2_entities]
            feature_key = ",".join(np1_pos) + ":" + ",".join(np2_pos)

            #Make feature weight equal to cosine similarity
            n1_vec = get_noun_phrase_vector(list(n1))
            n2_vec = get_noun_phrase_vector(list(n2))
            sim = 1 - cosine(n1_vec, n2_vec)
            feat[feature_key] = sim
    return feat


features_mapping = {'word_cross_product': word_cross_product_features,
            'word_overlap': word_overlap_features,
            'synset_overlap' : synset_overlap_features,
            'hypernyms' : hypernym_features,
            'new_hyp' : general_hypernym,
            'common_hypernym': phrase_common_hyp,
            'antonyms' : antonym_features,
            'first_not_second' : synset_exclusive_first_features,
            'second_not_first' : synset_exclusive_second_features,
            'frame_overlap' : frame_overlap_features,
            'frame_entailment' : frame_entailment_features,
            'frame_similarity' : frame_similarity_features,
            'frame_cross_product' : frame_cross_product_features,
            'negation' : negation_features,
            'length' : length_features,
            'tree_depth' : tree_depth_features,
            'noun_phrase_modifier' : noun_phrase_modifier_features,
            'noun_phrase_word_vec' : noun_phrase_word_vec_features,
    'bigram_cross_prod' : lambda t1, t2: gram_cross_product(t1, t2, n=2),
    'trigram_cross_prod' : lambda t1, t2: gram_cross_product(t1, t2, n=3),
    'quadgram_cross_prod' : lambda t1, t2: gram_cross_product(t1, t2, n=4),
    'bigram_word_overlap' : lambda t1, t2: gram_overlap(t1, t2, n=2),
    'trigram_word_overlap': lambda t1, t2: gram_overlap(t1, t2, n=3),
    'quadgram_word_overlap' : lambda t1, t2: gram_overlap(t1, t2, n=4),
    'phrase_share' : phrase_share_feature,
    'glv_diff': compare_glv_trees
             }
    
def featurizer(reader=sick_train_reader, features_funcs=None):
    """Map the data in reader to a list of features according to feature_function,
    and create the gold label vector.

    Valid feature_funcs return a dict of string : int key-value pairs.  """
    feats = []
    labels = []
    split_index = None

    for label, t1, t2, sf1, sf2 in reader():
        feat_dict = {} #Stores all features extracted using feature functions
        for feat in features_funcs:
            if feat.startswith('frame'):
                d = features_mapping[feat](t1, t2, sf1, sf2)
            else:
                d = features_mapping[feat](t1, t2)
            feat_dict.update(d)

        feats.append(feat_dict)
        labels.append(label)
    return (feats, labels)
