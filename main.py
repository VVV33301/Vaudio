import sys
import json

from PyQt6.QtGui import *
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtMultimedia import *

from librosa import load, amplitude_to_db

from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

VERSION = '0.1.3'

with open('config.json', encoding='utf-8') as config_file:
    config = json.load(config_file)
    config['playlists']['~buffer~'] = []


def save_config():
    with open('config.json', 'w', encoding='utf-8') as config_file_w:
        del config['playlists']['~buffer~']
        json.dump(config, config_file_w, ensure_ascii=False)
        config['playlists']['~buffer~'] = []


def mseconds_to_time(mseconds):
    hh, mm, ss = str(mseconds // 3600000).rjust(2, '0'), str((mseconds % 3600000) // 60000).rjust(2, '0'), str(
        mseconds % 60000 // 1000).rjust(2, '0')
    return hh + ':' + mm + ':' + ss if hh != '00' else mm + ':' + ss


def qurl_to_string(qurl):
    return qurl[0].upper() + qurl[1:]


class Playlist(QAbstractTableModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._data = []
        self._notes = []
        self._header = ['№', 'Name', 'Notes']
        self.current = 0

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self._header)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return index.row() + 1
            elif index.column() == 1:
                return self._data[index.row()].fileName()
            elif index.column() == 2:
                return self._notes[index.row()]
            return None
        elif role == Qt.ItemDataRole.BackgroundRole and index.row() == self.current:
            return QBrush(QColor(225, 120, 0))

    def setData(self, index, value, role):
        if role == Qt.ItemDataRole.EditRole:
            config['playlists'][config['current_playlist']][index.row()] = (
                    qurl_to_string(self._data[index.row()].url()) + '|' + value)
            self._notes[index.row()] = value
            self.dataChanged.emit(index, index)
            return True
        return False

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._header[section]

    def insert_rows(self, row, count, value=None, notes=None, parent=QModelIndex()):
        self.beginInsertRows(parent, row, row + count - 1)
        for i in range(count):
            self._data.insert(row + i, value[i])
            self._notes.insert(row + i, notes[i])
            config['playlists'][config['current_playlist']].insert(
                row + i, qurl_to_string(value[i].url()) + '|' + notes[i])
        self.endInsertRows()

    def remove_rows(self, row, count, parent=QModelIndex()):
        self.beginRemoveRows(parent, row, row + count - 1)
        for i in range(count - 1, -1, -1):
            self._data.pop(row + i)
            config['playlists'][config['current_playlist']].pop(row + i)
        self.endRemoveRows()

    def removeRow(self, row, parent=QModelIndex()):
        self.beginRemoveRows(parent, row, row)
        self._data.pop(row)
        self.endRemoveRows()

    def flags(self, index):
        if index.column() == 2:
            return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled |
                    Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsEditable)
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled |
                Qt.ItemFlag.ItemIsDropEnabled)

    def mimeTypes(self):
        return ['text']

    def mimeData(self, indexes):
        mimedata = QMimeData()
        b = bytearray('*'.join([self._data[i.row()].url() + '|' + self._notes[i.row()] for i in indexes[::2]]).encode())
        mimedata.setData('text', b)
        return mimedata

    def dropMimeData(self, mimedata, action, row, col, parent):
        if action == Qt.DropAction.CopyAction:
            drop_data = mimedata.data('text').split(b'*')
            item_list = [b.data().decode() for b in drop_data]
            position = self._data.index(item_list[-1]) if item_list[-1] in self._data else 0
            self.remove_rows(position, len(item_list))
            data_list = [QUrl(item.split('|')[0]) for item in item_list]
            notes_list = [item.split('|')[1] for item in item_list]
            self.insert_rows(parent.row(), len(item_list), data_list, notes_list)
            save_config()
            return True

    def clear_all_data(self):
        for row in range(self.rowCount() - 1, -1, -1):
            self.removeRow(row)

    def get_url(self, index):
        return self._data[index]

    def get_data(self, index):
        return qurl_to_string(self._data[index].url()) + '|' + self._notes[index]

    def new_row(self, value_url, value_notes):
        self._data.append(value_url)
        self._notes.append(value_notes)
        self.layoutChanged.emit()


