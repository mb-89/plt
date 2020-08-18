from src.plugins.plugin import Plugin as _P
from src.plugins.plugin import CMD, DATA
from PyQt5 import  QtWidgets, QtCore, QtGui
import time
from functools import partial
from lxml import etree
import os.path as op
import numpy as np
import pandas as pd
import re

log = None

class Plugin(_P):
    killWorker = QtCore.pyqtSignal()
    def __init__(self, rootapp):
        super().__init__(rootapp)
        global log; log = self.rootapp.log
        self.srcDict = {}
        self.srcList = []

        self.worker = DataBackgroundworker(self)
        self.workerThread = QtCore.QThread()
        self.worker.moveToThread(self.workerThread)
        self.workerThread.started.connect(self.worker.run)
        self.worker.done.connect(self.workerDone)
        self.killWorker.connect(self.worker.kill)

        self.widget = DataWidget(self)

    def start(self):
        self.workerThread.start()
        path = self.rootapp.args["src"]
        if path: QtCore.QTimer.singleShot(0, lambda: self.widget.parsefile(path))

    def stop(self):
        self.killWorker.emit()
        self.workerThread.quit()

    def workerDone(self, cmd):
        if cmd.IN_callback: cmd.IN_callback(cmd.OUT_result)

    def runcmd(self, cmd):
        self.worker.execCMD(cmd)

    def getActionDict(self):
        return {"plot selected data": (self.widget.sendplotCMD, f"Ctrl+P"),}

