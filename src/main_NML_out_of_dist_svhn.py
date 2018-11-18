from __future__ import print_function
from __future__ import print_function

import json
import os
import time

import torch

from dataset_utilities import create_cifar10_dataloaders
from dataset_utilities import create_svhn_dataloaders
from logger_utilities import Logger
from resnet import resnet20, load_pretrained_resnet20_cifar10_model
from train_utilities import TrainClass, eval_single_sample, execute_nml_training
from train_utilities import freeze_resnet_layers

# Training settings
with open(os.path.join('src', 'params.json')) as f:
    params = json.load(f)
params = params['nml_vanilla']

# Create logger and save params to output folder
logger = Logger(experiment_type='OutOfDist_SVHN', output_root='output')
# logger = Logger(experiment_type='TMP', output_root='output')
logger.info('OutputDirectory: %s' % logger.output_folder)
with open(os.path.join(logger.output_folder, 'params.json'), 'w', encoding='utf8') as outfile:
    outfile.write(json.dumps(params, indent=4, sort_keys=True))

################
# Load datasets
data_folder = './data'
trainloader, testloader, classes = create_cifar10_dataloaders(data_folder, params['batch_size'], params['num_workers'])
_, testloader_svhn, classes_svhn = create_svhn_dataloaders(data_folder, params['batch_size'], params['num_workers'])
dataloaders = {'train': trainloader, 'test': testloader_svhn,
               'classes': classes, 'classes_svhn': classes_svhn}

################
# Run basic training- so the base model will be in the same conditions as NML model
logger.info('Execute basic training')
model_base = load_pretrained_resnet20_cifar10_model(resnet20())
model_base = torch.nn.DataParallel(model_base) if torch.cuda.device_count() > 1 else model_base
train_class = TrainClass(filter(lambda p: p.requires_grad, model_base.parameters()),
                         params['fit_to_sample']['lr'],
                         params['fit_to_sample']['momentum'],
                         params['fit_to_sample']['step_size'],
                         params['fit_to_sample']['gamma'],
                         params['fit_to_sample']['weight_decay'],
                         logger.logger)
train_class.eval_test_during_train = False
model_base, train_loss, test_loss = train_class.train_model(model_base, dataloaders, params['fit_to_sample']['epochs'])
model_base = model_base.module if torch.cuda.device_count() > 1 else model_base

################
# Freeze layers
logger.info('Freeze layer: %d' % params['freeze_layer'])
model_base = freeze_resnet_layers(model_base, params['freeze_layer'], logger)

############################
# Iterate over test dataset
logger.info('Iterate over test dataset')
params_fit_to_sample = params['fit_to_sample']
for idx in range(params_fit_to_sample['test_start_idx'], params_fit_to_sample['test_end_idx'] + 1):
    time_start_idx = time.time()

    # Extract a sample from test dataset and check output of base model
    sample_test_data = dataloaders['test'].dataset.data[idx].transpose([1, 2, 0])
    sample_test_true_label = int(dataloaders['test'].dataset.labels[idx])
    prob_org, _ = eval_single_sample(model_base, testloader.dataset.transform(sample_test_data))
    logger.add_org_prob_to_results_dict(idx, prob_org, sample_test_true_label)

    # NML training- train the model with test sample
    execute_nml_training(params_fit_to_sample, dataloaders, sample_test_data, sample_test_true_label, idx,
                         model_base, logger)

    # Log and save
    logger.save_json_file()
    time_idx = time.time() - time_start_idx
    logger.info('----- Finish NML out of distb SVHN, labels idx = %d, time=%f[sec] ----' % (idx, time_idx))
logger.info('Finish All!')