import numpy
import os
import pyaudio
import subprocess
import struct
import wave
import copy
import locale
import random
import xml.etree.ElementTree as etree
import posixpath as xpath
import asyncio
import json
from typing import Callable, Literal, Union
from backend.db import SQLiteDatabase
from const import *
from readonly_env import *
import readonly_env as env
from xlocale import *
from util import *
import readonly_wwise_hierarchy_140 as wwise_hierarchy_140
import readonly_wwise_hierarchy_154 as wwise_hierarchy_154
from readonly_wwise_hierarchy_154 import WwiseHierarchy_154
from readonly_wwise_hierarchy_140 import WwiseHierarchy_140
from slim import load_package
from readonly_log import logger

class VideoSource:

    def __init__(self):
        self.replacement_filepath: str = ''
        self.filepath: str = ''
        self.video_size: int = 0
        self.replacement_video_size: int = 0
        self.replacement_video_offset: int = 0
        self.stream_offset: int = 0
        self.file_id: int = 0
        self.modified: bool = False

    def get_data(self):
        if not self.modified:
            _, _, stream_data = load_package(self.filepath)
            return stream_data[self.stream_offset:self.stream_offset + self.video_size]
        else:
            with open(self.replacement_filepath, 'rb') as f:
                f.seek(self.replacement_video_offset)
                return f.read(self.replacement_video_size)

    def set_data(self, replacement_filepath: str):
        self.replacement_filepath = replacement_filepath
        self.replacement_video_size = os.path.getsize(replacement_filepath)
        self.modified = True

    def get_id(self):
        return self.file_id

class AudioSource:

    def __init__(self):
        self.data: bytearray | Literal[b''] = b''
        self.size: int = 0
        self.resource_id: int = 0
        self.short_id: int = 0
        self.modified: bool = False
        self.data_old: bytearray | Literal[b''] = b''
        self.parents: set[wwise_hierarchy_154.HircEntry | wwise_hierarchy_140.HircEntry | WwiseStream] = set()
        self.stream_type: int = 0
        self.muted = False

    def set_data(self, data: bytearray, notify_subscribers: bool=True, set_modified: bool=True):
        if not self.modified and set_modified:
            self.data_old = self.data
        self.data = data
        self.size = len(self.data)
        if notify_subscribers:
            for item in self.parents:
                if not self.modified:
                    item.raise_modified()
                    if isinstance(item, (wwise_hierarchy_154.HircEntry, wwise_hierarchy_140.HircEntry)):
                        for bank in item.soundbanks:
                            bank.raise_modified()
        if set_modified:
            self.modified = True

    def get_id(self) -> int:
        if self.stream_type == BANK:
            return self.get_short_id()
        else:
            return self.get_resource_id()

    def is_modified(self) -> bool:
        return self.modified

    def get_data(self) -> bytearray:
        if not self.muted:
            return bytearray() if self.data == b'' else self.data
        else:
            return b''

    def get_resource_id(self) -> int:
        return self.resource_id

    def get_short_id(self) -> int:
        return self.short_id

class TocHeader:

    def __init__(self):
        self.file_id = self.type_id = self.toc_data_offset = self.stream_file_offset = self.gpu_resource_offset = 0
        self.unknown1 = self.unknown2 = self.toc_data_size = self.stream_size = self.gpu_resource_size = 0
        self.unknown3 = 16
        self.unknown4 = 64
        self.entry_index = 0

    def from_memory_stream(self, stream: MemoryStream):
        self.file_id = stream.uint64_read()
        self.type_id = stream.uint64_read()
        self.toc_data_offset = stream.uint64_read()
        self.stream_file_offset = stream.uint64_read()
        self.gpu_resource_offset = stream.uint64_read()
        self.unknown1 = stream.uint64_read()
        self.unknown2 = stream.uint64_read()
        self.toc_data_size = stream.uint32_read()
        self.stream_size = stream.uint32_read()
        self.gpu_resource_size = stream.uint32_read()
        self.unknown3 = stream.uint32_read()
        self.unknown4 = stream.uint32_read()
        self.entry_index = stream.uint32_read()

    def get_data(self) -> bytes:
        return struct.pack('<QQQQQQQIIIIII', self.file_id, self.type_id, self.toc_data_offset, self.stream_file_offset, self.gpu_resource_offset, self.unknown1, self.unknown2, self.toc_data_size, self.stream_size, self.gpu_resource_size, self.unknown3, self.unknown4, self.entry_index)

