import importlib.util
import json
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from privacy_check import PATTERNS,PUBLIC_FILES


class ReleaseTests(unittest.TestCase):
    def test_generic_identifier_scanner(self):
        self.assertTrue(PATTERNS['chat account identifier'].search('wxid_'+'fictional12345'))
        self.assertTrue(PATTERNS['API token literal'].search('sk-'+'x'*25))
        self.assertFalse(PATTERNS['chat account identifier'].search('A/B'))
    def test_allowlist_excludes_runtime_data(self):
        self.assertTrue(all(not p.startswith(('private-input/','private-output/')) for p in PUBLIC_FILES))
        self.assertFalse(any(p.endswith(('.db','.pem','.key','.sqlite')) for p in PUBLIC_FILES))
    def test_skill_entry_and_prompt(self):
        skill=(ROOT/'SKILL.md').read_text(encoding='utf-8')
        self.assertTrue(skill.startswith('---\nname: chat-reply-audit\n'))
        self.assertIn('$chat-reply-audit',(ROOT/'agents/openai.yaml').read_text(encoding='utf-8'))
    def test_local_demo_links_and_no_active_external_resources(self):
        class Inspector(HTMLParser):
            def __init__(self):super().__init__();self.links=[];self.external=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='a' and 'href' in attrs:self.links.append(attrs['href'])
                if tag in ('script','iframe','img','link') and any(k in attrs for k in ('src','href')):self.external.append(tag)
        for page in ROOT.glob('examples/demo-*/report.html'):
            parser=Inspector();parser.feed(page.read_text(encoding='utf-8'))
            self.assertEqual(parser.external,[])
            for link in parser.links:
                self.assertFalse(urlsplit(link).scheme)
                if not link.startswith('#'):self.assertTrue((page.parent/link).is_file())


if __name__=='__main__':unittest.main()
