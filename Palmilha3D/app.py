"""Palmilha3D — aplicativo desktop Tkinter, sem navegador ou serviço externo."""
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from PIL import Image, ImageTk, ImageOps
from core import extract_mask, build_mesh, save_stl, demo_image


class App:
    def __init__(self, root):
        self.root = root
        root.title('Palmilha3D • imagem para modelo 3D')
        root.geometry('1280x820')
        root.minsize(1000,680)
        self.image = demo_image()
        self.polygon = []
        self.manual = False
        self.mesh = None
        self.yaw, self.pitch, self.zoom = -30, 58, 1
        self.drag = None
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton',padding=8)
        style.configure('Title.TLabel',font=('Segoe UI',19,'bold'))
        bar = ttk.Frame(root,padding=14)
        bar.pack(fill='x')
        ttk.Label(bar,text='Palmilha3D',style='Title.TLabel').pack(side='left')
        ttk.Label(bar,text='  IMAGEM → CONTORNO → VOLUME',foreground='#567c40').pack(side='left',padx=16)
        ttk.Button(bar,text='Exportar STL',command=self.export).pack(side='right')
        body = ttk.Frame(root,padding=12)
        body.pack(fill='both',expand=True)
        controls = ttk.Frame(body,width=285)
        controls.pack(side='left',fill='y',padx=(0,14))
        controls.pack_propagate(False)
        ttk.Button(controls,text='Abrir JPG / JPEG / PNG',command=self.open_image).pack(fill='x')
        self.filename = ttk.Label(controls,text='Exemplo incluído',wraplength=270)
        self.filename.pack(anchor='w',pady=8)
        self.preview = tk.Canvas(controls,height=230,bg='white',highlightthickness=1,highlightbackground='#d6dce3')
        self.preview.pack(fill='x')
        self.preview.bind('<Button-1>',self.point)
        ttk.Button(controls,text='Marcar contorno manual',command=self.start_manual).pack(fill='x',pady=(8,3))
        ttk.Button(controls,text='Concluir contorno',command=self.finish_manual).pack(fill='x')
        self.values = {}
        for label,key,value in [('Tolerância do fundo','tolerance',45),('Comprimento (mm)','length',270),('Espessura mínima (mm)','base',3),('Elevação do calcanhar (mm)','heel',5),('Elevação do arco (mm)','arch',12)]:
            row = ttk.Frame(controls)
            row.pack(fill='x',pady=5)
            ttk.Label(row,text=label).pack(side='left')
            var = tk.StringVar(value=str(value))
            self.values[key] = var
            ttk.Entry(row,textvariable=var,width=7).pack(side='right')
        self.side = tk.StringVar(value='Esquerdo')
        ttk.Combobox(controls,textvariable=self.side,values=['Esquerdo','Direito'],state='readonly').pack(fill='x',pady=5)
        ttk.Button(controls,text='Gerar / atualizar 3D',command=self.generate).pack(fill='x',pady=8)
        ttk.Button(controls,text='Inverter ponta e calcanhar',command=self.flip).pack(fill='x')
        ttk.Label(controls,text='Imagem: ponta em cima, calcanhar embaixo.\nO lado selecionado posiciona o arco; confira a orientação antes de exportar.',wraplength=275,foreground='#667085').pack(pady=10)
        area = ttk.Frame(body)
        area.pack(side='left',fill='both',expand=True)
        actions = ttk.Frame(area)
        actions.pack(fill='x')
        for name,angles in [('Perspectiva',(-30,58)),('Superior',(0,0)),('Lateral',(0,85))]:
            ttk.Button(actions,text=name,command=lambda a=angles:self.view(a)).pack(side='left',padx=3)
        ttk.Label(actions,text='Arraste para girar • roda do mouse para zoom').pack(side='right')
        self.canvas = tk.Canvas(area,bg='#edf1f6',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,pady=8)
        self.canvas.bind('<Configure>',lambda e:self.render())
        self.canvas.bind('<ButtonPress-1>',lambda e:setattr(self,'drag',(e.x,e.y)))
        self.canvas.bind('<B1-Motion>',self.rotate)
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.status = tk.StringVar(value='')
        ttk.Label(root,textvariable=self.status,padding=10).pack(fill='x')
        self.draw_preview()
        root.after(150,self.generate)

    def open_image(self):
        path = filedialog.askopenfilename(filetypes=[('Imagens','*.jpg *.jpeg *.png')])
        if not path:
            return
        try:
            with Image.open(path) as im:
                self.image = ImageOps.exif_transpose(im).convert('RGBA')
            self.polygon = []
            self.manual = False
            self.mesh = None
            self.canvas.delete('all')
            self.filename.config(text=Path(path).name)
            self.draw_preview()
            self.generate()
        except Exception as exc:
            messagebox.showerror('Não foi possível abrir',str(exc))

    def draw_preview(self):
        im = self.image.copy()
        im.thumbnail((270,220))
        self.photo = ImageTk.PhotoImage(im)
        self.preview.delete('all')
        self.offset = ((280-im.width)/2,(230-im.height)/2)
        self.display_size = im.size
        self.preview.create_image(*self.offset,anchor='nw',image=self.photo)
        points = [(self.offset[0]+x*im.width,self.offset[1]+y*im.height) for x,y in self.polygon]
        if len(points)>1:
            self.preview.create_line(*[n for p in points for n in p],fill='#ed8624',width=2)
        for x,y in points:
            self.preview.create_oval(x-3,y-3,x+3,y+3,fill='#ed8624',outline='white')

    def start_manual(self):
        self.manual = True
        self.polygon = []
        self.draw_preview()
        self.status.set('Clique ao redor da palmilha na imagem e depois em Concluir contorno. Mínimo: 3 pontos.')

    def point(self,e):
        if self.manual:
            x,y = (e.x-self.offset[0])/self.display_size[0],(e.y-self.offset[1])/self.display_size[1]
            if 0<=x<=1 and 0<=y<=1:
                self.polygon.append((x,y))
                self.draw_preview()

    def finish_manual(self):
        if len(self.polygon)<3:
            messagebox.showinfo('Contorno','Marque pelo menos três pontos na imagem.')
            return
        self.manual = False
        self.generate()

    def flip(self):
        self.image = self.image.rotate(180)
        self.polygon = [(1-x,1-y) for x,y in self.polygon]
        self.draw_preview()
        self.generate()

    def generate(self):
        try:
            if self.manual:
                raise ValueError('Conclua o contorno manual antes de gerar.')
            values = {k:float(v.get().replace(',','.')) for k,v in self.values.items()}
            if not all(math.isfinite(v) for v in values.values()):
                raise ValueError('Informe valores numéricos finitos.')
            tolerance = values.pop('tolerance')
            if not 0<=tolerance<=441:
                raise ValueError('A tolerância deve estar entre 0 e 441.')
            mask = extract_mask(self.image,tolerance,self.polygon or None)
            self.mesh = build_mesh(mask,side=self.side.get(),**values)
            self.render()
            v,f = self.mesh
            size = np.ptp(v,axis=0)
            self.status.set(f'Modelo gerado • {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm • {len(f):,} triângulos • volume estimado a partir do contorno')
        except Exception as exc:
            self.mesh = None
            self.canvas.delete('all')
            self.status.set('Ajuste os parâmetros e gere novamente.')
            messagebox.showerror('Verifique a imagem ou os valores',str(exc))

    def view(self,angles):
        self.yaw,self.pitch = angles
        self.zoom = 1
        self.render()

    def rotate(self,e):
        if self.drag:
            self.yaw += (e.x-self.drag[0])*.6
            self.pitch = min(175,max(0,self.pitch+(e.y-self.drag[1])*.5))
            self.drag = (e.x,e.y)
            self.render()

    def wheel(self,e):
        self.zoom = min(5,max(.25,self.zoom*(1.12 if e.delta>0 else 1/1.12)))
        self.render()

    def render(self):
        if self.mesh is None:
            return
        vertices,faces = self.mesh
        v = vertices-(vertices.min(axis=0)+vertices.max(axis=0))/2
        a,b = np.deg2rad([self.yaw,self.pitch])
        rz = np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1]])
        rx = np.array([[1,0,0],[0,np.cos(b),-np.sin(b)],[0,np.sin(b),np.cos(b)]])
        v = v@rz.T@rx.T
        w,h = self.canvas.winfo_width(),self.canvas.winfo_height()
        scale = min(w,h)*.78/max(np.ptp(vertices,axis=0))*self.zoom
        xy = v[:,:2]*[scale,-scale]+[w/2,h/2]
        tri = v[faces]
        normals = np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        light = np.abs(normals@np.array([.25,-.4,.88]))/np.maximum(np.linalg.norm(normals,axis=1),1e-10)
        self.canvas.delete('all')
        for i in np.argsort(tri[:,:,2].mean(axis=1)):
            shade = .52+.48*light[i]
            color = '#%02x%02x%02x'%tuple(int(c*shade) for c in (244,168,64))
            self.canvas.create_polygon(*xy[faces[i]].flatten(),fill=color,outline=color)
        self.canvas.create_text(18,20,anchor='nw',text='PRÉVIA 3D  /  mm',fill='#667085',font=('Segoe UI',10,'bold'))

    def export(self):
        # Recalcula para aplicar também valores editados desde a última prévia.
        self.generate()
        if self.mesh is None:
            return
        path = filedialog.asksaveasfilename(defaultextension='.stl',initialfile='palmilha.stl',filetypes=[('Modelo STL','*.stl')])
        if path:
            try:
                save_stl(path,*self.mesh)
                self.status.set('STL exportado em milímetros: '+path)
            except OSError as exc:
                messagebox.showerror('Erro ao salvar',str(exc))


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
