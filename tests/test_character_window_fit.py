"""Whole-artwork regressions for legacy crop settings and constrained desktops."""
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
from test_random_gallery import RandomGalleryTkTests
from desktop_compact import CompactDesktopApp


class CharacterWindowFitTests(unittest.TestCase):
    setUpClass = classmethod(RandomGalleryTkTests.setUpClass.__func__)
    setUp = RandomGalleryTkTests.setUp
    close = RandomGalleryTkTests.close

    def test_legacy_crop_preserves_all_edges_and_ratio(self):
        for dims in ((1024,1536),(1800,400),(600,600),(40,90)):
            with self.subTest(dims=dims):
                path = self.data / ('art-%sx%s.png' % dims)
                im = Image.new('RGBA', dims, (0,0,0,0))
                draw = ImageDraw.Draw(im)
                draw.rectangle((0,0,dims[0]-1,dims[1]-1), fill=(245,80,40,255))
                im.save(path)
                with patch.object(self.app, '_custom_image', return_value=(path,'crop',(.5,.5))):
                    for scale in (80,100,110,150,170,200):
                        self.app.widget_scale_var.set(scale)
                        limits = self.app._character_fit_limits()
                        rendered = self.app._load_character_image('worry', limits, preserve_alpha=True)
                        expected = min(limits[0]/dims[0], limits[1]/dims[1], 1)
                        self.assertEqual(rendered.size, (max(1,round(dims[0]*expected)),max(1,round(dims[1]*expected))))
                        self.assertEqual(rendered.getchannel('A').getextrema(), (255,255))

    def test_roles_and_small_work_area_keep_art_inside_client(self):
        path = self.data / 'fullbody.png'
        Image.new('RGBA',(1024,1536),(245,80,40,255)).save(path)
        self.app._show_page('timer')
        with patch.object(self.app, '_work_areas', return_value=[(0,0,640,480)]), \
             patch.object(self.app, '_custom_image', return_value=(path,'crop',(.5,.5))):
            for scale in (80,110,170,200):
                self.app.widget_scale_var.set(scale)
                for role in ('default','rest','away','worry','nag','praise'):
                    self.app.character_role = None
                    self.app._set_character(role)
                    self.app._apply_widget_appearance()
                    self.app._resize_for_page('timer')
                    self.app.root.update()
                    label = self.app.character
                    root = self.app.root
                    x = label.winfo_rootx()-root.winfo_rootx()
                    y = label.winfo_rooty()-root.winfo_rooty()
                    with self.subTest(scale=scale,role=role):
                        self.assertGreaterEqual(x,0)
                        self.assertGreaterEqual(y,0)
                        self.assertLessEqual(x+label.winfo_width(),root.winfo_width())
                        self.assertLessEqual(y+label.winfo_height(),root.winfo_height())