class WwiseDep:

    def __init__(self):
        self.data: str = ''
        self.skip = True
        self.file_id = 0

    def from_memory_stream(self, stream: MemoryStream):
        self.offset = stream.tell()
        self.tag = stream.uint32_read()
        self.data_size = stream.uint32_read()
        self.skip = False
        self.data = stream.read(self.data_size).decode('utf-8')

    def get_data(self) -> bytes:
        return self.tag.to_bytes(4, byteorder='little') + self.data_size.to_bytes(4, byteorder='little') + self.data.encode('utf-8')

class DidxEntry:

    def __init__(self):
        self.id = self.offset = self.size = 0

    @classmethod
    def from_bytes(cls, bytes: bytes | bytearray):
        e = DidxEntry()
        e.id, e.offset, e.size = struct.unpack('<III', bytes)
        return e

    def get_data(self) -> bytes:
        return struct.pack('<III', self.id, self.offset, self.size)

class MediaIndex:

    def __init__(self):
        self.entries = {}
        self.data = {}

    def load(self, didxChunk: bytes | bytearray, dataChunk: bytes | bytearray):
        for n in range(int(len(didxChunk) / 12)):
            entry = DidxEntry.from_bytes(didxChunk[12 * n:12 * (n + 1)])
            self.entries[entry.id] = entry
            self.data[entry.id] = dataChunk[entry.offset:entry.offset + entry.size]

    def get_data(self) -> bytes:
        arr = [x.get_data() for x in self.entries.values()]
        data_arr = self.data.values()
        return b''.join(arr) + b''.join(data_arr)

class BankParser:

    def __init__(self):
        self.chunks = {}

    def load(self, bank_data: bytes | bytearray):
        self.chunks.clear()
        reader = MemoryStream()
        reader.write(bank_data)
        reader.seek(0)
        while True:
            tag = ''
            try:
                tag = reader.read(4).decode('utf-8')
            except:
                break
            size = reader.uint32_read()
            self.chunks[tag] = reader.read(size)

    def GetChunk(self, chunk_tag: str) -> bytearray:
        try:
            return self.chunks[chunk_tag]
        except:
            return bytearray()

class WwiseBank:

    def __init__(self):
        self.bank_header: bytes = b''
        self.bank_misc_data: bytes = b''
        self.modified: bool = False
        self.dep: WwiseDep | None = None
        self.modified_count: int = 0
        self.hierarchy: WwiseHierarchy_154 | None = None
        self.content: list[int] = []
        self.media_index = None
        self.file_id: int = 0

    def add_content(self, content: int):
        self.content.append(content)

    def remove_content(self, content: int):
        try:
            self.content.remove(content)
        except:
            pass

    def get_content(self) -> list[int]:
        return self.content

    def raise_modified(self):
        self.modified = True
        self.modified_count += 1

    def lower_modified(self):
        if self.modified:
            self.modified_count -= 1
            if self.modified_count == 0:
                self.modified = False

    def get_name(self) -> str:
        if self.dep == None:
            raise AssertionError('No WwiseDep instance is attached to this instance of WwiseBank')
        return self.dep.data

    def get_id(self) -> int:
        try:
            return self.file_id
        except:
            return 0

class WwiseStream:

    def __init__(self):
        self.audio_source: AudioSource | None = None
        self.modified: bool = False
        self.file_id: int = 0

    def set_source(self, audio_source: AudioSource):
        if self.audio_source != None:
            self.audio_source.parents.remove(self)
        self.audio_source = audio_source
        audio_source.parents.add(self)

    def raise_modified(self):
        self.modified = True

    def lower_modified(self):
        self.modified = False

    def get_id(self) -> int:
        try:
            return self.file_id
        except:
            return 0

    def get_data(self) -> bytearray | bytes:
        if self.audio_source == None:
            raise AssertionError(f'No audio source is attached to WwiseStream {self.file_id}')
        return self.audio_source.get_data()

