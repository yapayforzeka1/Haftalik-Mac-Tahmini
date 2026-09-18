"""Compact white table images for the five approved prediction formats."""
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from messages import prediction_message, prediction_tables

REPORT_DIR = Path('reports')
WIDTH = 1600
INK = '#17212b'
MUTED = '#526170'
ICONS = {'⚽', '🕒', '📋', '🏆', '🎯', '🤖', '⚠️', '✅'}


def _font(size, bold=False):
    for path in (
        'C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _kickoff(record):
    try:
        return datetime.fromisoformat(record.get('match_utc', '').replace('Z', '+00:00'))
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)


def kickoff_key(record):
    return _kickoff(record).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M')


def build_match_group_message(records, test_mode=False):
    return ('🧪 TEST\n' if test_mode else '') + '\n\n'.join(prediction_message(r) for r in sorted(records, key=_kickoff))


def _split_icon(text):
    parts = str(text).split(' ', 1)
    return (parts[0], parts[1]) if len(parts) == 2 and parts[0] in ICONS else ('', str(text))


def _icon(draw, x, y, token):
    """Portable pictograms: no external emoji downloads or missing Linux glyphs."""
    color = '#1d7750' if token == '✅' else '#ac7312' if token in {'⚠️', '🏆'} else MUTED
    if token == '✅':
        draw.rounded_rectangle((x, y, x+24, y+24), radius=4, fill=color)
        draw.line([(x+5,y+12),(x+10,y+18),(x+20,y+6)], fill='white', width=3)
    elif token == '⚠️':
        draw.polygon([(x+12,y),(x+25,y+24),(x,y+24)], fill=color)
        draw.line((x+12,y+7,x+12,y+15), fill='white', width=3)
        draw.ellipse((x+11,y+19,x+13,y+21), fill='white')
    elif token in {'🕒', '🎯', '⚽'}:
        draw.ellipse((x,y,x+25,y+25), outline=color, width=2)
        if token == '🕒':
            draw.line([(x+12,y+4),(x+12,y+13),(x+19,y+16)], fill=color, width=2)
        elif token == '🎯':
            draw.ellipse((x+5,y+5,x+20,y+20), outline=color, width=2)
            draw.ellipse((x+10,y+10,x+15,y+15), fill=color)
        else:
            draw.polygon([(x+12,y+7),(x+18,y+11),(x+16,y+18),(x+8,y+18),(x+6,y+11)], fill=color)
    elif token == '🤖':
        draw.rounded_rectangle((x,y+5,x+26,y+24),radius=4,outline=color,width=2)
        draw.line((x+13,y,x+13,y+5),fill=color,width=2)
        for eye in (7,18):
            draw.ellipse((x+eye-2,y+11,x+eye+2,y+15),fill=color)
        draw.line((x+8,y+20,x+18,y+20),fill=color,width=2)
    elif token == '🏆':
        draw.arc((x-2,y,x+27,y+17),0,180,fill=color,width=3)
        draw.polygon([(x+5,y),(x+20,y),(x+18,y+13),(x+12,y+18),(x+7,y+13)],fill=color)
        draw.line((x+12,y+17,x+12,y+24),fill=color,width=3)
        draw.line((x+6,y+25,x+19,y+25),fill=color,width=3)
    else:
        draw.rounded_rectangle((x+3,y+2,x+23,y+26),radius=2,outline=color,width=2)
        draw.rectangle((x+8,y,x+18,y+5),fill=color)
        for offset in (11,16,21):
            draw.line((x+7,y+offset,x+19,y+offset),fill=color,width=1)


def _wrap(draw, text, font, width):
    lines = []
    line = ''
    for word in text.split():
        candidate = (line + ' ' + word).strip()
        if line and draw.textlength(candidate, font=font) > width:
            lines.append(line)
            line = ''
        # Also break a long unspaced model/team name without clipping.
        for char in ((' ' if line else '') + word):
            if line and draw.textlength(line + char, font=font) > width:
                lines.append(line)
                line = ''
            line += char
    return lines + ([line] if line else []) or ['']


