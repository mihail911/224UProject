__author__ = 'mihaileric/chrisbillovits'

import os,sys
import re
import collections
import time
import numpy as np

"""Add root directory path"""
root_dir = os.path.dirname(os.path.dirname(os.path.abspath((__file__))))
sys.path.append(root_dir)
os.chdir(root_dir)

import logging
from models.models import *
from argparse import ArgumentParser
from util.colors import color, prettyPrint
from util import boundaryplot as bp
from ast import literal_eval as str2dict
from sklearn.feature_selection import SelectFpr, chi2, SelectKBest
import sklearn


def run(args):
    ''' Provides a simple execution of the test harness from
        command-line invocation.  ''' 
    params = set_config(args.conf)
    model, feat_vec, labels = train_model(params)
    
    load, params['load_vectors'] = params['load_vectors'], True
    
    test_model(params, 'train_dev', model, feat_vec, labels)
    params['load_vectors'] = load

    test_model(params, 'test', model, feat_vec, labels)
    prettyPrint("-" * 80, color.YELLOW)
    
def set_config(config_file):
    ''' Sets the configuration file.  Returns a parameter hash. '''
    params = collections.defaultdict(list)
    # Loads the parameters set in the conf file and saves in a global dict.
    with open(config_file, 'r') as f:
	stream = f.readlines()
	for line in stream:	
		kv = re.split(r'[ ,:;]*', line.rstrip())
		val = kv[1:] if (len(kv) > 2 or kv[0] == 'features') else kv[1]

		if kv[0] == 'param_grid': # Need to re-parse the expression
			# Eval to allow for numpy definitions in the config file.
			val = eval( ':'.join( line.split(':')[1 :] ).strip() )  
		
		params[kv[0]] = val
        # Special-case parsing of arguments
        for arg in ('load_vectors', 'plot'):
            params[arg] = False if not params[arg] or not params[arg].lower() == 'true' else True
        prettyPrint( '{0}'.format(params), color.YELLOW)
        prettyPrint('Configuration file used: ' + config_file, color.YELLOW)

    return params

def train_model(params):
    ''' Trains the model, with pretty output.  Returns the model, feature
        vectors, and labels tuple, ready for evaluation. '''
    compression = 'lsa' if params['plot'] else None # Test change to get rid of LSA
    
    prettyPrint("-" * 80 + "\nTraining model '{0}' ... ".format(params['model']), color.YELLOW)
    prettyPrint("With features: {0}".format(params['features']), color.YELLOW)
    start_train = time.time()
    model, feat_vec, labels = build_model(clf = params['model'],
                                          train_reader = sick_train_reader,
                                          features = params['features'],
                                          file_name = params['feature_file'] + ".train_dev",
                                          load_vec = params['load_vectors'],
                                          feature_selector = SelectKBest(chi2, k = 'all'),
                                          compression = compression)
    
    best_model = parameter_tune(params['model'], model, feat_vec, labels, grid = params['param_grid'])

    end_train = time.time() 
    prettyPrint ("Finished training.  Took {0:.2f} seconds".format(end_train - start_train), color.RED)
    
    return best_model, feat_vec, labels

def test_model (params = None, data_set = 'test', best_model = None, feat_vec = None, labels = None):
    ''' Tests a trained model, or plots it if the params[plot] flag is set '''
    if params['plot'] and data_set != 'train':
        prettyPrint("Generating decision boundary graph ...", color.YELLOW)

        filename = params['feature_file'] + '.{0}'.format(data_set)
        feat_vec, labels = obtain_vectors(file_extension = filename,
                                          load_vec = params['load_vectors'],
                                          reader = sick_dev_reader,
                                          features = params['features'])                                         
        bp.plot_boundary(best_model, feat_vec, labels)
        prettyPrint("Saved in output/foo.png\n" + "-" * 80, color.YELLOW)
        return
    '-----------------'
    
    prettyPrint("Testing on data set: {0}".format(data_set), color.YELLOW)
    
    evaluate_model(best_model, reader = 'sick_{0}_reader'.format(data_set),
                    features = params['features'],
                    file_name = params['feature_file'],
                    load_vec = params['load_vectors'])
    
    prettyPrint("Finished training and evaluating model\n" + "-" * 80, color.YELLOW)

if __name__ == '__main__':
    # Execute as command line
    parser = ArgumentParser('description = provide arguments for running model pipeline')
    parser.add_argument('--conf', help = 'name of configuration file ')
    arguments = parser.parse_args()
    run(arguments)
