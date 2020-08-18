from src.plugins.plugin import Plugin as _P
from src.plugins.plugin import CMD,Helpers
from PyQt5 import  QtWidgets, QtCore, QtGui
from functools import partial

import pyqtgraph.parametertree.parameterTypes as pTypes
import pyqtgraph as pg
from pyqtgraph.parametertree import Parameter, ParameterTree, ParameterItem, registerParameterType
import re
log = None

class Plugin(_P):
    def __init__(self, rootapp):
        super().__init__(rootapp)
        global log; log = self.rootapp.log
        self.params = self.getParamTree()
        self.plots = []

    def start(self):pass
    def stop(self):pass

    def getParamTree(self):
        p = Parameter.create(name='plotparams', type='group', children = [
        {
            'name': 'Data selection', 
            'type': 'group', 
            'children': [
                {'name': 'src dataframes', 'type': 'str', 'value': "",'readonly': True},
                {'name': 'dst axes', 'type': 'group', 'children':[]}
                ]
        },
        {
            'name': 'global options', 
            'type': 'group',
            'children': [
                {'name': 'white bg', 'type': 'bool', 'value': False},
                {'name': 'antialias', 'type': 'bool', 'value': False},
                {'name': 'fft', 'type': 'bool', 'value': False},
                ]
        },
        {
            'name': 'time sync', 
            'type': 'group',
            'children': [
                {'name': 'ch', 'type': 'str', 'value': ""},
                {'name': 'thresh', 'type': 'float', 'value': 0},
                {'name': 'crit', 'type': 'list', 'values': [">", ">=", "==", "!=", "<=", "<"]}
                ]
        },
        ScalableGroup(name="Math operations", children=[])
        ])
        p.toDict = partial(Helpers.pt2dict,p)
        return p

    def getPlotOptionWidget(self):
        t = ParameterTree()
        t.setParameters(self.params,showTop=False)
        t.params = self.params
        return t

    def plot(self, opts):
        plt = PlotWidget(opts.toDict(), self.delplot, self)
        self.rootapp.gui.addDockWidget(QtCore.Qt.TopDockWidgetArea, plt)
        plt.setFloating(True)
        self.plots.append(plt)

    def delplot(self, plt):
        self.plots.remove(plt)
        del plt

