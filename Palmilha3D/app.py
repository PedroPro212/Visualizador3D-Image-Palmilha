"""Palmilha Studio — desktop Qt + OpenGL, processamento fora da interface."""
import os
os.environ['PYQTGRAPH_QT_LIB'] = 'PySide6'
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.shaders import ShaderProgram, VertexShader, FragmentShader
from core import (extract_mask, build_mesh, save_stl, mirror_mesh, demo_image,
                  load_stl, normalize_foot_scan, build_sole_morph)

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


def pil_to_qimage(image):
    """Convert a Pillow image without relying on Pillow's optional Qt binding detection."""
    rgba=image.convert('RGBA')
    return G.QImage(rgba.tobytes(),rgba.width,rgba.height,rgba.width*4,
                    G.QImage.Format_RGBA8888).copy()


def foot_surface(sole_vertices, sole_faces, parameters, height, ankle, toe_relief):
    """Sculpt a foot relief over the exact triangulated footprint of the insole."""
    count = len(sole_vertices)//2
    sole = sole_vertices[:count]
    lo, hi = sole[:,:2].min(axis=0), sole[:,:2].max(axis=0)
    u = (sole[:,0]-lo[0])/max(hi[0]-lo[0],1e-6)
    t = (hi[1]-sole[:,1])/max(hi[1]-lo[1],1e-6)  # toe=0, heel=1
    medial = .72 if parameters['side']=='Esquerdo' else .28
    across = np.maximum(0,np.sin(np.pi*np.clip(u,0,1)))**.55
    def g(x,center,width):
        return np.exp(-.5*((x-center)/width)**2)

    # Instep, ball and heel form one continuous dorsum; the heel rises into an ankle.
    dorsum = height*(.60*g(t,.54,.25)+.48*g(t,.25,.15))
    arch_bias = .12*height*g(t,.56,.20)*g(u,medial,.24)
    ankle_rise = ankle*g(t,.90,.13)
    relief = across*(dorsum+arch_bias+ankle_rise)

    # Five rounded toe pads with a wider, longer big toe and shallow web grooves.
    centers = ([.77,.61,.48,.35,.22] if parameters['side']=='Esquerdo'
               else [.23,.39,.52,.65,.78])
    toe_t = [.075,.09,.105,.125,.145]
    toe_w = [.105,.082,.073,.065,.055]
    toe_h = [1,.84,.76,.68,.58]
    toes = np.zeros_like(relief)
    for cx,cy,sx,amp in zip(centers,toe_t,toe_w,toe_h):
        toes += amp*g(u,cx,sx)*g(t,cy,.072)
    grooves = np.zeros_like(relief)
    for left,right in zip(centers[:-1],centers[1:]):
        grooves += g(u,(left+right)/2,.018)*g(t,.105,.082)
    relief += across*toe_relief*np.maximum(0,toes-.82*grooves)

    upper = sole.copy()
    upper[:,2] += relief
    lower = sole.copy()
    faces = sole_faces[(sole_faces < count).all(axis=1)]
    # Keep the complete foot seated: every point on the insole perimeter touches it.
    edges = np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]])
    unique_edges,edge_counts = np.unique(np.sort(edges,axis=1),axis=0,return_counts=True)
    boundary = np.unique(unique_edges[edge_counts==1])
    upper[boundary,2] = sole[boundary,2]
    n = len(upper)
    closed_faces = np.vstack([faces,faces[:,::-1]+n]).astype(np.int32)
    vertices = np.vstack([upper,lower])

    # Subtle lighter nail patches make the five toe tips legible in the 3D view.
    base = np.array([.84,.55,.40,1.])
    nail = np.array([.96,.77,.68,1.])
    nail_strength = np.zeros(count)
    for i,(cx,cy,sx) in enumerate(zip(centers,[.027,.039,.052,.065,.079],toe_w)):
        nail_strength = np.maximum(nail_strength,g(u,cx,sx*.43)*g(t,cy,.027))
    colors = np.tile(base,(count,1))
    colors = colors*(1-nail_strength[:,None]*.78)+nail*nail_strength[:,None]*.78
    crease_strength = np.clip(grooves,0,1)*.26
    colors[:,:3] *= (1-crease_strength[:,None])
    return vertices,closed_faces,colors


def morphology_colors(sole_vertices):
    """Color the molded surface by its actual height; this is not a pressure sensor map."""
    z=np.asarray(sole_vertices[:,2],dtype=float)
    lo,hi=np.percentile(z,[5,95])
    field=np.clip((z-lo)/max(hi-lo,1e-6),0,1)
    stops=np.array([0,.25,.5,.75,1.])
    palette=np.array([[.08,.24,.72,.82],[.05,.75,.91,.86],[.20,.78,.44,.90],
                      [1.,.82,.12,.92],[.92,.12,.10,.94]])
    return np.column_stack([np.interp(field,stops,palette[:,i]) for i in range(4)])


