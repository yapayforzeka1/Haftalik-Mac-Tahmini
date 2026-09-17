from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from config import MODEL_ORDER, MODEL_SHORT, REPORT_DIR, SEASON

BG=(4,10,24); PANEL=(8,22,45); PANEL2=(11,31,61); BORDER=(38,104,174); WHITE=(242,247,252); CYAN=(72,205,255); GOLD=(255,199,55); MUTED=(174,194,215)
POINT_COLORS={"6":(27,157,94),"5":(34,125,205),"3":(207,148,32),"2":(207,86,43),"0":(190,50,58)}


def _font(size:int,bold:bool=False):
    candidates=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    for path in candidates:
        if Path(path).exists(): return ImageFont.truetype(path,size)
    return ImageFont.load_default()


def _text(draw,xy,text,size=24,bold=False,fill=WHITE): draw.text(xy,str(text),font=_font(size,bold),fill=fill)

def _center(draw,box,text,size=22,bold=False,fill=WHITE):
    f=_font(size,bold); bb=draw.textbbox((0,0),str(text),font=f); x1,y1,x2,y2=box
    draw.text(((x1+x2-(bb[2]-bb[0]))/2,(y1+y2-(bb[3]-bb[1]))/2-2),str(text),font=f,fill=fill)

def _panel(draw,box,fill=PANEL): draw.rounded_rectangle(box,radius=18,fill=fill,outline=BORDER,width=2)

def _distribution(draw,x,y,d):
    for p in ("6","5","3","2","0"):
        draw.rounded_rectangle((x,y,x+74,y+48),radius=9,fill=POINT_COLORS[p]); _center(draw,(x,y,x+74,y+48),f"{p}P",18,True); x+=84
    x-=420; y+=55
    for p in ("6","5","3","2","0"):
        _center(draw,(x,y,x+74,y+42),str((d or {}).get(p,0)),20,True); x+=84


def render_weekly_image(snapshot:dict[str,Any])->Path:
    w,h=1500,1540; im=Image.new("RGB",(w,h),BG); d=ImageDraw.Draw(im)
    d.rectangle((0,0,w,170),fill=(7,19,48)); _text(d,(55,35),"ŞAMPİYONLAR LİGİ",42,True); _text(d,(55,92),"HAFTALIK AI PERFORMANS RAPORU",29,True,CYAN); _text(d,(1120,52),f"MATCHDAY {snapshot['matchday']}",28,True,GOLD)
    stats=snapshot['stats']; c=stats['consensus']
    cards=[("DEĞERLENDİRİLEN MAÇ",snapshot['evaluated_matches']),("ORTAK KARAR",f"{c['matches']}/{c['evaluated_matches']}"),("AI MODELİ",len(MODEL_ORDER))]
    for i,(label,val) in enumerate(cards):
        x=55+i*465; _panel(d,(x,205,x+425,330),PANEL2); _text(d,(x+25,230),val,34,True,CYAN if i!=1 else GOLD); _text(d,(x+25,280),label,16,True,MUTED)
    _text(d,(55,375),"BİREYSEL AI PERFORMANSI",27,True,GOLD)
    y=425
    for model in MODEL_ORDER:
        s=stats['models'][model]; _panel(d,(55,y,1445,y+150)); _text(d,(80,y+22),MODEL_SHORT[model],24,True); _text(d,(310,y+20),f"{s['points']} PUAN",27,True,CYAN); _text(d,(310,y+62),f"Ort. {s['avg']} / 6",17,False,MUTED); _distribution(d,565,y+20,s.get('point_distribution')); _text(d,(1130,y+24),f"{s['successful_predictions']}/{s['prediction_opportunities']}",25,True); _text(d,(1130,y+62),f"Coverage %{s['coverage_pct']}",17,False,MUTED); y+=165
    _text(d,(55,y+10),"ORTAK KARAR PERFORMANSI",27,True,GOLD); y+=60; _panel(d,(55,y,1445,y+185),PANEL2)
    _text(d,(80,y+28),f"{c['points']} PUAN",30,True,GOLD); _text(d,(80,y+75),f"Ort. {c['avg']} / 6",18,False,MUTED); _text(d,(80,y+112),f"Ortak karar: {c['matches']}/{c['evaluated_matches']}  •  %{c['coverage_pct']}",17,True)
    _distribution(d,565,y+35,c.get('point_distribution')); _text(d,(1130,y+42),f"Ortak yok: {c['no_consensus']}",17,True); _text(d,(1130,y+78),f"Skor bölünmesi: {c['score_split']}",17,False,MUTED)
    _text(d,(55,h-80),"6P Tam skor  •  5P Kazanan + gol farkı  •  3P Beraberlik  •  2P Kazanan  •  0P Yanlış",16,True,MUTED)
    REPORT_DIR.mkdir(parents=True,exist_ok=True); path=REPORT_DIR/f"matchday_{snapshot['matchday']}_weekly.png"; im.save(path,quality=95); return path


