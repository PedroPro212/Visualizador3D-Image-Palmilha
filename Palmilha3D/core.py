"""Contorno suave, triangulação restrita e STL em milímetros."""
import struct
import re
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from scipy.ndimage import distance_transform_edt, gaussian_filter, gaussian_filter1d, map_coordinates
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree
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


def build_mesh(mask,length=270,base=3,heel=5,arch=12,side='Esquerdo',resolution=220,smoothing=1.2,width_scale=100,width_targets=None,rim_height=0,rim_width=8):
    if not np.isfinite([length,base,heel,arch,resolution,smoothing,width_scale,rim_height,rim_width]).all() or not (20<=length<=600 and .5<=base<=50 and 0<=heel<=80 and 0<=arch<=80 and 24<=resolution<=320 and 0<=smoothing<=5 and 30<=width_scale<=180 and 0<=rim_height<=20 and .5<=rim_width<=40):
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
    bottom_xy = xy.copy()
    bottom_z = np.zeros(len(xy),dtype=float)
    if rim_height > 0:
        # Recess the underside perimeter inward and downward, fading into the sole.
        edge_distance,nearest=cKDTree(p).query(xy,workers=-1)
        rim=np.clip(1-edge_distance/rim_width,0,1)
        rim=rim*rim*(3-2*rim)
        bottom_z -= rim_height*rim
        outward=p[nearest]-xy
        lengths=np.linalg.norm(outward,axis=1)
        on_edge=lengths<1e-8
        if np.any(on_edge):
            tangent=np.roll(p,-1,axis=0)-np.roll(p,1,axis=0)
            edge_tangent=tangent[nearest[on_edge]]
            outward[on_edge]=np.column_stack([edge_tangent[:,1],-edge_tangent[:,0]])
            lengths[on_edge]=np.linalg.norm(outward[on_edge],axis=1)
        outward/=np.maximum(lengths[:,None],1e-8)
        bottom_xy -= outward*(rim_width*rim)[:,None]
    n = len(xy)
    middle_z=(z+bottom_z)/2
    vertices = np.vstack([np.column_stack([xy,z]),
                          np.column_stack([bottom_xy,bottom_z]),
                          np.column_stack([xy,middle_z])])
    edges = np.vstack([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]])
    _,inverse,counts = np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    a,b = edges[counts[inverse]==1].T
    middle=a+2*n
    # Keep the upper half of the side wall vertical; the lower half forms the
    # inward/downward resalto shown in the reference.
    upper_walls=np.vstack([np.column_stack([b,a,middle]),
                           np.column_stack([b,middle,b+2*n])])
    lower_walls=np.vstack([np.column_stack([b+2*n,a+2*n,a+n]),
                           np.column_stack([b+2*n,a+n,b+n])])
    walls=np.vstack([upper_walls,lower_walls])
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


def load_stl(path):
    """Read binary or ASCII STL into an (n, 3, 3) float32 triangle array."""
    with open(path,'rb') as source:
        data=source.read()
    if len(data)>=84:
        count=struct.unpack('<I',data[80:84])[0]
        if 84+count*50==len(data) and count>0:
            records=np.frombuffer(data,dtype=[('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attribute','<u2')],offset=84,count=count)
            triangles=records['vertices'].copy()
        else:
            text=data.decode('utf-8-sig',errors='ignore')
            coords=re.findall(r'\bvertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)',text,re.IGNORECASE)
            if len(coords)<30 or len(coords)%3:
                raise ValueError('O arquivo não parece ser um STL válido.')
            triangles=np.asarray(coords,dtype=np.float32).reshape(-1,3,3)
    else:
        raise ValueError('O arquivo STL está vazio ou incompleto.')
    if len(triangles)<10 or not np.isfinite(triangles).all():
        raise ValueError('O STL não contém uma malha de pé válida.')
    return triangles.astype(np.float32,copy=False)


