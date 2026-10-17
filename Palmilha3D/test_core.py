import collections
import tempfile
import unittest
from pathlib import Path
import numpy as np
from core import demo_image, extract_mask, build_mesh, save_stl


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


if __name__ == '__main__':
    unittest.main()
