"""Build supersampled UI glyphs; no dependence on symbol-font fallback."""
from pathlib import Path
from PIL import Image, ImageDraw
ROOT=Path(__file__).parent/'ui_assets'
ROOT.mkdir(exist_ok=True)
for theme,color in [('dark','#e5e8ed'),('light','#283548')]:
    for size in (16,20,24,28,32,40):
        for name in ('play','pause','up','down','check','blank'):
            im=Image.new('RGBA',(size*4,size*4));d=ImageDraw.Draw(im)
            def pt(x,y):return (round(x*size*4),round(y*size*4))
            if name=='play':d.polygon([pt(.3,.18),pt(.3,.82),pt(.8,.5)],fill=color)
            elif name=='pause':
                d.rounded_rectangle([pt(.25,.2),pt(.42,.8)],radius=size*.14,fill=color)
                d.rounded_rectangle([pt(.58,.2),pt(.75,.8)],radius=size*.14,fill=color)
            elif name=='check':
                d.line([pt(.18,.5),pt(.4,.72),pt(.82,.25)],fill=color,width=max(4,round(size*.4)),joint='curve')
            elif name in ('up','down'):
                y1,y2=(.62,.36) if name=='up' else (.38,.64)
                d.line([pt(.22,y1),pt(.5,y2),pt(.78,y1)],fill=color,width=max(4,round(size*.4)),joint='curve')
            im.resize((size,size),Image.Resampling.LANCZOS).save(ROOT/f'{theme}-{name}-{size}.png')
app=Image.new('RGBA',(1024,1024));d=ImageDraw.Draw(app)
d.rounded_rectangle((32,32,992,992),radius=220,fill='#273448')
for x,h in [(230,220),(350,380),(470,580),(590,380),(710,220)]:
    d.rounded_rectangle((x,512-h//2,x+70,512+h//2),radius=35,fill='#d5e6fa')
app.resize((64,64),Image.Resampling.LANCZOS).save(ROOT/'app.png')
app.save(ROOT/'app.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
