import logging
import sys
from PyQt5 import  QtWidgets, QtCore
from src.plugins.plugin import Plugin as _P

log = None

class Plugin(_P):
    def __init__(self, rootapp):
        super().__init__(rootapp)
        self.logger = Logger(rootapp)
        self.log = self.logger.log
        self.rootapp.log = self.log

    def getActionDict(self): return self.logger.getActionDict()
    def stop(self):return self.logger.stop()
    def start(self): return self.logger.start()

class Logger():
    def __init__(self, rootapp):
        #basic setup
        self.rootapp = rootapp
        global log
        log = logging.getLogger(self.rootapp.info["name"])

        self.log = log
        log.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(relativeCreated)08d %(name)s\t%(levelname)s:\t%(message)s')
        log._fmt = formatter

        #reroute stdin, stderr
        log._STDerrLogger = StreamToLogger(log, logging.ERROR)
        log._origSTDerr = sys.stderr
        log._STDoutLogger = StreamToLogger(log, logging.INFO)
        log._origSTDout = sys.stdout

        #add to file
        #fh = logging.FileHandler("workspace/msglog",mode="w")
        #fh.setLevel(logging.DEBUG)
        #fh.setFormatter(log._fmt)
        #log.addHandler(fh)

        #add to statusbar
        widget = self.rootapp.gui.ui.statusBar
        QtHandler = QtLog2StatusBarHandler()
        QtHandler.setFormatter(log._fmt)
        QtHandler.setLevel(logging.DEBUG)
        QtHandler.sig.connect(lambda x: widget.showMessage(x, 0))
        log.addHandler(QtHandler)

        #add to widget
        QtHandler = QtLog2TextEditHandler()
        QtHandler.setFormatter(log._fmt)
        QtHandler.setLevel(logging.DEBUG)
        self.logwidget = LogWidget(self.rootapp)
        QtHandler.sig.connect(self.logwidget.append)
        log.addHandler(QtHandler)

        #add to console
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(log._fmt)
        log.addHandler(ch)

    def getActionDict(self):
        return {"toggle log": (self.logwidget.togglehide, f"Ctrl+L"),}
    def stop(self):pass
    def start(self): pass

class LogWidget(QtWidgets.QDockWidget):
    def __init__(self, app):
        super().__init__()
        self.rootapp = app
        ui = app.gui.ui
        self.lw = QtWidgets.QPlainTextEdit()
        self.lw.setReadOnly(True)
        self.lw.setUndoRedoEnabled(False)
        self.lw.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
        self.hide()
        self.setWidget(self.lw)
        self.rootapp.gui.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self)
        self.resize(600,400)
        self.setWindowTitle(self.rootapp.info["name"]+' log')
        self.append = self.lw.appendPlainText

    def togglehide(self):
        self.setVisible(self.isHidden())

class StreamToLogger():
    """
    Fake file-like stream object that redirects writes to a logger instance.
    https://www.electricmonk.nl/log/2011/08/14/redirect-stdout-and-stderr-to-a-logger-in-python/
    """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):pass

class QtLog2StatusBarHandler(QtCore.QObject,logging.StreamHandler):
    sig = QtCore.pyqtSignal(str)
    def __init__(self):
        super().__init__()

    def emit(self, logRecord):
        msg = self.format(logRecord)
        self.sig.emit(msg)

class QtLog2TextEditHandler(QtCore.QObject,logging.StreamHandler):
    sig = QtCore.pyqtSignal(str)
    def __init__(self):
        super().__init__()

    def emit(self, logRecord):
        msg = self.format(logRecord)
        self.sig.emit(msg)