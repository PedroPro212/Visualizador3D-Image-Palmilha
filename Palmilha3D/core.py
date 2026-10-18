"""Contorno suave, triangulação restrita e STL em milímetros."""
import struct
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from scipy.ndimage import gaussian_filter1d
import triangle


def largest_component(mask):
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype('uint8'), 8)
    return labels == (1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])) if n > 1 else np.zeros_like(mask, dtype=bool)


def extract_mask(image, tolerance=45, polygon=None):
    if not np.isfinite(tolerance) or not 0 <= tolerance <= 441:
        raise ValueError('A tolerância deve estar entre 0 e 441.')
    im = ImageOps.exif_transpose(image).convert('RGBA')
    im.thumbnail((900, 900), Image.Resampling.LANCZOS)
    if polygon:
        m = Image.new('L', im.size)
        ImageDraw.Draw(m).polygon([(x*im.width,y*im.height) for x,y in polygon], fill=255)
        mask = np.asarray(m) > 0
    else:
        a = np.asarray(im)
        if (a[:,:,3] < 128).any():
            mask = a[:,:,3] > 128
        else:
            rgb = a[:,:,:3].astype(np.float32)
            corners = np.concatenate([rgb[:5,:5].reshape(-1,3),rgb[:5,-5:].reshape(-1,3),rgb[-5:,:5].reshape(-1,3),rgb[-5:,-5:].reshape(-1,3)])
            mask = np.linalg.norm(rgb-np.median(corners,axis=0),axis=2) > tolerance
    mask = largest_component(mask)
    if mask.sum() < 80:
        raise ValueError('Contorno não encontrado. Ajuste a tolerância ou marque manualmente.')
    contours, _ = cv2.findContours(mask.astype('uint8'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(mask, dtype='uint8')
    cv2.drawContours(filled, [max(contours,key=cv2.contourArea)], -1, 1, cv2.FILLED)
    ys,xs = np.where(filled)
    mask = filled[ys.min():ys.max()+1,xs.min():xs.max()+1].astype(bool)
    return np.rot90(mask) if mask.shape[1] > mask.shape[0] else mask


def smooth_outline(mask, smoothing=1.2):
    contours, _ = cv2.findContours(np.pad(mask.astype('uint8'),1), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError('Silhueta vazia.')
    p = max(contours,key=cv2.contourArea)[:,0,:].astype(float)-1
    if len(p) < 4 or cv2.contourArea(p.astype('float32')) < 4:
        raise ValueError('Silhueta muito estreita.')
    closed = np.vstack([p,p[0]])
    d = np.r_[0,np.cumsum(np.linalg.norm(np.diff(closed,axis=0),axis=1))]
    # Sample the source contour densely so STL side walls do not inherit pixel-like facets.
    t = np.linspace(0,d[-1],min(1800,max(240,int(d[-1]/1.5))),endpoint=False)
    p = np.column_stack([np.interp(t,d,closed[:,i]) for i in range(2)])
    if smoothing:
        p = gaussian_filter1d(p,smoothing,axis=0,mode='wrap')
    p[:,1] *= -1
    p -= (p.min(axis=0)+p.max(axis=0))/2
    area = np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1))
    return p if area > 0 else p[::-1].copy()


def build_mesh(mask,length=270,base=3,heel=5,arch=12,side='Esquerdo',resolution=220,smoothing=1.2,width_scale=100,width_targets=None):
    if not np.isfinite([length,base,heel,arch,resolution,smoothing,width_scale]).all() or not (20<=length<=600 and .5<=base<=50 and 0<=heel<=80 and 0<=arch<=80 and 24<=resolution<=320 and 0<=smoothing<=5 and 30<=width_scale<=180):
        raise ValueError('Medidas fora dos limites permitidos.')
    if side not in ('Esquerdo','Direito'):
        raise ValueError('Selecione Esquerdo ou Direito.')
    mask = np.asarray(mask,dtype=bool)
    if mask.ndim != 2 or min(mask.shape)<2:
        raise ValueError('Silhueta inválida.')
    p = smooth_outline(mask,smoothing)
    p *= length/np.ptp(p[:,1])
    p[:,0] *= width_scale/100
    targets = width_targets or {}
    regions = {'toe':(.10,.065),'metatarsal':(.27,.075),'arch':(.55,.075),'heel':(.90,.065)}
    if any(key not in regions or not np.isfinite(value) or not 10<=value<=250 for key,value in targets.items()):
        raise ValueError('Largura de componente fora dos limites permitidos.')
    # Adjust each longitudinal section smoothly while retaining the neighboring outline.
    for _ in range(5):
        fraction=(p[:,1].max()-p[:,1])/length
        for key,target in targets.items():
            center,sigma=regions[key]
            band=max(1.,length*.012)
            section=p[np.abs(fraction-center)*length<=band,0]
            if len(section)<2:
                section=p[np.argsort(np.abs(fraction-center))[:max(2,len(p)//100)],0]
            current=float(section.max()-section.min())
            ratio=float(target)/max(current,1e-6)
            influence=np.exp(-.5*((fraction-center)/sigma)**2)
            p[:,0] *= 1+(ratio-1)*influence
    segments = np.column_stack([np.arange(len(p)),np.roll(np.arange(len(p)),-1)])
    mesh = triangle.triangulate({'vertices':p,'segments':segments},f'pq25a{(length/resolution)**2/2:.6f}Q')
    xy = mesh['vertices']
    f = mesh['triangles'].astype(np.int32)
    ab,ac = xy[f[:,1]]-xy[f[:,0]],xy[f[:,2]]-xy[f[:,0]]
    flip = ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0] < 0
    f[flip] = f[flip,::-1]
    u = (xy[:,0]-p[:,0].min())/np.ptp(p[:,0])
    v = (p[:,1].max()-xy[:,1])/length
    medial = .72 if side=='Esquerdo' else .28
    z = base+heel*np.exp(-((v-.88)/.19)**2)+arch*np.exp(-((v-.57)/.22)**2-((u-medial)/.24)**2)
    n = len(xy)
    vertices = np.vstack([np.column_stack([xy,z]),np.column_stack([xy,np.zeros(n)])])
    edges = np.vstack([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]])
    _,inverse,counts = np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    a,b = edges[counts[inverse]==1].T
    walls = np.vstack([np.column_stack([b,a,a+n]),np.column_stack([b,a+n,b+n])])
    return vertices,np.vstack([f,f[:,::-1]+n,walls]).astype(np.int32)


def save_stl(path,vertices,faces):
    tris = vertices[faces].astype('<f4')
    normals = np.cross(tris[:,1]-tris[:,0],tris[:,2]-tris[:,0])
    normals /= np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
    records = np.zeros(len(faces),dtype=[('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attribute','<u2')])
    records['normal'],records['vertices'] = normals,tris
    with open(path,'wb') as f:
        f.write(b'Palmilha Studio - millimeters'.ljust(80,b' '))
        f.write(struct.pack('<I',len(faces)))
        f.write(records.tobytes())


def mirror_mesh(vertices,faces):
    """Mirror a watertight insole across its longitudinal centerline."""
    mirrored_vertices=vertices.copy()
    mirrored_vertices[:,0]*=-1
    # A reflection reverses handedness; reverse winding to keep outward normals.
    mirrored_faces=np.asarray(faces)[:,::-1].copy()
    return mirrored_vertices,mirrored_faces


def demo_image():
    from scipy.interpolate import splprep, splev
    points = np.array([(65,22),(110,12),(157,28),(185,70),(194,135),(175,210),(143,290),(143,366),(159,438),(143,487),(106,503),(65,490),(48,453),(49,391),(57,325),(45,250),(27,167),(28,90),(43,43),(65,22)])
    spline,_ = splprep(points.T,s=0,per=True)
    curve = np.column_stack(splev(np.linspace(0,1,700),spline))*4
    im = Image.new('RGB',(880,2080),'white')
    ImageDraw.Draw(im).polygon([tuple(p) for p in curve],fill='#567c40')
    return im.resize((440,1040),Image.Resampling.LANCZOS)
