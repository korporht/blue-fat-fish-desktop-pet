"""Verify original assets, canvas alignment, finite motion and user entry points."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,json,hashlib,unittest,random
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
APP=Path(__file__).resolve().parents[1];sys.path.insert(0,str(APP))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect,QPoint
from PySide6.QtGui import QImage
from whale_pet import Pet,Sprites,ACTIONS
from animation_policy import IDLE_RULES,BalancedChooser
from conversation_reactions import keyword_reaction
from extra_activities import ACTIVITY_STATES
app=QApplication.instance() or QApplication([])
sprites=Sprites(str(APP/'assets'))

class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.pet=Pet(sprites,selftest=True);self.pet.timer.stop();self.pet.show()
        self.pet._screen_rect=lambda:QRect(0,0,1600,900)
        self.pet.move(600,self.pet._ground_y());self.pet._auto_ds=False
        self.pet.next_attention=self.pet.next_walk=self.pet.next_behaviour=1e9
        self.pet._cursor_override=QPoint(-2000,-2000)
        self.ms=0;self.pet.last_ms=0;self.pet.clock=SimpleNamespace(elapsed=lambda:self.ms)
    def tearDown(self):
        self.pet.timer.stop();self.pet.click_timer.stop();self.pet.deleteLater();app.processEvents()
    def step(self):
        self.ms+=50;self.pet._tick()
    def test_all_197_original_frames_keep_alpha_size_hash_and_timing(self):
        meta=json.loads((APP/'assets/extra/activities.json').read_text(encoding='utf-8'))
        original={n:a for n,a in meta['animations'].items() if n!='ds_lion_dance'}
        self.assertEqual(sum(a['frames'] for a in original.values()),197)
        for name,info in original.items():
            self.assertEqual(sprites[name].fps,10)
            for i,digest in enumerate(info['frame_sha256']):
                path=APP/'assets/extra'/info['folder']/f'{i:02d}.png'
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
                image=QImage(str(path));self.assertTrue(image.hasAlphaChannel())
                self.assertEqual([image.width(),image.height()],info['canvas'])
    def test_lion_dance_frames_registered_with_source_fps(self):
        meta=json.loads((APP/'assets/extra/activities.json').read_text(encoding='utf-8'))
        info=meta['animations']['ds_lion_dance']
        self.assertEqual(info['frames'],241)
        self.assertEqual(info['fps'],24)
        self.assertEqual(info['loop'],False)
        self.assertEqual(info['canvas'],[480,270])
        self.assertEqual(sprites['ds_lion_dance'].fps,info['fps'])
        for i,digest in enumerate(info['frame_sha256']):
            path=APP/'assets/extra'/info['folder']/f'{i:02d}.png'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
            image=QImage(str(path));self.assertTrue(image.hasAlphaChannel())
            self.assertEqual([image.width(),image.height()],info['canvas'])
    def test_lion_dance_ground_line_and_alpha_survive_export(self):
        meta=json.loads((APP/'assets/extra/activities.json').read_text(encoding='utf-8'))
        info=meta['animations']['ds_lion_dance'];ox,oy=info['offset']
        self.assertEqual(tuple(info['offset']),sprites['ds_lion_dance'].offset)
        self.assertEqual(len(sprites['ds_lion_dance']),info['frames'])
        partial_seen=False
        for i in range(info['frames']):
            image=QImage(str(APP/'assets/extra'/info['folder']/f'{i:02d}.png')).convertToFormat(QImage.Format_RGBA8888)
            w,h=image.width(),image.height();b=bytes(image.constBits());bl=image.bytesPerLine()
            miny=maxy=None
            for y in range(h):
                if max(b[y*bl+3:y*bl+w*4:4]):
                    miny=y if miny is None else miny;maxy=y
                    if not partial_seen and any(0<v<255 for v in b[y*bl+3:y*bl+w*4:4]):
                        partial_seen=True
            self.assertIsNotNone(miny,f'frame {i} empty')
            cell_bottom=maxy-oy
            if i==0:
                self.assertEqual(cell_bottom,244)
            else:
                self.assertLessEqual(cell_bottom,246)  # shoe-sole squash dips 2px during the bounce
        self.assertTrue(partial_seen)
    def test_enlarged_canvas_preserves_normal_origin_feet_and_character_pixels(self):
        for scale in (.5,1,1.5,2):
            self.pet.set_scale(scale);self.pet.set_state('idle')
            self.pet.move(600,self.pet._ground_y());normal=self.pet.pos()
            idle=sprites['idle'].frames[0].toImage().convertToFormat(QImage.Format_RGBA8888)
            for state in ACTIVITY_STATES:
                self.pet.do_action(state,0);ox,oy=self.pet.anim.offset
                self.assertEqual(self.pet.x()+round(ox*self.pet.display_scale),normal.x())
                self.assertEqual(self.pet.y()+round(oy*self.pet.display_scale),normal.y())
                self.assertEqual(self.pet.y(),self.pet._ground_y())
                frame=self.pet.current_pixmap().toImage().copy(ox,oy,256,256).convertToFormat(QImage.Format_RGBA8888)
                if state=='ds_lion_dance':
                    # foreign render: cannot match idle pixels, check the standing geometry instead
                    b=bytes(frame.constBits());bl=frame.bytesPerLine();w,h=frame.width(),frame.height()
                    xs=[];ys=[]
                    for y in range(h):
                        for x in range(w):
                            if b[y*bl+x*4+3]:
                                xs.append(x);ys.append(y)
                    self.assertAlmostEqual((min(xs)+max(xs))/2,128,delta=4)
                    self.assertEqual(max(ys),244)
                    self.assertAlmostEqual(max(ys)-min(ys)+1,200,delta=6)
                else:
                    self.assertEqual(frame,idle)
                anchor=self.pet.reply_anchor_rect()
                self.assertEqual(anchor.topLeft(),normal)
                self.pet.set_state('idle');self.assertEqual(self.pet.pos(),normal)
    def test_each_activity_finishes_at_original_speed_and_copter_moves_both_ways(self):
        expected={'ds_bamboo_copter':11.9,'ds_sweep':6.8,'ds_bubble_pop':7.0,'ds_lion_dance':10.04}
        for state,seconds in expected.items():
            self.pet.set_state('idle');self.pet.move(600,self.pet._ground_y())
            self.pet.do_action(state,0);start=self.ms;positions=[]
            while self.pet.state==state and self.ms-start<20000:
                positions.append(self.pet.x());self.step()
            self.assertEqual(self.pet.state,'idle')
            self.assertAlmostEqual((self.ms-start)/1000,seconds,delta=.1)
            if state=='ds_bamboo_copter':
                self.assertLess(min(positions),positions[0]-30)
                self.assertGreater(positions[-1],min(positions)+30)
                self.assertEqual(self.pet.x(),600)
    def test_edges_interruptions_and_scale_changes_leave_pet_on_screen(self):
        for x in (0,1344):
            for state in ACTIVITY_STATES:
                self.pet.set_state('idle');self.pet.move(x,self.pet._ground_y())
                self.pet.do_action(state,0);self.pet.set_scale(1.5)
                for _ in range(25):self.step()
                self.assertGreaterEqual(self.pet.x(),0)
                self.assertLessEqual(self.pet.x()+self.pet.width(),1600)
                self.pet.do_action('petted',2)
                self.assertEqual(self.pet.anim.offset,(0,0))
                self.assertEqual(self.pet.y(),self.pet._ground_y())
                self.pet.set_scale(1)
    def test_menu_keywords_and_balanced_pool_reach_all_new_states(self):
        self.assertTrue(set(ACTIVITY_STATES)<=set(state for _,state,_ in ACTIONS))
        for text,label in [('扫地','sweep'),('用竹蜻蜓飞一圈','copter'),('吹泡泡','bubble'),('舞狮头','lion'),('来段舞狮','lion')]:
            self.assertEqual(keyword_reaction(text),label)
        chooser=BalancedChooser(IDLE_RULES,random.Random(42));counts=Counter()
        for now in range(0,7200,15):
            choice=chooser.choose(now)
            if choice:counts[choice]+=1
        self.assertTrue(all(counts[name]>10 for name in ACTIVITY_STATES))

if __name__=='__main__':unittest.main()
