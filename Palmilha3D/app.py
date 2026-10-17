"""Palmilha Studio — desktop Qt + OpenGL, processamento fora da interface."""
import os
os.environ['PYQTGRAPH_QT_LIB'] = 'PySide6'
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from PIL.ImageQt import ImageQt
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.shaders import ShaderProgram, VertexShader, FragmentShader
from core import extract_mask, build_mesh, save_stl, demo_image

STYLE = '''
QWidget {font-family: 'Segoe UI'; font-size: 13px; color: #dce5ef; background: #111c2e;}
QMainWindow {background: #0b1320;}
QFrame#sidebar {background: #111c2e; border: 1px solid #26344a; border-radius: 16px;}
QLabel#brand {font-size: 23px; font-weight: 700; color: #f6f9fc;}
QLabel#muted {color: #94a6bd; font-size: 12px;}
QLabel#section {color: #63ddbf; font-size: 11px; font-weight: 700; letter-spacing: 2px;}
QLabel#title {font-size: 18px; font-weight: 600;}
QPushButton {background: #1d2c42; border: 1px solid #32435b; border-radius: 8px; padding: 9px 13px;}
QPushButton:hover {background: #2d425d; border-color: #63ddbf;}
QPushButton:disabled {color: #63748c; background: #172236;}
QPushButton#primary {background: #63ddbf; color: #102f2a; border: 0; font-weight: 700;}
QPushButton#primary:hover {background: #8cebd4;}
QDoubleSpinBox, QComboBox {background: #0c1626; border: 1px solid #34445b; border-radius: 6px; padding: 6px; min-height: 20px;}
QComboBox QAbstractItemView {background: #17273b; selection-background-color: #31564f;}
QScrollArea {border: 0; background: transparent;}
QScrollBar:vertical {width: 7px; background: #111c2e;}
QScrollBar::handle:vertical {background: #3a4e66; border-radius: 3px; min-height: 30px;}
QCheckBox {spacing: 7px;}
QToolTip {background: #203249; color: white; border: 1px solid #63ddbf;}
'''


def label(text, name=None):
    item = W.QLabel(text)
    if name: item.setObjectName(name)
    item.setWordWrap(name == 'muted')
    return item


def button(text, callback, primary=False):
    item = W.QPushButton(text)
    item.clicked.connect(callback)
    if primary: item.setObjectName('primary')
    return item


class Preview(W.QWidget):
    changed = C.Signal()
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(190)
        self.image = None
        self.points = []
        self.manual = False
        self.rect = C.QRectF()
    def set_image(self, im):
        self.image = G.QImage(ImageQt(im.convert('RGBA'))).copy()
        self.update()
    def paintEvent(self, event):
        painter = G.QPainter(self)
        painter.setRenderHint(G.QPainter.Antialiasing)
        painter.setBrush(G.QColor('#f2f5f7'))
        painter.setPen(C.Qt.NoPen)
        painter.drawRoundedRect(C.QRectF(self.rect_for_background()), 10, 10)
        if self.image:
            size = self.image.size().scaled(self.width()-24, self.height()-20, C.Qt.KeepAspectRatio)
            self.rect = C.QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
            painter.drawImage(self.rect,self.image)
            points = [C.QPointF(self.rect.x()+x*self.rect.width(),self.rect.y()+y*self.rect.height()) for x,y in self.points]
            if points:
                painter.setPen(G.QPen(G.QColor('#e18c26'),2))
                painter.setBrush(C.Qt.NoBrush)
                if self.manual: painter.drawPolyline(G.QPolygonF(points))
                else: painter.drawPolygon(G.QPolygonF(points))
                painter.setBrush(G.QColor('#e18c26'))
                for p in points: painter.drawEllipse(p,3,3)
    def rect_for_background(self):
        return C.QRect(0,0,self.width(),self.height())
    def mousePressEvent(self,event):
        if self.manual and self.rect.contains(event.position()):
            p = event.position()
            self.points.append(((p.x()-self.rect.x())/self.rect.width(),(p.y()-self.rect.y())/self.rect.height()))
            self.update()
            self.changed.emit()


