from PyQt5 import QtCore,QtWidgets,QtGui
import re
from functools import partial
import typing
from dataclasses import dataclass, field
import json
from enum import Enum

log = None

@dataclass
class CMD:
    IN_args : field(default_factory=dict)
    IN_callback: typing.Any = None
    OUT_retcode: int = 0
    OUT_retstr: str = ""
    OUT_result: typing.Any = None

class DATA(Enum):
    SRCIDX = QtCore.Qt.UserRole+1
    SRCSUBIDX = QtCore.Qt.UserRole+2
    ROW0 = QtCore.Qt.UserRole+3

class Plugin(QtCore.QObject):
    def __init__(self, rootapp):
        super().__init__()
        global log
        self.rootapp = rootapp
        self.log = rootapp.log
        log = self.log

    def getActionDict(self): return {}
    def stop(self): pass
    def start(self): pass

class Helpers():
    activeMappers = {}
    @staticmethod
    def chunks(lst, n):
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i:i + n]
    @staticmethod
    def pt2dict(pt):
        dct = {}
        for ch in pt.childs:
            dct[ch.name()] = Helpers.pt2dict(ch)
        if not pt.childs:
            return pt.value()
        return dct