class PlaylistWidget(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent = parent
        self.setWindowTitle('Playlist')

        self.table = QTableView(self)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.table.setDragDropOverwriteMode(False)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.double_play)

        self.model = Playlist(self)
        self.table.setModel(self.model)
        self.table.setColumnWidth(0, 30)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.setWidget(self.table)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

    def add_item(self, data):
        url, notes = data.split('|')
        self.model.new_row(QUrl(url), notes)

    def change_song(self, x):
        self.model.current = (self.model.current + x) % self.model.rowCount()
        self.table.update()

    def double_play(self, index):
        self.model.current = index.row()
        self.parent.play_new()
        self.table.update()

    def get_song(self):
        return self.model.get_url(self.model.current)


class Settings(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent = parent
        self.setWindowTitle('Settings')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self.lay = QVBoxLayout()
        self.setLayout(self.lay)

        self.top_hint = QCheckBox('Top hint', self)
        self.top_hint.setChecked(config['top_hint'])
        self.top_hint.clicked.connect(self.top_hint_checked)
        self.lay.addWidget(self.top_hint)

        self.auto_load = QCheckBox('Auto load', self)
        self.auto_load.setChecked(config['auto_load'])
        self.auto_load.clicked.connect(self.auto_load_checked)
        self.lay.addWidget(self.auto_load)

        self.auto_play = QCheckBox('Auto play', self)
        self.auto_play.setChecked(config['auto_play'])
        self.auto_play.clicked.connect(self.auto_play_checked)
        self.lay.addWidget(self.auto_play)

        self.docks_movable = QCheckBox('Docks movable', self)
        self.docks_movable.clicked.connect(self.docks_movable_checked)
        self.lay.addWidget(self.docks_movable)

        self.short_cuts = QTableWidget(15, 2, self)
        self.short_cuts.verticalHeader().setVisible(False)
        self.short_cuts.setHorizontalHeaderLabels(['Action', 'Shortcut'])
        self.short_cuts.horizontalHeader().setStretchLastSection(True)
        self.short_cuts.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.short_cuts.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lay.addWidget(self.short_cuts)

        keys = tuple(config['shortcuts'].keys())
        for i in range(15):
            self.short_cuts.setItem(i, 0, QTableWidgetItem(keys[i]))
            self.short_cuts.setItem(i, 1, QTableWidgetItem(','.join(config['shortcuts'][keys[i]])))
            self.short_cuts.item(i, 0).setFlags(self.short_cuts.item(i, 0).flags() ^ Qt.ItemFlag.ItemIsEditable)
        self.short_cuts.itemChanged.connect(self.update_short_cuts)

    def top_hint_checked(self):
        config['top_hint'] = self.auto_load.isChecked()
        self.close()
        self.parent.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.top_hint.isChecked())
        self.parent.show()
        self.show()
        save_config()

    def auto_load_checked(self):
        config['auto_load'] = self.auto_load.isChecked()
        save_config()

    def auto_play_checked(self):
        config['auto_play'] = self.auto_play.isChecked()
        save_config()

    def docks_movable_checked(self):
        for dock in self.parent.findChildren(QDockWidget):
            dock.setFeatures(dock.features() ^ QDockWidget.DockWidgetFeature.DockWidgetFloatable)

    def update_short_cuts(self, sc: QTableWidgetItem):
        sc_name = self.short_cuts.item(sc.row(), 0).text()
        a = config['shortcuts'][sc_name] = sc.text().strip().split(',')
        save_config()
        self.parent.menu.findChild(QAction, sc_name).setShortcuts(a)


