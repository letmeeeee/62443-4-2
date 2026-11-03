#!/usr/bin/env python3
"""Restore table run formatting using corresponding pre-edit DOCX cells."""
from pathlib import Path
import collections
import io
import json
import sys
import zipfile

HERE=Path(__file__).resolve().parent
PREVIOUS=HERE.parent/'2026-10-23'
sys.path.insert(0,str(PREVIOUS))
import revise_office as o


def ancestor(node,name):
    node=node.parentNode
    while node is not None:
        if node.nodeType==node.ELEMENT_NODE and node.namespaceURI==o.W and node.localName==name:return node
        node=node.parentNode
    return None


def owntext(run,p):
    return ''.join(o.text(t) for t in o.elements(run,o.W,'t') if ancestor(t,'p') is p)


def runs(p):
    return [r for r in o.elements(p,o.W,'r') if ancestor(r,'p') is p and ancestor(r,'del') is None and owntext(r,p).strip()]


def properties(run):
    return o.children(run,o.W,'rPr')


def dominant(p):
    candidates=runs(p)
    if not candidates:return None
    weights=collections.Counter()
    for r in candidates:
        weights[properties(r)[0].toxml() if properties(r) else '']+=len(owntext(r,p))
    best=weights.most_common(1)[0][0]
    return next(r for r in candidates if (properties(r)[0].toxml() if properties(r) else '')==best)


def setproperties(run,ref):
    old=properties(run);source=properties(ref)
    before=old[0].toxml() if old else ''
    after=source[0].toxml() if source else ''
    if before==after:return None
    for node in old:run.removeChild(node)
    if source:run.insertBefore(source[0].cloneNode(True),run.firstChild)
    return before,after


def historyrows(doc):
    result=[]
    for t in o.elements(doc,o.W,'tbl'):
        if '变更内容' not in o.wtext(t) or '版本' not in o.wtext(t):continue
        for row in o.children(t,o.W,'tr'):
            cells=o.children(row,o.W,'tc')
            if len(cells)==6 and o.wtext(cells[1])==o.HISTORY_DESCRIPTION and o.wtext(cells[5])==o.HISTORY_DATE:
                result.append(row)
    return result


def runformat(doc,baseline,file,part):
    entries=[];newrows=historyrows(doc)
    original_tables=o.elements(baseline,o.W,'tbl');tables=o.elements(doc,o.W,'tbl')
    assert len(tables)==len(original_tables)
    oldps=o.elements(baseline,o.W,'p')
    newps=[p for p in o.elements(doc,o.W,'p') if not any(row is ancestor(p,'tr') for row in newrows)]
    assert len(oldps)==len(newps),(file,part,len(oldps),len(newps))

    def apply(run,reference,location,reason):
        change=setproperties(run,reference)
        if change:
            p=ancestor(run,'p')
            entries.append(dict(file=file,location=part+' / '+location,text=owntext(run,p),
                                before=change[0] or '（继承样式）',after=change[1] or '（继承原样式）',
                                reason=reason,evidence='2026-10-23原文件备份.zip中相应表格/单元格的原始文字格式',date='2026-10-26',kind='表格字体格式'))

    for index,(original,current) in enumerate(zip(oldps,newps)):
        if ancestor(current,'tbl') is None:continue
        oldruns=runs(original);newruns=runs(current)
        if not oldruns or not newruns:continue
        original_texts=[owntext(r,original) for r in oldruns]
        current_texts=[owntext(r,current) for r in newruns]
        if original_texts==current_texts:
            for n,(a,b) in enumerate(zip(oldruns,newruns)):
                apply(b,a,f'P{index}/R{n}','原文未改的文字恢复其对应原始格式，保留原有表头、强调和中西文字体区别。')
        else:
            reference=dominant(original)
            for n,r in enumerate(newruns):
                apply(r,reference,f'P{index}/R{n}','修改文字沿用该原段落实际文字的主格式，避免误用段落标记或默认字体。')

    for row in newrows:
        table=ancestor(row,'tbl');ti=tables.index(table);original_table=original_tables[ti]
        bodyrows=[r for r in o.children(original_table,o.W,'tr') if len(o.children(r,o.W,'tc'))==6]
        bodyrows=[r for r in bodyrows if o.wtext(o.children(r,o.W,'tc')[0]).strip() not in ('版本','')]
        assert bodyrows,(file,'history reference')
        for ci,cell in enumerate(o.children(row,o.W,'tc')):
            reference=None
            for candidate in reversed(bodyrows):
                refs=o.elements(o.children(candidate,o.W,'tc')[ci],o.W,'p')
                reference=next((dominant(p) for p in refs if dominant(p) is not None),None)
                if reference is not None:break
            if reference is None:
                reference=next(dominant(p) for p in o.elements(bodyrows[-1],o.W,'p') if dominant(p) is not None)
            for p in o.elements(cell,o.W,'p'):
                for n,r in enumerate(runs(p)):
                    apply(r,reference,f'表格{ti+1}/新增履历行/列{ci+1}/R{n}','新增变更履历行沿用原履历记录同列的文字格式；空列参照原履历正文格式。')
    return entries,len(tables)