class DataBackgroundworker(QtCore.QObject):
    done = QtCore.pyqtSignal(CMD)
    def __init__(self,parent):
        super().__init__()
        self.cmdqueue = []
        self.killed = False
        self.rootapp = parent.rootapp
        self.rootplugin = parent
    def kill(self):
        self.killed = True
    def execCMD(self, cmd):
        self.cmdqueue.append(cmd)
    def run(self):
        while not self.killed:
            if not self.cmdqueue: 
                time.sleep(0.1)
            else:
                cmd = self.cmdqueue.pop(0)
                self._exec(cmd)
                self.done.emit(cmd)
    def _exec(self,cmd):
        args = cmd.IN_args
        if args["cmd"] == "parse": 
            self.parse(cmd, args)
        else:
            cmd.OUT_result = None
            cmd.OUT_retcode = -1
            cmd.OUT_retstr = "unknown cmd"
        if cmd.OUT_retcode != 0:
            log.error(f"command <{args['cmd']}> returned {cmd.OUT_retcode}/{cmd.OUT_retstr}")

    def parse(self, cmd, args):
        cmd.OUT_retcode = 0
        cmd.OUT_retstr = "ok"
        filename = args["path"]

        if filename.endswith(".xml"):
            #peek and see if its a visionxml file:
            isVisionXML = False
            rootxml = etree.parse(filename).getroot()
            isVisionXML = rootxml.tag == "DataSet"

            if isVisionXML: cmd.OUT_result = self.parseVisionXML(filename, rootxml)
            
            if cmd.OUT_result:
                self.postprocessDataFrames(cmd.OUT_result)

        if cmd.OUT_result == None:
            cmd.OUT_retcode = -2
            cmd.OUT_retstr = "unknown file format"

    def postprocessDataFrames(self, dfs):
        for df in dfs:
            try: df.attribs = {} #we need to work on this. dataframes do not support metadata natively
            except UserWarning:pass
            constcols = tuple(x for x in df.columns if df[x].nunique()==1)
            for cc in constcols:
                name = cc
                val = df[name].iloc[0]
                df.attribs[name] = val
                del df[name]

    def parseVisionXML(self, filename, xml):
        dirname = op.dirname(filename)
        dataframes = []
        log.info(f"started parsing {op.basename(filename)} (visionxml)")

        #first, clean up the xml and resolve all children:
        xml = xml.find("VisionStructure")
        self._recursiveResolveXMLchildren(xml, dirname)
        
        #get all mass data files
        massData = []
        for record in (x for x in xml.iter("AssociatedRecord") if x.find("Name").text == "MassData"):
            path = [record.find("RecordRef").text]
            target = record.getparent()
            columnInfo = target.getparent().find("Private").find("Columns")
            while target != xml:
                nameelem = target.find("RecordRef")
                if nameelem is not None:
                    path.append(op.dirname(target.find("RecordRef").text))
                target=target.getparent()
            path = op.join(dirname, *reversed(path))
            if op.isfile(path) and op.getsize(path):
                massData.append((path,columnInfo))

        #parse all data matrices
        L = len(massData)
        idx = 0
        for f, cols in massData:
            basename = op.basename(op.dirname(f))
            log.info(f"extracting datamatrix {f}...")
            dtypes = self.getdtypes(cols)
            data = np.fromfile(f, dtype=dtypes)
            df = pd.DataFrame(data)
            cols = [c for c in df.columns if not c.startswith("$pad")]
            df = df[cols]

            #find time skips in col 0 (which is always time)
            #and split the frame from there
            dT = (df.iloc[3,0]-df.iloc[0,0])/3
            skipIndices = (df.iloc[:,0].diff()>(dT*5))
            skipsAt = list(skipIndices[skipIndices].index)+[-1]

            start = 0
            for end in skipsAt:
                chunk = df[start:end]
                chunk.reset_index(inplace=True)
                chunk["index"]-=chunk["index"].iloc[0]
                chunk.name = basename+f".{idx}"
                dataframes.append(chunk)
                idx+=1
                start = end

        log.info(f"done parsing {op.basename(filename)}, extracted {len(dataframes)} dataframes")
        return dataframes

    def getdtypes(self, cols):
        dtypeListlist = []
        dt = np.dtype([('a', 'i4'), ('b', 'i4'), ('c', 'i4'), ('d', 'f4'), ('e', 'i4'),
                    ('f', 'i4', (256,))])

        colnames = []
        nrOfplaceHolders = 0
        for col in cols.iter("Column"):

            quantityName = col.find("Quantity").text
            signame = col.find("Signal").text.replace("\\","")
            unit = col.find("Unit").text
            fullname = signame+"_"+quantityName#+"_"+unit
            if   quantityName is None:
                raise UserWarning("invalid rawdata")

            elif quantityName == "Logical":
                dtypeListlist.append((fullname,'b'))
                dtypeListlist.append((f"$pad{nrOfplaceHolders}",'V7'))
                nrOfplaceHolders+=1
                #mask="b7x"

            elif quantityName in ["Integer", "Integer Flag"]:
                dtypeListlist.append((f"$pad{nrOfplaceHolders}",'V4'))
                dtypeListlist.append((fullname,'i4'))
                nrOfplaceHolders+=1

            elif quantityName in "Text":
                #dtypeListlist.append((fullname,'i4'))
                dtypeListlist.append((f"$pad{nrOfplaceHolders}",'V8'))
                nrOfplaceHolders+=1

            else:
                type = np.dtype('d')
                dtypeListlist.append((fullname,type))

        return np.dtype(dtypeListlist)

    def _recursiveResolveXMLchildren(self, xml, dirname):
        for ch in list(xml.iterchildren("Child")):
            file = op.join(dirname, ch.find("RecordRef").text)
            tmproot = etree.parse(file).getroot()
            chxml = tmproot
            #if not chxml: continue
            #tmproot.remove(chxml)
            namechild = etree.SubElement(chxml, "Name")
            namechild.text = ch.find("Name").text
            recordchild = etree.SubElement(chxml, "RecordRef")
            recordchild.text = ch.find("RecordRef").text
            xml.remove(ch)
            chxml.tag = namechild.text
            xml.append(chxml)