class Actions(QMenuBar):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent: MainWindow = parent

        self.previous = QAction('Previous', self)
        self.previous.setObjectName('previous')
        self.previous.setShortcuts(config['shortcuts']['previous'])
        self.previous.triggered.connect(self.parent.previous_song)

        self.next = QAction('Next', self)
        self.next.setObjectName('next')
        self.next.setShortcuts(config['shortcuts']['next'])
        self.next.triggered.connect(self.parent.next_song)

        self.play = QAction('Play', self)
        self.play.setObjectName('play')
        self.play.setShortcuts(config['shortcuts']['play'])
        self.play.triggered.connect(self.parent.play)

        self.stop = QAction('Stop', self)
        self.stop.setObjectName('stop')
        self.stop.setShortcuts(config['shortcuts']['stop'])
        self.stop.triggered.connect(self.parent.player.stop)

        self.repeat = QAction('Repeat', self)
        self.repeat.setObjectName('repeat')
        self.repeat.setShortcuts(config['shortcuts']['repeat'])
        self.repeat.triggered.connect(self.parent.repeat)

        self.plus = QAction('Plus', self)
        self.plus.setObjectName('plus')
        self.plus.setShortcuts(config['shortcuts']['plus'])
        self.plus.triggered.connect(
            lambda: self.parent.volume_pr.slider.setValue(self.parent.volume_pr.slider.value() + 4))

        self.minus = QAction('Minus', self)
        self.minus.setObjectName('minus')
        self.minus.setShortcuts(config['shortcuts']['minus'])
        self.minus.triggered.connect(
            lambda: self.parent.volume_pr.slider.setValue(self.parent.volume_pr.slider.value() - 4))

        self.add = QAction('Add', self)
        self.add.setObjectName('add')
        self.add.setShortcuts(config['shortcuts']['add'])
        self.add.triggered.connect(self.parent.open_songs)

        self.remove = QAction('Remove', self)
        self.remove.setObjectName('remove')
        self.remove.setShortcuts(config['shortcuts']['remove'])
        self.remove.triggered.connect(self.parent.delete_song)

        self.settings = QAction('Settings', self)
        self.settings.setObjectName('settings')
        self.settings.setShortcuts(config['shortcuts']['settings'])
        self.settings.triggered.connect(self.parent.settings.exec)

        self.open = QAction('Open', self)
        self.open.setObjectName('open')
        self.open.setShortcuts(config['shortcuts']['open'])
        self.open.triggered.connect(self.parent.open_playlist)

        self.new = QAction('New', self)
        self.new.setObjectName('new')
        self.new.setShortcuts(config['shortcuts']['new'])
        self.new.triggered.connect(self.parent.new_playlist)

        self.save = QAction('Save', self)
        self.save.setObjectName('save')
        self.save.setShortcuts(config['shortcuts']['save'])
        self.save.triggered.connect(self.parent.save_playlist)

        self.close = QAction('Close', self)
        self.close.setObjectName('close')
        self.close.setShortcuts(config['shortcuts']['close'])
        self.close.triggered.connect(self.parent.close_playlist)

        self.delete = QAction('Delete', self)
        self.delete.setObjectName('delete')
        self.delete.setShortcuts(config['shortcuts']['delete'])
        self.delete.triggered.connect(self.parent.delete_playlist)

        self.pl_menu = QMenu('Playlists', self)
        self.pl_menu.addAction(self.new)
        self.pl_menu.addAction(self.open)
        self.pl_menu.addAction(self.save)
        self.pl_menu.addAction(self.close)
        self.pl_menu.addAction(self.delete)
        self.addMenu(self.pl_menu)

        self.s_menu = QMenu('Songs', self)
        self.s_menu.addAction(self.add)
        self.s_menu.addAction(self.remove)
        self.addMenu(self.s_menu)

        self.addAction(self.settings)

        self.ex_menu = QMenu(self)
        self.ex_menu.addAction(self.previous)
        self.ex_menu.addAction(self.play)
        self.ex_menu.addAction(self.next)
        self.ex_menu.addAction(self.stop)
        self.ex_menu.addAction(self.repeat)
        self.ex_menu.addAction(self.minus)
        self.ex_menu.addAction(self.plus)
        self.addMenu(self.ex_menu)


class VolumeSlider(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent = parent
        self.setWindowTitle('Volume')

        self.slider = QSlider(self)
        self.slider.setRange(0, 100)

        self.slider.setLayout(QVBoxLayout(self.slider))
        self.vol = QLabel(self.slider)
        self.slider.layout().addWidget(self.vol)

        self.slider.valueChanged.connect(self.value_changed)

        self.setWidget(self.slider)
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)

        self.setMinimumWidth(70)
        self.setMaximumWidth(105)
        self.slider.setMaximumWidth(105)

    def value_changed(self):
        self.parent.audio.setVolume(self.slider.value() / 100)
        self.vol.setText(f'{self.slider.value()}%')

    def resizeEvent(self, event):
        self.slider.resize(event.size().width(), self.slider.geometry().height())


class SystemVolumeSlider(VolumeSlider):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle('System')

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        self.volume_object = cast(interface, POINTER(IAudioEndpointVolume))

    def value_changed(self):
        self.volume_object.SetMasterVolumeLevelScalar(self.slider.value() / 100, None)
        self.vol.setText(f'{self.slider.value()}%')