def normalize_foot_scan(triangles,scale=1.0):
    """Center an upright foot scan in XY, put its lowest point at Z=0, and scale to mm."""
    if not np.isfinite(scale) or not .05<=scale<=1000:
        raise ValueError('A escala do STL deve ficar entre 5% e 100.000%.')
    tris=np.asarray(triangles,dtype=np.float32).copy()*float(scale)
    if tris.ndim!=3 or tris.shape[1:]!=(3,3) or not np.isfinite(tris).all():
        raise ValueError('Malha STL inválida.')
    points=tris.reshape(-1,3)
    lo,hi=points.min(axis=0),points.max(axis=0)
    extent=hi-lo
    if extent[1]<20 or extent[1]>600 or extent[0]<20 or extent[0]>300 or extent[2]<10 or extent[2]>300:
        raise ValueError('Orientação ou escala inesperada. O pé deve estar deitado, com comprimento no eixo Y e altura no eixo Z; confira a escala em milímetros.')
    tris[:,:,0]-=(lo[0]+hi[0])/2
    tris[:,:,1]-=(lo[1]+hi[1])/2
    tris[:,:,2]-=lo[2]
    return tris


def _smooth_mask_outline(mask,x_min,y_min,pixels_per_mm,smoothing):
    contours,_=cv2.findContours(mask.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError('Não foi possível detectar o contorno plantar do STL.')
    contour=max(contours,key=cv2.contourArea)[:,0,:].astype(float)
    p=np.column_stack([x_min+contour[:,0]/pixels_per_mm,y_min+contour[:,1]/pixels_per_mm])
    closed=np.vstack([p,p[0]])
    d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(closed,axis=0),axis=1))]
    if d[-1]<40:
        raise ValueError('O contorno plantar do STL é pequeno ou incompleto.')
    t=np.linspace(0,d[-1],min(2200,max(300,int(d[-1]*2))),endpoint=False)
    p=np.column_stack([np.interp(t,d,closed[:,i]) for i in range(2)])
    if smoothing:
        p=gaussian_filter1d(p,float(smoothing)*pixels_per_mm,axis=0,mode='wrap')
    area=np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1))
    return p if area>0 else p[::-1].copy()