class Signals(C.QObject):
    finished = C.Signal(int, object, str)


class Job(C.QRunnable):
    def __init__(self, revision, source, polygon, params, cached):
        super().__init__()
        self.signals = Signals()
        self.args = revision,source,polygon,params,cached
    def run(self):
        revision,source,polygon,params,cached = self.args
        image = None
        try:
            start = time.perf_counter()
            if isinstance(source,str):
                with Image.open(source) as opened:
                    image = ImageOps.exif_transpose(opened)
                    image.thumbnail((1800,1800),Image.Resampling.LANCZOS)
                    image = image.convert('RGBA')
            else: image = source
            tolerance = params.pop('tolerance')
            mask = cached if cached is not None else extract_mask(image,tolerance,polygon or None)
            mesh = build_mesh(mask,**params)
            v,f = mesh
            z = v[f,2]
            groups = np.where((z>0).all(axis=1),0,np.where((z==0).all(axis=1),1,2))
            # Split cap/wall normals and prepare rendering data off the GUI thread.
            render_data = gl.MeshData(vertexes=np.vstack([v,v,v]),faces=f+groups[:,None]*len(v))
            render_data.vertexNormals()
            render_data.edges()
            self.signals.finished.emit(revision,(image,mask,mesh,render_data,time.perf_counter()-start),'')
        except Exception as exc:
            self.signals.finished.emit(revision,image,str(exc))


