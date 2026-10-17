"""Integração real Qt/OpenGL. Executar com um desktop disponível."""
import os
import tempfile
import time
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6 import QtWidgets as W, QtGui as G
from PySide6.QtTest import QTest
from app import App, STYLE


class InterfaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = W.QApplication.instance() or W.QApplication([])
        cls.application.setStyle('Fusion')
        cls.application.setStyleSheet(STYLE)

    def wait_ready(self,window):
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            self.application.processEvents()
            if not window.busy and not window.timer.isActive(): return
            QTest.qWait(20)
        self.fail('A geração não terminou em 20 segundos.')

    def test_render_updates_manual_recovery_and_export(self):
        window = App()
        window.show()
        QTest.qWait(150)
        self.wait_ready(window)
        try:
            self.assertIsNotNone(window.mesh)
            self.assertTrue(window.export_button.isEnabled())
            self.assertTrue(window.viewer.isValid(),'Contexto OpenGL indisponível')
            frame = window.viewer.grabFramebuffer()
            self.assertFalse(frame.isNull())
            self.assertGreater(window.surface_shader.prog,0,'Falha ao compilar o material OpenGL')
            if os.environ.get('PALMILHA_SCREENSHOT'):
                window.grab().save(os.environ['PALMILHA_SCREENSHOT'])
            # Simulate a burst of edits while a generation is running.
            window.values['length'].setValue(280)
            window.generate()
            window.values['length'].setValue(310)
            window.values['length'].setValue(300)
            self.assertFalse(window.export_button.isEnabled())
            self.wait_ready(window)
            self.assertAlmostEqual(np.ptp(window.mesh[0][:,1]),300)
            with tempfile.TemporaryDirectory() as tmp:
                white = Path(tmp)/'blank.png'
                Image.new('RGB',(200,400),'white').save(white)
                window.load(str(white))
                self.wait_ready(window)
                self.assertIsNone(window.mesh)
                self.assertIsInstance(window.source,Image.Image)
                window.start_manual()
                window.preview.points = [(.2,.1),(.8,.1),(.75,.9),(.3,.9)]
                window.finish_manual()
                self.wait_ready(window)
                self.assertIsNotNone(window.mesh)
                self.assertTrue(window.export_button.isEnabled())
                window.flip()
                self.wait_ready(window)
                target = str(Path(tmp)/'output.stl')
                old = W.QFileDialog.getSaveFileName
                W.QFileDialog.getSaveFileName = lambda *a,**k:(target,'STL (*.stl)')
                try: window.export()
                finally: W.QFileDialog.getSaveFileName = old
                self.assertGreater(Path(target).stat().st_size,84)
                window.load(str(Path(tmp)/'missing.png'))
                self.wait_ready(window)
                self.assertIsNone(window.mesh)
                self.assertFalse(window.export_button.isEnabled())
        finally:
            window.close()


if __name__ == '__main__': unittest.main()