class StringEntry:

    def __init__(self):
        self.text = ''
        self.text_old = ''
        self.string_id = 0
        self.modified = False
        self.parent: TextBank | None = None

    def get_id(self) -> int:
        return self.string_id

    def get_text(self) -> str:
        return self.text

    def set_text(self, text: str):
        if not self.modified:
            self.text_old = self.text
            if self.parent != None:
                self.parent.raise_modified()
        self.modified = True
        self.text = text

class TextBank:

    def to_json_obj(self) -> dict:
        return {'file_id': self.get_id(), 'language': self.get_language(), 'entries': {str(sid): entry.get_text() for sid, entry in self.entries.items()}}

    def __init__(self):
        self.file_id = 0
        self.entries = {}
        self.language = 0
        self.modified = False
        self.modified_count = 0

    def set_data(self, data: bytearray):
        self.entries.clear()
        num_entries = int.from_bytes(data[8:12], byteorder='little')
        self.language = int.from_bytes(data[12:16], byteorder='little')
        id_section_start = 16
        offset_section_start = id_section_start + 4 * num_entries
        data_section_start = offset_section_start + 4 * num_entries
        ids = data[id_section_start:offset_section_start]
        offsets = data[offset_section_start:data_section_start]
        for n in range(num_entries):
            entry = StringEntry()
            entry.parent = self
            string_id = int.from_bytes(ids[4 * n:+4 * (n + 1)], byteorder='little')
            string_offset = int.from_bytes(offsets[4 * n:4 * (n + 1)], byteorder='little')
            entry.string_id = string_id
            stopIndex = string_offset + 1
            while data[stopIndex] != 0:
                stopIndex += 1
            entry.text = data[string_offset:stopIndex].decode('utf-8')
            self.entries[string_id] = entry

    def update(self):
        pass

    def get_language(self) -> int:
        return self.language

    def is_modified(self) -> bool:
        return self.modified

    def get_id(self) -> int:
        return self.file_id

    def raise_modified(self):
        self.modified_count += 1
        self.modified = True

    def lower_modified(self):
        if self.modified:
            self.modified_count -= 1
            if self.modified_count == 0:
                self.modified = False

