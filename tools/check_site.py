"""Verify the public site's local resources and evidence payload before release."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit,unquote
import json
ROOT=Path(__file__).resolve().parents[1]
SITE=ROOT/'docs' if (ROOT/'docs/index.html').exists() else ROOT
class Document(HTMLParser):
    def __init__(self):super().__init__();self.refs=[];self.lang=False;self.h1=0;self.viewport=False;self.csp=False;self.in_data=False;self.data=''
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='html':self.lang=bool(a.get('lang'))
        if tag=='h1':self.h1+=1
        if tag=='meta':
            self.viewport |= a.get('name')=='viewport'
            self.csp |= a.get('http-equiv','').lower()=='content-security-policy'
        if tag=='script' and a.get('type')=='application/json':self.in_data=True
        for k in ['src','href']:
            if a.get(k):self.refs.append(a[k])
    def handle_endtag(self,tag):
        if tag=='script':self.in_data=False
    def handle_data(self,data):
        if self.in_data:self.data+=data
for path in [SITE/'index.html']:
    p=Document();p.feed(path.read_text());assert p.lang and p.h1==1 and p.viewport and p.csp,path
    for ref in p.refs:
        url=urlsplit(ref)
        if url.scheme or url.netloc or ref.startswith(('#','/')):continue
        assert (path.parent/unquote(url.path)).exists(),ref
    if p.data:json.loads(p.data)
print('Site resources, semantics and evidence payload passed.')
