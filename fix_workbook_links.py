"""Preserve source hyperlinks when the employment table expands.

Artifact Tool currently leaves imported hyperlinks attached after range.clear.
This small OOXML repair moves only the four known source links below the new
table; it does not rewrite workbook values, formulas, formatting or other parts.
"""
import argparse
import os
import posixpath
import tempfile
import xml.etree.ElementTree as ET
import zipfile

NS = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'p':'http://schemas.openxmlformats.org/package/2006/relationships'}

def repair(filename, footer_row):
    with zipfile.ZipFile(filename) as z:
        book=ET.fromstring(z.read('xl/workbook.xml'))
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets={r.attrib['Id']:r.attrib['Target'] for r in rels}
        item=next(s for s in book.findall('s:sheets/s:sheet',NS) if s.attrib['name']=='Employment ')
        target=targets[item.attrib['{'+NS['r']+'}id']]
        part=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl',target))
        sheet=ET.fromstring(z.read(part))
        links=sheet.find('s:hyperlinks',NS)
        if links is None:
            return
        relpart=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
        relationships=ET.fromstring(z.read(relpart))
        targets={r.attrib['Id']:r.attrib['Target'] for r in relationships}
        known=['https://www.bls.gov/news.release/pdf/empsit.pdf','https://econvitals.org/labor/','https://fred.stlouisfed.org/series/PAYEMS','https://fred.stlouisfed.org/series/MANEMP']
        moved=0
        for link in links:
            dest=targets.get(link.attrib.get('{'+NS['r']+'}id'))
            if dest in known:
                link.attrib['ref']=f'C{footer_row+known.index(dest)}'
                moved+=1
        payload=ET.tostring(sheet,encoding='utf-8',xml_declaration=True)
        fd,temp=tempfile.mkstemp(prefix='.links-',suffix='.xlsx',dir=os.path.dirname(os.path.abspath(filename)))
        os.close(fd)
        try:
            with zipfile.ZipFile(temp,'w') as out:
                for info in z.infolist():
                    out.writestr(info,payload if info.filename==part else z.read(info.filename))
            os.replace(temp,filename)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return moved

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('workbook');p.add_argument('--footer-row',type=int,required=True)
    a=p.parse_args();repair(a.workbook,a.footer_row)
