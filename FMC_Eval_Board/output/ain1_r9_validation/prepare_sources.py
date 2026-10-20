from pathlib import Path
import urllib.request
import zipfile
import subprocess
from pypdf import PdfReader

root=Path(__file__).resolve().parent
vendor=root/'vendor'
vendor.mkdir(exist_ok=True)
sources={
    'ina851.pdf':'https://www.ti.com/lit/ds/symlink/ina851.pdf',
    'SBOMC50.zip':'https://www.ti.com/lit/zip/SBOMC50',
    'SBOMC52.zip':'https://www.ti.com/lit/zip/SBOMC52',
}
for name,url in sources.items():
    target=vendor/name
    if not target.exists():
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=45) as response:
            target.write_bytes(response.read())
    if name.endswith('.zip'):
        with zipfile.ZipFile(target) as archive:
            dest=vendor/target.stem
            dest.mkdir(exist_ok=True)
            for member in archive.infolist():
                resolved=(dest/member.filename).resolve()
                if not resolved.is_relative_to(dest.resolve()):
                    raise ValueError('Invalid ZIP path')
            archive.extractall(dest)
    print(name,target.stat().st_size)
pdf=PdfReader(vendor/'ina851.pdf')
(vendor/'ina851.txt').write_text('\n'.join(p.extract_text() for p in pdf.pages),encoding='utf8')
subprocess.run(['pdftoppm','-f','4','-l','4','-r','180','-x','0','-y','0',
                '-W','1650','-H','1200','-singlefile','-png',
                str(root.parents[1]/'CaravelReRAM-SenseEval_v1.2F.pdf'),
                str(root/'u10_schematic')],check=True)

