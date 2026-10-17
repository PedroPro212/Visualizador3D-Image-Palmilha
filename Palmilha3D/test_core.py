import collections
import tempfile
import unittest
from pathlib import Path
import numpy as np
from core import demo_image, extract_mask, build_mesh, save_stl, smooth_outline


class MeshTest(unittest.TestCase):
    def test_closed_oriented_scaled_mesh_and_stl(self):
        mask = extract_mask(demo_image())
        vertices, faces = build_mesh(mask,length=280)
        edges = collections.Counter()
        directed = collections.Counter()
        for a,b,c in faces:
            for x,y in ((a,b),(b,c),(c,a)):
                edges[tuple(sorted((x,y)))] += 1
                directed[(x,y)] += 1
        self.assertTrue(all(n == 2 for n in edges.values()))
        self.assertTrue(all(directed[(b,a)]==n for (a,b),n in directed.items()))
        self.assertAlmostEqual(np.ptp(vertices[:,1]),280)
        self.assertEqual(vertices[:,2].min(),0)
        tris = vertices[faces]
        volume = np.einsum('ij,ij->i',tris[:,0],np.cross(tris[:,1],tris[:,2])).sum()/6
        self.assertGreater(volume,0)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            p = Path(d)/'test.stl'
            save_stl(p,vertices,faces)
            self.assertEqual(p.stat().st_size,84+50*len(faces))

    def test_manual_and_transparent(self):
        im = demo_image().convert('RGBA')
        self.assertGreater(extract_mask(im,polygon=[(.2,.1),(.8,.1),(.7,.9),(.3,.9)]).sum(),100)
        a = np.asarray(im).copy()
        a[:,:,3] = np.where(a[:,:,0]>240,0,255)
        from PIL import Image
        self.assertGreater(extract_mask(Image.fromarray(a)).sum(),100)

    def test_empty_and_invalid(self):
        from PIL import Image
        with self.assertRaises(ValueError):
            extract_mask(Image.new('RGB',(200,400),'white'))
        with self.assertRaises(ValueError):
            build_mesh(np.ones((20,10),bool),base=-1)

    def test_concave_outline_fidelity_and_nondegenerate_faces(self):
        import cv2
        mask = extract_mask(demo_image())
        outline = smooth_outline(mask)
        raster = np.zeros_like(mask, dtype='uint8')
        p = outline.copy()
        p[:,1] *= -1
        p -= p.min(axis=0)
        p *= (np.array([mask.shape[1],mask.shape[0]])-1)/np.ptp(p,axis=0)
        cv2.fillPoly(raster,[np.rint(p).astype('int32')],1)
        iou = np.logical_and(mask,raster).sum()/np.logical_or(mask,raster).sum()
        self.assertGreater(iou,.97)
        vertices,faces = build_mesh(mask)
        tris = vertices[faces]
        area = np.linalg.norm(np.cross(tris[:,1]-tris[:,0],tris[:,2]-tris[:,0]),axis=1)/2
        self.assertTrue((area>1e-8).all())
        top = tris[(tris[:,:,2]>0).all(axis=1)]
        top_area = np.abs(np.cross(top[:,1]-top[:,0],top[:,2]-top[:,0])[:,2]).sum()/2
        outline *= 270/np.ptp(outline[:,1])
        polygon_area = cv2.contourArea(outline.astype('float32'))
        self.assertAlmostEqual(top_area,polygon_area,delta=.01)

    def test_nonfinite_and_empty_mesh_input(self):
        for values in ({'length':float('nan')},{'arch':float('inf')},{'resolution':10000},{'smoothing':-1}):
            with self.assertRaises(ValueError):
                build_mesh(np.ones((20,10),bool),**values)
        with self.assertRaises(ValueError):
            build_mesh(np.zeros((20,10),bool))

    def test_heel_and_arch_orientation(self):
        mask = extract_mask(demo_image())
        left,_ = build_mesh(mask,side='Esquerdo',heel=0)
        right,_ = build_mesh(mask,side='Direito',heel=0)
        self.assertGreater(left[left[:,2].argmax(),0],0)
        self.assertLess(right[right[:,2].argmax(),0],0)
        heel,_ = build_mesh(mask,arch=0)
        self.assertLess(heel[heel[:,2].argmax(),1],0)


if __name__ == '__main__':
    unittest.main()