class GameArchive:

    def __init__(self):
        self.magic: int = -1
        self.name: str = ''
        self.num_files: int = -1
        self.num_types: int = -1
        self.path: str = ''
        self.unk4Data: bytes | bytearray = b''
        self.unknown: int = -1
        self.wwise_streams: dict[int, WwiseStream] = {}
        self.wwise_banks: dict[int, WwiseBank] = {}
        self.audio_sources: dict[int, AudioSource] = {}
        self.hierarchy_entries: dict[int, wwise_hierarchy_140.HircEntry | wwise_hierarchy_154.HircEntry] = {}
        self.video_sources: dict[int, VideoSource] = {}
        self.text_banks = {}

    @classmethod
    def from_file(cls, path: str) -> 'GameArchive':
        archive = GameArchive()
        archive.name = os.path.basename(path)
        archive.path = path
        toc_data, _, stream_data = load_package(path)
        if not toc_data:
            return None
        toc_file = MemoryStream(toc_data)
        stream_file = MemoryStream(stream_data)
        archive.load(toc_file, stream_file)
        return archive

    def get_wwise_streams(self) -> dict[int, WwiseStream]:
        return self.wwise_streams

    def get_wwise_banks(self) -> dict[int, WwiseBank]:
        return self.wwise_banks

    def get_audio_sources(self) -> dict[int, AudioSource]:
        return self.audio_sources

    def get_video_sources(self) -> dict[int, VideoSource]:
        return self.video_sources

    def get_text_banks(self) -> dict[int, TextBank]:
        return self.text_banks

    def get_hierarchy_entries(self) -> dict[int, wwise_hierarchy_140.HircEntry | wwise_hierarchy_154.HircEntry]:
        return self.hierarchy_entries

    def load(self, toc_file: MemoryStream, stream_file: MemoryStream):
        self.wwise_streams.clear()
        self.wwise_banks.clear()
        self.audio_sources.clear()
        self.video_sources.clear()
        self.text_banks.clear()
        self.hierarchy_entries.clear()
        media_index = MediaIndex()
        self.magic = toc_file.uint32_read()
        if self.magic != 4026531857:
            return False
        self.num_types = toc_file.uint32_read()
        self.num_files = toc_file.uint32_read()
        self.unknown = toc_file.uint32_read()
        self.unk4Data = toc_file.read(56)
        toc_file.seek(toc_file.tell() + 32 * self.num_types)
        toc_start = toc_file.tell()
        for n in range(self.num_files):
            toc_file.seek(toc_start + n * 80)
            toc_header = TocHeader()
            toc_header.from_memory_stream(toc_file)
            entry = None
            if toc_header.type_id == WWISE_STREAM:
                audio = AudioSource()
                audio.stream_type = STREAM
                entry = WwiseStream()
                entry.file_id = toc_header.file_id
                toc_file.seek(toc_header.toc_data_offset)
                stream_file.seek(toc_header.stream_file_offset)
                audio.set_data(stream_file.read(toc_header.stream_size), notify_subscribers=False, set_modified=False)
                audio.resource_id = toc_header.file_id
                entry.set_source(audio)
                self.wwise_streams[entry.get_id()] = entry
            elif toc_header.type_id == WWISE_BANK:
                entry = WwiseBank()
                toc_file.seek(toc_header.toc_data_offset)
                toc_file.advance(16)
                entry.file_id = toc_header.file_id
                bank = BankParser()
                bank.load(toc_file.read(toc_header.toc_data_size - 16))
                entry.bank_header = 'BKHD'.encode('utf-8') + len(bank.chunks['BKHD']).to_bytes(4, byteorder='little') + bank.chunks['BKHD']
                bank_version = int.from_bytes(bank.chunks['BKHD'][0:4], 'little') ^ BANK_VERSION_KEY
                if bank_version == 154:
                    hirc = WwiseHierarchy_154(soundbank=entry)
                else:
                    hirc = WwiseHierarchy_140(soundbank=entry)
                try:
                    hirc.load(bank.chunks['HIRC'])
                except KeyError:
                    pass
                replacements = {}
                for hirc_id, hirc_entry in hirc.entries.items():
                    if hirc_id in self.hierarchy_entries:
                        existing_entry = self.hierarchy_entries[hirc_id]
                        if isinstance(hirc_entry, (wwise_hierarchy_140.ActorMixer, wwise_hierarchy_140.SwitchContainer, wwise_hierarchy_140.RandomSequenceContainer, wwise_hierarchy_140.LayerContainer, wwise_hierarchy_140.MusicSwitchContainer, wwise_hierarchy_154.ActorMixer, wwise_hierarchy_154.SwitchContainer, wwise_hierarchy_154.RandomSequenceContainer, wwise_hierarchy_154.LayerContainer, wwise_hierarchy_154.MusicSwitchContainer)):
                            for child in hirc_entry.children.children:
                                if child not in existing_entry.children.children:
                                    existing_entry.children.children.append(child)
                                    existing_entry.children.numChildren += 1
                                    existing_entry.size += 4
                        existing_entry.soundbanks.append(entry)
                        replacements[hirc_id] = existing_entry
                    else:
                        self.hierarchy_entries[hirc_id] = hirc_entry
                for hirc_id, hirc_entry in replacements.items():
                    hirc._remove_categorized_entry(hirc.entries[hirc_id])
                    hirc._categorized_entry(hirc_entry)
                hirc.entries.update(replacements)
                entry.hierarchy = hirc
                if 'DIDX' in bank.chunks.keys():
                    new_media_index = MediaIndex()
                    new_media_index.load(bank.chunks['DIDX'], bank.chunks['DATA'])
                    new_media_index.data = {}
                    entry.media_index = list(new_media_index.entries.keys())
                    media_index.load(bank.chunks['DIDX'], bank.chunks['DATA'])
                entry.bank_misc_data = b''
                for chunk in bank.chunks.keys():
                    if chunk not in ['BKHD', 'DATA', 'DIDX', 'HIRC']:
                        entry.bank_misc_data = entry.bank_misc_data + chunk.encode('utf-8') + len(bank.chunks[chunk]).to_bytes(4, byteorder='little') + bank.chunks[chunk]
                dep = WwiseDep()
                dep.skip = True
                dep.data = f'Bank {entry.get_id()}'
                dep.file_id = toc_header.file_id
                entry.dep = dep
                self.wwise_banks[entry.get_id()] = entry
            elif toc_header.type_id == WWISE_DEP:
                dep = WwiseDep()
                dep.file_id = toc_header.file_id
                toc_file.seek(toc_header.toc_data_offset)
                dep.from_memory_stream(toc_file)
                try:
                    self.wwise_banks[toc_header.file_id].dep = dep
                except KeyError:
                    pass
            elif toc_header.type_id == TEXT_BANK:
                toc_file.seek(toc_header.toc_data_offset)
                data = toc_file.read(toc_header.toc_data_size)
                text_bank = TextBank()
                text_bank.file_id = toc_header.file_id
                text_bank.set_data(data)
                self.text_banks[text_bank.get_id()] = text_bank
            elif toc_header.type_id == BINK_VIDEO:
                new_video_source = VideoSource()
                new_video_source.file_id = toc_header.file_id
                new_video_source.stream_offset = toc_header.stream_file_offset
                new_video_source.video_size = toc_header.stream_size
                new_video_source.filepath = self.path
                self.video_sources[new_video_source.file_id] = new_video_source
        self._create_all_audio_source_objects(media_index)
        self._book_keep_audio_sources_per_bank()

    def _create_all_audio_source_objects(self, media_index: MediaIndex):
        for bank in self.wwise_banks.values():
            self._create_all_audio_source_objects_from_bank(bank, media_index)

    def _create_all_audio_source_objects_from_bank(self, bank: WwiseBank, media_index: MediaIndex):
        if bank.hierarchy == None:
            raise AssertionError(f'WwiseBank {bank.file_id} has no WwiseHierarchy')
        if bank.dep == None:
            raise AssertionError(f'WwiseBank {bank.file_id} has no WwiseDep')
        hirc = bank.hierarchy
        dep = bank.dep
        entries_with_audio_sources = hirc.get_sounds() + hirc.get_music_tracks()
        for entry_with_audio_source in entries_with_audio_sources:
            for source_struct in entry_with_audio_source.sources:
                audio_source = self._create_audio_source(source_struct, media_index, hirc, dep)
                if audio_source == None:
                    continue
                self.audio_sources[audio_source.short_id] = audio_source

    def _create_audio_source(self, source: wwise_hierarchy_140.BankSourceStruct | wwise_hierarchy_154.BankSourceStruct, media_index: MediaIndex, hirc: WwiseHierarchy_154, dep: WwiseDep) -> AudioSource | None:
        """
        Question: for REV_AUDIO, it uses media index ID. Should we use source 
        ID to check for duplication again?
        """
        source_id = source.source_id
        if source_id in self.audio_sources:
            logger.info(f'Audio source {source_id} already registered. Skipping audio source {source_id}...')
            return None
        plugin_id = source.plugin_id
        if plugin_id not in [VORBIS, REV_AUDIO]:
            logger.info(f'Audio source {source_id} has plugin ID {plugin_id}. Audio tool currently can only unpack audio source with plugin_id of {VORBIS} or {REV_AUDIO}')
            return None
        stream_type = source.stream_type
        if stream_type not in [BANK, STREAM, PREFETCH_STREAM]:
            logger.warning(f'Audio source {source_id} has stream type: {stream_type}. Audiotool currently can only unpack audio source with stream type  {BANK}, {STREAM}, or {PREFETCH_STREAM}.')
            return None
        if stream_type == BANK and plugin_id == REV_AUDIO:
            if not hirc.has_entry(source_id):
                logger.warning(f"There's no custom FX hierarchy entry associated with audio source {source_id}!")
                return None
            return self._create_audio_source_type_rev_audio(hirc.get_entry(source_id), media_index)
        if stream_type == BANK:
            if source_id not in media_index.data:
                logger.warning(f'There is no media index data associated with audio source ID {source_id}')
                return None
            return self._create_audio_source_type_bank(source, media_index)
        if stream_type in [STREAM, PREFETCH_STREAM]:
            return self._create_audio_source_type_stream(source, dep)
        raise AssertionError('Invalid code path!')

    @staticmethod
    def _create_audio_source_type_bank(source: wwise_hierarchy_140.BankSourceStruct | wwise_hierarchy_154.BankSourceStruct, media_index: MediaIndex) -> AudioSource:
        audio = AudioSource()
        audio.stream_type = BANK
        audio.short_id = source.source_id
        audio.set_data(media_index.data[source.source_id], set_modified=False, notify_subscribers=False)
        return audio

    def _create_audio_source_type_rev_audio(self, custom_fx_entry: wwise_hierarchy_140.HircEntry | wwise_hierarchy_154.HircEntry, media_index: MediaIndex) -> AudioSource | None:
        data = custom_fx_entry.get_data()
        plugin_param_size = int.from_bytes(data[13:17], byteorder='little')
        plugin_data_start = 19 + plugin_param_size
        plugin_data_end = 23 + plugin_param_size
        media_index_id = int.from_bytes(data[plugin_data_start:plugin_data_end], byteorder='little')
        if media_index_id not in media_index.data:
            logger.warning(f'There is no media index data associated with {media_index_id}')
            return None
        audio = AudioSource()
        audio.stream_type = BANK
        audio.short_id = media_index_id
        audio.set_data(media_index.data[media_index_id], set_modified=False, notify_subscribers=False)
        return audio

    def _create_audio_source_type_stream(self, source: wwise_hierarchy_140.BankSourceStruct | wwise_hierarchy_154.BankSourceStruct, dep: WwiseDep) -> AudioSource | None:
        stream_resource_id = murmur64_hash((os.path.dirname(dep.data) + '/' + str(source.source_id)).encode('utf-8'))
        if stream_resource_id not in self.wwise_streams:
            logger.warning(f'There is no WwiseStream associated with stream resource ID{stream_resource_id}')
            return None
        audio = self.wwise_streams[stream_resource_id].audio_source
        if audio == None:
            logger.warning(f'WwiseStream {stream_resource_id} has no audio source.')
            return None
        audio.short_id = source.source_id
        return audio

    def _book_keep_audio_sources_per_bank(self):
        for bank in self.wwise_banks.values():
            if bank.hierarchy == None:
                raise AssertionError(f'WwiseBank {bank.file_id} has no WwiseHierarchy')
            bank_audio_sources = bank.get_content()
            music_tracks = bank.hierarchy.get_music_tracks()
            for music_track in music_tracks:
                for info in music_track.track_info:
                    source_id = info.source_id
                    if source_id == 0:
                        continue
                    if source_id not in self.audio_sources:
                        logger.warning(f'There is no audio source associated with audio source ID {source_id}.')
                        continue
                    '\n                    TODO: determine whether if adding TrackInfoStruct into \n                    audio source\n                    '
                for source in music_track.sources:
                    if source.plugin_id != VORBIS:
                        continue
                    source_id = source.source_id
                    if source_id not in self.audio_sources:
                        logger.warning(f'Audio source {source_id} is not tracked and registered in the list of all audio sources!')
                        continue
                    self.audio_sources[source_id].parents.add(music_track)
                    if source_id not in bank_audio_sources:
                        bank.add_content(source_id)
            sounds = bank.hierarchy.get_sounds()
            for sound in sounds:
                assert_equal(f'Sound object should only one single audio source but Sound  {sound.hierarchy_id} does not.', 1, len(sound.sources))
                source = sound.sources[0]
                source_id = source.source_id
                if source_id not in self.audio_sources:
                    logger.warning(f'Audio source {source_id} is not tracked and registered in the list of all audio sources!')
                    continue
                if source.plugin_id != VORBIS:
                    continue
                audio_source = self.audio_sources[source_id]
                audio_source.parents.add(sound)
                if audio_source.get_short_id() not in bank_audio_sources:
                    bank.add_content(audio_source.get_short_id())