def _table_layout(draw, headers, rows, weights):
    available = WIDTH - 80
    widths = [int(available*w/sum(weights)) for w in weights]
    widths[-1] += available - sum(widths)
    output = []
    for index, row in enumerate([headers] + rows):
        font = _font(24 if index == 0 else 28, index == 0)
        cells = []
        for text, width in zip(row, widths):
            icon, text = _split_icon(text)
            cells.append((icon, _wrap(draw,text,font,width-32-(36 if icon else 0))))
        height = max(66, max(len(lines) for _,lines in cells)*36+30)
        output.append((height,font,cells))
    return widths, output


def _draw_table(draw, y, layout):
    widths, rows = layout
    for index, (height,font,cells) in enumerate(rows):
        if index == 0:
            draw.rectangle((40,y,WIDTH-40,y+height),fill='#f2f5f8')
        x = 40
        for width,(icon,lines) in zip(widths,cells):
            tx, ty = x+16, y+(height-len(lines)*36)/2
            if icon:
                _icon(draw,tx,ty+3,icon)
                tx += 36
            for line in lines:
                draw.text((tx,ty),line,font=font,fill=INK)
                ty += 36
            x += width
        y += height
        draw.line((40,y,WIDTH-40,y),fill='#dce2e8',width=1)
    return y


def _render_record(record, test_mode):
    table = record.get('prediction_table') or prediction_tables(record)
    probe = ImageDraw.Draw(Image.new('RGB',(WIDTH,1)))
    summary_weights = {4:[4,1.8,2,3],5:[3.5,1.7,2,2.6,1.8],6:[3.1,1.6,1.9,2.5,1.7,2.7]}
    summary = _table_layout(probe,table['summary_headers'],[table['summary']],summary_weights[len(table['summary'])])
    detail = None
    if table['headers']:
        weights = [6,2,1] if table['mode']=='OUTCOME_COMMON_SCORE_SPLIT' else ([2,7,1.5,1] if len(table['headers'])==4 else [2,7,1.5])
        detail = _table_layout(probe,table['headers'],table['rows'],weights)
    top = 76 if test_mode else 32
    height = top + sum(row[0] for row in summary[1]) + 32
    if detail:
        height += 32 + sum(row[0] for row in detail[1])
    note = _wrap(probe,_split_icon(table['note'])[1],_font(25),WIDTH-140) if table['note'] else []
    if note:
        height += 32 + 34*len(note)
    canvas = Image.new('RGB',(WIDTH,height),'white')
    draw = ImageDraw.Draw(canvas)
    if test_mode:
        draw.text((56,22),'TEST',font=_font(26,True),fill='#ac7312')
    y = _draw_table(draw,top,summary)
    if detail:
        y = _draw_table(draw,y+32,detail)
    if note:
        y += 30
        _icon(draw,56,y+3,'⚠️')
        for line in note:
            draw.text((94,y),line,font=_font(25),fill=MUTED)
            y += 34
    return canvas


def render_match_group_image(records, test_mode=False):
    if not records:
        raise ValueError('Görsel için en az bir maç gerekir.')
    records = sorted(records,key=_kickoff)
    images = [_render_record(r,test_mode) for r in records]
    canvas = Image.new('RGB',(WIDTH,sum(im.height for im in images)+24*(len(images)-1)),'#e8edf1')
    y = 0
    for im in images:
        canvas.paste(im,(0,y))
        y += im.height+24
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    stamp = kickoff_key(records[0]).replace(':','').replace('-','')
    # Distinguish simultaneous matches without embedding arbitrary provider text in paths.
    import hashlib
    key = hashlib.sha256('|'.join(str(r.get('match_id',r.get('home_team',''))) for r in records).encode()).hexdigest()[:10]
    path = REPORT_DIR / f'match_prediction_{stamp}_{key}.png'
    canvas.save(path,optimize=True)
    return path
