#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function

import os, shutil, sys, glob, subprocess, logging
import os.path as osp
from string import Template
from distutils.dir_util import copy_tree
from time import strftime

logger = logging.getLogger('root')

import svj.genprod
from .lhaIDs import lhaIDs


#____________________________________________________________________
class GridpackGenerator(object):
    """docstring for GridpackGenerator"""

    def __init__(self, config):
        super(GridpackGenerator, self).__init__()
        self.config = svj.genprod.Config.flexible_init(config)
        svj.core.utils.check_scram_arch()
        self.force_renew_model_dir = True
        self.force_renew_input_dir = True
        self.force_renew_gridpack_dir = True
        self.cleanup_gp_generation_dir = True
        self.mg_model_dir = svj.genprod.MG_MODEL_DIR
        self.mg_input_dir = svj.genprod.MG_INPUT_DIR
        self.mg_genprod_dir = svj.genprod.MG_GENPROD_DIR
        self.set_class_variables_from_config(config)
        self.define_paths()

    def set_class_variables_from_config(self, config):
        logger.info('Setting class variables from config')
        config.basic_checks()
        # Set variables from config file
        self.model_name = config.get_model_name()
        self.process_type = config['process_type']
        self.channel = self.process_type.replace('-channel', '')
        self.m_med = config['m_med']
        self.m_d = config['m_d']
        self.r_inv = config['r_inv']
        self.alpha_d = config['alpha_d']
        self.year = config['year']
        # Does the number of events matter at all during gridpack generation?
        # Maybe for the cross section?
        if not 'n_events' in config:
            self.n_events = 1000
            logger.warning('n_events not specified in config; setting to {0}'.format(self.n_events))
        else:
            self.n_events = config['n_events']

    def define_paths(self):
        """
        Uses the variables from the config to determine paths and
        the model name.

        Split function from init so that it's possible to tweak config parameters
        and simply re-call define_paths.
        """
        # Set process-specific variables
        if self.channel == 's':
            self.med_type = 'Zp'
            self.template_model_dir = osp.join(svj.genprod.SVJ_INPUT_DIR, 'mg_model_templates/DMsimp_SVJ_s_spin1_template')
            if self.config.get('lowmassZ', False):
                self.template_input_dir = osp.join(svj.genprod.SVJ_INPUT_DIR, 'mg_input_templates/DMsimp_SVJ_s_spin1_lowmassZ_input_template')
                logger.info('Detected low mass Z\' option; using {0}'.format(self.template_input_dir))
            else:
                self.template_input_dir = osp.join(svj.genprod.SVJ_INPUT_DIR, 'mg_input_templates/DMsimp_SVJ_s_spin1_input_template')
        elif self.channel == 't':
            self.med_type = 'Phi'
            self.template_model_dir = osp.join(svj.genprod.SVJ_INPUT_DIR, 'mg_model_templates/DMsimp_SVJ_t_template')
            self.template_input_dir = osp.join(svj.genprod.SVJ_INPUT_DIR, 'mg_input_templates/DMsimp_SVJ_t_input_template')
        else:
            raise ValueError('Unknown channel \'{0}\''.format(self.channel))
        self.new_model_dir = os.path.join(self.mg_model_dir, self.model_name)

    def run_gridpack_generation(self):
        self.setup_model_dir()
        self.setup_input_dir()
        self.compile_gridpack()

    def setup_model_dir(self):
        self.create_model_dir()
        self.write_param_card()

    def create_model_dir(self):
        created = svj.core.utils.create_directory(self.new_model_dir, force=self.force_renew_model_dir)
        if not created:
            logger.info('Not re-copying in template files')
            return
        # Copy model files to new directory and change relevant parameters according to config
        logger.info('Copying template model: {0} to {1}'.format(self.template_model_dir, self.new_model_dir))
        copy_tree(self.template_model_dir, self.new_model_dir)
        # Read the parameters file (containing the dark particle masses) in the new model directory
        with open(os.path.join(self.new_model_dir, 'parameters.py'), 'r+') as f:
            old_params = Template(f.read())
            # Fill placeholders with values chosen by user
            new_params = old_params.substitute(dark_quark_mass=str(self.m_d), mediator_mass=str(self.m_med))
            f.seek(0)
            f.truncate()
            f.write(new_params)
        logger.info('New parameters written in model files!')

    def write_param_card(self):
        logger.info('Writing param_card.dat')
        # Use the write_param_card.py module that is in the newly created model_dir
        sys.path.append(self.new_model_dir)
        from write_param_card import ParamCardWriter
        param_card_file = osp.join(self.new_model_dir, 'param_card.dat')
        ParamCardWriter(param_card_file, generic=True)
        logger.info('Done writing param_card.dat')

    def setup_input_dir(self):
        self.new_input_dir = osp.join(self.mg_input_dir, self.model_name + '_input')
        logger.info('Preparing input_cards_dir: {0}'.format(self.new_input_dir))
        logger.info('Getting templates from mg_input_template_dir: {0}'.format(self.template_input_dir))
        svj.core.utils.create_directory(self.new_input_dir, force=self.force_renew_input_dir)

        def fill_template(card_file, model_name, total_events, lhaid):
            with open(card_file, 'r+') as f:
                template = f.read()
            return template.format(modelName=model_name, totalEvents=total_events, lhaid=lhaid)

        for template in glob.glob(osp.join(self.template_input_dir, '*.dat')):
            out_file = osp.join(
                self.new_input_dir,
                osp.basename(template).replace('modelname', self.model_name)
                )
            out_contents = fill_template(
                card_file = template,
                # model_name = 'DMsimp_SVJ_s_spin1' if template.endswith('extramodels.dat') else self.model_name,
                model_name = self.model_name,
                total_events = self.n_events,
                lhaid = lhaIDs[self.year]
                )
            logger.info('Writing formatted template to {0}'.format(out_file))
            with open(out_file, 'w') as f:
                f.write(out_contents)

        logger.info('Tarring up input_cards_dir')
        shutil.make_archive(
            base_name = osp.join(self.new_input_dir, self.model_name),
            format =  'tar',
            root_dir = self.mg_model_dir,
            base_dir = self.model_name,
            logger = logger
            )
        logger.info('Inputs directory finished')


    def compile_gridpack(self):
        with svj.core.utils.switchdir(self.mg_genprod_dir):
            assert osp.isfile('gridpack_generation.sh')
            self.logfile = osp.abspath(self.model_name + '.log') # Expected location of log file

            svj.core.utils.create_directory(
                self.model_name,
                force = self.force_renew_gridpack_dir,
                must_not_exist = True
                )

            # MadGraph wants a relative path to the input cards dir
            input_cards_dir_relative = osp.relpath(self.new_input_dir, self.mg_genprod_dir)

            # Unset some environment variables that otherwise crash MG compilation
            env = os.environ.copy()
            to_unset = [
                'LD_LIBRARY_PATH',
                'FC',
                'COMPILER_PATH',
                'PYTHONPATH',
                'CC',
                'COMPILER_PATH',
                'CXX'
                ]
            for var in to_unset:
                if var in env: del env[var]

            cmd = [
                    'source /cvmfs/cms.cern.ch/cmsset_default.sh',
                    ['bash',
                        'gridpack_generation.sh',
                        self.model_name,
                        input_cards_dir_relative,
                        ],
                    ]
            try:
                # svj.core.utils.run_command(cmd, env=env)
                # svj.core.utils.run_command(cmd, env=svj.core.utils.get_clean_env())
                svj.core.utils.run_multiple_commands(cmd, env=svj.core.utils.get_clean_env())
                if self.cleanup_gp_generation_dir:
                    logger.warning('Deleting %s', self.model_name)
                    shutil.rmtree(self.model_name)
            except subprocess.CalledProcessError:
                # Try to display the log file if there is one before throwing
                if osp.isfile(self.logfile):
                    with open(self.logfile, 'r') as f:
                        logger.info(
                            'Contents of {0}:\n{1}'
                            .format(self.logfile, f.read())
                            )
                else:
                    logger.warning('File {0} does not exist'.format(self.logfile))
                raise

    def get_mg_crosssection(self):
        return svj.genprod.utils.get_mg_crosssection_from_logfile(self.logfile)

    def _get_output_files_and_dirs(self):
        """
        Collects all files to be copied into a list, and makes a destination dir
        """
        return glob.glob(osp.join(self.mg_genprod_dir, self.model_name + '*'))  # Includes a log

    def _make_output_directory(self, output_dir=None):
        """
        Catches directory creation error and prints where the tarball might still exist
        Useful in case you run a long gridpack generation and there is only an error in
        copying the file
        Creates a uniquely named output directory of output_dir is None
        """
        if output_dir is None:
            output_dir = osp.join(
                svj.genprod.SVJ_OUTPUT_DIR,
                strftime('%y%m%d_%H%M_') + self.model_name
                )
        try:
            svj.core.utils.create_directory(output_dir, must_not_exist=True)
        except OSError:
            logger.error(
                'Directory {0} already exists; '
                'Not moving files to output directory, tarballs should be '
                'still available in {1}'
                .format(output_dir, self.mg_genprod_dir)
                )
            raise
        return output_dir


    def _transfer_to_output(self, move=False, output_dir=None, dry=False):
        srcs = self._get_output_files_and_dirs()
        output_dir = self._make_output_directory(output_dir)
        for src in srcs:
            dst = osp.join(output_dir, osp.basename(src))
            if move:
                logger.info('Moving {0} ==> {1}'.format(src, dst))
                if not dry: shutil.move(src, dst)
            else:
                logger.info('Copying {0} ==> {1}'.format(src, dst))
                if not dry: shutil.copyfile(src, dst)
            # Slightly hacky: assuming there is one log file, point to the moved/copied
            # log file after this function is called
            if src.endswith('.log'):
                logger.info('Log file now in {0}'.format(dst))
                self.logfile = osp.abspath(dst)


    def copy_to_output(self, output_dir=None, dry=False):
        self._transfer_to_output(move=False, output_dir=output_dir, dry=dry)

    def move_to_output(self, output_dir=None, dry=False):
        self._transfer_to_output(move=True, output_dir=output_dir, dry=dry)

