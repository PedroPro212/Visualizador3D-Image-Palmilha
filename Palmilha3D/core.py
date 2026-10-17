"""Processamento local de silhuetas e malha fechada, em milímetros."""
from collections import deque
import struct
import numpy as np
from PIL import Image, ImageDraw


def largest_component(mask):
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best = []
    for y, x in zip(*np.where(mask)):
        if seen[y, x]:
            continue
        q = deque([(y, x)])
        seen[y, x] = True
        part = []
        while q:
            a, b = q.popleft()
            part.append((a, b))
            for c, d in ((a-1,b),(a+1,b),(a,b-1),(a,b+1)):
                if 0 <= c < h and 0 <= d < w and mask[c,d] and not seen[c,d]:
                    seen[c,d] = True
                    q.append((c,d))
        if len(part) > len(best):
            best = part
    result = np.zeros_like(mask, dtype=bool)
    if best:
        yy, xx = zip(*best)
        result[yy, xx] = True
    return result


def extract_mask(image, tolerance=45, polygon=None):
    im = image.copy().convert('RGBA')
    im.thumbnail((420,420))
    if polygon:
        m = Image.new('L', im.size)
        ImageDraw.Draw(m).polygon([(x*im.width,y*im.height) for x,y in polygon], fill=255)
        mask = np.asarray(m) > 0
    else:
        a = np.asarray(im)
        if (a[:,:,3] < 128).any():
            mask = a[:,:,3] > 128
        else:
            rgb = a[:,:,:3].astype(float)
            corners = np.concatenate([rgb[:5,:5].reshape(-1,3),rgb[:5,-5:].reshape(-1,3),rgb[-5:,:5].reshape(-1,3),rgb[-5:,-5:].reshape(-1,3)])
            bg = np.median(corners,axis=0)
            mask = np.linalg.norm(rgb-bg,axis=2) > tolerance
    mask = largest_component(mask)
    if mask.sum() < 80:
        raise ValueError('Contorno não encontrado. Ajuste a tolerância ou marque o contorno manualmente.')
    # Preenche furos internos por inundação do fundo a partir das bordas.
    padded = np.pad(mask,1)
    outside = np.zeros_like(padded)
    q = deque([(0,0)])
    outside[0,0] = True
    while q:
        y,x = q.popleft()
        for yy,xx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
            if 0 <= yy < padded.shape[0] and 0 <= xx < padded.shape[1] and not padded[yy,xx] and not outside[yy,xx]:
                outside[yy,xx] = True
                q.append((yy,xx))
    mask = (~outside)[1:-1,1:-1]
    ys,xs = np.where(mask)
    mask = mask[ys.min():ys.max()+1,xs.min():xs.max()+1]
    if mask.shape[1] > mask.shape[0]:
        mask = np.rot90(mask)
    return mask


def build_mesh(mask, length=270, base=3, heel=5, arch=12, side='Esquerdo', resolution=72):
    if length <= 0 or base <= 0 or heel < 0 or arch < 0:
        raise ValueError('Comprimento e espessura devem ser positivos; alturas não podem ser negativas.')
    h,w = mask.shape
    ny = resolution
    nx = max(8, round(ny*w/h))
    cells = np.asarray(Image.fromarray(mask).resize((nx,ny), Image.Resampling.NEAREST)).astype(bool)
    scale = length/ny
    vertices, faces, lookup = [], [], {}
    def vertex(x,y,top):
        key = (x,y,top)
        if key not in lookup:
            u,v = x/nx,y/ny
            medial = .72 if side == 'Esquerdo' else .28
            z = base + heel*np.exp(-((v-.88)/.19)**2) + arch*np.exp(-((v-.57)/.22)**2-((u-medial)/.24)**2)
            lookup[key] = len(vertices)
            vertices.append(((x-nx/2)*scale,(ny-y)*scale,z if top else 0))
        return lookup[key]
    def quad(coords):
        a,b,c,d = [vertex(*p) for p in coords]
        faces.extend(((a,b,c),(a,c,d)))
    for y,x in zip(*np.where(cells)):
        # Clockwise image coordinates become counterclockwise in world XY.
        ring = [(x,y),(x,y+1),(x+1,y+1),(x+1,y)]
        quad([(a,b,True) for a,b in ring])
        quad([(a,b,False) for a,b in reversed(ring)])
        for i,(dx,dy) in enumerate(((-1,0),(0,1),(1,0),(0,-1))):
            xx,yy = x+dx,y+dy
            if not (0 <= xx < nx and 0 <= yy < ny and cells[yy,xx]):
                a,b = ring[i],ring[(i+1)%4]
                quad([(*b,True),(*a,True),(*a,False),(*b,False)])
    return np.array(vertices,float),np.array(faces,int)


def save_stl(path, vertices, faces):
    with open(path,'wb') as f:
        f.write(b'Palmilha3D - millimeters'.ljust(80,b' '))
        f.write(struct.pack('<I',len(faces)))
        for face in faces:
            triangle = vertices[face]
            normal = np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])
            normal /= max(np.linalg.norm(normal),1e-12)
            f.write(struct.pack('<12fH',*normal,*triangle.flatten(),0))


def demo_image():
    im = Image.new('RGB',(220,520),'white')
    ImageDraw.Draw(im).polygon([(65,22),(110,12),(157,28),(185,70),(194,135),(175,210),(143,290),(143,366),(159,438),(143,487),(106,503),(65,490),(48,453),(49,391),(57,325),(45,250),(27,167),(28,90),(43,43)],fill='#567c40')
    return im