class Progress(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle('Not media loaded')
        self.parent = parent
        self.setMinimumHeight(60)

        self.wgt = QWidget(self)
        self.wgtlay = QGridLayout(self.wgt)
        self.wgt.setLayout(self.wgtlay)

        self.progress_bar = QSlider(Qt.Orientation.Horizontal, self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.actionTriggered.connect(lambda: self.parent.player.setPosition(self.progress_bar.value()))
        self.parent.player.positionChanged.connect(self.song_position)
        self.parent.player.durationChanged.connect(self.song_duration)
        self.parent.player.sourceChanged.connect(lambda: self.setWindowTitle(self.parent.player.source().fileName()))
        self.wgtlay.addWidget(self.progress_bar, 0, 0, 1, 10)

        self.position = QLabel('00:00', self)
        self.wgtlay.addWidget(self.position, 1, 0, 1, 1)

        self.stop_btn = QPushButton('#', self)
        self.stop_btn.clicked.connect(self.parent.player.stop)
        self.wgtlay.addWidget(self.stop_btn, 1, 1, 1, 1)

        self.previous_btn = QPushButton('<', self)
        self.previous_btn.clicked.connect(self.parent.previous_song)
        self.wgtlay.addWidget(self.previous_btn, 1, 2, 1, 2)

        self.play_btn = QPushButton('=', self)
        self.play_btn.clicked.connect(self.parent.play)
        self.wgtlay.addWidget(self.play_btn, 1, 4, 1, 2)

        self.next_btn = QPushButton('>', self)
        self.next_btn.clicked.connect(self.parent.next_song)
        self.wgtlay.addWidget(self.next_btn, 1, 6, 1, 2)

        self.repeat_btn = QPushButton('-', self)
        self.repeat_btn.clicked.connect(self.parent.repeat)
        self.wgtlay.addWidget(self.repeat_btn, 1, 8, 1, 1)

        self.duration = QLabel('00:00', self)
        self.wgtlay.addWidget(self.duration, 1, 9, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)

        self.setWidget(self.wgt)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)

    def song_position(self):
        self.progress_bar.setValue(tm := self.parent.player.position())
        self.position.setText(mseconds_to_time(tm))

    def song_duration(self):
        self.progress_bar.setMaximum(tm := self.parent.player.duration())
        self.duration.setText(mseconds_to_time(tm))


class AudioVisualization(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle('Visualization')
        self.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.setMinimumWidth(80)
        self.setMaximumWidth(120)

        self.wgt = QWidget(self)
        self.wgtlay = QHBoxLayout()
        self.wgt.setLayout(self.wgtlay)
        self.setWidget(self.wgt)

        self.value_left = QProgressBar(self)
        self.value_left.setOrientation(Qt.Orientation.Vertical)
        self.value_left.setRange(-60, 0)
        self.wgtlay.addWidget(self.value_left)

        self.value_right = QProgressBar(self)
        self.value_right.setOrientation(Qt.Orientation.Vertical)
        self.value_right.setRange(-60, 0)
        self.wgtlay.addWidget(self.value_right)

        self.parent.player.sourceChanged.connect(self.set_data)
        self.parent.player.positionChanged.connect(self.update_data)

    def update_data(self, pos):
        try:
            self.value_left.setValue(int(self.data_left[pos]))
            self.value_right.setValue(int(self.data_right[pos]))
        except Exception:
            self.value_left.setValue(-60)
            self.value_right.setValue(-60)

    def set_data(self):
        try:
            data, sample_rate = load(self.parent.player.source().url(), sr=None, mono=False)
        except Exception:
            data, sample_rate = [[0], [0]], 1000
        self.data_left = amplitude_to_db(data[0][::sample_rate // 1000])
        self.data_right = amplitude_to_db(data[1][::sample_rate // 1000])


class MediaInfo(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent: MainWindow = parent
        self.setWindowTitle('Information')
        self.parent.player.metaDataChanged.connect(self.update_info)

        self.wgt = QWidget(self)
        self.wgtlay = QGridLayout(self.wgt)
        self.wgt.setLayout(self.wgtlay)

        self.filepath = QLabel(self)
        self.wgtlay.addWidget(self.filepath)

        self.or_name = QLabel(self)
        self.wgtlay.addWidget(self.or_name)

        self.setWidget(self.wgt)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetClosable)

    def update_info(self):
        self.filepath.setText(self.parent.player.source().url())
        meta = self.parent.player.metaData()
        self.or_name.setText(meta.value(QMediaMetaData.Key.Title))
        if self.or_name.text() == '':
            self.or_name.setText(self.parent.player.source().fileName())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Vaudio v%s' % VERSION)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, config['top_hint'])
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks)
        self.setMinimumSize(600, 300)

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.audio_d = QAudioDecoder()
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self.media_status)

        self.is_repeat = False

        self.settings = Settings(self)
        self.menu = Actions(self)
        self.setMenuBar(self.menu)

        self.table = PlaylistWidget(self)
        self.progress_bar = Progress(self)
        self.info = MediaInfo(self)
        self.visualize = AudioVisualization(self)

        self.volume_pr = VolumeSlider(self)
        self.volume_pr.slider.setValue(config['volume'])
        self.volume_sys = SystemVolumeSlider(self)
        self.volume_sys.slider.setValue(int(round(self.volume_sys.volume_object.GetMasterVolumeLevelScalar() * 100, 0)))

        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.volume_sys)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.volume_pr)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.table)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.visualize)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.info)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.progress_bar)

        self.load_playlist(config['current_playlist'])

    def add_song(self, song):
        self.table.add_item(song)

    def load_playlist(self, playlist_name):
        config['current_playlist'] = playlist_name
        self.table.model.clear_all_data()
        if playlist_name != '~buffer~':
            for song in config['playlists'][playlist_name]:
                self.add_song(song)
            if config['auto_load'] and self.table.model.rowCount():
                self.player.setSource(QUrl(config['playlists'][playlist_name][0].split('|')[0]))
            self.table.setWindowTitle('Playlist ' + playlist_name)
        else:
            self.table.setWindowTitle('Buffer mode')

    def play(self):
        if not self.player.isPlaying():
            self.player.play()
        else:
            self.player.pause()

    def play_new(self):
        self.player.setSource(self.table.get_song())
        self.player.play()

    def repeat(self):
        self.is_repeat = not self.is_repeat
        self.progress_bar.repeat_btn.setText('@' if self.is_repeat else '-')

    def next_song(self):
        if self.table.model.rowCount():
            self.table.change_song(1)
            self.play_new()

    def previous_song(self):
        if self.table.model.rowCount():
            self.table.change_song(-1)
            self.play_new()

    def media_status(self, status):
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.progress_bar.setWindowTitle('Invalid media. Please try again')
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.is_repeat:
                self.play()
            elif config['auto_play'] and self.table.model.rowCount():
                self.table.change_song(1)
                self.play_new()
            elif config['auto_load'] and self.table.model.rowCount():
                self.table.change_song(1)
                self.player.setSource(self.table.get_song())

    def open_songs(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Add Songs', '/',
                                                'Supported media files(*.mp3 *.wav);;All Files (*.*)')
        if files:
            for file in files:
                self.add_song(file + '|')
                config['playlists'][config['current_playlist']].append(file + '|')

    def delete_song(self):
        for song in sorted(self.table.table.selectionModel().selectedRows(), reverse=True):
            config['playlists'][config['current_playlist']].remove(self.table.model.get_data(song.row()))
            self.table.model.removeRow(song.row())

    def new_playlist(self):
        name, _ = QInputDialog.getText(self, 'New playlist', 'Print playlist name:')
        if name:
            if name not in config['playlists'].keys():
                config['playlists'][name] = []
                save_config()
                self.load_playlist(name)
            else:
                QMessageBox.warning(self, 'Creating playlist error', 'Current playlist already exists')

    def open_playlist(self):
        lst = tuple(config['playlists'].keys())
        name, _ = QInputDialog.getItem(self, 'Open playlist', 'Select playlist:', lst, lst.index('~buffer~'), False)
        if name:
            self.load_playlist(name)

    def save_playlist(self):
        save_config()

    def close_playlist(self):
        save_config()
        self.load_playlist('~buffer~')

    def delete_playlist(self):
        if config['current_playlist'] != '~buffer~':
            del config['playlists'][config['current_playlist']]
            save_config()

    def dragEnterEvent(self, a0):
        if a0.mimeData().hasUrls():
            a0.accept()

    def dropEvent(self, a0):
        for url in map(lambda u: u.url().replace('file:///', ''), a0.mimeData().urls()):
            self.add_song(url + '|')
            config['playlists'][config['current_playlist']].append(url + '|')

    def closeEvent(self, event):
        config['volume'] = self.volume_pr.slider.value()
        save_config()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