def build_conformed_insole(foot_triangles,thickness=3,clearance=1,plantar_limit=20,resolution=220,smoothing=.6,surface_smoothing=0):
    """Create a watertight insole whose top follows the scan's lower plantar band.

    The scan must use millimeters, length on Y, and vertical on Z. Faces above
    plantar_limit are ignored to exclude the dorsum and ankle. Clearance is
    subtracted so the insole sits below the scanned plantar surface.
    """
    tris=np.asarray(foot_triangles,dtype=np.float64)
    if tris.ndim!=3 or tris.shape[1:]!=(3,3) or len(tris)<10 or not np.isfinite(tris).all():
        raise ValueError('Malha de pé inválida.')
    if not np.isfinite([thickness,clearance,plantar_limit,resolution,smoothing,surface_smoothing]).all() or not (.5<=thickness<=50 and 0<=clearance<=10 and 5<=plantar_limit<=60 and 24<=resolution<=500 and 0<=smoothing<=5 and 0<=surface_smoothing<=10):
        raise ValueError('Espessura, folga ou suavização fora dos limites.')

    pts=tris.reshape(-1,3)
    lo,hi=pts.min(axis=0),pts.max(axis=0)
    pixels_per_mm=2.0
    margin=2.0
    x_min,y_min=lo[:2]-margin
    width=int(np.ceil((hi[0]-x_min+margin)*pixels_per_mm))+2
    height=int(np.ceil((hi[1]-y_min+margin)*pixels_per_mm))+2
    if width*height>2_000_000:
        raise ValueError('A escala do STL gera uma área de processamento grande demais.')
    footprint=np.zeros((height,width),dtype=np.uint8)
    plantar=np.full((height,width),np.inf,dtype=np.float32)
    px=tris[:,:,:2].copy()
    px[:,:,0]=(px[:,:,0]-x_min)*pixels_per_mm
    px[:,:,1]=(px[:,:,1]-y_min)*pixels_per_mm
    for i,tri_px in enumerate(px):
        # Ignore the raised dorsum and ankle when the STL contains the whole foot.
        # Only the lower band contributes to the insole footprint and fit surface.
        if tris[i,:,2].max()>plantar_limit:
            continue
        poly=np.rint(tri_px).astype(np.int32)
        if np.all(np.abs(poly)<2_000_000):
            cv2.fillConvexPoly(footprint,poly,1)
        area=(tri_px[1,0]-tri_px[0,0])*(tri_px[2,1]-tri_px[0,1])-(tri_px[1,1]-tri_px[0,1])*(tri_px[2,0]-tri_px[0,0])
        if abs(area)<1e-5:
            continue
        x0=max(0,int(np.floor(tri_px[:,0].min())))
        x1=min(width-1,int(np.ceil(tri_px[:,0].max())))
        y0=max(0,int(np.floor(tri_px[:,1].min())))
        y1=min(height-1,int(np.ceil(tri_px[:,1].max())))
        if x1<x0 or y1<y0:
            continue
        gx,gy=np.meshgrid(np.arange(x0,x1+1),np.arange(y0,y1+1))
        w0=((tri_px[1,0]-gx)*(tri_px[2,1]-gy)-(tri_px[1,1]-gy)*(tri_px[2,0]-gx))/area
        w1=((tri_px[2,0]-gx)*(tri_px[0,1]-gy)-(tri_px[2,1]-gy)*(tri_px[0,0]-gx))/area
        w2=1-w0-w1
        inside=(w0>=-.01)&(w1>=-.01)&(w2>=-.01)
        if inside.any():
            z=w0*tris[i,0,2]+w1*tris[i,1,2]+w2*tris[i,2,2]
            block=plantar[y0:y1+1,x0:x1+1]
            np.minimum(block,np.where(inside,z,np.inf),out=block)

    if not footprint.any() or not np.isfinite(plantar).any():
        raise ValueError('Não encontrei faces suficientes na região plantar. Aumente o limite plantar ou confira a orientação e a escala do STL.')
    footprint=cv2.morphologyEx(footprint,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    contours,_=cv2.findContours(footprint,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    footprint[:]=0
    cv2.drawContours(footprint,[max(contours,key=cv2.contourArea)],-1,1,cv2.FILLED)
    nearest=distance_transform_edt(~np.isfinite(plantar),return_distances=False,return_indices=True)
    plantar_filled=plantar[tuple(nearest)].astype(np.float32)
    if surface_smoothing>0:
        plantar_filled=gaussian_filter(plantar_filled,float(surface_smoothing)*pixels_per_mm,mode='nearest')
    outline=_smooth_mask_outline(footprint,x_min,y_min,pixels_per_mm,smoothing)
    segments=np.column_stack([np.arange(len(outline)),np.roll(np.arange(len(outline)),-1)])
    length=float(np.ptp(outline[:,1]))
    tri=triangle.triangulate({'vertices':outline,'segments':segments},f'pq25a{(length/resolution)**2/2:.6f}Q')
    xy=tri['vertices']
    faces=tri['triangles'].astype(np.int32)
    ab,ac=xy[faces[:,1]]-xy[faces[:,0]],xy[faces[:,2]]-xy[faces[:,0]]
    flip=ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0]<0
    faces[flip]=faces[flip,::-1]
    grid_x=(xy[:,0]-x_min)*pixels_per_mm
    grid_y=(xy[:,1]-y_min)*pixels_per_mm
    sole=map_coordinates(plantar_filled,[grid_y,grid_x],order=1,mode='nearest')
    top_z=sole-float(clearance)
    bottom_z=top_z-float(thickness)
    n=len(xy)
    vertices=np.vstack([np.column_stack([xy,top_z]),np.column_stack([xy,bottom_z])])
    edges=np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]])
    _,inverse,counts=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    a,b=edges[counts[inverse]==1].T
    walls=np.vstack([np.column_stack([b,a,a+n]),np.column_stack([b,a+n,b+n])])
    mesh_faces=np.vstack([faces,faces[:,::-1]+n,walls]).astype(np.int32)
    return vertices,mesh_faces,footprint