class PlotWidget(QtWidgets.QDockWidget):
    def __init__(self, opts, onClose, parent):
        super().__init__()
        self.opts = opts
        self.onClose = onClose
        self.setFloating(True)
        self.rootplugin = parent
        self.rootapp = parent.rootapp
        self.pw = self.buildGraphicsLayout()
        self.setWidget(self.pw)
        L = self.layout()
        L.setContentsMargins(0,0,0,0)
        L.setSpacing(0)
        self.plotData()
    
    def buildGraphicsLayout(self):
        return pg.GraphicsLayoutWidget()

    def plotData(self):
        if self.opts["global options"]["white bg"]: self.pw.setBackground('w')
        if self.opts["global options"]["antialias"]: self.pw.setAntialiasing(True)

        self.plots = []
        dsts = dict( (k, [[y[0],int(y[1:])] for y in v.replace(" ","").split(";")] ) for k,v in self.opts["Data selection"]["dst axes"].items())
        srcs = tuple(tuple(int(y) for y in x.split(".")) for x in self.opts["Data selection"]["src dataframes"].split(";"))
        fft = self.opts["global options"]["fft"]
        dataList = self.rootapp.plugins["data"].srcList
        dataDict = self.rootapp.plugins["data"].srcDict
        dfs = tuple(dataDict[dataList[x[0]]][x[1]] for x in srcs)

        dstList = []
        currIdx = 0
        fndmax = sum([len(x) for x in dsts.values()])
        fndcnt = 0
        while fndcnt<fndmax:
            fnd = [k for k,v in dsts.items() if any((x[1] == currIdx for x in v))]
            X = [x for x in fnd if any(y[0]=="x" for y in dsts[x])]
            Y = [x for x in fnd if any(y[0]=="y" for y in dsts[x])]
            currfnd = len(X)+len(Y)
            if currfnd:
                fndcnt+=currfnd
                if not X: X = ["index"]
                if Y: dstList.append(X+Y)
            currIdx +=1

        for row,xy in enumerate(dstList):
            p = self.pw.addPlot(row,0)
            p.addLegend()
            p.showGrid(x = True, y = True, alpha = 0.3)
            p.ctrl.fftCheck.setChecked(fft)
            if len(self.plots)>0: p.setXLink(self.plots[0])
            self.plots.append(p)

            nrofYs = len(xy)-1
            nrofplots = nrofYs*len(dfs)
            dfsyncIdxs = self.getSyncIdxs(dfs)

            for dfIdx,(srcIdxs, df,syncIdx) in enumerate(zip(srcs,dfs,dfsyncIdxs)):
                xvals = self.applyMath(df[xy[0]].values,xy[0],row,syncIdx, isX=True)
                if fft:xvals = xvals[:(len(xvals)//2)*2]
                if syncIdx is not None: xvals -= xvals[syncIdx]
                for yidx,y in enumerate(xy[1:]):
                    yvals = self.applyMath(df[y].values,y,row,syncIdx)
                    p.plot(x=xvals,y=yvals, pen = (nrofYs*dfIdx+yidx,nrofplots))

    def applyMath(self, vals, name, yaxis, idxsync, isX = False):
        math = self.opts["Math operations"]
        if not math: return vals
        for operation in math:
            sfilt = math[operation]["series filter"]
            yfilt = math[operation]["yax filter"]
            tara = math[operation]["tara"]
            norm = math[operation]["normalize"]
            gain = math[operation]["gain"]
            offset = math[operation]["offset"]

            if sfilt and not re.search(sfilt, name):continue
            if yfilt>=0 and yfilt !=yaxis:continue

            if tara == "@idx0": vals -= vals[0]
            elif tara == "@idxsync" and idxsync is not None: vals -= vals[idxsync]

            vals = vals*gain+offset

            if norm and not isX:
                vmax = abs(max(vals))
                vmin = abs(min(vals))
                vals /=max(vmax,vmin)

            bla = 1

        return vals

    def closeEvent(self, e):
        super().closeEvent(e)
        self.onClose(self)

    def getSyncIdxs(self,dfs):
        chname = self.opts["time sync"]["ch"]
        thresh = self.opts["time sync"]["thresh"]
        crit = self.opts["time sync"]["crit"]

        idxs = []
        for df in dfs:
            if chname not in df.columns: 
                idxs.append(None)
                continue
            ch = df[chname]

            if crit == ">":     sync =(ch > thresh)
            if crit == ">":     sync =(ch > thresh)
            elif crit == "<":   sync =(ch < thresh)
            elif crit == "!=":  sync =(ch != thresh)
            elif crit == "==":  sync =(ch == thresh)
            elif crit == ">=":  sync =(ch >= thresh)
            elif crit == "<=":  sync =(ch <= thresh)
            else:               sync=[0]

            if max(sync)==0:
                idxs.append(None)
                continue
            idxs.append(sync.idxmax())

        return idxs

class ScalableGroup(pTypes.GroupParameter):
    def __init__(self, **opts):
        opts['type'] = 'group'
        opts['addText'] = "Add"
        pTypes.GroupParameter.__init__(self, **opts)
    
    def addNew(self):
        self.addChild({"name":f"OP{len(self.childs)}", "type":'group', "children":[
            {"name": "series filter","type":"str","value":""},
            {"name": "yax filter","type":"int","value":-1},
            {"name": "tara","type":"list","values":["None", "@idx0", "@idxsync"]},
            {"name": "normalize","type":"bool","value":False},
            {"name": "gain","type":"float","value":1.0},
            {"name": "offset","type":"float","value":0.0},

        ],"removable":True})