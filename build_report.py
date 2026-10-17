"""Build the static report from retained local evidence, without external requests."""
from pathlib import Path
import json,html,csv
ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    data=json.loads((ROOT/'demo/evidence.json').read_text())
    template=(ROOT/'docs/report-template.html').read_text()
    out=template.replace('__REPORT_DATA__',json.dumps(data).replace('<','\\u003c')).replace('__DETAIL_DATA__',html.escape(json.dumps(data,indent=2)))
    (ROOT/'docs/index.html').write_text(out)
    (ROOT/'docs/data.json').write_text(json.dumps(data,indent=2)+'\n')
    print('Built docs/index.html')
