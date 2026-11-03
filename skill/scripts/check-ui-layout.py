#!/usr/bin/env python3
"""Offline embedded-UI contract checks. No camera, Vivado or board access.
Usage: python3 skill/scripts/check-ui-layout.py layout.json | --selftest
Checks declarations, not rendered glyphs, finger accuracy or board FPS.
"""
import argparse,copy,json,math,sys,unittest

def number(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def check(s):
    errors=[]
    def need(ok,msg):
        if not ok:errors.append(msg)
    size=s.get('canvas',[])
    if not (isinstance(size,list) and len(size)==2 and all(number(v) and v>0 for v in size)):
        return ['canvas must contain two positive finite dimensions']
    width,height=size
    def rect(v):return isinstance(v,list) and len(v)==4 and all(number(x) for x in v) and v[2]>0 and v[3]>0
    minimum=s.get('min_touch_px',48)
    need(number(minimum) and minimum>0,'invalid min_touch_px')
    ids=set()
    for c in s.get('controls',[]):
        name=c.get('id');need(isinstance(name,str) and name and name not in ids,'missing or duplicate control id');ids.add(name)
        v,h=c.get('visible'),c.get('hit')
        if not (rect(v) and rect(h)):errors.append(str(name)+': invalid visible/hit rectangle');continue
        for r in (v,h):need(r[0]>=0 and r[1]>=0 and r[0]+r[2]<=width and r[1]+r[3]<=height,str(name)+': outside canvas')
        need(h[0]<=v[0] and h[1]<=v[1] and h[0]+h[2]>=v[0]+v[2] and h[1]+h[3]>=v[1]+v[3],str(name)+': hit does not cover visible')
        if number(minimum):need(h[2]>=minimum and h[3]>=minimum,str(name)+': touch target too small')
    fps=s.get('fps',{})
    for k in ('window_s','refresh_s'):need(number(fps.get(k)) and fps[k]>0,'invalid FPS '+k)
    need(fps.get('label_px')==fps.get('value_px') and number(fps.get('label_px')) and fps.get('label_px',0)>0,'FPS label/value fonts differ or missing')
    preview=s.get('preview');source=s.get('source')
    need(rect(preview),'invalid preview rectangle')
    need(isinstance(source,list) and len(source)==2 and all(number(x) and x>0 for x in source),'invalid source dimensions')
    return errors

def source_point(point,preview,source):
    x,y,w,h=preview
    if not x<=point[0]<x+w or not y<=point[1]<y+h:return None
    return ((point[0]-x)*source[0]/w,(point[1]-y)*source[1]/h)

def sample():return dict(canvas=[1280,720],min_touch_px=48,source=[800,600],preview=[0,124,640,480],controls=[dict(id='back',visible=[0,0,180,72],hit=[0,0,180,72])],fps=dict(window_s=3,refresh_s=.1,label_px=52,value_px=52))
class Tests(unittest.TestCase):
    def test_good(self):self.assertEqual(check(sample()),[])
    def test_bad_contracts(self):
        for change in ('offscreen','mismatch','small','duplicate','negative_window','nan_refresh','bool_canvas','font'):
            with self.subTest(change=change):
                s=sample();c=s['controls'][0]
                if change=='offscreen':c['hit']=[-1,0,180,72]
                if change=='mismatch':c['hit']=[10,0,180,72]
                if change=='small':c['hit']=c['visible']=[0,0,20,20]
                if change=='duplicate':s['controls'].append(copy.deepcopy(c))
                if change=='negative_window':s['fps']['window_s']=-3
                if change=='nan_refresh':s['fps']['refresh_s']=float('nan')
                if change=='bool_canvas':s['canvas']=[True,720]
                if change=='font':s['fps']['value_px']=36
                self.assertTrue(check(s))
    def test_600p_coordinates(self):self.assertEqual(source_point((400,364),[0,124,640,480],[800,600]),(500,300))
    def test_480p_coordinates(self):self.assertEqual(source_point((400,364),[0,124,640,480],[640,480]),(400,240))
    def test_outside_preview(self):self.assertIsNone(source_point((650,364),[0,124,640,480],[800,600]))
if __name__=='__main__':
    if sys.argv[1:]==['--selftest']:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests));sys.exit(not result.wasSuccessful())
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('layout');a=p.parse_args()
    try:
        with open(a.layout,encoding='utf-8') as f:s=json.load(f)
        problems=check(s)
    except (OSError,ValueError,TypeError,AttributeError,KeyError) as e:print('ERROR:',e);sys.exit(2)
    print(json.dumps(dict(passed=not problems,errors=problems,scope='offline declared layout only; board and render untested'),ensure_ascii=False,indent=2));sys.exit(1 if problems else 0)
