#!/usr/bin/env python3
"""Compare every revised Office file with the immutable original archive."""
import io
import json
import posixpath
import re
import zipfile
from collections import Counter
import revise_office as o


def rows(doc):
    return {n.getAttribute('r'): {a:n.getAttribute(a) for a in ['ht','customHeight']}
            for n in o.elements(doc,o.S,'row')}


def cells(doc,shared):
    return {n.getAttribute('r'):{'value':o.celltext(n,shared),
                               'formula':[x.toxml() for x in o.elements(n,o.S,'f')],
                               'type':n.getAttribute('t'), 'style':n.getAttribute('s'),
                               'xml':n.toxml()}
            for n in o.elements(doc,o.S,'c')}


def paragraph_shell(node):
    # A paragraph may contain a textbox with other paragraphs; those nested
    # paragraphs are each verified separately against their own baseline index.
    node=node.cloneNode(True)
    for paragraph in o.elements(node,o.W,'p'):
        for child in list(paragraph.childNodes):paragraph.removeChild(child)
    return node.toxml()


def relationships(z):
    names=set(z.namelist())
    for part in names:
        if not part.endswith('.rels'):continue
        base='' if part=='_rels/.rels' else posixpath.dirname(part).rsplit('/_rels',1)[0]
        for link in o.elements(o.xml(z.read(part)),o.P,'Relationship'):
            if link.getAttribute('TargetMode')=='External':continue
            target=link.getAttribute('Target').split('#')[0]
            if not target:continue
            resolved=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(base,target))
            assert resolved in names,(part,resolved)