class DataWidget(QtWidgets.QDockWidget):
    def __init__(self, parent):
        super().__init__()
        self.rootapp = parent.rootapp
        self.rootplugin = parent
        ui = self.rootapp.gui.ui
        self.w = self.buildWidget()
        self.setWidget(self.w)
        self.rootapp.gui.setCentralWidget(self)
        self.setWindowTitle('data')

    def buildWidget(self):
        w = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout()
        L.setContentsMargins(0,0,0,0)
        L.setSpacing(0)
        S = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        L.addWidget(S)
        w.setLayout(L)

        datasrcview = Datasrcview()
        datasrcview.fileDropped.connect(self.parsefile)
        datasrcmdl = QtGui.QStandardItemModel()
        datasrcmdl.appendRow(QtGui.QStandardItem("<drop files here>"))
        datasrcview.setModel(datasrcmdl)
        datasrcview.selectionModel().selectionChanged.connect(self.displayselectedfiles)
        datasrcview.selectionModel().selectionChanged.connect(self.addselectedfiles2params)
        datasrcview.setHeaderHidden(True)
        S.addWidget(datasrcview)

        T = QtWidgets.QTabWidget()

        seriesview = QtWidgets.QTreeView()
        seriesview.setAlternatingRowColors(True)
        seriesmdl = QtGui.QStandardItemModel()
        sortedseriesmdl = QtCore.QSortFilterProxyModel()
        seriesview.setModel(sortedseriesmdl)
        sortedseriesmdl.setSourceModel(seriesmdl)
        T.addTab(seriesview,"series")
        seriesmdl.dataChanged.connect(self.addselectedseries2params)

        attribview = QtWidgets.QTreeView()
        attribview.setAlternatingRowColors(True)
        attribmdl = QtGui.QStandardItemModel()
        sortedattribmdl = QtCore.QSortFilterProxyModel()
        attribview.setModel(sortedattribmdl)
        sortedattribmdl.setSourceModel(attribmdl)

        T.addTab(attribview,"attribs")
        S.addWidget(T)

        self.opt = self.rootapp.plugins["plotter"].getPlotOptionWidget()
        self.plt = QtWidgets.QPushButton("plot")
        selfdockollectplt = QtWidgets.QPushButton("dock plots")
        self.plt.clicked.connect(self.sendplotCMD)
        selfdockollectplt.clicked.connect(self.dockplots)
        W2 = QtWidgets.QWidget()
        L2 = QtWidgets.QHBoxLayout()
        L2.addWidget(self.plt)
        L2.addWidget(selfdockollectplt)
        L2.setContentsMargins(0,0,0,0)
        L2.setSpacing(0)
        W2.setLayout(L2)

        S.addWidget(self.opt)
        S.addWidget(W2)

        self.datasrcmdl = datasrcmdl
        self.datasrcview = datasrcview
        self.seriesmdl = seriesmdl
        self.seriesview = seriesview
        self.attribmdl = attribmdl
        self.attribview= attribview

        self.displaydataframedetails([])

        return w

    def dockplots(self):
        for plt in self.rootapp.plugins["plotter"].plots:
            self.rootapp.gui.addDockWidget(QtCore.Qt.TopDockWidgetArea, plt)
            plt.setFloating(False)

    def sendplotCMD(self):
        para = self.opt.params
        if not len(para.param("Data selection").param("dst axes").childs):return
        if not para.param("Data selection").param("src dataframes").value():return
        self.rootapp.plugins["plotter"].plot(para)

    def parsefile(self, path, _ret = None):
        if _ret is None:
            parsedData = self.rootplugin.srcDict.get(path)
            if parsedData is None:
                self.rootplugin.srcDict[path] = []
                args = {"cmd": "parse","path": path}
                cb = partial(self.parsefile, path)
                cmd = CMD(args, cb)
                self.rootplugin.runcmd(cmd)
        else:
            self.rootplugin.srcDict[path] = _ret
            if _ret:
                if not self.rootplugin.srcList:self.datasrcmdl.clear()
                self.rootplugin.srcList.append(path)
                nr = self.datasrcmdl.rowCount()
                newItem = QtGui.QStandardItem(f"[{nr}] {path}")
                for idx,df in enumerate(_ret):
                    newChild = QtGui.QStandardItem(f"[{nr}.{idx}] {df.name}")
                    newChild.setData(nr, DATA.SRCIDX.value)
                    newChild.setData(idx, DATA.SRCSUBIDX.value)
                    newItem.appendRow(newChild)
                self.datasrcmdl.appendRow(newItem)
                self.displayselectedfiles()
    
    def displayselectedfiles(self):
        selectedIDXs = self.datasrcview.selectedIndexes()
        if len(selectedIDXs)<1:
            self.displaydataframedetails([])
            return
        paths = []
        for idx in selectedIDXs:
            item = self.datasrcmdl.itemFromIndex(idx)
            paths.append( (  item.data(DATA.SRCIDX.value), item.data(DATA.SRCSUBIDX.value)  ) )
            for chIdx in range(item.rowCount()):
                ch = item.child(chIdx)
                paths.append( (  ch.data(DATA.SRCIDX.value), ch.data(DATA.SRCSUBIDX.value)  ) )
        paths = [x for x in paths if x[0] is not None]

        self.datasrcview.resizeColumnToContents(0)
        self.displaydataframedetails(paths)

    def displaydataframedetails(self, dfs):
        self.attribmdl.clear()
        self.seriesmdl.setHorizontalHeaderLabels(["series", "dst axes (x1,y1,...)"])
        self.attribmdl.setHorizontalHeaderLabels(["attrib", "vals"])
        self.seriesmdl.setColumnCount(2)
        self.attribmdl.setColumnCount(2)

        if not dfs:
            self.seriesmdl.clear()
            self.seriesmdl.setHorizontalHeaderLabels(["series", "dst axes (x1,y1,...)"])
            self.seriesmdl.appendRow(QtGui.QStandardItem("<no src selected>"))
            self.attribmdl.appendRow(QtGui.QStandardItem("<no src selected>"))
            self.seriesview.resizeColumnToContents(0)
            self.attribview.resizeColumnToContents(0)
            self.addselectedseries2params()
            return

        srcs = self.rootplugin.srcDict
        srcL = self.rootplugin.srcList
        dfIdxs = dfs
        dfs = tuple(srcs[srcL[x[0]]][x[1]] for x in dfs)

        #update series -----------------------------------------------------------------------------
        newcols = []
        for df in dfs: newcols.extend(df.columns)
        newcols = tuple(set(newcols))

        existingCols = {}
        sroot = self.seriesmdl.invisibleRootItem()
        for idx in range(sroot.rowCount()):
            item = sroot.child(idx)
            if not item:continue
            existingCols[item.text()] = item
            
        for ex in list(existingCols.keys()):
            if ex not in newcols:
                item = existingCols.pop(ex)
                sroot.removeRow(item.row())

        for nc in newcols:
            if nc not in existingCols:
                item = QtGui.QStandardItem(nc)
                #item.setEditable(False)
                pltitem = QtGui.QStandardItem("")

                item.setData(   item, DATA.ROW0.value)
                pltitem.setData(item, DATA.ROW0.value)
                sroot.appendRow([item,pltitem])

        self.seriesview.model().sort(0)

        #update attribs ----------------------------------------------------------------------------
        attribs = {}
        header = ["attrib"]
        for df,dfIdx in zip(dfs,dfIdxs):
            header.append(f"val@df[{dfIdx[0]}.{dfIdx[1]}]")
            for k,v in df.attribs.items():
                target = attribs.setdefault(k,[])
                target.append(v)
                attribs[k] = target
        aroot = self.attribmdl.invisibleRootItem()
        self.attribmdl.setColumnCount(len(dfs)+1)
        self.attribmdl.setHorizontalHeaderLabels(header)

        for k in sorted(attribs.keys()):
            nameitem = QtGui.QStandardItem(k)
            vals = [QtGui.QStandardItem(f"{x.attribs.get(k)}") for x in dfs]
            aroot.appendRow([nameitem]+vals)

        self.seriesview.resizeColumnToContents(0)
        self.attribview.resizeColumnToContents(0)
        self.addselectedseries2params()

    def addselectedseries2params(self, unused1 = None, unused2 = None):
        root = self.seriesmdl.invisibleRootItem()
        newdstDict = {}
        params = self.rootapp.plugins["plotter"].params.param("Data selection").param("dst axes")
        params.clearChildren()

        for idx in range(root.rowCount()):
            name = self.seriesmdl.item(idx,0)
            dsts = self.seriesmdl.item(idx,1)
            if not dsts: continue
            name = name.text()
            dsts = dsts.text()
            dsts = [x.lower().strip() for x in dsts.replace(",", ";").split(";")]
            dsts = [x for x in dsts if re.match(r"^[xy]\d+$",x)]
            if dsts: newdstDict[name] = dsts
        
        for k,v in newdstDict.items():
            params.addChild({"name":k,"type":"str","value":"; ".join(v),"readonly":True})

    def addselectedfiles2params(self):
        selectedIDXs = self.datasrcview.selectedIndexes()
        if len(selectedIDXs)<1:
            self.displaydataframedetails([])
            return
        paths = []
        for idx in selectedIDXs:
            item = self.datasrcmdl.itemFromIndex(idx)
            paths.append( (  item.data(DATA.SRCIDX.value), item.data(DATA.SRCSUBIDX.value)  ) )
            for chIdx in range(item.rowCount()):
                ch = item.child(chIdx)
                paths.append( (  ch.data(DATA.SRCIDX.value), ch.data(DATA.SRCSUBIDX.value)  ) )
        paths = [x for x in paths if x[0] is not None]
        pathstr = "; ".join((f"{x[0]}.{x[1]}" for x in paths))
        self.rootapp.plugins["plotter"].params.param("Data selection").param("src dataframes").setValue(pathstr)

class Datasrcview(QtWidgets.QTreeView):
    fileDropped = QtCore.pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DropOnly)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():  e.accept()
        else:                       e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.setDropAction(QtCore.Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            e.accept()
            for url in e.mimeData().urls():
                self.fileDropped.emit(str(url.toLocalFile()))
        else:
            e.ignore()