def pressure_colors(sole_vertices, side, levels):
    """Return an adjustable illustrative pressure field, not measured data."""
    lo, hi = sole_vertices.min(axis=0), sole_vertices.max(axis=0)
    width, length = hi[0]-lo[0], hi[1]-lo[1]
    u = (sole_vertices[:,0]-lo[0])/max(width,1e-6)
    v = (hi[1]-sole_vertices[:,1])/max(length,1e-6)
    medial = .72 if side=='Esquerdo' else .28
    def spot(cx, cy, sx, sy):
        return np.exp(-.5*((u-cx)/sx)**2-.5*((v-cy)/sy)**2)
    field = (levels[0]*spot(.50,.88,.22,.11) +
             levels[1]*spot(medial,.56,.20,.13) +
             levels[2]*(spot(.34,.29,.13,.09)+spot(.66,.29,.13,.09))*.5 +
             levels[3]*spot(.53,.09,.18,.09))
    field /= max(float(field.max()),1e-9)
    stops = np.array([0,.25,.5,.75,1.])
    palette = np.array([[.08,.24,.72,.78],[.05,.75,.91,.82],[.20,.78,.44,.86],
                        [1.,.82,.12,.90],[.92,.12,.10,.94]])
    return np.column_stack([np.interp(field,stops,palette[:,i]) for i in range(4)])


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
        self.image = pil_to_qimage(im)
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


