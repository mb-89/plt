from PyQt5 import QtCore, QtGui, QtWidgets
import os.path as op
import json
from jsmin import jsmin
import importlib
import argparse

class GUIapp(QtWidgets.QApplication):
    def __init__(self):
        super().__init__([])

        infopath = op.join(op.dirname(__file__),"appinfo.jsonc")
        self.info = json.loads(jsmin(open(infopath,"r").read()))

        parser = argparse.ArgumentParser(description= self.info["name"]+' cmd line')
        parser.add_argument('--src', type=str, help = "load this datasrc directly after startup", default = "")
        self.args = vars(parser.parse_args())

        self.gui = Gui(self)
        self.log = None

        self.plugins = {}
        for k,v in self.info["plugins"].items():
            self.plugins[k] = importlib.import_module(v).Plugin(self)

        self.running = False
        self.aboutToQuit.connect(self.stop)

    def run(self):
        self.gui.start()
        for k,v in self.plugins.items(): v.start()
        self.running = True
        self.exec_()

    def stop(self):
        if not self.running: return
        self.running = False
        for k,v in self.plugins.items(): v.stop()
        self.quit()

    def __del__(self):
        self.stop()

class Gui(QtWidgets.QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.rootapp = app

        from src.app import gui_ui
        self.ui = gui_ui.Ui_ui()
        self.ui.setupUi(self)
        self.rootapp.setApplicationDisplayName(self.rootapp.info["name"])

    def start(self):
        #build plugin menu
        self.ui.PluginsBar = QtWidgets.QMenuBar(self.ui.menuBar)
        self.ui.PluginsMenu= QtWidgets.QMenu("Plugins", self.ui.PluginsBar)
        self.ui.PluginsMenu.plugins = {}
        self.ui.PluginsBar.addMenu(self.ui.PluginsMenu)
        self.ui.menuBar.setCornerWidget(self.ui.PluginsBar)

        #register shortcuts
        self.actions = {}
        for k,v in self.rootapp.plugins.items():
            acts = v.getActionDict()
            for actname, act in acts.items():
                self.actions[k+"."+actname] = self.registerAction(k,actname,*act)
        self.show()

    def registerAction(self, pluginname, actname, fn, shortcut = None, ToolbarEntry = None):
        action = QtWidgets.QAction(self)
        action.triggered.connect(fn)
        action.setText(actname)
        self.addAction(action)
        menu = self.ui.PluginsMenu
        plugmenu = menu.plugins.get(pluginname)
        if not plugmenu:
            plugmenu = QtWidgets.QMenu(menu)
            plugmenu.setTitle(pluginname)
            menu.plugins[pluginname] = plugmenu
            menu.addMenu(plugmenu)
        plugmenu.addAction(action)
        if shortcut: action.setShortcut(shortcut)
        return action