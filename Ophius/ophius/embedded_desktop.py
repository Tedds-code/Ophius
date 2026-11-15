"""Desktop window embedding the preserved HTML/CSS view; no external browser."""
from pathlib import Path
import queue


def desktop_loop(url,notifications,stop,show_window,hide_window,hidden=False,testing_mode=False):
    from PySide6.QtCore import QTimer,QUrl
    from PySide6.QtGui import QAction,QIcon,QKeySequence
    from PySide6.QtWidgets import QApplication,QFileDialog,QMainWindow,QMenu,QSystemTrayIcon
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage

    app=QApplication.instance() or QApplication(['Ophius'])
    app.setApplicationName('Ophius');app.setQuitOnLastWindowClosed(False)
    icon=QIcon(str(Path(__file__).resolve().parents[1]/'assets'/'ophius.svg'))
    app.setWindowIcon(icon)
    references=[]

    class View(QWebEngineView):
        def __init__(self,parent=None):
            super().__init__(parent);self.setPage(QWebEnginePage(profile,self))
        def createWindow(self,kind):
            window=QMainWindow();view=View(window);window.setCentralWidget(view)
            window.setWindowTitle('Ophius — reference');window.resize(980,740)
            references.append(window);window.show()
            return view

    class Window(QMainWindow):
        def closeEvent(self,event):
            event.ignore();self.hide()

    from . import __version__
    window=Window();window.setWindowTitle(f'Ophius {__version__} — '+('TESTING MODE' if testing_mode else 'crew health monitor'));window.setWindowIcon(icon)
    window.resize(1360,900)
    profile=QWebEngineProfile(app)
    # Do not persist a cache of short-lived sensor readings in the embedded renderer.
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    def download(request):
        name,_=QFileDialog.getSaveFileName(window,'Save exported file',request.downloadFileName())
        if not name:request.cancel();return
        path=Path(name);request.setDownloadDirectory(str(path.parent));request.setDownloadFileName(path.name);request.accept()
    profile.downloadRequested.connect(download)
    view=View(window);window.setCentralWidget(view);view.setUrl(QUrl(url))
    menu=window.menuBar().addMenu('Application')
    restore=QAction('Show monitor',window);restore.triggered.connect(lambda:window.showNormal());menu.addAction(restore)
    hide=QAction('Hide and keep monitoring',window);hide.triggered.connect(window.hide);menu.addAction(hide)
    quit_action=QAction('Quit & save',window);quit_action.setShortcut(QKeySequence.StandardKey.Quit)
    quit_action.triggered.connect(lambda:(stop.set(),app.quit()));menu.addAction(quit_action)
    tray=None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray=QSystemTrayIcon(icon,app);tray.setToolTip('Ophius — monitoring')
        tray_menu=QMenu();tray_menu.addAction(restore);tray_menu.addAction(hide);tray_menu.addAction(quit_action)
        tray.setContextMenu(tray_menu);tray.activated.connect(lambda reason:window.showNormal());tray.show()
    def restore_window():
        window.showNormal();window.raise_();window.activateWindow()
    def poll():
        if stop.is_set():app.quit();return
        if show_window.is_set():show_window.clear();restore_window()
        if hide_window.is_set():hide_window.clear();window.hide()
        new=[]
        while True:
            try:new.append(notifications.get_nowait())
            except queue.Empty:break
        if new:
            if not window.isVisible() or window.isMinimized():restore_window()
            if tray is not None:tray.showMessage('Ophius warning',new[0]['alert'].get('message','New warning'))
            app.beep()
    timer=QTimer();timer.timeout.connect(poll);timer.start(500)
    if not hidden:window.show()
    try:app.exec()
    finally:
        stop.set();timer.stop()
        if tray is not None:tray.hide()
        for reference in references:reference.close()
        window.deleteLater()
