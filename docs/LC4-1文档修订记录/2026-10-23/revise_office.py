#!/usr/bin/env python3
"""Apply a reviewed, exact-text Office edit plan without third-party packages.

The original package members, namespace prefixes, document styles, workbook
formulas and relationships are retained. Only named XML parts are replaced.
"""
import copy
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.dom import minidom as D
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
TARGET = ROOT / 'docs/LC4-1差距分析表格要求文件'
DATE = '2026-10-23'
STAMP = DATE + 'T08:00:00Z'
AUTHOR = '项目文档修订'
HISTORY_DESCRIPTION = '依据当前后端及 Modbus TLS 实现局部更新。'
HISTORY_DATE = '2026/10/23'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
C = 'http://schemas.openxmlformats.org/package/2006/content-types'
LEDGER = []


def next_version(value):
    value=value.strip()
    if value.isdigit():return str(int(value)+1).zfill(len(value))
    if re.fullmatch('[A-Y]',value):return chr(ord(value)+1)
    raise ValueError('Unrecognized revision version: '+value)


def elements(node, ns, name):
    return list(node.getElementsByTagNameNS(ns, name))


def children(node, ns, name):
    return [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE
            and c.namespaceURI == ns and c.localName == name]


def text(node):
    return ''.join(c.data if c.nodeType in (c.TEXT_NODE, c.CDATA_SECTION_NODE)
                   else text(c) for c in node.childNodes)


def wtext(node):
    return ''.join(text(c) for c in elements(node, W, 't'))


def actual_run_properties(paragraph):
    """Use actual text formatting, not the paragraph mark's rPr."""
    candidates=[r for r in elements(paragraph,W,'r') if wtext(r).strip()]
    if not candidates:return None
    counts=Counter()
    for r in candidates:
        props=children(r,W,'rPr')
        counts[props[0].toxml() if props else '']+=len(wtext(r))
    best=counts.most_common(1)[0][0]
    candidate=next(r for r in candidates if (children(r,W,'rPr')[0].toxml() if children(r,W,'rPr') else '')==best)
    props=children(candidate,W,'rPr')
    return props[0] if props else None


def xml(data):
    return D.parseString(data)


