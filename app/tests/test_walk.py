"""Bound walking through the real scheduler, including delayed GUI updates."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys,json,tempfile,unittest
APP=Path(__file__).resolve().parents[1];sys.path.insert(0,str(APP))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint,QRect,QPointF,Qt
from whale_pet import Pet,Sprites
from animation_policy import WALK_GAP
from pet_support import Preferences
app=QApplication.instance() or QApplication([])
sprites=Sprites(str(APP/'assets'))

class FakeMouse:
    """Only the four accessors the pet's handlers use."""
    def __init__(self,gx,gy,button=Qt.LeftButton,buttons=Qt.LeftButton):
        self._g=QPoint(gx,gy);self._b=button;self._bs=buttons
    def globalPosition(self): return SimpleNamespace(toPoint=lambda: self._g)
    def position(self): return QPointF(self._g.x(),self._g.y())
    def button(self): return self._b
    def buttons(self): return self._bs

class WalkTests(unittest.TestCase):
    def setUp(self):
        self.pet=Pet(sprites,selftest=True);self.pet.timer.stop();self.pet.show()
        self.ms=0;self.pet.last_ms=0;self.pet.clock=SimpleNamespace(elapsed=lambda:self.ms)
        self.pet._screen_rect=lambda:QRect(0,0,500,800)
        self.pet._cursor_override=QPoint(-2000,-2000);self.pet._auto_ds=False
        self.pet.next_attention=self.pet.next_behaviour=1e9
    def tearDown(self):
        self.pet.deleteLater();app.processEvents()
    def step(self,ms=50):
        self.ms+=ms;self.pet._tick()
    def start(self):
        with patch('whale_pet.random.uniform',return_value=2.5),patch('whale_pet.random.random',return_value=1):
            self.pet.do_action('walk',0)
        self.assertEqual(self.pet.state,'walk')
    def test_delayed_update_cannot_leave_walk_running_after_its_deadline(self):
        self.start();self.step(8000)
        self.assertEqual(self.pet.state,'trip')
        self.assertGreaterEqual(self.pet.next_walk,WALK_GAP[0])
        for _ in range(100):
            if self.pet.state=='idle':break
            self.step()
        self.assertEqual(self.pet.state,'idle')
    def test_walk_stops_after_short_trip_even_when_bouncing_at_screen_edge(self):
        self.pet.move(240,550);self.start()
        for _ in range(72):
            if self.pet.state=='trip':break
            self.step()
        self.assertEqual(self.pet.state,'trip')
        for _ in range(100):
            if self.pet.state=='idle':break
            self.step()
        self.assertEqual(self.pet.state,'idle')
        self.assertGreaterEqual(self.pet.next_walk,WALK_GAP[0]-1)
        self.assertEqual(sprites['walk_right'].fps,8)
    def test_menu_pause_is_excluded_from_walk_duration_and_toggle_can_stop_it(self):
        self.start();self.pet.menu_open=True;self.step(10000)
        self.assertEqual(self.pet.state,'walk');self.assertEqual(self.pet.state_t,0)
        self.pet.menu_open=False;self.step()
        self.assertEqual(self.pet.state,'walk')
        self.pet.set_walking(False);self.assertEqual(self.pet.state,'idle')
    def test_open_menu_keeps_animation_playing_but_no_automatic_behaviour(self):
        self.pet.set_state('idle')
        self.pet.next_behaviour=self.pet.next_walk=self.pet.next_beg=-1.0   # everything overdue
        self.pet.menu_open=True
        t0=self.pet.t
        for _ in range(400):self.step()                                   # 20 s with the menu up
        self.assertEqual(self.pet.state,'idle')                           # nothing fired
        self.assertGreater(self.pet.t,t0)                                 # ...but she kept breathing
        self.pet.menu_open=False
        self.pet.next_walk=-1.0;self.pet.next_behaviour=1e9
        for _ in range(40):
            if self.pet.state=='walk':break
            self.step()
        self.assertEqual(self.pet.state,'walk')                           # scheduling resumes after closing