class App(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.surface_shader = ShaderProgram('palmilhaStudio', [
            VertexShader('''
                uniform mat4 u_mvp;
                uniform mat3 u_normal;
                attribute vec4 a_position;
                attribute vec3 a_normal;
                attribute vec4 a_color;
                varying vec3 normal;
                varying vec4 color;
                void main() {
                    normal = u_normal * a_normal;
                    color = a_color;
                    gl_Position = u_mvp * a_position;
                }
            '''),
            FragmentShader('''
                #ifdef GL_ES
                precision mediump float;
                #endif
                varying vec3 normal;
                varying vec4 color;
                void main() {
                    vec3 n = normalize(normal);
                    vec3 light = normalize(vec3(-0.45, 0.65, 1.0));
                    float diffuse = max(dot(n, light), 0.0);
                    float fill = max(dot(n, normalize(vec3(0.8,-0.2,0.5))),0.0);
                    float specular = pow(max(dot(n,normalize(light+vec3(0.,0.,1.))),0.),40.);
                    gl_FragColor = vec4(color.rgb*(0.38+0.55*diffuse+0.16*fill)+vec3(0.18)*specular,color.a);
                }
            ''')])
        self.setWindowTitle('Palmilha Studio • Imagem para 3D')
        self.resize(1380,900)
        self.setMinimumSize(1050,720)
        self.setAcceptDrops(True)
        self.source = demo_image()
        self.mesh = None
        self.mesh_item = None
        self.dimension_items = []
        self.revision = 0
        self.busy = False
        self.cache = None
        self.cache_key = None
        self.source_id = 0
        self.pool = C.QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.timer = C.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(220)
        self.timer.timeout.connect(self.generate)
        root = W.QWidget()
        self.setCentralWidget(root)
        outer = W.QVBoxLayout(root)
        outer.setContentsMargins(24,18,24,16)
        outer.setSpacing(16)
        header = W.QHBoxLayout()
        brand = W.QVBoxLayout()
        brand.addWidget(label('◈  Palmilha Studio','brand'))
        brand.addWidget(label('DO CONTORNO À FORMA. COM PRECISÃO.','muted'))
        header.addLayout(brand,1)
        header.addStretch()
        header.addWidget(label('●  PROCESSAMENTO LOCAL','section'))
        self.export_button = button('Exportar STL  ↗',self.export,True)
        self.export_button.setEnabled(False)
        header.addWidget(self.export_button)
        outer.addLayout(header)
        body = W.QHBoxLayout()
        body.setSpacing(18)
        sidebar = W.QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(330)
        sl = W.QVBoxLayout(sidebar)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        content = W.QWidget()
        controls = W.QVBoxLayout(content)
        controls.setContentsMargins(12,12,12,12)
        controls.setSpacing(10)
        controls.addWidget(label('01  /  IMAGEM DE ORIGEM','section'))
        controls.addWidget(button('＋  Importar PNG ou JPG',self.open_image,True))
        self.filename = label('Exemplo • arraste sua imagem para a janela','muted')
        controls.addWidget(self.filename)
        self.preview = Preview()
        self.preview.set_image(self.source)
        self.tabs = W.QTabWidget()
        self.tabs.addTab(self.preview,'Imagem original')
        self.contour_preview = W.QLabel()
        self.contour_preview.setAlignment(C.Qt.AlignCenter)
        self.contour_preview.setMinimumHeight(190)
        self.contour_preview.setStyleSheet('background: #f2f5f7; border-radius: 8px;')
        self.tabs.addTab(self.contour_preview,'Contorno detectado')
        controls.addWidget(self.tabs)
        manual_row = W.QHBoxLayout()
        manual_row.addWidget(button('Marcar contorno',self.start_manual))
        manual_row.addWidget(button('Concluir',self.finish_manual))
        controls.addLayout(manual_row)
        controls.addWidget(button('Restaurar detecção automática',self.reset_manual))
        controls.addWidget(label('02  /  FORMA E MEDIDAS','section'))
        self.values = {}
        for title,key,value,low,high,step in [
            ('Tolerância do fundo','tolerance',45,0,441,5),
            ('Comprimento · mm','length',270,20,600,1),
            ('Espessura mínima · mm','base',3,.5,50,.5),
            ('Elevação do calcanhar · mm','heel',5,0,80,.5),
            ('Elevação do arco · mm','arch',12,0,80,.5),
            ('Suavização do contorno','smoothing',1.2,0,5,.2)]:
            row = W.QHBoxLayout()
            row.addWidget(label(title))
            field = W.QDoubleSpinBox()
            field.setRange(low,high)
            field.setDecimals(1)
            field.setSingleStep(step)
            field.setValue(value)
            field.setFixedWidth(94)
            field.valueChanged.connect(self.schedule)
            self.values[key] = field
            row.addWidget(field)
            controls.addLayout(row)
        self.side = W.QComboBox()
        self.side.addItems(['Esquerdo','Direito'])
        self.side.currentTextChanged.connect(self.schedule)
        controls.addWidget(self.side)
        controls.addWidget(button('↕  Inverter ponta e calcanhar',self.flip))
        controls.addWidget(label('Ponta para cima, calcanhar para baixo. O lado selecionado posiciona o arco.','muted'))
        controls.addStretch()
        scroll.setWidget(content)
        sl.addWidget(scroll)
        body.addWidget(sidebar)
        area = W.QVBoxLayout()
        heading = W.QHBoxLayout()
        heading.addWidget(label('Seu modelo, em cada detalhe.','title'))
        heading.addStretch()
        self.badge = label('PREPARANDO','section')
        heading.addWidget(self.badge)
        area.addLayout(heading)
        views = W.QHBoxLayout()
        for name,angles in [('Perspectiva',(36,-48)),('Superior',(90,-90)),('Lateral',(5,0))]:
            views.addWidget(button(name,lambda checked=False,a=angles:self.view(*a)))
        views.addStretch()
        self.wire = W.QCheckBox('Malha')
        self.wire.toggled.connect(self.appearance)
        views.addWidget(self.wire)
        self.material = W.QComboBox()
        self.material.addItems(['Jade','Âmbar','Cerâmica'])
        self.material.currentIndexChanged.connect(self.appearance)
        views.addWidget(self.material)
        area.addLayout(views)
        self.viewer = gl.GLViewWidget()
        self.viewer.setBackgroundColor('#edf2f4')
        self.viewer.setCameraPosition(distance=440,elevation=36,azimuth=-48)
        self.viewer.opts['fov'] = 45
        self.grid = gl.GLGridItem()
        self.grid.setSize(400,400)
        self.grid.setSpacing(25,25)
        self.grid.setColor((90,110,125,42))
        self.grid.translate(0,0,-.5)
        self.viewer.addItem(self.grid)
        area.addWidget(self.viewer,1)
        self.metrics = label('Extraindo a silhueta e preparando a superfície…','title')
        area.addWidget(self.metrics)
        area.addWidget(label('Arraste para girar  •  Roda para zoom  •  Ctrl + arraste para mover','muted'))
        area.addWidget(label('O contorno vem da imagem. Altura, arco e calcanhar são estimados pelos ajustes.','muted'))
        body.addLayout(area,1)
        outer.addLayout(body,1)
        self.status = label('Pronto para criar.','muted')
        outer.addWidget(self.status)
        C.QTimer.singleShot(100,self.generate)

    def parameters(self):
        return {**{k:v.value() for k,v in self.values.items()},'side':self.side.currentText(),'resolution':100}

    def schedule(self,*args):
        self.revision += 1
        self.export_button.setEnabled(False)
        self.badge.setText('ALTERAÇÕES PENDENTES')
        if not self.preview.manual: self.timer.start()

    def generate(self):
        if self.busy or self.preview.manual: return
        self.busy = True
        self.badge.setText('GERANDO…')
        self.status.setText('Atualizando a superfície em segundo plano…')
        p = self.parameters()
        self.job_key = (self.source_id,p['tolerance'],tuple(self.preview.points))
        cached = self.cache if self.cache_key == self.job_key else None
        self.job = Job(self.revision,self.source,list(self.preview.points),p,cached)
        self.job.signals.finished.connect(self.completed)
        self.pool.start(self.job)

    def completed(self,revision,result,error):
        self.busy = False
        if revision != self.revision:
            if not self.preview.manual: self.generate()
            return
        if error:
            if isinstance(result,Image.Image):
                self.source = result
                self.preview.set_image(result)
            self.contour_preview.clear()
            for item in self.dimension_items: self.viewer.removeItem(item)
            self.dimension_items = []
            self.mesh = None
            self.export_button.setEnabled(False)
            self.badge.setText('REVISAR IMAGEM')
            self.status.setText(error)
            if self.mesh_item:
                self.viewer.removeItem(self.mesh_item)
                self.mesh_item = None
            self.metrics.setText('Ajuste a imagem ou marque o contorno.')
            return
        image,mask,self.mesh,render_data,elapsed = result
        self.source = image
        self.preview.set_image(image)
        self.cache,self.cache_key = mask,self.job_key
        contour_image = Image.fromarray(np.where(mask[:,:,None],np.array([55,170,145],dtype='uint8'),np.array([242,245,247],dtype='uint8')))
        self.contour_preview.setPixmap(G.QPixmap.fromImage(G.QImage(ImageQt(contour_image))).scaled(260,190,C.Qt.KeepAspectRatio,C.Qt.SmoothTransformation))
        v,f = self.mesh
        if self.mesh_item is None:
            self.mesh_item = gl.GLMeshItem(meshdata=render_data,smooth=True,shader=self.surface_shader,drawEdges=False)
            self.viewer.addItem(self.mesh_item)
        else: self.mesh_item.setMeshData(meshdata=render_data)
        self.appearance()
        size = np.ptp(v,axis=0)
        for item in self.dimension_items: self.viewer.removeItem(item)
        lo,hi = v.min(axis=0),v.max(axis=0)
        x,y0,y1 = hi[0]+15,lo[1],hi[1]
        lines = np.array([(x,y0,0),(x,y1,0),(x-4,y0,0),(x+4,y0,0),(x-4,y1,0),(x+4,y1,0)],dtype=float)
        self.dimension_items = [gl.GLLinePlotItem(pos=lines,color=(.3,.43,.49,.7),width=1,mode='lines',antialias=True),
                                gl.GLTextItem(pos=(x+4,0,0),text=f'{size[1]:.0f} mm',color='#536e7c',font=G.QFont('Segoe UI',10))]
        for item in self.dimension_items: self.viewer.addItem(item)
        self.metrics.setText(f'{size[1]:.1f} mm comprimento     ×     {size[0]:.1f} mm largura     ×     {size[2]:.1f} mm altura')
        self.status.setText(f'Contorno suavizado  •  {len(f):,} triângulos  •  geração em {elapsed*1000:.0f} ms  •  STL em milímetros')
        self.badge.setText('●  MODELO ATUALIZADO')
        self.export_button.setEnabled(True)

    def appearance(self,*args):
        if self.mesh_item:
            colors = [(0.21,.70,.58,1),(1,.65,.22,1),(.80,.85,.91,1)]
            self.mesh_item.setColor(colors[self.material.currentIndex()])
            self.mesh_item.opts['drawEdges'] = self.wire.isChecked()
            self.mesh_item.opts['edgeColor'] = (.12,.22,.27,.25)
            self.mesh_item.meshDataChanged()

    def view(self,elevation,azimuth):
        self.viewer.opts['center'] = G.QVector3D(0,0,0)
        self.viewer.setCameraPosition(distance=self.values['length'].value()*1.65,elevation=elevation,azimuth=azimuth)

    def open_image(self):
        path,_ = W.QFileDialog.getOpenFileName(self,'Importar palmilha','','Imagens (*.png *.jpg *.jpeg)')
        if path: self.load(path)

    def load(self,path):
        self.source = path
        self.source_id += 1
        self.preview.manual = False
        self.preview.points = []
        self.preview.image = None
        self.contour_preview.clear()
        self.preview.update()
        self.filename.setText(Path(path).name)
        self.schedule()

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and Path(event.mimeData().urls()[0].toLocalFile()).suffix.lower() in ('.png','.jpg','.jpeg'):
            event.acceptProposedAction()

    def dropEvent(self,event):
        self.load(event.mimeData().urls()[0].toLocalFile())

    def start_manual(self):
        if isinstance(self.source,str): return
        self.preview.manual = True
        self.tabs.setCurrentIndex(0)
        self.preview.points = []
        self.preview.update()
        self.schedule()
        self.status.setText('Clique ao redor da palmilha na imagem; depois clique em Concluir.')

    def finish_manual(self):
        if not self.preview.manual: return
        if len(self.preview.points)<3:
            self.status.setText('Marque pelo menos 3 pontos ao redor da palmilha.')
            return
        self.preview.manual = False
        self.preview.update()
        self.schedule()

    def reset_manual(self):
        self.preview.manual = False
        self.preview.points = []
        self.preview.update()
        self.schedule()

    def flip(self):
        if isinstance(self.source,str): return
        self.source = self.source.rotate(180)
        self.source_id += 1
        self.preview.points = [(1-x,1-y) for x,y in self.preview.points]
        self.preview.set_image(self.source)
        self.schedule()

    def export(self):
        if self.mesh is None or not self.export_button.isEnabled(): return
        path,_ = W.QFileDialog.getSaveFileName(self,'Exportar modelo em milímetros','palmilha.stl','STL (*.stl)')
        if path:
            if not path.lower().endswith('.stl'): path += '.stl'
            try:
                save_stl(path,*self.mesh)
                self.status.setText('STL exportado: '+path)
            except OSError as exc:
                W.QMessageBox.warning(self,'Não foi possível exportar',str(exc))

    def closeEvent(self,event):
        self.timer.stop()
        self.pool.waitForDone()
        event.accept()


def main():
    fmt = G.QSurfaceFormat()
    fmt.setSamples(4)
    fmt.setDepthBufferSize(24)
    G.QSurfaceFormat.setDefaultFormat(fmt)
    app = W.QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__': main()