def encoded(doc):
    # minidom otherwise writes literal attribute newlines; the next XML reader
    # normalizes those to spaces (notably inside Office drawing metadata).
    result=doc.toxml()
    result=re.sub(r'(\s[\w:.-]+=")([^"]*)(")',
                  lambda m:m[1]+m[2].replace('\t','&#9;').replace('\n','&#10;').replace('\r','&#13;')+m[3],result)
    return result.encode('UTF-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(path, location, before, after, reason, evidence, kind='正文'):
    row = dict(id=f'LC41-{len(LEDGER)+1:04d}', file=str(path.relative_to(TARGET)),
               location=location, before=before, after=after, reason=reason,
               evidence=evidence, date=DATE, kind=kind)
    LEDGER.append(row)
    return row


def package(path, replacements, additions=None):
    """Copy untouched ZIP members byte-for-byte at the uncompressed level."""
    stream = io.BytesIO()
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(stream, 'w') as dst:
        for item in src.infolist():
            dst.writestr(item, replacements.get(item.filename, src.read(item.filename)))
        for name, value in (additions or {}).items():
            assert name not in src.namelist(), name
            dst.writestr(name, value, compress_type=zipfile.ZIP_DEFLATED)
    return stream.getvalue()


def word_update(path, edits):
    with zipfile.ZipFile(path) as z:
        doc = xml(z.read('word/document.xml'))
        settings = xml(z.read('word/settings.xml'))
    paras = elements(doc, W, 'p')  # Fixed indices from the original baseline.
    revision_id = max([int(n.getAttributeNS(W, 'id')) for tag in ('ins', 'del')
                       for n in elements(doc, W, tag) if n.getAttributeNS(W, 'id').isdigit()] + [0])

    def revision(tag):
        nonlocal revision_id
        revision_id += 1
        node = doc.createElementNS(W, 'w:' + tag)
        for key, value in [('id', str(revision_id)), ('author', AUTHOR), ('date', STAMP)]:
            node.setAttributeNS(W, 'w:' + key, value)
        return node

    def run(value, properties=None, deleted=False):
        node = doc.createElementNS(W, 'w:r')
        if properties is not None:
            node.appendChild(properties.cloneNode(True))
        content = doc.createElementNS(W, 'w:delText' if deleted else 'w:t')
        content.setAttribute('xml:space', 'preserve')
        content.appendChild(doc.createTextNode(value))
        node.appendChild(content)
        return node

    for edit in edits:
        p = paras[edit['paragraph']]
        before = wtext(p)
        assert before == edit['before'], (path, edit['paragraph'], before)
        if edit.get('kind') == '版本编号':
            texts=elements(p,W,'t')
            assert texts
            for index,node in enumerate(texts):
                for child in list(node.childNodes):node.removeChild(child)
                if index==0:node.appendChild(doc.createTextNode(edit['after']))
            record(path,'word/document.xml / P'+str(edit['paragraph']),before,edit['after'],edit['reason'],edit['evidence'],'版本编号')
            continue
        assert not elements(p, W, 'ins') and not elements(p, W, 'del'), 'existing tracked paragraph'
        assert not elements(p, W, 'drawing') and not elements(p, W, 'fldChar'), 'complex paragraph'
        ancestor = p.parentNode
        while ancestor is not None and ancestor != doc:
            if ancestor.nodeType == ancestor.ELEMENT_NODE and ancestor.namespaceURI == W and ancestor.localName == 'tr':
                for height in elements(ancestor, W, 'trHeight'):
                    if height.getAttributeNS(W, 'hRule') == 'exact':
                        height.setAttributeNS(W, 'w:hRule', 'atLeast')
                break
            ancestor = ancestor.parentNode
        props = actual_run_properties(p)
        old = revision('del')
        # Keep the original runs and their character formatting in the deletion.
        for child in list(p.childNodes):
            if child.nodeType == child.ELEMENT_NODE and child.namespaceURI == W and child.localName in ('r', 'hyperlink'):
                for original in ([child] if child.localName == 'r' else elements(child, W, 'r')):
                    original = original.cloneNode(True)
                    for t in elements(original, W, 't'):
                        dt = doc.createElementNS(W, 'w:delText')
                        dt.setAttribute('xml:space', 'preserve')
                        dt.appendChild(doc.createTextNode(text(t)))
                        t.parentNode.replaceChild(dt, t)
                    old.appendChild(original)
                p.removeChild(child)
        p.appendChild(old)
        ins = revision('ins')
        ins.appendChild(run(edit['after'], props))
        p.appendChild(ins)
        preceding = [wtext(q) for q in paras[max(0, edit['paragraph']-5):edit['paragraph']] if wtext(q).strip()]
        location = 'word/document.xml / P' + str(edit['paragraph'])
        if preceding:
            location += '（前文：' + preceding[-1][:60] + '）'
        record(path, location, before, edit['after'], edit['reason'], edit['evidence'])

    if all(e.get('kind')=='版本编号' for e in edits):
        return package(path,{'word/document.xml':encoded(doc)})
    history = next(t for t in elements(doc, W, 'tbl')
                   if '变更内容' in wtext(t) and ('版本' in wtext(t)) and len(wtext(t)) < 2500)
    rows = children(history, W, 'tr')
    prototype = next(tr for tr in reversed(rows) if len(children(tr, W, 'tc')) >= 6)
    newrow = prototype.cloneNode(True)
    existing=[wtext(children(tr,W,'tc')[0]) for tr in rows if len(children(tr,W,'tc'))>=6]
    version=str(sum(bool(re.fullmatch(r'\d+|[A-Z]',value.strip())) for value in existing))
    values = [version, HISTORY_DESCRIPTION, '', '', '', HISTORY_DATE]
    reference_rows=[r for r in rows if len(children(r,W,'tc'))==6
                    and re.fullmatch(r'\d+|[A-Z]',wtext(children(r,W,'tc')[0]).strip())]
    for ci,(cell, value) in enumerate(zip(children(newrow, W, 'tc'), values)):
        reference=None
        for candidate in reversed(reference_rows):
            reference=next((p for p in elements(children(candidate,W,'tc')[ci],W,'p') if wtext(p).strip()),None)
            if reference is not None:break
        if reference is None:
            reference=next(p for p in elements(reference_rows[-1],W,'p') if wtext(p).strip())
        oldps = children(cell, W, 'p')
        p = oldps[0].cloneNode(True) if oldps else doc.createElementNS(W, 'w:p')
        for child in list(p.childNodes):
            if not (child.nodeType == child.ELEMENT_NODE and child.namespaceURI == W and child.localName == 'pPr'):
                p.removeChild(child)
        if value:
            ins = revision('ins')
            ins.appendChild(run(value,actual_run_properties(reference)))
            p.appendChild(ins)
        for child in list(cell.childNodes):
            if not (child.nodeType == child.ELEMENT_NODE and child.namespaceURI == W and child.localName == 'tcPr'):
                cell.removeChild(child)
        cell.appendChild(p)
    trpr = children(newrow, W, 'trPr')
    if not trpr:
        trpr = [doc.createElementNS(W, 'w:trPr')]
        newrow.insertBefore(trpr[0], newrow.firstChild)
    for height in children(trpr[0], W, 'trHeight'):
        trpr[0].removeChild(height)
    trpr[0].appendChild(revision('ins'))
    blank=next((tr for tr in rows if len(children(tr,W,'tc'))>=6 and not wtext(tr).strip()),None)
    history.insertBefore(newrow,blank)
    record(path, '变更履历 / 新增版本'+version+'修订行', '', ' | '.join(values),
           '按用户示例记录递进版本、简洁变更内容和日期；编制、审核、批准留空，详细对照独立保存。', '本轮用户确认', '修订履历')
    if not elements(settings, W, 'trackRevisions'):
        settings.documentElement.appendChild(settings.createElementNS(W, 'w:trackRevisions'))
    return package(path, {'word/document.xml': encoded(doc), 'word/settings.xml': encoded(settings)})


def colnum(value):
    out = 0
    for c in value:
        out = out * 26 + ord(c) - 64
    return out


def colname(value):
    out = ''
    while value:
        value, r = divmod(value-1, 26)
        out = chr(65+r) + out
    return out


def sheet_table(headers, rows, widths=None):
    """Standalone worksheet XML used for the visible audit ledger."""
    data = [headers] + rows
    widths = widths or [18] * len(headers)
    output = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
              f'<worksheet xmlns="{S}"><dimension ref="A1:{colname(len(headers))}{len(data)}"/>',
              '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
              '<sheetFormatPr defaultRowHeight="15"/><cols>']
    for i, width in enumerate(widths, 1):
        output.append(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>')
    output.append('</cols><sheetData>')
    for r, row in enumerate(data, 1):
        maxlines = max([max(1, math.ceil(sum(2 if ord(c)>255 else 1 for c in str(v))/widths[i]))
                        for i,v in enumerate(row)] or [1])
        height = 30 if r == 1 else min(409, max(30, maxlines*15))
        output.append(f'<row r="{r}" ht="{height}" customHeight="1">')
        for c, value in enumerate(row, 1):
            value = str(value)
            assert len(value) <= 32767
            output.append(f'<c r="{colname(c)}{r}" s="1" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>')
        output.append('</row>')
    output += ['</sheetData>', f'<autoFilter ref="A1:{colname(len(headers))}{len(data)}"/>',
               '<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>', '</worksheet>']
    return ''.join(output).encode()


HEADERS = ['修改编号', '文件', '位置', '修改前', '修改后', '修改原因', '代码/资料依据', '日期', '类型']
WIDTHS = [17, 45, 40, 80, 90, 45, 65, 14, 14]


def ledger_rows(rows):
    return [[x[k] for k in ['id','file','location','before','after','reason','evidence','date','kind']] for x in rows]


def new_workbook(path, headers, rows, widths):
    styles = f'''<styleSheet xmlns="{S}"><fonts count="1"><font><sz val="11"/><name val="等线"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    content = f'''<Types xmlns="{C}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'''
    parts = {'[Content_Types].xml': content,
             '_rels/.rels':f'<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
             'xl/workbook.xml':f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="修改总台账" sheetId="1" r:id="rId1"/></sheets></workbook>',
             'xl/_rels/workbook.xml.rels':f'<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{R}/styles" Target="styles.xml"/></Relationships>',
             'xl/styles.xml':styles,
             'xl/worksheets/sheet1.xml':sheet_table(headers,rows,widths)}
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,value in parts.items(): z.writestr(name,value)


def workbook_parts(z):
    wb = xml(z.read('xl/workbook.xml'))
    rel = xml(z.read('xl/_rels/workbook.xml.rels'))
    targets = {n.getAttribute('Id'):n.getAttribute('Target') for n in elements(rel,P,'Relationship')}
    sheets = {}
    for n in elements(wb,S,'sheet'):
        target = targets[n.getAttributeNS(R,'id')]
        sheets[n.getAttribute('name')] = target.lstrip('/') if target.startswith('/') else 'xl/'+target
    return wb,rel,sheets


def strings(z):
    return [ ''.join(text(t) for t in elements(si,S,'t')) for si in elements(xml(z.read('xl/sharedStrings.xml')),S,'si')] if 'xl/sharedStrings.xml' in z.namelist() else []


def celltext(cell, shared):
    if cell is None: return ''
    if cell.getAttribute('t') == 'inlineStr': return ''.join(text(t) for t in elements(cell,S,'t'))
    values = elements(cell,S,'v')
    value = text(values[0]) if values else ''
    return shared[int(value)] if cell.getAttribute('t')=='s' and value else value


def workbook_update(path, edits):
    replacements = {}
    start = len(LEDGER)
    with zipfile.ZipFile(path) as z:
        wb,rel,sheets = workbook_parts(z)
        # Some existing workbooks use only an x: prefix, with r declared on
        # each sheet. Bind the names used by newly created nodes explicitly.
        wb.documentElement.setAttribute('xmlns', S)
        wb.documentElement.setAttribute('xmlns:r', R)
        rel.documentElement.setAttribute('xmlns', P)
        shared = strings(z)
        docs = {name:xml(z.read(part)) for name,part in sheets.items()}
        for document in docs.values():
            document.documentElement.setAttribute('xmlns', S)
        styles = xml(z.read('xl/styles.xml'))
        styles.documentElement.setAttribute('xmlns', S)
        xfs = elements(styles,S,'cellXfs')[0]
        stylemap = {}

        def wrapstyle(old):
            if old in stylemap: return stylemap[old]
            node = children(xfs,S,'xf')[int(old)].cloneNode(True)
            align = children(node,S,'alignment')
            if not align:
                align = [styles.createElementNS(S,'alignment')]; node.appendChild(align[0])
            align[0].setAttribute('wrapText','1'); align[0].setAttribute('vertical','top')
            node.setAttribute('applyAlignment','1')
            new = str(len(children(xfs,S,'xf')))
            xfs.appendChild(node); xfs.setAttribute('count',str(len(children(xfs,S,'xf'))))
            stylemap[old] = new
            return new

        def setcell(name, address, value):
            doc = docs[name]
            cells = {c.getAttribute('r'):c for c in elements(doc,S,'c')}
            # Never write into the covered part of a merged area.
            for merge in elements(doc,S,'mergeCell'):
                first,last = merge.getAttribute('ref').split(':')
                a,b = re.fullmatch(r'([A-Z]+)(\d+)',first).groups()
                c,d = re.fullmatch(r'([A-Z]+)(\d+)',last).groups()
                e,f = re.fullmatch(r'([A-Z]+)(\d+)',address).groups()
                if colnum(a)<=colnum(e)<=colnum(c) and int(b)<=int(f)<=int(d):
                    assert address==first, ('merged cell', name,address,first)
            cell = cells.get(address)
            if cell is None:
                rn = int(re.search(r'\d+',address).group())
                sd = elements(doc,S,'sheetData')[0]
                rows = children(sd,S,'row')
                row = next((r for r in rows if int(r.getAttribute('r'))==rn),None)
                if row is None:
                    row=doc.createElementNS(S,'row'); row.setAttribute('r',str(rn))
                    nxt=next((r for r in rows if int(r.getAttribute('r'))>rn),None)
                    sd.insertBefore(row,nxt)
                cell=doc.createElementNS(S,'c');cell.setAttribute('r',address)
                cn=colnum(re.match('[A-Z]+',address).group())
                nxt=next((c for c in children(row,S,'c') if colnum(re.match('[A-Z]+',c.getAttribute('r')).group())>cn),None)
                row.insertBefore(cell,nxt)
            assert not elements(cell,S,'f'), ('formula target',name,address)
            old_style=cell.getAttribute('s') or '0'
            cell.setAttribute('s',wrapstyle(old_style));cell.setAttribute('t','inlineStr')
            for child in list(cell.childNodes): cell.removeChild(child)
            node=doc.createElementNS(S,'is');t=doc.createElementNS(S,'t');t.setAttribute('xml:space','preserve')
            t.appendChild(doc.createTextNode(value));node.appendChild(t);cell.appendChild(node)
            # Increase only touched rows; keep unrelated layout and print settings.
            row=cell.parentNode
            column=colnum(re.match('[A-Z]+',address).group())
            widths={}
            for co in elements(doc,S,'col'):
                for i in range(int(co.getAttribute('min')),int(co.getAttribute('max'))+1):
                    widths[i]=float(co.getAttribute('width') or 9)
            width=widths.get(column,9)
            for merge in elements(doc,S,'mergeCell'):
                if merge.getAttribute('ref').split(':')[0]==address:
                    end=colnum(re.match('[A-Z]+',merge.getAttribute('ref').split(':')[1]).group())
                    width=sum(widths.get(i,9) for i in range(column,end+1))
            lines=sum(max(1,math.ceil(sum(2 if ord(c)>255 else 1 for c in line)/max(1,width-2))) for line in value.split('\n'))
            height=min(409,max(float(row.getAttribute('ht') or 15),lines*15+6))
            row.setAttribute('ht',str(height));row.setAttribute('customHeight','1')

        for edit in edits:
            name=edit['sheet'];address=edit['cell']
            cell=next((c for c in elements(docs[name],S,'c') if c.getAttribute('r')==address),None)
            before=celltext(cell,shared)
            assert before==edit['before'],(path,name,address,before)
            setcell(name,address,edit['after'])
            record(path,name+'!'+address,before,edit['after'],edit['reason'],edit['evidence'])

        name=next(n for n in sheets if '修订记录' in n)
        history=docs[name]
        populated=[int(re.search(r'\d+',c.getAttribute('r')).group()) for c in elements(history,S,'c') if celltext(c,shared)]
        nr=max(populated)+1
        versions=[celltext(c,shared) for c in elements(history,S,'c')
                  if re.fullmatch(r'A\d+',c.getAttribute('r')) and re.fullmatch(r'\d+|[A-Z]',celltext(c,shared).strip())]
        version=versions[-1].strip()  # Excel retains its original version.
        values=[version,HISTORY_DESCRIPTION,'','','',HISTORY_DATE]
        for i,value in enumerate(values,1):
            if value: setcell(name,f'{colname(i)}{nr}',value)
        record(path,name+f'!A{nr}:F{nr}','',' | '.join(values),
               'Excel版本保持原值，保留简洁变更内容和日期，人员栏留空；详细修改记录独立保存。','本轮用户确认','修订履历')
        # Recompute dimensions only if added history cells extend the used range.
        for sn,doc in docs.items():
            dim=elements(doc,S,'dimension')
            if dim:
                cells=elements(doc,S,'c')
                maxc=max(colnum(re.match('[A-Z]+',c.getAttribute('r')).group()) for c in cells)
                maxr=max(int(re.search(r'\d+',c.getAttribute('r')).group()) for c in cells)
                oldref=dim[0].getAttribute('ref').split(':')[-1]
                maxc=max(maxc,colnum(re.match('[A-Z]+',oldref).group()))
                maxr=max(maxr,int(re.search(r'\d+',oldref).group()))
                dim[0].setAttribute('ref',f'A1:{colname(maxc)}{maxr}')
            replacements[sheets[sn]]=encoded(doc) if sn in {e['sheet'] for e in edits}|{name} else z.read(sheets[sn])
        replacements['xl/styles.xml']=encoded(styles)
    return package(path,replacements)


def main():
    plan=json.loads((OUT/'edit_plan.json').read_text())
    manifest=[]
    for item in plan['files']:
        path=TARGET/item['file']
        payload=path.read_bytes()
        assert sha(payload)==item['sha256'],('baseline changed',path)
        manifest.append({'file':item['file'],'sha256_before':sha(payload),'bytes_before':len(payload)})
    if (OUT/'原文件备份.zip').exists():
        with zipfile.ZipFile(OUT/'原文件备份.zip') as backup:
            for item in plan['files']:
                assert sha(backup.read(item['file'])) == item['sha256'], 'Backup baseline mismatch'
    else:
        with zipfile.ZipFile(OUT/'原文件备份.zip','w',compression=zipfile.ZIP_DEFLATED) as backup:
            for item in plan['files']: backup.write(TARGET/item['file'],item['file'])
    # Build every result before replacing any source file.
    ready={}
    for item in plan['files']:
        if not item['edits']:continue
        path=TARGET/item['file']
        ready[path]=word_update(path,item['edits']) if path.suffix=='.docx' else workbook_update(path,item['edits'])
    for path,payload in ready.items():
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            assert z.testzip() is None
            for part in z.namelist():
                if part.endswith('.xml') or part.endswith('.rels'):xml(z.read(part))
    for path,payload in ready.items():path.write_bytes(payload)
    for item in manifest:
        path=TARGET/item['file'];payload=path.read_bytes()
        item.update(sha256_after=sha(payload),bytes_after=len(payload),modified=path in ready)
    (OUT/'原件与修订件校验清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    (OUT/'修改总台账.json').write_text(json.dumps(LEDGER,ensure_ascii=False,indent=2))
    new_workbook(OUT/'修改总台账.xlsx',HEADERS,ledger_rows(LEDGER),WIDTHS)
    lines=['# 逐项修改总台账','',f'修订日期：{DATE}。原件见原文件备份.zip。正文位置 P 编号以原文件 word/document.xml 的全部段落从 0 计数，包含表格段落。','']
    for item in LEDGER:
        lines += [f"## {item['id']} · {item['file']}",'',f"位置：{item['location']}",f"类型：{item['kind']}",'','修改前：','',item['before'] or '（空白/新增）','','修改后：','',item['after'],'',f"原因：{item['reason']}",f"依据：{item['evidence']}",'']
    (OUT/'修改总台账.md').write_text('\n'.join(lines))
    print(json.dumps({'modified_files':len(ready),'records':len(LEDGER),'by_kind':dict(Counter(x['kind'] for x in LEDGER))},ensure_ascii=False))


if __name__=='__main__':main()