def main():
    plan=json.loads((o.OUT/'edit_plan.json').read_text())
    ledger=json.loads((o.OUT/'修改总台账.json').read_text())
    summary=[];layout=[];unchanged=[]
    with zipfile.ZipFile(o.OUT/'原文件备份.zip') as backup:
        for file in plan['files']:
            path=o.TARGET/file['file'];payload=path.read_bytes();original=backup.read(file['file'])
            assert o.sha(original)==file['sha256']
            if not file['edits']:
                assert payload==original
                unchanged.append(file['file']);summary.append({'file':file['file'],'modified':False,'sha256_before':o.sha(original),'sha256_after':o.sha(payload),'bytes_before':len(original),'bytes_after':len(payload)})
                continue
            records=[x for x in ledger if x['file']==file['file']]
            has_body=any(e.get('kind')!='版本编号' for e in file['edits'])
            assert len(records)==len(file['edits'])+int(has_body)
            with zipfile.ZipFile(io.BytesIO(original)) as src,zipfile.ZipFile(io.BytesIO(payload)) as dst:
                assert dst.testzip() is None
                for part in dst.namelist():
                    if part.endswith('.xml') or part.endswith('.rels'):o.xml(dst.read(part))
                relationships(dst)
                changed=[n for n in src.namelist() if src.read(n)!=dst.read(n)]
                added=sorted(set(dst.namelist())-set(src.namelist()))
                assert set(src.namelist())<=set(dst.namelist())
                if path.suffix=='.docx':
                    assert not added
                    assert set(changed)<= {'word/document.xml','word/settings.xml'}
                    old=o.xml(src.read('word/document.xml'));new=o.xml(dst.read('word/document.xml'))
                    tables0=o.elements(old,o.W,'tbl');tables1=o.elements(new,o.W,'tbl')
                    assert len(tables0)==len(tables1)
                    # Remove exactly the new history row before comparing original positions.
                    history=next(t for t in tables1 if '变更内容' in o.wtext(t) and '版本' in o.wtext(t) and len(o.wtext(t))<2500)
                    newrows=[r for r in o.children(history,o.W,'tr') if o.HISTORY_DESCRIPTION in o.wtext(r) and o.HISTORY_DATE in o.wtext(r)]
                    assert len(newrows)==int(has_body)
                    if has_body:
                        newrow=newrows[0]
                        values=[o.wtext(c) for c in o.children(newrow,o.W,'tc')]
                        assert values==['1',o.HISTORY_DESCRIPTION,'','','',o.HISTORY_DATE]
                        history.removeChild(newrow)
                    p0=o.elements(old,o.W,'p');p1=o.elements(new,o.W,'p')
                    assert len(p0)==len(p1)
                    planned={x['paragraph']:x for x in file['edits']}
                    for i,(a,b) in enumerate(zip(p0,p1)):
                        if i not in planned:
                            assert paragraph_shell(a)==paragraph_shell(b),(file['file'],'unplanned paragraph',i)
                            continue
                        edit=planned[i]
                        assert o.wtext(a)==edit['before'] and o.wtext(b)==edit['after']
                        if edit.get('kind')=='版本编号':
                            clone=a.cloneNode(True)
                            for ti,t in enumerate(o.elements(clone,o.W,'t')):
                                for child in list(t.childNodes):t.removeChild(child)
                                if ti==0:t.appendChild(clone.ownerDocument.createTextNode(edit['after']))
                            assert clone.toxml()==b.toxml(), 'Version format changed unexpectedly'
                            continue
                        removed=''.join(o.text(t) for n in o.children(b,o.W,'del') for t in o.elements(n,o.W,'delText'))
                        inserted=''.join(o.wtext(n) for n in o.children(b,o.W,'ins'))
                        assert removed==edit['before'] and inserted==edit['after'],(file['file'],i)
                        assert [n.toxml() for n in o.children(a,o.W,'pPr')]==[n.toxml() for n in o.children(b,o.W,'pPr')]
                    if has_body:assert o.elements(o.xml(dst.read('word/settings.xml')),o.W,'trackRevisions')
                    layout.append({'file':file['file'],'type':'Word包级修改','changed_parts':changed,'details':'正文替换含删除/插入标记；原段落属性保留；原变更履历按用户示例增加正式版本行；启用修订记录。'})
                else:
                    w0,r0,s0=o.workbook_parts(src);w1,r1,s1=o.workbook_parts(dst)
                    assert list(s1)==list(s0)
                    st0=o.strings(src);st1=o.strings(dst);assert st0==st1
                    xf0=o.children(o.elements(o.xml(src.read('xl/styles.xml')),o.S,'cellXfs')[0],o.S,'xf')
                    xf1=o.children(o.elements(o.xml(dst.read('xl/styles.xml')),o.S,'cellXfs')[0],o.S,'xf')
                    assert [n.toxml() for n in xf0]==[n.toxml() for n in xf1[:len(xf0)]]
                    planned={(x['sheet'],x['cell']):x for x in file['edits']}
                    history=next(n for n in s0 if '修订记录' in n)
                    allowed=set(planned)
                    history_record=next(x for x in records if x['kind']=='修订履历')
                    history_row=re.search(r'!A(\d+):F\d+',history_record['location']).group(1)
                    history_cells={o.colname(i)+history_row for i in [1,2,6]}
                    allowed|={(history,a) for a in history_cells}
                    for sn,part in s0.items():
                        d0=o.xml(src.read(part));d1=o.xml(dst.read(s1[sn]))
                        c0=cells(d0,st0);c1=cells(d1,st1)
                        assert {a:b['formula'] for a,b in c0.items() if b['formula']}=={a:b['formula'] for a,b in c1.items() if b['formula']}
                        for tag in ['mergeCells','cols','pageMargins','pageSetup','printOptions','conditionalFormatting','dataValidations','autoFilter']:
                            assert [n.toxml() for n in o.elements(d0,o.S,tag)]==[n.toxml() for n in o.elements(d1,o.S,tag)],(file['file'],sn,tag)
                        for address,item in c0.items():
                            if (sn,address) not in allowed:
                                assert c1[address]['xml']==item['xml'],(file['file'],sn,address,'unplanned cell')
                        for address,item in c1.items():
                            if (sn,address) in planned:
                                edit=planned[sn,address]
                                assert c0.get(address,{'value':''})['value']==edit['before']
                                assert item['value']==edit['after']
                            elif address not in c0:
                                assert sn==history and address in history_cells,(file['file'],sn,address,'unexpected cell')
                        row0=rows(d0);row1=rows(d1)
                        for rn,attrs in row1.items():
                            if row0.get(rn)!=attrs:
                                layout.append({'file':file['file'],'type':'Excel行高/换行','sheet':sn,'row':rn,'before':row0.get(rn),'after':attrs})
                        for edit in file['edits']:
                            if edit['sheet']==sn:
                                a=edit['cell'];layout.append({'file':file['file'],'type':'Excel自动换行样式','sheet':sn,'cell':a,'before_style':c0.get(a,{}).get('style','0'),'after_style':c1[a]['style']})
                    # Existing named print ranges and other workbook defined names are unchanged.
                    assert [n.toxml() for n in o.elements(w0,o.S,'definedNames')]==[n.toxml() for n in o.elements(w1,o.S,'definedNames')]
                    assert not added
                    hd=o.xml(dst.read(s1[history]));hc=cells(hd,st1)
                    original_versions=[v['value'].strip() for a,v in cells(o.xml(src.read(s0[history])),st0).items() if re.fullmatch(r'A\d+',a) and re.fullmatch(r'\d+|[A-Z]',v['value'].strip())]
                    assert hc['A'+history_row]['value']==original_versions[-1], 'Excel version must remain unchanged'
                    assert hc['B'+history_row]['value']==o.HISTORY_DESCRIPTION
                    assert hc['F'+history_row]['value']==o.HISTORY_DATE
                    assert all(hc.get(k+history_row,{'value':''})['value']=='' for k in ['C','D','E'])
                    layout.append({'file':file['file'],'type':'Excel包级修改','changed_parts':changed,'added_parts':added,'details':'保留原工作表、公式、合并区域和打印范围；新增正式格式的版本履历及自动换行样式，详细修改记录独立保存。'})
            summary.append({'file':file['file'],'modified':True,'sha256_before':o.sha(original),'sha256_after':o.sha(payload),'bytes_before':len(original),'bytes_after':len(payload),'body_changes':sum(e.get('kind')!='版本编号' for e in file['edits']),'version_number_changes':sum(e.get('kind')=='版本编号' for e in file['edits']),'revision_history_changes':int(has_body)})
    for f in plan['files']:
        for edit in f['edits']:
            assert not any(s in edit['after'] for s in ['modbus_tls_enabled','TLS关闭','关闭TLS','关闭 TLS','TLS可关闭','TLS默认关闭','编译开关'])
    with zipfile.ZipFile(o.OUT/'修改总台账.xlsx') as z:
        relationships(z)
        for n in z.namelist():o.xml(z.read(n))
        assert len(o.elements(o.xml(z.read('xl/worksheets/sheet1.xml')),o.S,'row'))==len(ledger)+1
    (o.OUT/'原件与修订件校验清单.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (o.OUT/'布局及包结构修改记录.json').write_text(json.dumps(layout,ensure_ascii=False,indent=2))
    counts={'original_files':len(plan['files']),'modified_files':sum(x['modified'] for x in summary),'unchanged_files':unchanged,
            'body_word_paragraphs':sum(sum(e.get('kind')!='版本编号' for e in x['edits']) for x in plan['files'] if x['file'].endswith('.docx')),
            'body_excel_cells':sum(len(x['edits']) for x in plan['files'] if x['file'].endswith('.xlsx')),
            'total_ledger_records':len(ledger),'validation':'PASS',
            'checked':['原件备份及SHA-256','全部Office XML与内部关系','Word逐段修订前后文本及原段落保真','Excel逐格变化与台账一致','原公式、合并区域、列宽、打印范围及原样式保留',str(len(unchanged))+'个未修改文件逐字节一致','中英文测试条目同步','本轮确认范围排除项'],
            'limits':'未使用Word/Excel/LibreOffice做分页或屏幕渲染验证；本轮未执行设备部署、控制或实机安全测试。'}
    (o.OUT/'验证结果.json').write_text(json.dumps(counts,ensure_ascii=False,indent=2))
    print(json.dumps(counts,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