class SoundHandler:
    handler_instance: Union['SoundHandler', None] = None

    def __init__(self, start_func=None, update_func=None):
        self.audio_process = None
        self.wave_object = None
        self.audio_id = 0
        self.playing = False
        self.audio_file = ''
        self.wave_file = None
        self.frame_count = 0
        self.audio = pyaudio.PyAudio()
        self.update_func = update_func
        self.start_func = start_func

    @classmethod
    def create_instance(cls):
        cls.handler_instance = SoundHandler()

    @classmethod
    def get_instance(cls) -> 'SoundHandler':
        if cls.handler_instance == None:
            cls.handler_instance = SoundHandler()
        return cls.handler_instance

    def kill_sound(self):
        if self.audio_process is not None:
            if self.callback is not None:
                try:
                    self.callback()
                except:
                    pass
                self.callback = None
            self.audio_process.close()
            self.wave_file.close()
            try:
                pass
            except:
                pass
            self.audio_process = None
            self.playing = False

    def play_audio(self, sound_id: int, sound_data: bytearray, callback: Callable | None=None):
        if not os.path.exists(VGMSTREAM):
            return
        self.kill_sound()
        self.callback = callback
        if self.wave_file is not None:
            self.wave_file.close()
        if self.audio_process is not None:
            self.audio_process.close()
        if os.path.exists(self.audio_file):
            try:
                pass
            except OSError:
                pass
        filename = f'temp{sound_id}'
        if not os.path.isfile(f'{filename}.wav'):
            with open(f'{os.path.join(TMP, filename)}.wem', 'wb') as f:
                f.write(sound_data)
            process = subprocess.run([VGMSTREAM, '-o', f'{os.path.join(TMP, filename)}.wav', f'{os.path.join(TMP, filename)}.wem'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, creationflags=0x08000000)
            pass
            if process.returncode != 0:
                logger.error(f'Encountered error when converting {sound_id}.wem for playback')
                self.callback = None
                return
        self.audio_id = sound_id
        self.wave_file = wave.open(f'{os.path.join(TMP, filename)}.wav')
        self.audio_file = f'{os.path.join(TMP, filename)}.wav'
        self.frame_count = 0
        self.frame_count_timer = 0
        self.max_frames = self.wave_file.getnframes()
        if self.start_func is not None:
            self.start_func(self.max_frames / self.wave_file.getframerate())

        def read_stream(_, frame_count, __, ___):
            self.frame_count += frame_count
            self.frame_count_timer += frame_count
            if self.frame_count > self.max_frames:
                if self.callback is not None:
                    self.callback()
                return (None, pyaudio.paComplete)
            data = self.wave_file.readframes(frame_count)
            if self.wave_file.getnchannels() > 2:
                data = self.downmix_to_stereo(data, self.wave_file.getnchannels(), self.wave_file.getsampwidth(), frame_count)
            if self.update_func is not None and self.frame_count_timer > self.wave_file.getframerate() / 10:
                self.frame_count_timer = 0
                self.update_func(self.frame_count / self.wave_file.getframerate())
            return (data, pyaudio.paContinue)
        self.audio_process = self.audio.open(format=self.audio.get_format_from_width(self.wave_file.getsampwidth()), channels=min(self.wave_file.getnchannels(), 2), rate=self.wave_file.getframerate(), output=True, stream_callback=read_stream)
        self.audio_file = f'{os.path.join(TMP, filename)}.wav'
        self.playing = True

    def toggle_play_pause(self):
        if self.audio_process is not None:
            if self.playing:
                self.playing = False
                self.audio_process.stop_stream()
            elif not self.playing and self.audio_id != 0:
                self.playing = True
                self.audio_process.start_stream()

    def pause(self):
        if self.audio_process is not None:
            if self.playing:
                self.playing = False
                try:
                    self.audio_process.stop_stream()
                except:
                    self.audio_process.close()
                    self.audio_process = None

    def play(self):
        if self.audio_process is not None:
            if not self.playing and self.audio_id != 0:
                self.playing = True
                self.audio_process.start_stream()

    def seek(self, time):
        if self.wave_file is not None:
            new_frame = int(time * self.wave_file.getframerate())
            self.wave_file.setpos(new_frame)
            self.frame_count = new_frame

    def downmix_to_stereo(self, data: bytearray, channels: int, channel_width: int, frame_count: int) -> bytes:
        if channel_width == 2:
            arr = numpy.frombuffer(data, dtype=numpy.int16)
            stereo_array = numpy.zeros(shape=(frame_count, 2), dtype=numpy.int16)
        elif channel_width == 1:
            arr = numpy.frombuffer(data, dtype=numpy.int8)
            stereo_array = numpy.zeros(shape=(frame_count, 2), dtype=numpy.int8)
        elif channel_width == 4:
            arr = numpy.frombuffer(data, dtype=numpy.int32)
            stereo_array = numpy.zeros(shape=(frame_count, 2), dtype=numpy.int32)
        arr = arr.reshape((frame_count, channels))
        for index, frame in enumerate(arr):
            stereo_array[index][0] = frame[0]
            stereo_array[index][1] = frame[1]
        return stereo_array.tobytes()
