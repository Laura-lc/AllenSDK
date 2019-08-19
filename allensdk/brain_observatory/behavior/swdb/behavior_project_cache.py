import os
import pandas as pd
import numpy as np
import json

from allensdk import one
from allensdk.brain_observatory.behavior.behavior_ophys_api.behavior_ophys_nwb_api import BehaviorOphysNwbApi
from allensdk.brain_observatory.behavior.behavior_ophys_session import BehaviorOphysSession
from allensdk.core.lazy_property import LazyProperty
from allensdk.brain_observatory.behavior.trials_processing import calculate_reward_rate
from allensdk.brain_observatory.behavior.image_api import ImageApi

csv_io = {
    'reader': lambda path: pd.read_csv(path, index_col='Unnamed: 0'),
    'writer': lambda path, df: df.to_csv(path)
}

cache_paths_example = {'manifest_path': '/allen/programs/braintv/workgroups/nc-ophys/visual_behavior/SWDB_2019/visual_behavior_data_manifest.csv',
                      'nwb_base_dir': '/allen/programs/braintv/workgroups/nc-ophys/visual_behavior/SWDB_2019/nwb_files',
                      'analysis_files_base_dir': '/allen/programs/braintv/workgroups/nc-ophys/visual_behavior/SWDB_2019/analysis_files',
                      'analysis_files_metadata_path':'/allen/programs/braintv/workgroups/nc-ophys/visual_behavior/SWDB_2019/analysis_files_metadata.json',
                      }

class BehaviorProjectCache(object):

    def __init__(self, cache_paths):
        '''
        A cache-level object for the behavior/ophys data. Provides access to the manifest of 
        ophys/behavior containers, as well as pre-computed analysis files for each 
        experiment.

        Args:
            cache_paths (dict): must provide the following keys:
                manifest_path: Full path to the behavior project manifest CSV file
                nwb_base_dir: Direcotry containing NWB files.
                analysis_files_base_dir: Directory containing trial response, flash response,
                                         and stimulus presentation extra columns files.
                analysis_files_metadata_path: Full path to the JSON file providing metadata
                                         relating to the creation of the analysis files.
        
        Attributes: 
            manifest: (pd.DataFrame)
                Table containing information about all ophys sessions.
            analysis_files_metadata (dict):
                Metadata relating to the creation of the analysis files.
            
        Methods: 
            get_session(ophys_experiment_id):
                Returns an extended BehaviorOphysSession object, including trial_response_df and
                flash_response_df

            get_container_sessions(container_id):
                Returns a dictionary with behavior stages as keys and the corresponding session
                object from that container, that stage as the value.

        Class Methods:
            from_json(json_path):
                Returns an instance constructed using cache_paths defined in a JSON file.

        '''
        manifest = csv_io['reader'](cache_paths['manifest_path'])
        self.manifest = manifest[[
            'ophys_experiment_id',
            'container_id',
            'full_genotype',
            'imaging_depth',
            'targeted_structure',
            'stage_name',
            'animal_name',
            'sex',
            'date_of_acquisition',
            'retake_number'
        ]]
        self.nwb_base_dir = cache_paths['nwb_base_dir']
        self.analysis_files_base_dir = cache_paths['analysis_files_base_dir']

        if 'analysis_files_metadata_path' in cache_paths:
            self.analysis_files_metadata = self.get_analysis_files_metadata(cache_paths['analysis_files_metadata_path'])
        else:
            print('Warning! No metadata supplied for analysis files. Set analysis_files_metadata_path to point at the json file containing the metadata')
            self.analysis_files_metadata = None

    def get_analysis_files_metadata(self, path):
        with open(path, 'r') as metadata_path:
            metadata = json.load(metadata_path)
        return metadata

    def get_nwb_filepath(self, experiment_id):
        return os.path.join(
            self.nwb_base_dir,
            'behavior_ophys_session_{}.nwb'.format(experiment_id)
        )

    def get_trial_response_df_path(self, experiment_id):
        return os.path.join(
            self.analysis_files_base_dir,
            'trial_response_df_{}.h5'.format(experiment_id)
        )

    def get_flash_response_df_path(self, experiment_id):
        return os.path.join(
            self.analysis_files_base_dir,
            'flash_response_df_{}.h5'.format(experiment_id)
        )

    def get_extended_stimulus_presentations_df(self, experiment_id):
        return os.path.join(
            self.analysis_files_base_dir,
            'extended_stimulus_presentations_df_{}.h5'.format(experiment_id)
        )

    def get_session(self, experiment_id):
        '''
        Return a BehaviorOphysSession object given an ophys_experiment_id.
        '''
        nwb_path = self.get_nwb_filepath(experiment_id)
        trial_response_df_path = self.get_trial_response_df_path(experiment_id)
        flash_response_df_path = self.get_flash_response_df_path(experiment_id)
        extended_stim_df_path = self.get_extended_stimulus_presentations_df(experiment_id)
        api = ExtendedNwbApi(
            nwb_path,
            trial_response_df_path,
            flash_response_df_path,
            extended_stim_df_path
        )
        session = ExtendedBehaviorSession(api)
        return session 

    def get_container_sessions(self, container_id):
        container_stages = {}
        container_manifest = self.manifest.groupby('container_id').get_group(container_id)
        for ind_row, row in container_manifest.iterrows():
            container_stages.update(
                {row['stage_name']: self.get_session(row['ophys_experiment_id'])}
            )
        return container_stages

    @classmethod
    def from_json(cls, json_path):
        '''
        Return a cache using paths stored in a JSON file
        '''
        with open(json_path, 'r') as json_file:
            cache_json = json.load(json_file)
        return cls(cache_json)