def render_season_image(season:dict[str,Any])->Path:
    w,h=1500,1500; im=Image.new("RGB",(w,h),BG); d=ImageDraw.Draw(im)
    d.rectangle((0,0,w,170),fill=(7,19,48)); _text(d,(55,35),"ŞAMPİYONLAR LİGİ",42,True); _text(d,(55,92),"SEZON GENELİ AI PERFORMANSI",29,True,CYAN); _text(d,(1190,55),SEASON,25,True,GOLD)
    weeks=season.get('finalized_matchdays',[]); total_matches=max([season['models'][m].get('prediction_opportunities',0) for m in MODEL_ORDER] or [0]); c=season['consensus']
    cards=[("TOPLAM MAÇ",total_matches),("FINAL MATCHDAY",len(weeks)),("ORTAK KARAR",f"{c['matches']}/{c['evaluated_matches']}")]
    for i,(label,val) in enumerate(cards):
        x=55+i*465; _panel(d,(x,205,x+425,330),PANEL2); _text(d,(x+25,230),val,34,True,CYAN if i<2 else GOLD); _text(d,(x+25,280),label,16,True,MUTED)
    _text(d,(55,375),"AI MODELLERİ SEZON PERFORMANSI",27,True,GOLD); y=425
    for model in MODEL_ORDER:
        s=season['models'][model]; _panel(d,(55,y,1445,y+150)); _text(d,(80,y+22),MODEL_SHORT[model],24,True); _text(d,(310,y+20),f"{s['points']} PUAN",27,True,CYAN); _text(d,(310,y+62),f"Ort. {s['avg']} / 6",17,False,MUTED); _distribution(d,565,y+20,s.get('point_distribution')); _text(d,(1130,y+24),f"{s['successful_predictions']}/{s['prediction_opportunities']}",25,True); _text(d,(1130,y+62),f"Coverage %{s['coverage_pct']}",17,False,MUTED); y+=165
    _text(d,(55,y+10),"ORTAK KARAR — SEZON GENELİ",27,True,GOLD); y+=60; _panel(d,(55,y,1445,y+185),PANEL2)
    _text(d,(80,y+28),f"{c['points']} PUAN",30,True,GOLD); _text(d,(80,y+75),f"Ort. {c['avg']} / 6",18,False,MUTED); _text(d,(80,y+112),f"Ortak karar: {c['matches']}/{c['evaluated_matches']}  •  %{c['coverage_pct']}",17,True); _distribution(d,565,y+35,c.get('point_distribution')); _text(d,(1130,y+42),f"Ortak yok: {c['no_consensus']}",17,True); _text(d,(1130,y+78),f"Tam skor: {c['exact']}",17,False,MUTED)
    _text(d,(55,h-70),"Coverage, model/API erişilebilirliğini; puan ise yalnızca geçerli tahminlerin futbol performansını gösterir.",16,True,MUTED)
    REPORT_DIR.mkdir(parents=True,exist_ok=True); path=REPORT_DIR/"season_performance.png"; im.save(path,quality=95); return path
