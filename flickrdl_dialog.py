# -*- coding: utf-8 -*-
"""
/***************************************************************************
 FlickrdlDialog
                                 A QGIS plugin
 This plugin helps downloading metadata of geotagged Flickr photos
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2018-06-04
        git sha              : $Format:%H$
        copyright            : (C) 2018 by Mátyás Gede
        email                : saman@map.elte.hu
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
import requests
import qgis.utils

from PyQt5 import uic
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QAction, QMessageBox, QWidget
from PyQt5.QtCore import *
from PyQt5 import QtSql
from PyQt5.QtSql import *
from collections import deque

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'flickrdl_dialog_base.ui'))


class FlickrdlDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(FlickrdlDialog, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)
        self.fwDBFile.setFilter("SQLite files (*.sqlite)")
        # event handlers
        self.pbStart.clicked.connect(self.startDlThread) # Start button
        self.pbClose.clicked.connect(self.close) # Close button
        self.pbHelp.clicked.connect(self.help) # Close button
    
    def close(self):
        """Close dialog"""
        self.WT.stop()
        self.reject()
    
    def help(self):
        QMessageBox.information(self,"Help",'This plugin requires a Flickr API key.<br/> Please obtain a key at <br/>'+
            '<a href="https://www.flickr.com/services/api/misc.api_keys.html">https://www.flickr.com/services/api/misc.api_keys.html</a>'+
            '<h3>Usage</h3>Create a Spatialite database file. Select the database file, and set the bounding latitudes/longitudes of the area to download, '+
            'then press "Start".<br/>Depending on the number of photos in the area, download may take several minutes.')
        
    def startDlThread(self):
        """Starts downloading thread"""
        if self.pbStart.text()=="Start":
            # change button text to stop
            self.pbStart.setText("Stop");
            # clear log box
            self.teLog.clear()
            # get values from ui
            key=self.leApiKey.text()
            # key="ee27f5b7187c0c765d3c81f32b5488ee"
            dbFile=self.fwDBFile.filePath()
            tblName=self.leTblName.text()
            initialBB=[self.leWLon.text(),self.leSLat.text(),self.leELon.text(),self.leNLat.text()]
            # create and start thread
            self.WT=WorkerThread(qgis.utils.iface.mainWindow(),key,dbFile,tblName,initialBB)
            self.WT.jobFinished.connect(self.jobFinishedFromThread)
            self.WT.addMsg.connect(self.msgFromThread)
            self.WT.setTotal.connect(self.setTotal)
            self.WT.setProgress.connect(self.setProgress)
            self.WT.start()
        else:
            # change button text to start
            self.pbStart.setText("Start")
            # stop working thread
            self.WT.stop()
            self.teLog.append("Downloading stopped")
            
    def jobFinishedFromThread( self, success ):
        self.progressBar.setValue(self.progressBar.maximum())
        self.WT.stop()

    def msgFromThread( self, msg ):
        self.teLog.append(msg)        
    
    def setTotal( self, total ):
        self.progressBar.setMaximum(int(total))
        
    def setProgress( self, p ):
        self.progressBar.setValue(p)

class WorkerThread( QThread ):
    # signals
    addMsg=pyqtSignal(str)
    jobFinished=pyqtSignal(bool)
    setTotal=pyqtSignal(str)
    setProgress=pyqtSignal(int)
    
    def __init__( self, parentThread,key,dbFile,tblName,initialBB):
        QThread.__init__( self, parentThread )
        self.key=key
        self.dbFile=dbFile
        self.tblName=tblName
        self.initialBB=initialBB
    def run( self ):
        self.running = True
        success = self.doWork()
        self.jobFinished.emit(success)
    def stop( self ):
        self.running = False
        pass
    def doWork( self ):
        """Starts download process"""
        key=self.key
        dbFile=self.dbFile
        tblName=self.tblName
        initialBB=self.initialBB
        # check key validity
        self.addMsg.emit('Checking connection to Flickr API...')
        url='https://api.flickr.com/services/rest/?api_key='+key+'&method=flickr.test.echo&format=json&nojsoncallback=1'
        data=requests.get(url).json()
        if data['stat']=='fail':
            self.addMsg.emit('Error: '+data['message'])
            return
        else:    
            self.addMsg.emit('Connection OK.')
        
        # connect to spatialite
        con=qgis.utils.spatialite_connect(dbFile)
        cur=con.cursor()
        
        # create table
        cur.execute("drop table if exists "+tblName) 
        self.addMsg.emit("old table dropped if there was one")
        cur.execute("create table "+tblName+" (p_id integer primary key autoincrement, lat real, lon real, o_id text, p_date text, accuracy int, title text, tags text, url text)")        
        self.addMsg.emit(tblName+" table created")
        cur.execute("select AddGeometryColumn('"+tblName+"', 'geom', 4326, 'POINT', 'XY');")
                  
        # fifo list of bboxes to get
        bboxes=deque()
        bb=None
        
        # escapes 's for sqlite
        def escquotes(s):
            return s.replace("'","''")
            
        # send request to Flickr and get response
        def getPage(bbx,page):
            bbox=bbx[0]+','+bbx[1]+','+bbx[2]+','+bbx[3]
            url='https://api.flickr.com/services/rest/?api_key='+key+'&method=flickr.photos.search&bbox='+bbox+'&accuracy=1&format=json&nojsoncallback=1&page='+str(page)+'&perpage=250&extras=geo%2Cdate_taken%2Ctags%2Curl_s'
            return requests.get(url).json();
        
        # push photo data do DB
        def pushData(data):
            q="replace into "+tblName+" (p_id,lat,lon,o_id,p_date,accuracy,title,tags,url,geom) values "
            qv=''
            for p in data['photos']['photo']:
                if p['latitude']!=0 and p['longitude']!=0:
                    if qv!='':
                        qv+=','
                    qv+='('+p['id']+','+p['latitude']+','+p['longitude']+",'"+p['owner']+"','"+p['datetaken']+"',"+p['accuracy']+",'"+escquotes(p['title'])+"','"+escquotes(p['tags'])+"','"+escquotes(p['url_s'])+"',PointFromText('point("+p['longitude']+' '+p['latitude']+")',4326))"
            if qv!='':
                cur.execute(q+qv)
                self.addMsg.emit('page '+str(pg)+' from '+str(pages)+' inserted')
                # get number of records for setting progress bar
                res=cur.execute("select count(*) from "+tblName) 
                con.commit()
                self.setProgress.emit(res.fetchone()[0])
                
        # put initial bbox into queue
        bboxes.append(initialBB)
        
        first=True;
        
        # main downloading loop
        while len(bboxes)>0:
            # exit if thread stopped
            if not self.running:
                return False
            bb=bboxes.popleft() # next bbox to download
            pp=1 # start with first page
            data=getPage(bb,pp)
            # if there is a problem...
            if data['stat']=='fail':
                self.addMsg.emit('Error: '+data['message'])
                rd-=1
                return False
            # number of pages
            pages=data['photos']['pages']
            pg=data['photos']['page']
            if first:
                first=False
                self.setTotal.emit(data['photos']['total'])
            if pages>16:
                # too much data, dividing bbox
                self.addMsg.emit(str(pages)+" pages, dividing...")
                mlon=str((float(bb[0])+float(bb[2]))/2)
                mlat=str((float(bb[1])+float(bb[3]))/2)
                bboxes.append([bb[0],bb[1],mlon,mlat]);
                bboxes.append([mlon,bb[1],bb[2],mlat]);
                bboxes.append([bb[0],mlat,mlon,bb[3]]);
                bboxes.append([mlon,mlat,bb[2],bb[3]]);
            else:
                # push first page
                pushData(data)
                # get and push remaining pages
                while pp<pages:
                    # exit if thread stopped
                    if not self.running:
                        return False
                    pp+=1
                    data=getPage(bb,pp)
                    pages=data['photos']['pages']
                    pg=data['photos']['page']
                    pushData(data)
        # finished
        # cur.execute("SELECT CreateIsoMetadataTables();")
        # con.commit()
        self.addMsg.emit("I think it's ready...")    
        return True
        
    def cleanUp( self):
        pass