class ExtendedNwbApi(BehaviorOphysNwbApi):
    
    def __init__(self, nwb_path, trial_response_df_path, flash_response_df_path,
                 extended_stimulus_presentations_df_path):
        '''
        Api to read data from an NWB file and associated analysis HDF5 files.
        '''
        super(ExtendedNwbApi, self).__init__(path=nwb_path, filter_invalid_rois=True)
        self.trial_response_df_path = trial_response_df_path
        self.flash_response_df_path = flash_response_df_path
        self.extended_stimulus_presentations_df_path = extended_stimulus_presentations_df_path

    def get_trial_response_df(self):
        tdf = pd.read_hdf(self.trial_response_df_path, key='df')
        tdf.reset_index(level=1, inplace=True)
        # tdf.insert(loc=0, column='cell_specimen_id', value=tdf.index.values)
        #  tdf['cell_specimen_id'] = tdf.index.values #add this as a column to the end
        tdf.drop(columns=['cell_roi_id'], inplace=True)
        return tdf

    def get_flash_response_df(self):
        fdf = pd.read_hdf(self.flash_response_df_path, key='df')
        fdf.reset_index(level=1, inplace=True)
        # fdf.insert(loc=0, column='cell_specimen_id', value=fdf.index.values)
        #  fdf['cell_specimen_id'] = fdf.index.values #add this as a column to the end
        fdf.drop(columns=['image_name', 'cell_roi_id'], inplace=True)
        fdf = fdf.join(self.get_stimulus_presentations(), on='flash_id', how='left')
        return fdf

    def get_extended_stimulus_presentations_df(self):
        return pd.read_hdf(self.extended_stimulus_presentations_df_path, key='df')

    def get_task_parameters(self):
        '''
        The task parameters are incorrect.
        See: https://github.com/AllenInstitute/AllenSDK/issues/637
        We need to hard-code the omitted flash fraction and stimulus duration here. 
        '''
        task_parameters = super(ExtendedNwbApi, self).get_task_parameters()
        task_parameters['omitted_flash_fraction'] = 0.05
        task_parameters['stimulus_duration_sec'] = 0.25
        return task_parameters

    def get_metadata(self):
        metadata = super(ExtendedNwbApi, self).get_metadata()

        # We want stage name in metadata for easy access by the students
        task_parameters = self.get_task_parameters()
        metadata['stage'] = task_parameters['stage']

        # metadata should not include 'session_type' because it is 'Unknown'
        metadata.pop('session_type')

        # For SWDB only
        # metadata should not include 'behavior_session_uuid' because it is not useful to students and confusing
        metadata.pop('behavior_session_uuid')

        # Rename LabTracks_ID to mouse_id to reduce student confusion
        metadata['mouse_id'] = metadata.pop('LabTracks_ID')

        return metadata

    def get_running_speed(self):
        # We want the running speed attribute to be a dataframe (like licks, rewards, etc.) instead of a 
        # RunningSpeed object. This will improve consistency for students. For SWDB we have also opted to 
        # have columns for both 'timestamps' and 'values' of things, since this is more intuitive for students
        running_speed = super(ExtendedNwbApi, self).get_running_speed()
        return pd.DataFrame({'speed': running_speed.values,
                             'timestamps': running_speed.timestamps})

    def get_trials(self, filter_aborted_trials=True):
        trials = super(ExtendedNwbApi, self).get_trials()
        stimulus_presentations = super(ExtendedNwbApi, self).get_stimulus_presentations()

        # Note: everything between dashed lines is a patch to deal with timing issues in
        # the AllenSDK
        # This should be removed in the future after issues #876 and #802 are fixed.
        # --------------------------------------------------------------------------------

        # gets start_time of next stimulus after timestamp in stimulus_presentations 
        def get_next_flash(timestamp):
            query = stimulus_presentations.query('start_time >= @timestamp')
            if len(query) > 0:
                return query.iloc[0]['start_time']
            else:
                return None
        trials['change_time'] = trials['change_time'].map(lambda x:get_next_flash(x))

        ### This method can lead to a NaN change time for any trials at the end of the session.
        ### However, aborted trials at the end of the session also don't have change times. 
        ### The safest method seems like just droping any trials that aren't covered by the
        ### stimulus_presentations
        #Using start time in case last stim is omitted
        last_stimulus_presentation = stimulus_presentations.iloc[-1]['start_time']
        trials = trials[np.logical_not(trials['stop_time'] > last_stimulus_presentation)]

        # recalculates response latency based on corrected change time and first lick time
        def recalculate_response_latency(row):
            if len(row['lick_times'] > 0) and not pd.isnull(row['change_time']):
                return row['lick_times'][0] - row['change_time']
            else:
                return np.nan
        trials['response_latency'] = trials.apply(recalculate_response_latency,axis=1)
        # -------------------------------------------------------------------------------

        # asserts that every change time exists in the stimulus_presentations table
        for change_time in trials[trials['change_time'].notna()]['change_time']:
            assert change_time in stimulus_presentations['start_time'].values

        # Return only non-aborted trials from this API by default
        if filter_aborted_trials:
            trials = trials.query('not aborted')

        # Reorder / drop some columns to make more sense to students
        trials = trials[[
            'initial_image_name',
            'change_image_name',
            'change_time',
            'lick_times',
            'response_latency',
            'reward_time',
            'go',
            'catch',
            'hit',
            'miss',
            'false_alarm',
            'correct_reject',
            'aborted',
            'auto_rewarded',
            'reward_volume',
            'start_time',
            'stop_time',
            'trial_length'
        ]]

        # Calculate reward rate per trial
        trials['reward_rate'] = calculate_reward_rate(
            response_latency=trials.response_latency,
            starttime=trials.start_time,
            window=.75,
            trial_window=25,
            initial_trials=10
        )

        # Response_binary is just whether or not they responded - e.g. true for hit or FA. 
        hit = trials['hit'].values
        fa = trials['false_alarm'].values
        trials['response_binary'] = np.logical_or(hit, fa)

        return trials

    def get_stimulus_presentations(self):
        stimulus_presentations = super(ExtendedNwbApi, self).get_stimulus_presentations()
        extended_stimulus_presentations = self.get_extended_stimulus_presentations_df()
        extended_stimulus_presentations = extended_stimulus_presentations.drop(columns = ['omitted'])
        stimulus_presentations = stimulus_presentations.join(extended_stimulus_presentations)

        # Reorder the columns returned to make more sense to students
        stimulus_presentations = stimulus_presentations[[
            'image_name',
            'image_index',
            'start_time',
            'stop_time',
            'omitted',
            'change',
            'duration',
            'licks',
            'rewards',
            'running_speed',
            'index',
            'time_from_last_lick',
            'time_from_last_reward',
            'time_from_last_change',
            'block_index',
            'image_block_repetition',
            'repeat_within_block',
            'image_set'
        ]]

        # Rename some columns to make more sense to students
        stimulus_presentations = stimulus_presentations.rename(
            columns={'index':'absolute_flash_number',
                     'running_speed':'mean_running_speed'})
        # Replace image set with A/B
        stimulus_presentations['image_set'] = self.get_task_parameters()['stage'][15]
        # Change index name for easier merge with flash_response_df
        stimulus_presentations.index.rename('flash_id', inplace=True)
        return stimulus_presentations

    def get_stimulus_templates(self):
        # super stim templates is a dict with one annoyingly-long key, so pop the val out
        stimulus_templates = super(ExtendedNwbApi, self).get_stimulus_templates()
        return stimulus_templates[list(stimulus_templates.keys())[0]]

    def get_segmentation_mask_image(self):
        # We need to binarize the segmentation mask image. Currently ROIs have values
        # between 0 and 1, but it is unclear what the values are and this will be 
        # confusing to students.
        segmentation_mask_itk = super(ExtendedNwbApi, self).get_segmentation_mask_image()
        segmentation_mask_image = ImageApi.deserialize(segmentation_mask_itk)
        segmentation_mask_image.data[segmentation_mask_image.data > 0] = 1
        segmentation_mask_itk = ImageApi.serialize(data=segmentation_mask_image.data,
                                                   spacing=segmentation_mask_image.spacing,
                                                   unit=segmentation_mask_image.unit)
        return segmentation_mask_itk

    def get_licks(self):
        # Licks column 'time' should be 'timestamps' to be consistent with rest of session
        licks = super(ExtendedNwbApi, self).get_licks()
        licks = licks.rename(columns = {'time':'timestamps'})
        return licks

    def get_rewards(self):
        # Rewards has timestamps in the index which is confusing and not consistent with the
        # rest of the session. Use a normal index and have timestamps as a column
        rewards = super(ExtendedNwbApi, self).get_rewards()
        rewards = rewards.reset_index()
        return rewards

    def get_dff_traces(self):
        # We want to drop the 'cell_roi_id' column from the dff traces dataframe
        # This is just for Friday Harbor, not for eventual inclusion in the LIMS api.
        dff_traces = super(ExtendedNwbApi, self).get_dff_traces()
        dff_traces = dff_traces.drop(columns=['cell_roi_id'])
        return dff_traces


