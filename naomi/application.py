# -*- coding: utf-8 -*-
import logging
import os
import re
import shutil
import yaml
import pkg_resources

from . import audioengine
from . import brain
from . import paths
from . import populate
from . import pluginstore
from . import conversation
from . import mic
from . import profile
from . import local_mic
from . import batch_mic

USE_STANDARD_MIC = 0
USE_TEXT_MIC = 1
USE_BATCH_MIC = 2


class Naomi(object):
    def __init__(
        self,
        use_mic=USE_STANDARD_MIC,
        batch_file=None,
        repopulate=False,
        print_transcript=False
    ):
        self._logger = logging.getLogger(__name__)
        # Create .naomi dir if it does not exist yet
        if not os.path.exists(paths.SUB_PATH):
            try:
                os.makedirs(paths.SUB_PATH)
            except OSError:
                self._logger.error("Could not create .naomi dir: '%s'",
                                   paths.SUB_PATH, exc_info=True)
                raise

        # Check if .naomi dir is writable
        if not os.access(paths.SUB_PATH, os.W_OK):
            self._logger.critical(
                " ".join([
                    ".naomi dir {:s} is not writable. Naomi",
                    "won't work correctly."
                ]).format(
                    paths.SUB_PATH
                )
            )
        # Create .naomi/configs dir if it does not exist yet
        if not os.path.exists(paths.CONFIG_PATH):
            try:
                os.makedirs(paths.CONFIG_PATH)
            except OSError:
                self._logger.error("Could not create .naomi/configs dir: '%s'",
                                   paths.CONFIG_PATH, exc_info=True)
                raise

        # Check if .naomi/configs dir is writable
        if not os.access(paths.CONFIG_PATH, os.W_OK):
            self._logger.critical(
                " ".join([
                    ".naomi/configs dir {:s} is not writable. Naomi",
                    "won't work correctly."
                ]).format(
                    paths.CONFIG_PATH
                )
            )
        # For backwards compatibility, move old profile.yml to newly
        # created config dir
        old_configfile = paths.sub('profile.yml')
        new_configfile = os.path.join('configs','profile.yml')
        if os.path.exists(old_configfile):
            if os.path.exists(new_configfile):
                self._logger.warning(
                    " ".join([
                        "Deprecated profile file found: '{:s}'. ",
                        "Please remove it."
                    ]).sub(old_configfile)
                )
            else:
                self._logger.warning(
                    " ".join([
                        "Deprecated profile file found: '{:s}'.",
                        "Trying to move it to new location '{:s}'."
                    ]).format(
                        old_configfile,
                        new_configfile
                    )
                )
                try:
                    shutil.move(old_configfile, new_configfile)
                except shutil.Error:
                    self._logger.error(
                        " ".join([
                            "Unable to move config file.",
                            "Please move it manually.",
                            "~/.naomi/profile.yml -> ~/.naomi/configs/profile.yml"
                        ]),
                        exc_info=True
                    )
                    raise

        # Read config
        # set a loop so we can keep looping back until the config file exists
        config_read = False
        while(not config_read):
            try:
                self.config = profile.get_profile()
                config_read = True
                if(repopulate):
                    populate.run()
            except IOError:
                # AJC 2018-07-29 Changed this from a warning to debug, since
                # we attempt to fix the problem right here
                self._logger.debug(
                    "Can't open config file: '%s'" % new_configfile
                )
                # raise
                print("Your config file does not exist.")
                text_input = input(
                    " ".join([
                        "Would you like to answer a few ",
                        "questions to create a new one? "
                    ])
                )
                if(re.match(r'\s*[Yy]', text_input)):
                    populate.run({})
                else:
                    print("Cannot continue. Exiting.")
                    quit()
            except (yaml.parser.ParserError, yaml.scanner.ScannerError) as e:
                self._logger.error("Unable to parse config file: %s %s",
                                e.problem.strip(), str(e.problem_mark).strip())
                raise

        language = profile.get_profile_var(['language'])
        if(not language):
            language = 'en-US'
            self._logger.warn(
                ' '.join([
                    'language not specified in profile,',
                    'using default ({})'.format(language)
                ])
            )
        self._logger.info("Using Language '{}'".format(language))

        audio_engine_slug = profile.get_profile_var(['audio_engine'])
        if(not audio_engine_slug):
            audio_engine_slug = 'pyaudio'
            self._logger.warn(
                ' '.join([
                    "audio_engine not specified in profile, using",
                    "defaults ({}).".format(audio_engine_slug)
                ])
            )
        self._logger.info("Using Audio engine '{}'".format(audio_engine_slug))

        active_stt_slug = profile.get_profile_var(
            ['active_stt', 'engine']
        )
        if(not active_stt_slug):
            active_stt_slug = 'sphinx'
            self._logger.warning(
                " ".join([
                    "stt_engine not specified in profile,",
                    "using default ({}).".format(active_stt_slug)
                ])
            )
        self._logger.info(
            "Using STT (speech to text) engine '{}'".format(active_stt_slug)
        )

        active_stt_reply = profile.get_profile_var(
            ['active_stt', 'reply']
        )
        if(active_stt_reply):
            self._logger.info(
                "Using active STT voice reply '{}'".format(active_stt_reply)
            )

        active_stt_response = profile.get_profile_var(
            ['active_stt', 'response']
        )
        if(active_stt_response):
            self._logger.info(
                "Using active STT voice response '{}'".format(
                    active_stt_response
                )
            )

        passive_stt_slug = profile.get_profile_var(
            ['passive_stt', 'engine'],
            active_stt_slug
        )
        self._logger.info(
            "Using passive STT engine '{}'".format(passive_stt_slug)
        )

        tts_slug = profile.get_profile_var(['tts_engine'])
        if(not tts_slug):
            tts_slug = 'espeak-tts'
            self._logger.warning(
                " ".join([
                    "tts_engine not specified in profile, using",
                    "defaults."
                ])
            )
        self._logger.info("Using TTS engine '{}'".format(tts_slug))

        keyword = profile.get_profile_var(['keyword'], 'NAOMI')
        self._logger.info("Using keyword '{}'".format(keyword))

        if(not print_transcript):
            print_transcript = profile.get_profile_flag(
                ['print_transcript'],
                False
            )

        # Load plugins
        plugin_directories = [
            paths.config('plugins'),
            pkg_resources.resource_filename(__name__, '../plugins')
        ]
        self.plugins = pluginstore.PluginStore(plugin_directories)
        self.plugins.detect_plugins()

        # Initialize AudioEngine
        ae_info = self.plugins.get_plugin(
            audio_engine_slug,
            category='audioengine'
        )
        self.audio = ae_info.plugin_class(ae_info, self.config)

        # Initialize audio input device
        devices = [device.slug for device in self.audio.get_devices(
            device_type=audioengine.DEVICE_TYPE_INPUT)]
        try:
            device_slug = profile.get_profile_var(['audio', 'input_device'])
        except KeyError:
            device_slug = self.audio.get_default_device(output=False).slug
            self._logger.warning(
                " ".join([
                    "input_device not specified in profile, ",
                    "defaulting to '{:s}' (Possible values: {:s})"
                ]).format(
                    device_slug,
                    ', '.join(devices)
                )
            )
        try:
            input_device = self.audio.get_device_by_slug(device_slug)
            if audioengine.DEVICE_TYPE_INPUT not in input_device.types:
                raise audioengine.UnsupportedFormat(
                    "Audio device with slug '%s' is not an input device"
                    % input_device.slug)
        except (audioengine.DeviceException) as e:
            self._logger.critical(e.args[0])
            self._logger.warning('Valid input devices: %s',
                                 ', '.join(devices))
            raise
        input_device._input_rate = profile.get_profile_var(
            ['audio', 'input_samplerate'],
            16000
        )
        input_device._input_bits = profile.get_profile_var(
            ['audio', 'input_samplewidth'],
            16
        )
        input_device._input_channels = profile.get_profile_var(
            ['audio', 'input_channels'],
            1
        )
        input_device._input_chunksize = profile.get_profile_var(
            ['audio', 'input_chunksize'],
            1024
        )
        self._logger.debug(
            'Input sample rate: {:d} Hz'.format(
                input_device._input_rate
            )
        )
        self._logger.debug(
            'Input sample width: {:d} bit'.format(
                input_device._input_bits
            )
        )
        self._logger.debug(
            'Input channels: {:d}'.format(
                input_device._input_channels
            )
        )
        self._logger.debug(
            'Input chunksize: {:d} frames'.format(
                input_device._input_chunksize
            )
        )

        # Initialize audio output device
        devices = [device.slug for device in self.audio.get_devices(
            device_type=audioengine.DEVICE_TYPE_OUTPUT)]
        try:
            device_slug = self.config['audio']['output_device']
        except KeyError:
            device_slug = self.audio.get_default_device(output=True).slug
            self._logger.warning(
                " ".join([
                    "output_device not specified in profile,",
                    "defaulting to '{0:s}' (Possible values: {1:s})"
                ]).format(device_slug, ', '.join(devices))
            )
        try:
            output_device = self.audio.get_device_by_slug(device_slug)
            if audioengine.DEVICE_TYPE_OUTPUT not in output_device.types:
                raise audioengine.UnsupportedFormat(
                    " ".join([
                        "Audio device with slug '{:s}'",
                        "is not an output device"
                    ]).format(output_device.slug)
                )
        except (audioengine.DeviceException) as e:
            self._logger.critical(e.args[0])
            self._logger.warning(
                'Valid output devices: {:s}'.format(', '.join(devices))
            )
            raise
        output_device._output_chunksize = profile.get_profile_var(
            ['audio', 'output_chunksize'],
            1024
        )
        output_device._output_padding = profile.get_profile_flag(
            ['audio', 'output_padding'],
            False
        )
        self._logger.debug(
            'Output chunksize: {:d} frames'.format(
                output_device._output_chunksize
            )
        )
        self._logger.debug(
            'Output padding: {:s}'.format(
                'yes' if output_device._output_padding else 'no'
            )
        )

        # Initialize Voice activity detection
        vad_slug = profile.get_profile_var(['vad_engine'], 'snr_vad')
        vad_info = self.plugins.get_plugin(
            vad_slug,
            category='vad'
        )
        vad_plugin = vad_info.plugin_class(input_device)

        # Initialize Brain
        self.brain = brain.Brain(self.config)
        for info in self.plugins.get_plugins_by_category('speechhandler'):
            try:
                plugin = info.plugin_class(info, self.config)
            except Exception as e:
                self._logger.warning(
                    "Plugin '%s' skipped! (Reason: %s)", info.name,
                    e.message if hasattr(e, 'message') else 'Unknown',
                    exc_info=(
                        self._logger.getEffectiveLevel() == logging.DEBUG))
            else:
                self.brain.add_plugin(plugin)

        if len(self.brain.get_plugins()) == 0:
            msg = 'No plugins for handling speech found!'
            self._logger.error(msg)
            raise RuntimeError(msg)
        elif len(self.brain.get_all_phrases()) == 0:
            msg = 'No command phrases found!'
            self._logger.error(msg)
            raise RuntimeError(msg)

        active_stt_plugin_info = self.plugins.get_plugin(
            active_stt_slug,
            category='stt'
        )
        active_stt_plugin = active_stt_plugin_info.plugin_class(
            'default',
            self.brain.get_plugin_phrases(),
            active_stt_plugin_info,
            self.config
        )
        if(profile.check_profile_var_exists(['active_stt', 'samplerate'])):
            active_stt_plugin._samplerate = int(
                profile.get_profile_var(['active_stt', 'samplerate'])
            )
        if(profile.check_profile_var_exists(
            ['active_stt', 'volume_normalization']
        )):
            active_stt_plugin._volume_normalization = float(
                profile.get_profile_var(['active_stt', 'volume_normalization'])
            )

        if passive_stt_slug != active_stt_slug:
            passive_stt_plugin_info = self.plugins.get_plugin(
                passive_stt_slug, category='stt'
            )
        else:
            passive_stt_plugin_info = active_stt_plugin_info

        passive_stt_plugin = passive_stt_plugin_info.plugin_class(
            'keyword',
            self.brain.get_standard_phrases() + [keyword],
            passive_stt_plugin_info,
            self.config
        )

        if(profile.check_profile_var_exists(['passive_stt', 'samplerate'])):
            passive_stt_plugin._samplerate = int(
                profile.get_profile_var(['passive_stt', 'samplerate'])
            )
        if(profile.check_profile_var_exists(
            ['passive_stt', 'volume_normalization']
        )):
            passive_stt_plugin._volume_normalization = float(
                profile.get_profile_var(['passive_stt', 'volume_normalization'])
            )

        active_stt_reply = profile.get_profile_var(['active_stt', 'reply'])
        active_stt_response = profile.get_profile_var(
            ['active_stt', 'response']
        )

        tts_plugin_info = self.plugins.get_plugin(tts_slug, category='tts')
        tts_plugin = tts_plugin_info.plugin_class(tts_plugin_info, self.config)

        # Initialize Mic
        if use_mic == USE_TEXT_MIC:
            self.mic = local_mic.Mic()
            self._logger.info('Using local text input and output')
        elif use_mic == USE_BATCH_MIC:
            self.mic = batch_mic.Mic(
                passive_stt_plugin,
                active_stt_plugin,
                batch_file,
                keyword=keyword
            )
            self._logger.info('Using batched mode')
        else:
            self.mic = mic.Mic(
                input_device,
                output_device,
                active_stt_reply,
                active_stt_response,
                passive_stt_plugin,
                active_stt_plugin,
                tts_plugin,
                vad_plugin,
                self.config,
                keyword=keyword,
                print_transcript=print_transcript
            )

        self.conversation = conversation.Conversation(
            self.mic, self.brain, self.config)

    def list_plugins(self):
        plugins = self.plugins.get_plugins()
        len_name = max(len(info.name) for info in plugins)
        len_version = max(len(info.version) for info in plugins)
        for info in plugins:
            print("%s %s - %s" % (info.name.ljust(len_name),
                                  ("(v%s)" % info.version).ljust(len_version),
                                  info.description))

    def list_audio_devices(self):
        for device in self.audio.get_devices():
            device.print_device_info(
                verbose=(self._logger.getEffectiveLevel() == logging.DEBUG))

    def run(self):
        self.conversation.askName()
        self.conversation.greet()
        self.conversation.handleForever()