def body_without_format(data):
    doc=o.xml(data)
    for pr in list(o.elements(doc,o.W,'rPr')):
        if pr.parentNode is not None:pr.parentNode.removeChild(pr)
    return o.encoded(doc)


def main():
    plan=json.loads((PREVIOUS/'edit_plan.json').read_text())
    ready={};entries=[];checked=[];beforehash={}
    with zipfile.ZipFile(PREVIOUS/'原文件备份.zip') as backup:
        for item in plan['files']:
            if not item['file'].endswith('.docx'):continue
            path=o.TARGET/item['file'];beforehash[item['file']]=o.sha(path.read_bytes())
            replacements={};tablecount=0
            with zipfile.ZipFile(path) as current,zipfile.ZipFile(io.BytesIO(backup.read(item['file']))) as original:
                for part in current.namelist():
                    if not part.startswith('word/') or not part.endswith('.xml') or part not in original.namelist():continue
                    baseline=o.xml(original.read(part));doc=o.xml(current.read(part))
                    if not o.elements(doc,o.W,'tbl'):continue
                    changes,count=runformat(doc,baseline,item['file'],part)
                    tablecount+=count
                    if changes:
                        revised=o.encoded(doc)
                        assert body_without_format(revised)==body_without_format(current.read(part)), 'Non-format change'
                        assert not runformat(doc,baseline,item['file'],part)[0], 'Normalization is not stable'
                        replacements[part]=revised;entries.extend(changes)
                if replacements:
                    payload=o.package(path,replacements)
                    with zipfile.ZipFile(io.BytesIO(payload)) as final:
                        assert final.testzip() is None
                        for part in current.namelist():
                            if part not in replacements:assert current.read(part)==final.read(part)
                    ready[path]=payload
            checked.append(dict(file=item['file'],tables_checked=tablecount,changed=bool(replacements)))
    for i,row in enumerate(entries,1):row['id']=f'LC41-TABLE-FONT-{i:03d}'
    backupfile=HERE/'DOCX表格字体调整前备份.zip'
    assert not backupfile.exists()
    with zipfile.ZipFile(backupfile,'w',compression=zipfile.ZIP_DEFLATED) as backup:
        for item in checked:backup.write(o.TARGET/item['file'],item['file'])
    for path,payload in ready.items():path.write_bytes(payload)
    (HERE/'DOCX表格字体调整记录.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2))
    o.new_workbook(HERE/'DOCX表格字体调整记录.xlsx',o.HEADERS,
                   [[r[k] for k in ['id','file','location','before','after','reason','evidence','date','kind']] for r in entries],o.WIDTHS)
    report=dict(date='2026-10-26',files_checked=len(checked),tables_checked=sum(r['tables_checked'] for r in checked),
                files_changed=len(ready),runs_changed=len(entries),files=checked,
                checks=['全部表格参照原文件逐段文字格式核对','新增履历参照原履历对应列','二次应用无变化','仅rPr文字格式变化，正文及修订标记保留','其他ZIP部件逐字节一致'],
                limits='未使用Office进行屏幕渲染与分页验证。')
    (HERE/'DOCX表格字体验证结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