class ExtendedBehaviorSession(BehaviorOphysSession):
    """Represents data from a single Visual Behavior Ophys imaging session.  LazyProperty attributes access the data only on the first demand, and then memoize the result for reuse.
    
    Attributes:
        ophys_experiment_id : int (LazyProperty)
            Unique identifier for this experimental session
        max_projection : allensdk.brain_observatory.behavior.image_api.Image (LazyProperty)
            2D max projection image
        stimulus_timestamps : numpy.ndarray (LazyProperty)
            Timestamps associated the stimulus presentations on the monitor 
        ophys_timestamps : numpy.ndarray (LazyProperty)
            Timestamps associated with frames captured by the microscope
        metadata : dict (LazyProperty)
            A dictionary of session-specific metadata
        dff_traces : pandas.DataFrame (LazyProperty)
            The traces of dff organized into a dataframe; index is the cell roi ids
        cell_specimen_table : pandas.DataFrame (LazyProperty)
            Cell roi information organized into a dataframe; index is the cell roi ids
        running_speed : allensdk.brain_observatory.running_speed.RunningSpeed (LazyProperty)
            NamedTuple with two fields
                timestamps : numpy.ndarray
                    Timestamps of running speed data samples
                values : np.ndarray
                    Running speed of the experimental subject (in cm / s).
        stimulus_presentations : pandas.DataFrame (LazyProperty)
            Table whose rows are stimulus presentations (i.e. a given image, for a given duration, typically 250 ms) and whose columns are presentation characteristics.
        stimulus_templates : dict (LazyProperty)
            A dictionary containing the stimulus images presented during the session keys are data set names, and values are 3D numpy arrays.
        licks : pandas.DataFrame (LazyProperty)
            A dataframe containing lick timestamps
        rewards : pandas.DataFrame (LazyProperty)
            A dataframe containing timestamps of delivered rewards
        task_parameters : dict (LazyProperty)
            A dictionary containing parameters used to define the task runtime behavior
        trials : pandas.DataFrame (LazyProperty)
            A dataframe containing behavioral trial start/stop times, and trial data
        corrected_fluorescence_traces : pandas.DataFrame (LazyProperty)
            The motion-corrected fluorescence traces organized into a dataframe; index is the cell roi ids
        average_projection : allensdk.brain_observatory.behavior.image_api.Image (LazyProperty)
            2D image of the microscope field of view, averaged across the experiment
        motion_correction : pandas.DataFrame LazyProperty
            A dataframe containing trace data used during motion correction computation

    Attributes for internal / advanced users
        running_data_df : pandas.DataFrame (LazyProperty)
            Dataframe containing various signals used to compute running speed
    """
    def __init__(self, api):

        super(ExtendedBehaviorSession, self).__init__(api)
        self.api = api

        self.trial_response_df = LazyProperty(self.api.get_trial_response_df)
        self.flash_response_df = LazyProperty(self.api.get_flash_response_df)
        self.image_index = LazyProperty(self.get_image_index)

    def get_image_index(self):
        image_index_names = self.get_stimulus_presentations().groupby('image_index').apply(
            lambda group: one(group['image_name'].unique())
        )