class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.pet=Pet(sprites,selftest=True);self.pet.timer.stop();self.pet.show()
        self.ms=0;self.pet.last_ms=0;self.pet.clock=SimpleNamespace(elapsed=lambda:self.ms)
        self.pet._screen_rect=lambda:QRect(0,0,500,800)
        self.pet._cursor_override=QPoint(-2000,-2000);self.pet._auto_ds=False
        self.pet.next_attention=self.pet.next_behaviour=1e9
        self.pet.move(200,self.pet._ground_y())
    def tearDown(self):
        self.pet.deleteLater();app.processEvents()
    def step(self,ms=50):
        self.ms+=ms;self.pet._tick()
    def drop_above_ground(self):
        ground=self.pet._ground_y()
        self.pet.mousePressEvent(FakeMouse(210,ground+40))
        self.pet.mouseMoveEvent(FakeMouse(210,300))          # cursor climbs; she dangles
        self.assertEqual(self.pet.state,'dangle')
        self.pet.mouseReleaseEvent(FakeMouse(210,300,button=Qt.LeftButton,buttons=Qt.NoButton))
        self.assertLess(self.pet.y(),ground-50)
    def test_drop_above_ground_stays_put_and_suppresses_walking(self):
        self.drop_above_ground()
        self.assertTrue(self.pet.floating);self.assertEqual(self.pet.state,'idle')
        y=self.pet.y()
        self.pet.next_walk=-1.0                               # overdue walk must not fire
        for _ in range(400):self.step()                       # 20 s of idle scheduler
        self.assertNotIn(self.pet.state,('walk','trip','fall'))
        self.assertEqual(self.pet.y(),y)
        self.assertTrue(self.pet.floating)
    def test_drop_to_ground_falls_lands_and_clears_floating(self):
        self.drop_above_ground()
        self.pet.drop_to_ground()
        self.assertFalse(self.pet.floating);self.assertEqual(self.pet.state,'fall')
        for _ in range(200):
            if self.pet.state!='fall':break
            self.step()
        self.assertEqual(self.pet.state,'land')
        for _ in range(100):
            if self.pet.state=='idle':break
            self.step()
        self.assertEqual(self.pet.y(),self.pet._ground_y())
        self.assertFalse(self.pet.floating)
    def test_floating_spot_round_trips_through_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,'settings.json')
            with open(path,'w',encoding='utf-8') as f:
                json.dump({'x':123,'y':321,'floating':True,'scale':1.0},f)
            data=Preferences(path).load()
        self.assertTrue(data.get('floating'));self.assertEqual(data.get('y'),321)
        self.pet.restore_preferences(data)
        self.assertTrue(self.pet.floating);self.assertEqual(self.pet.y(),321)
        self.pet.restore_preferences({'x':123,'floating':False})
        self.assertFalse(self.pet.floating);self.assertEqual(self.pet.y(),self.pet._ground_y())
    def test_floating_spot_survives_full_play_of_auto_activities(self):
        self.drop_above_ground()
        y=self.pet.y()
        for state in ('ds_bamboo_copter','ds_sweep','ds_bubble_pop','ds_lion_dance','dance'):
            self.pet.do_action(state,0)
            for _ in range(30):self.step()          # let root-motion frames run mid-clip
            self.assertTrue(self.pet.floating,f'{state} cleared floating')
            oy=self.pet.anim.offset[1]              # window y shifts for big canvases; the anchor must not
            self.assertEqual(self.pet.y()+round(oy*self.pet.display_scale),y,f'{state} moved her anchor')
        self.pet.do_action('wave',0.3)              # a full clip must land her back on the exact spot
        for _ in range(200):
            if self.pet.state=='idle':break
            self.step()
        self.assertEqual(self.pet.state,'idle')
        self.assertTrue(self.pet.floating)
        self.assertEqual(self.pet.y(),y)
    def test_movement_actions_ground_a_floating_pet(self):
        self.drop_above_ground()
        self.pet.do_action('walk',0)
        self.assertFalse(self.pet.floating)
        self.assertEqual(self.pet.state,'walk')
        self.step()
        self.assertEqual(self.pet.y(),self.pet._ground_y())
        for _ in range(10):self.step()
        self.assertEqual(self.pet.y(),self.pet._ground_y())

if __name__=='__main__':unittest.main()