class DimensionViewer(gl.GLViewWidget):
    """3D viewer with double-click editing for dimension callouts."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dimension_hit = None
    def mouseDoubleClickEvent(self, event):
        pos = event.position() if hasattr(event, 'position') else event.localPos()
        if event.button() == C.Qt.LeftButton and self.dimension_hit and self.dimension_hit(pos):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class Signals(C.QObject):
    finished = C.Signal(int, object, str)


class Job(C.QRunnable):
    def __init__(self, revision, source, polygon, params, cached, foot_scan=None):
        super().__init__()
        self.signals = Signals()
        self.args = revision,source,polygon,params,cached,foot_scan
    def run(self):
        revision,source,polygon,params,cached,foot_scan = self.args
        image = None
        try:
            start = time.perf_counter()
            if foot_scan is not None:
                if isinstance(source,str):
                    with Image.open(source) as opened:
                        image=ImageOps.exif_transpose(opened)
                        image.thumbnail((1800,1800),Image.Resampling.LANCZOS)
                        image=image.convert('RGBA')
                else:
                    image=source
                tolerance=params.pop('tolerance')
                mask=cached if cached is not None else extract_mask(image,tolerance,polygon or None)
                base_params={k:params[k] for k in ('length','base','heel','arch','side','resolution','smoothing','width_scale','width_targets','rim_height','rim_width')}
                if params.get('flat_insole',False):
                    base_params['heel']=0
                    base_params['arch']=0
                base_mesh=build_mesh(mask,**base_params)
                if params.get('solemorph',True) and not params.get('flat_insole',False):
                    mesh=build_sole_morph(foot_scan,base_mesh,thickness=params['base'],
                        clearance=params['fit_clearance'],plantar_limit=params['fit_crop'],
                        resolution=params['resolution'],smoothing=params['smoothing'],
                        planes=params['morph_planes'],start_at=params['morph_start'],
                        plane_spacing=params['morph_spacing'],
                        offset_x=params['morph_offset_x'],offset_y=params['morph_offset_y'],
                        rotation_deg=params['morph_rotation'],
                        surface_smoothing=params['morph_smoothing'],blend_distance=params['morph_blend'],
                        morph_strength=params['morph_strength'])
                else:
                    mesh=base_mesh
                params.pop('fit_clearance',None); params.pop('fit_crop',None)
            else:
                if isinstance(source,str):
                    with Image.open(source) as opened:
                        image = ImageOps.exif_transpose(opened)
                        image.thumbnail((1800,1800),Image.Resampling.LANCZOS)
                        image = image.convert('RGBA')
                else: image = source
                tolerance = params.pop('tolerance')
                params.pop('fit_clearance',None)
                params.pop('fit_crop',None)
                params.pop('fit_scale',None)
                flat=params.pop('flat_insole',False)
                if flat:
                    params['heel']=0
                    params['arch']=0
                params.pop('solemorph',None)
                for key in ('morph_planes','morph_start','morph_spacing','morph_offset_x','morph_offset_y','morph_rotation','morph_smoothing','morph_blend','morph_strength'): params.pop(key,None)
                mask = cached if cached is not None else extract_mask(image,tolerance,polygon or None)
                mesh = build_mesh(mask,**params)
            v,f = mesh
            if foot_scan is not None:
                half=len(v)//2
                top=(f<half).all(axis=1)
                bottom=((f>=half)&(f<2*half)).all(axis=1)
                groups=np.where(top,0,np.where(bottom,1,2))
            else:
                half=len(v)//2
                top=(f<half).all(axis=1)
                bottom=((f>=half)&(f<2*half)).all(axis=1)
                groups=np.where(top,0,np.where(bottom,1,2))
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
        self.foot_item = None
        self.foot_scan = None
        self.foot_scan_raw = None
        self.foot_scan_path = None
        self.pressure_item = None
        self.overlay_mode = 0
        self.dimension_items = []
        self.dimension_labels = []
        self.dimension_specs = []
        self.width_targets = {}
        self.dimension_editor = None
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
        controls.addWidget(button('＋  Importar pé 3D (STL)',self.open_foot_stl))
        controls.addWidget(label('O STL deve estar em milímetros, com o comprimento no eixo Y e a sola voltada para -Z.','muted'))
        self.scan_filename=label('Nenhum scan de pé carregado','muted')
        controls.addWidget(self.scan_filename)
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
        self.mark_contour_button=button('Marcar contorno',self.start_manual)
        self.finish_contour_button=button('Concluir',self.finish_manual)
        manual_row.addWidget(self.mark_contour_button)
        manual_row.addWidget(self.finish_contour_button)
        controls.addLayout(manual_row)
        self.reset_contour_button=button('Restaurar detecção automática',self.reset_manual)
        controls.addWidget(self.reset_contour_button)
        controls.addWidget(label('02  /  FORMA E MEDIDAS','section'))
        self.values = {}
        for title,key,value,low,high,step in [
            ('Tolerância do fundo','tolerance',45,0,441,5),
            ('Comprimento · mm','length',270,20,600,1),
            ('Escala de largura · %','width_scale',100,30,180,1),
            ('Espessura mínima · mm','base',3,.5,50,.5),
            ('Elevação do calcanhar · mm','heel',5,0,80,.5),
            ('Elevação do arco · mm','arch',12,0,80,.5),
            ('Suavização do contorno','smoothing',2.0,0,5,.2)]:
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
        self.flat_insole=W.QCheckBox('Palmilha plana (sem elevação)')
        self.flat_insole.setToolTip('Mantém o contorno e a espessura mínima, sem arco, elevação do calcanhar ou relevo do scan.')
        self.flat_insole.toggled.connect(self.update_flat_mode)
        controls.addWidget(self.flat_insole)
        self.rim_toggle=W.QCheckBox('Adicionar resalto inferior recuado')
        self.rim_toggle.setToolTip('Inclina a borda inferior para dentro e para baixo, como na referência, integrado à malha exportada.')
        self.rim_toggle.toggled.connect(self.update_rim_mode)
        controls.addWidget(self.rim_toggle)
        self.rim_values={}
        for title,key,value,low,high,step in [
            ('Altura do resalto inferior · mm','rim_height',4,0,20,.5),
            ('Largura do recuo inferior · mm','rim_width',3,.5,12,.5)]:
            row=W.QHBoxLayout(); row.addWidget(label(title))
            field=W.QDoubleSpinBox(); field.setRange(low,high); field.setDecimals(1)
            field.setSingleStep(step); field.setValue(value); field.setFixedWidth(94)
            field.setEnabled(False); field.valueChanged.connect(self.schedule)
            self.rim_values[key]=field; row.addWidget(field); controls.addLayout(row)
        controls.addWidget(label('03  /  ENCAIXE PERSONALIZADO','section'))
        self.fit_values = {}
        for title,key,value,low,high,step in [
            ('Folga sob o pé · mm','fit_clearance',1,0,10,.5),
            ('Limite plantar · mm','fit_crop',20,10,50,1),
            ('Escala do STL · %','fit_scale',100,5,100000,1)]:
            row=W.QHBoxLayout(); row.addWidget(label(title))
            field=W.QDoubleSpinBox(); field.setRange(low,high); field.setDecimals(1 if step<1 else 0)
            field.setSingleStep(step); field.setValue(value); field.setFixedWidth(94)
            if key=='fit_scale': field.valueChanged.connect(self.rescale_foot_scan)
            else: field.valueChanged.connect(self.schedule)
            if key=='fit_crop': field.setToolTip('Corta tornozelo e peito do pé do scan. Aumente apenas se o arco plantar estiver sendo cortado.')
            self.fit_values[key]=field; row.addWidget(field); controls.addLayout(row)
        for field in self.fit_values.values(): field.setEnabled(False)
        controls.addWidget(label('O STL não informa unidade. A escala inicial presume milímetros; confira o comprimento real do pé antes de imprimir.','muted'))
        controls.addWidget(label('SOLE MORPH  /  CONFORMAÇÃO PLANTAR','section'))
        self.solemorph_toggle=W.QCheckBox('Moldar a palmilha ao scan')
        self.solemorph_toggle.setChecked(True)
        self.solemorph_toggle.setEnabled(False)
        self.solemorph_toggle.toggled.connect(self.schedule)
        controls.addWidget(self.solemorph_toggle)
        self.morph_values={}
        for title,key,value,low,high,step in [
            ('Planos de leitura','morph_planes',3,1,12,1),
            ('Início · mm','morph_start',.5,0,20,.5),
            ('Espaçamento entre planos · mm','morph_spacing',5,.5,20,.5),
            ('Posição X · mm','morph_offset_x',0,-100,100,1),
            ('Posição Y · mm','morph_offset_y',0,-100,100,1),
            ('Rotação do scan · °','morph_rotation',0,-45,45,1),
            ('Suavização da superfície · mm','morph_smoothing',6,0,10,.5),
            ('Transição suave · mm','morph_blend',30,2,50,1),
            ('Intensidade do relevo · %','morph_strength',55,0,100,5)]:
            row=W.QHBoxLayout(); row.addWidget(label(title))
            field=W.QDoubleSpinBox(); field.setRange(low,high); field.setDecimals(1 if step<1 else 0)
            field.setSingleStep(step); field.setValue(value); field.setFixedWidth(94)
            field.setEnabled(False); field.valueChanged.connect(self.schedule)
            self.morph_values[key]=field; row.addWidget(field); controls.addLayout(row)
        controls.addWidget(label('A palmilha mantém seu contorno e base próprios; o scan altera somente a superfície superior.','muted'))
        self.side = W.QComboBox()
        self.side.addItems(['Esquerdo','Direito'])
        self.side.currentTextChanged.connect(self.schedule)
        controls.addWidget(self.side)
        controls.addWidget(label('03  /  PÉ E PRESSÃO ESTIMADA','section'))
        controls.addWidget(label('O contorno do pé acompanha exatamente o contorno da palmilha.','muted'))
        self.foot_values = {}
        for title,key,value,low,high,step in [
            ('Volume do peito do pé · mm','height',42,15,80,1),
            ('Volume do tornozelo · mm','ankle',30,5,60,1),
            ('Separação dos dedos · mm','toe_relief',16,0,28,1)]:
            row = W.QHBoxLayout()
            row.addWidget(label(title))
            field = W.QDoubleSpinBox()
            field.setRange(low,high)
            field.setDecimals(0)
            field.setSingleStep(step)
            field.setValue(value)
            field.setFixedWidth(94)
            field.valueChanged.connect(self.update_overlay)
            self.foot_values[key] = field
            row.addWidget(field)
            controls.addLayout(row)
        controls.addWidget(label('Intensidade relativa por região','muted'))
        self.pressure_values = {}
        for title,key,value in [
            ('Calcanhar','heel',80),('Arco / mediopé','midfoot',20),
            ('Metatarsos','forefoot',70),('Dedos','toes',40)]:
            row = W.QHBoxLayout()
            row.addWidget(label(title))
            field = W.QDoubleSpinBox()
            field.setRange(0,100)
            field.setDecimals(0)
            field.setSingleStep(5)
            field.setValue(value)
            field.setSuffix(' %')
            field.setFixedWidth(94)
            field.valueChanged.connect(self.update_overlay)
            self.pressure_values[key] = field
            row.addWidget(field)
            controls.addLayout(row)
        controls.addWidget(label('Mapa ilustrativo, sem sensores: não mede a pressão real nem substitui avaliação clínica.','muted'))
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
        self.view_mode = W.QComboBox()
        self.view_mode.addItems(['Palmilha','Pé 3D','Pressão estimada','Mapa SoleMorph'])
        self.view_mode.currentIndexChanged.connect(self.update_overlay)
        views.addWidget(self.view_mode)
        self.show_foot = W.QCheckBox('Mostrar pé')
        self.show_foot.setVisible(False)
        self.show_foot.toggled.connect(self.toggle_foot_visibility)
        views.addWidget(self.show_foot)
        self.wire = W.QCheckBox('Malha')
        self.wire.toggled.connect(self.appearance)
        views.addWidget(self.wire)
        self.material = W.QComboBox()
        self.material.addItems(['Jade','Âmbar','Cerâmica'])
        self.material.currentIndexChanged.connect(self.appearance)
        views.addWidget(self.material)
        area.addLayout(views)
        self.viewer = DimensionViewer()
        self.viewer.dimension_hit = self.edit_dimension_at
        self.viewer.setToolTip('Dê dois cliques em uma cota para editar o componente. O modelo atualiza automaticamente.')
        self.viewer.setBackgroundColor('#edf2f4')
        # Start directly above the footprint so its outline can be compared with the imported image.
        self.viewer.setCameraPosition(distance=self.values['length'].value()*1.65,elevation=90,azimuth=-90)
        self.viewer.opts['fov'] = 45
        self.grid = gl.GLGridItem()
        self.grid.setSize(400,400)
        self.grid.setSpacing(25,25)
        self.grid.setColor((90,110,125,42))
        self.grid.translate(0,0,-.5)
        self.grid_z=-.5
        self.viewer.addItem(self.grid)
        area.addWidget(self.viewer,1)
        self.metrics = label('Extraindo a silhueta e preparando a superfície…','title')
        area.addWidget(self.metrics)
        area.addWidget(label('Dois cliques em uma cota para editar  •  Arraste para girar  •  Roda para zoom  •  Ctrl + arraste para mover','muted'))
        self.model_note=label('O contorno vem da imagem. Altura, arco e calcanhar são estimados pelos ajustes.','muted')
        area.addWidget(self.model_note)
        body.addLayout(area,1)
        outer.addLayout(body,1)
        self.status = label('Pronto para criar.','muted')
        outer.addWidget(self.status)
        C.QTimer.singleShot(100,self.generate)

    def parameters(self):
        return {**{k:v.value() for k,v in self.values.items()},
                **{k:v.value() for k,v in self.fit_values.items()},
                'side':self.side.currentText(),'resolution':220,
                'width_targets':self.width_targets.copy(),
                'flat_insole':self.flat_insole.isChecked(),
                'rim_height':self.rim_values['rim_height'].value() if self.rim_toggle.isChecked() and not self.flat_insole.isChecked() else 0,
                'rim_width':self.rim_values['rim_width'].value(),
                'solemorph':self.solemorph_toggle.isChecked(),
                **{k:v.value() for k,v in self.morph_values.items()}}

    def update_flat_mode(self,flat):
        self.values['heel'].setEnabled(not flat)
        self.values['arch'].setEnabled(not flat)
        has_scan=self.foot_scan is not None
        self.solemorph_toggle.setEnabled(has_scan and not flat)
        for field in self.morph_values.values():
            field.setEnabled(has_scan and not flat)
        self.rim_toggle.setEnabled(not flat)
        for field in self.rim_values.values():
            field.setEnabled(self.rim_toggle.isChecked() and not flat)
        self.schedule()

    def update_rim_mode(self,enabled):
        for field in self.rim_values.values():
            field.setEnabled(enabled and not self.flat_insole.isChecked())
        self.schedule()

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
        self.job_key = (self.source_id,p['tolerance'],p['fit_scale'],p['fit_clearance'],p['fit_crop'],tuple(self.preview.points))
        cached = self.cache if self.cache_key == self.job_key else None
        self.job = Job(self.revision,self.source,list(self.preview.points),p,cached,self.foot_scan)
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
            self.badge.setText('FALHA NO PÉ 3D' if self.foot_scan is not None else 'REVISAR IMAGEM')
            self.status.setText(error)
            self.metrics.setText('Falha ao gerar o modelo: '+str(error))
            self.metrics.setToolTip(str(error))
            if self.mesh_item:
                self.viewer.removeItem(self.mesh_item)
                self.mesh_item = None
            for attr in ('foot_item','pressure_item'):
                item = getattr(self,attr,None)
                if item is not None:
                    self.viewer.removeItem(item)
                    setattr(self,attr,None)
            return
        image,mask,self.mesh,render_data,elapsed = result
        if image is not None:
            self.source = image
            self.preview.set_image(image)
        self.cache,self.cache_key = mask,self.job_key
        contour_image = Image.fromarray(np.where(mask[:,:,None],np.array([55,170,145],dtype='uint8'),np.array([242,245,247],dtype='uint8')))
        self.contour_preview.setPixmap(G.QPixmap.fromImage(pil_to_qimage(contour_image)).scaled(260,190,C.Qt.KeepAspectRatio,C.Qt.SmoothTransformation))
        v,f = self.mesh
        if self.mesh_item is None:
            self.mesh_item = gl.GLMeshItem(meshdata=render_data,smooth=True,shader=self.surface_shader,drawEdges=False)
            self.viewer.addItem(self.mesh_item)
        else: self.mesh_item.setMeshData(meshdata=render_data)
        self.appearance()
        size = np.ptp(v,axis=0)
        for item in self.dimension_items: self.viewer.removeItem(item)
        self.dimension_items, self.dimension_labels, self.dimension_specs = [], [], []
        lo,hi = v.min(axis=0),v.max(axis=0)
        # Keep the floor grid below the lowest STL vertex so it cannot show
        # through the downward-projecting underside rim.
        grid_z=min(-.5,float(lo[2])-2.0)
        self.grid.translate(0,0,grid_z-self.grid_z)
        self.grid_z=grid_z
        length=size[1]
        # Cross sections sampled from the triangulated top surface at five useful foot landmarks.
        sections=[]
        for name,key,fraction in [('Largura dos dedos','toe',.10),('Largura metatarsal','metatarsal',.27),('Largura do arco','arch',.55),('Largura do calcanhar','heel',.90)]:
            yy=hi[1]-fraction*length
            band=max(1.5,length*.012)
            sample=v[:len(v)//2]
            xs=sample[np.abs(sample[:,1]-yy)<=band,0]
            if len(xs)<2:
                nearest=np.argsort(np.abs(sample[:,1]-yy))[:max(2,len(sample)//80)]
                xs=sample[nearest,0]
            sections.append((name,key,float(xs.max()-xs.min()),yy,float(xs.min()),float(xs.max())))
        specs=[('Comprimento',float(length),'length',(hi[0]+17,0,0), (hi[0]+17,lo[1],hi[1]))]
        specs.append(('Largura máxima',float(size[0]),'width',(0,lo[1]-15,0),(lo[0],lo[1]-15,0),(hi[0],lo[1]-15,0)))
        for i,(name,key,value,yy,x0,x1) in enumerate(sections):
            xx=lo[0]-18-i*7
            specs.append((name,value,'region_width',(xx,yy,0),key,(x0,yy,0),(x1,yy,0)))
        specs.append(('Espessura total',float(size[2]),'height',(hi[0]+25,0,hi[2]),(hi[0]+21,0,0),(hi[0]+21,0,hi[2])))
        for spec in specs:
            name,value,kind,anchor,*rest=spec
            key=rest.pop(0) if kind=='region_width' else None
            segments=rest
            for a,b in zip(segments[::2],segments[1::2]):
                line=gl.GLLinePlotItem(pos=np.array([a,b],dtype=float),color=(.25,.43,.49,.78),width=1.3,mode='lines',antialias=True)
                self.dimension_items.append(line); self.viewer.addItem(line)
            text=gl.GLTextItem(pos=anchor,text=f'{name}: {value:.1f} mm',color='#536e7c',font=G.QFont('Segoe UI',9))
            self.dimension_labels.append(text); self.dimension_specs.append((name,value,kind,key))
            self.dimension_items.append(text); self.viewer.addItem(text)
        self.metrics.setText(f'{size[1]:.1f} mm comprimento     ×     {size[0]:.1f} mm largura     ×     {size[2]:.1f} mm altura')
        self.metrics.setToolTip('')
        self.status.setText(f'Contorno suavizado  •  {len(f):,} triângulos  •  geração em {elapsed*1000:.0f} ms  •  STL em milímetros')
        self.badge.setText('●  MODELO ATUALIZADO')
        self.export_button.setEnabled(True)
        self.update_overlay()

    def _project_dimension(self, item):
        point=item.pos
        viewport=(0,0,self.viewer.width(),self.viewer.height())
        transform=self.viewer.projectionMatrix(viewport,viewport)*self.viewer.viewMatrix()
        projected=transform.map(G.QVector3D(float(point[0]),float(point[1]),float(point[2])))
        if projected.z() < -1 or projected.z() > 1: return None
        return C.QPointF((projected.x()+1)*self.viewer.width()/2,(1-projected.y())*self.viewer.height()/2)

    def edit_dimension_at(self, pos):
        if not self.dimension_labels: return False
        for i,item in enumerate(self.dimension_labels):
            point=self._project_dimension(item)
            if point is None: continue
            text=item.text
            bounds=G.QFontMetrics(item.font).tightBoundingRect(text)
            rect=C.QRectF(point.x()-2,point.y()-bounds.height()-6,max(bounds.width()+8,65),bounds.height()+12)
            if rect.contains(pos):
                self.open_dimension_editor(i,point)
                return True
        return False

    def open_dimension_editor(self,index,point):
        if self.dimension_editor is not None:
            self.commit_dimension_edit()
        name,value,kind,key=self.dimension_specs[index]
        editor=W.QLineEdit(self.viewer)
        editor.setObjectName('dimensionEditor')
        editor.setStyleSheet('QLineEdit#dimensionEditor {background:#ffffff; color:#142438; border:2px solid #20a88c; border-radius:5px; padding:3px 7px; font-size:13px;}')
        editor.setFixedSize(150,30)
        editor.setText(f'{value:.1f}')
        editor.setValidator(G.QRegularExpressionValidator(
            C.QRegularExpression(r'[0-9]{0,3}(?:[.,][0-9]?)?'),editor))
        editor.setGeometry(int(point.x()),max(0,int(point.y()-32)),150,30)
        editor.editingFinished.connect(self.commit_dimension_edit)
        self.dimension_editor=editor
        self.dimension_edit_index=index
        editor.show(); editor.raise_(); editor.setFocus(); editor.selectAll()

    def commit_dimension_edit(self):
        editor=self.dimension_editor
        if editor is None: return
        self.dimension_editor=None
        index=self.dimension_edit_index
        text=editor.text().strip().replace(',','.')
        editor.hide(); editor.deleteLater()
        try: edited=float(text)
        except ValueError: return
        name,value,kind,key=self.dimension_specs[index]
        edited=max(.5,min(600,edited))
        if kind=='length':
            if self.foot_scan is not None:
                self.fit_values['fit_scale'].setValue(self.fit_values['fit_scale'].value()*edited/max(value,1e-6))
            else:
                self.values['length'].setValue(max(20,min(600,edited)))
        elif kind=='width':
            if self.foot_scan is not None:
                self.fit_values['fit_scale'].setValue(self.fit_values['fit_scale'].value()*edited/max(value,1e-6))
            else:
                self.values['width_scale'].setValue(max(30,min(180,self.values['width_scale'].value()*edited/max(value,1e-6))))
        elif kind=='region_width':
            self.width_targets[key]=max(10,min(250,edited))
            self.schedule()
        elif kind=='height':
            field=self.values['base']
            field.setValue(max(.5,min(50,field.value()+edited-value)))

    def appearance(self,*args):
        if self.mesh_item:
            colors = [(0.21,.70,.58,1),(1,.65,.22,1),(.80,.85,.91,1)]
            self.mesh_item.setColor(colors[self.material.currentIndex()])
            self.mesh_item.opts['drawEdges'] = self.wire.isChecked()
            self.mesh_item.opts['edgeColor'] = (.12,.22,.27,.25)
            self.mesh_item.meshDataChanged()

    def toggle_foot_visibility(self,visible):
        self.show_foot.setText('Ocultar pé' if visible else 'Mostrar pé')
        self.show_foot.setToolTip('Clique para ocultar o scan do pé.' if visible else 'Clique para mostrar o scan do pé.')
        self.update_overlay()

    def update_overlay(self,*args):
        if self.mesh is None or self.mesh_item is None or not hasattr(self,'view_mode'):
            return
        mode = self.view_mode.currentIndex()
        if mode != self.overlay_mode:
            self.overlay_mode = mode
            if mode in (1,2,3):
                self.view(36,-48)
        if self.foot_item is not None:
            self.viewer.removeItem(self.foot_item)
            self.foot_item = None
        if self.pressure_item is not None:
            self.viewer.removeItem(self.pressure_item)
            self.pressure_item = None
        vertices,faces = self.mesh
        if self.foot_scan is not None:
            if self.show_foot.isChecked():
                foot_v=self.foot_scan.reshape(-1,3).copy()
                sole_top=vertices[:len(vertices)//2]
                foot_center=(foot_v[:,:2].min(axis=0)+foot_v[:,:2].max(axis=0))/2
                sole_center=(sole_top[:,:2].min(axis=0)+sole_top[:,:2].max(axis=0))/2
                angle=np.deg2rad(self.morph_values['morph_rotation'].value())
                rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
                foot_v[:,:2]=(foot_v[:,:2]-foot_center)@rotation.T+sole_center+np.array([
                    self.morph_values['morph_offset_x'].value(),self.morph_values['morph_offset_y'].value()])
                foot_v[:,2]+=float(np.median(sole_top[:,2]))
                foot_f=np.arange(len(foot_v),dtype=np.int32).reshape(-1,3)
                foot_colors=np.tile([.86,.52,.35,.30],(len(foot_v),1))
                self.foot_item = gl.GLMeshItem(vertexes=foot_v,faces=foot_f,vertexColors=foot_colors,
                    smooth=True,shader=self.surface_shader,drawEdges=False,computeNormals=True)
                self.foot_item.setGLOptions('translucent')
                self.viewer.addItem(self.foot_item)
        elif mode == 1:
            params = self.parameters()
            foot_v,foot_f,foot_colors = foot_surface(vertices,faces,params,
                self.foot_values['height'].value(),self.foot_values['ankle'].value(),
                self.foot_values['toe_relief'].value())
            foot_colors = np.vstack([foot_colors,np.tile([.84,.55,.40,1.],(len(foot_colors),1))])
            self.foot_item = gl.GLMeshItem(vertexes=foot_v,faces=foot_f,vertexColors=foot_colors,
                smooth=True,shader=self.surface_shader,drawEdges=False,computeNormals=True)
            self.viewer.addItem(self.foot_item)
        if mode in (2,3):
            top_count = len(vertices)//2
            top_vertices = vertices[:top_count].copy()
            top_faces = faces[(faces < top_count).all(axis=1)]
            top_vertices[:,2] += .16
            if mode==3:
                colors=morphology_colors(top_vertices)
            else:
                levels = [self.pressure_values[k].value()/100 for k in ('heel','midfoot','forefoot','toes')]
                colors = pressure_colors(top_vertices,self.side.currentText(),levels)
            data = gl.MeshData(vertexes=top_vertices,faces=top_faces,vertexColors=colors)
            self.pressure_item = gl.GLMeshItem(meshdata=data,smooth=True,
                shader=self.surface_shader,drawEdges=False,computeNormals=True)
            self.viewer.addItem(self.pressure_item)

    def view(self,elevation,azimuth):
        self.viewer.opts['center'] = G.QVector3D(0,0,0)
        self.viewer.setCameraPosition(distance=self.values['length'].value()*1.65,elevation=elevation,azimuth=azimuth)

    def open_image(self):
        path,_ = W.QFileDialog.getOpenFileName(self,'Importar palmilha','','Imagens (*.png *.jpg *.jpeg)')
        if path: self.load(path)

    def open_foot_stl(self):
        path,_=W.QFileDialog.getOpenFileName(self,'Importar digitalização do pé','','Modelo STL (*.stl)')
        if not path: return
        self.load_foot(path)

    def load_foot(self,path):
        try:
            raw=load_stl(path)
            scale=self.fit_values['fit_scale'].value()/100
            normalized=normalize_foot_scan(raw,scale)
        except (OSError,ValueError) as exc:
            W.QMessageBox.warning(self,'Não foi possível importar o pé',str(exc))
            return
        self.foot_scan_raw=raw
        self.foot_scan=normalized
        self.foot_scan_path=path
        self.source_id+=1
        self.scan_filename.setText('Scan: '+Path(path).name)
        lower_name=Path(path).name.lower()
        if 'right' in lower_name or 'direit' in lower_name:
            self.side.setCurrentText('Direito')
        elif 'left' in lower_name or 'esquerd' in lower_name:
            self.side.setCurrentText('Esquerdo')
        for field in self.fit_values.values(): field.setEnabled(True)
        self.solemorph_toggle.setChecked(True)
        self.solemorph_toggle.setEnabled(not self.flat_insole.isChecked())
        for field in self.morph_values.values(): field.setEnabled(not self.flat_insole.isChecked())
        self.show_foot.blockSignals(True)
        self.show_foot.setChecked(False)
        self.show_foot.setText('Mostrar pé')
        self.show_foot.blockSignals(False)
        self.show_foot.setToolTip('Clique para mostrar o scan do pé.')
        self.show_foot.setVisible(True)
        self.view_mode.setCurrentIndex(0)
        self.model_note.setText('O scan é usado para moldar a superfície superior. A silhueta e a base da palmilha permanecem independentes e imprimíveis.')
        self.status.setText('Scan importado. SoleMorph está ativo; confira o alinhamento e a escala antes de exportar.')
        self.schedule()

    def rescale_foot_scan(self,*args):
        if self.foot_scan_raw is None: return
        try:
            self.foot_scan=normalize_foot_scan(self.foot_scan_raw,self.fit_values['fit_scale'].value()/100)
        except ValueError as exc:
            W.QMessageBox.warning(self,'Escala inválida',str(exc))
            return
        self.schedule()

    def load(self,path):
        self.foot_scan=None
        self.foot_scan_raw=None
        self.foot_scan_path=None
        self.scan_filename.setText('Nenhum scan de pé carregado')
        self.solemorph_toggle.setEnabled(False)
        for field in self.morph_values.values(): field.setEnabled(False)
        for key in ('tolerance','length','width_scale','heel','arch'):
            self.values[key].setEnabled(not self.flat_insole.isChecked() if key in ('heel','arch') else True)
        for field in self.fit_values.values(): field.setEnabled(False)
        for control in (self.mark_contour_button,self.finish_contour_button,self.reset_contour_button):
            control.setEnabled(True)
        if self.foot_item is not None:
            self.viewer.removeItem(self.foot_item)
            self.foot_item=None
        self.view_mode.setCurrentIndex(0)
        self.show_foot.setChecked(False)
        self.show_foot.setText('Mostrar pé')
        self.show_foot.setVisible(False)
        self.tabs.setTabText(1,'Contorno detectado')
        self.tabs.setCurrentIndex(0)
        self.model_note.setText('O contorno vem da imagem. Altura, arco e calcanhar são estimados pelos ajustes.')
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
        if event.mimeData().hasUrls() and Path(event.mimeData().urls()[0].toLocalFile()).suffix.lower() in ('.png','.jpg','.jpeg','.stl'):
            event.acceptProposedAction()

    def dropEvent(self,event):
        path=event.mimeData().urls()[0].toLocalFile()
        if Path(path).suffix.lower()=='.stl':
            self.load_foot(path)
        else:
            self.load(path)

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
        current_side=self.side.currentText()
        choices=['Par de palmilhas (Esquerdo + Direito)',f'Somente modelo atual ({current_side})']
        choice,ok=W.QInputDialog.getItem(self,'Exportar STL','Escolha o que deseja exportar:',choices,0,False)
        if not ok: return
        export_pair=choice==choices[0]
        initial='palmilha_par.stl' if export_pair else f'palmilha_{current_side.lower()}.stl'
        path,_=W.QFileDialog.getSaveFileName(self,'Salvar arquivo STL',initial,'STL (*.stl)')
        if not path: return
        if not path.lower().endswith('.stl'): path += '.stl'
        try:
            if export_pair:
                base=Path(path)
                stem=base.stem.removesuffix('_par')
                left_path=base.with_name(stem+'_esquerdo.stl')
                right_path=base.with_name(stem+'_direito.stl')
                targets=[left_path,right_path]
                existing=[str(p) for p in targets if p.exists()]
                if existing and W.QMessageBox.question(self,'Substituir arquivos?',
                    'Estes arquivos já existem e serão substituídos:\n'+'\n'.join(existing),
                    W.QMessageBox.Yes|W.QMessageBox.No,W.QMessageBox.No)!=W.QMessageBox.Yes:
                    return
                opposite=mirror_mesh(*self.mesh)
                pair={current_side:self.mesh,'Direito' if current_side=='Esquerdo' else 'Esquerdo':opposite}
                save_stl(str(left_path),*pair['Esquerdo'])
                save_stl(str(right_path),*pair['Direito'])
                self.status.setText(f'Par exportado: {left_path.name} e {right_path.name}')
            else:
                save_stl(path,*self.mesh)
                self.status.setText('STL exportado: '+path)
        except OSError as exc:
            W.QMessageBox.warning(self,'Não foi possível exportar',str(exc))

    def closeEvent(self,event):
        self.timer.stop()
        self.pool.waitForDone()
        event.accept()


def main():
    # Prefer the Windows desktop OpenGL implementation. Qt may otherwise select
    # an ANGLE/ES or core context that is incompatible with pyqtgraph's legacy GL.
    W.QApplication.setAttribute(C.Qt.AA_UseDesktopOpenGL, True)
    fmt = G.QSurfaceFormat()
    # Request the widely supported OpenGL 2.1 desktop context. Profiles are only
    # defined for OpenGL 3.2+, so leave this as NoProfile for maximum driver
    # compatibility with pyqtgraph's legacy OpenGL calls.
    fmt.setRenderableType(G.QSurfaceFormat.OpenGL)
    fmt.setVersion(2,1)
    fmt.setProfile(G.QSurfaceFormat.NoProfile)
    fmt.setSamples(0)
    fmt.setDepthBufferSize(24)
    G.QSurfaceFormat.setDefaultFormat(fmt)
    app = W.QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__': main()