def build_sole_morph(foot_triangles, base_mesh, thickness=3, clearance=1,
                     plantar_limit=20, resolution=220, smoothing=.6,
                     planes=3, start_at=.5, plane_spacing=5,
                     offset_x=0, offset_y=0, rotation_deg=0,
                     surface_smoothing=6, blend_distance=30, morph_strength=55):
    """Morph only the top of a separate insole using the plantar scan surface.

    The silhouette and bottom of base_mesh stay intact. Scan scale is preserved;
    its plantar relief is sampled in the centered XY frame with user offsets.
    """
    if (not np.isfinite([planes,start_at,plane_spacing,offset_x,offset_y,rotation_deg,surface_smoothing,blend_distance,morph_strength]).all() or
            not (1<=planes<=12 and 0<=start_at<=20 and .5<=plane_spacing<=20 and
                 -100<=offset_x<=100 and -100<=offset_y<=100 and -45<=rotation_deg<=45 and
                 0<=surface_smoothing<=10 and 2<=blend_distance<=50 and 0<=morph_strength<=100)):
        raise ValueError('Parâmetros SoleMorph fora dos limites permitidos.')
    base_vertices,base_faces=base_mesh
    base_vertices=np.asarray(base_vertices,dtype=np.float64).copy()
    base_faces=np.asarray(base_faces,dtype=np.int32).copy()
    if len(base_vertices)<12 or len(base_vertices)%3:
        raise ValueError('A malha base da palmilha é inválida.')
    depth=min(float(plantar_limit),float(start_at)+max(1,int(planes)-1)*float(plane_spacing))
    scan_vertices,_,footprint=build_conformed_insole(foot_triangles,thickness=thickness,
        clearance=0,plantar_limit=max(5,depth),resolution=resolution,smoothing=smoothing,
        surface_smoothing=surface_smoothing)
    scan_count=len(scan_vertices)//2
    scan_top=scan_vertices[:scan_count]
    top_count=len(base_vertices)//3
    base_top=base_vertices[:top_count]
    scan_xy=scan_top[:,:2]
    scan_lo,scan_hi=scan_xy.min(axis=0),scan_xy.max(axis=0)
    base_lo,base_hi=base_top[:,:2].min(axis=0),base_top[:,:2].max(axis=0)
    if np.any(scan_hi-scan_lo<1) or np.any(base_hi-base_lo<1):
        raise ValueError('Não foi possível alinhar o scan do pé à palmilha.')
    scan_center=(scan_lo+scan_hi)/2
    base_center=(base_lo+base_hi)/2+np.array([float(offset_x),float(offset_y)])
    angle=np.deg2rad(float(rotation_deg))
    rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    aligned_xy=(scan_xy-scan_center)@rotation.T+base_center
    query=(base_top[:,:2]-base_center)@rotation+scan_center
    plantar=scan_top[:,2]
    linear=LinearNDInterpolator(aligned_xy,plantar,fill_value=np.nan)
    sampled=np.asarray(linear(query),dtype=np.float64)
    # Fade the scan relief smoothly to the original surface at its footprint edge.
    baseline=float(np.percentile(plantar,10))
    sampled[~np.isfinite(sampled)]=baseline
    relief=np.clip(sampled-baseline-float(clearance),0,max(1.,depth))
    inside=footprint.astype(bool)
    signed_distance=distance_transform_edt(inside)-distance_transform_edt(~inside)
    # The raster in build_conformed_insole uses 2 px/mm with a 2 mm border.
    gx=(query[:,0]-(scan_lo[0]-2.0))*2.0
    gy=(query[:,1]-(scan_lo[1]-2.0))*2.0
    distance_mm=map_coordinates(signed_distance,[gy,gx],order=1,mode='constant',cval=-1)/2.0
    blend=np.clip(distance_mm/float(blend_distance),0,1)
    blend=blend*blend*(3-2*blend)
    relief*=blend*(float(morph_strength)/100.0)
    base_top[:,2]+=relief
    # The intermediate side-wall ring follows half of the top relief so its
    # upper section stays continuous after SoleMorph deformation.
    base_vertices[2*top_count:3*top_count,2]+=relief*.5
    # Preserve the original underside, footprint, and watertight side-wall topology.
    return base_vertices,base_faces


def demo_image():
    from scipy.interpolate import splprep, splev
    points = np.array([(65,22),(110,12),(157,28),(185,70),(194,135),(175,210),(143,290),(143,366),(159,438),(143,487),(106,503),(65,490),(48,453),(49,391),(57,325),(45,250),(27,167),(28,90),(43,43),(65,22)])
    spline,_ = splprep(points.T,s=0,per=True)
    curve = np.column_stack(splev(np.linspace(0,1,700),spline))*4
    im = Image.new('RGB',(880,2080),'white')
    ImageDraw.Draw(im).polygon([tuple(p) for p in curve],fill='#567c40')
    return im.resize((440,1040),Image.Resampling.LANCZOS)
