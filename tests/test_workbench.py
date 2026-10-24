"""Offline review selection, safe rendering and persisted suggestion provenance."""
import base64
import copy
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from audit_core import review_template
from reply_audit import main
from review_workbench import select_cases, write_workbench


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        scratch=ROOT/'private-output';scratch.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=scratch);self.path=Path(self.tmp.name)
        self.packet=json.loads((ROOT/'examples/demo-context.json').read_text(encoding='utf-8'))
    def tearDown(self):self.tmp.cleanup()
    def payload(self,page):
        encoded=re.search(r"atob\('([A-Za-z0-9+/=]+)'\)",page).group(1)
        return json.loads(base64.b64decode(encoded))
    def test_selection_preserves_ids_and_input(self):
        ids=[self.packet['cases'][2]['event']['event_id']]
        result=select_cases(self.packet,ids)
        self.assertEqual(result['analysis_id'],self.packet['analysis_id'])
        self.assertEqual([c['event']['event_id'] for c in result['cases']],ids)
        self.assertEqual(len(self.packet['cases']),11)
    def test_selection_rejects_unknown_or_duplicate(self):
        for ids in [[],['E999999'],['E000007','E000007']]:
            with self.assertRaises(ValueError):select_cases(self.packet,ids)
    def test_hostile_content_is_encoded_and_no_remote_resources(self):
        attack='</script><img src="https://example.com/pixel">alert("fiction")'
        self.packet['cases'][0]['context']['before'][0]['text']=attack
        write_workbench(self.path/'desk',self.packet)
        page=(self.path/'desk/index.html').read_text(encoding='utf-8')
        self.assertNotIn(attack,page)
        self.assertEqual(self.payload(page)['packet']['cases'][0]['context']['before'][0]['text'],attack)
        class Inspect(HTMLParser):
            def __init__(self):super().__init__();self.remote=[];self.csp=''
            def handle_starttag(self,tag,attrs):
                a=dict(attrs)
                if tag in ('script','img','iframe','link') and ('src' in a or 'href' in a):self.remote.append(tag)
                if a.get('http-equiv')=='Content-Security-Policy':self.csp=a['content']
        p=Inspect();p.feed(page)
        self.assertEqual(p.remote,[]);self.assertIn("connect-src 'none'",p.csp)
    def test_model_prefill_does_not_become_human(self):
        annotations=review_template(self.packet);annotations['review_source']='model_suggestion'
        write_workbench(self.path/'desk',self.packet,annotations)
        data=self.payload((self.path/'desk/index.html').read_text(encoding='utf-8'))
        self.assertEqual(data['annotations']['review_source'],'model_suggestion')
        self.assertEqual(len(data['annotations']['reviews']),len(self.packet['cases']))
    def test_invalid_prefill_is_rejected_before_output(self):
        annotations=review_template(self.packet)
        annotations['reviews'][0]['basis_refs']=['M999999']
        with self.assertRaises(ValueError):write_workbench(self.path/'desk',self.packet,annotations)
        self.assertFalse((self.path/'desk').exists())
    def test_workbench_does_not_overwrite(self):
        write_workbench(self.path/'desk',self.packet)
        with self.assertRaises(ValueError):write_workbench(self.path/'desk',self.packet)
    def test_cli_tutorial_flow_and_selected_review(self):
        stats=self.path/'stats';context=self.path/'context';desk=self.path/'desk';report=self.path/'result'
        commands=[['analyze','--input',str(ROOT/'examples/demo.csv'),'--phases',str(ROOT/'examples/phases.json'),
                   '--as-of','2030-01-07T18:00:00+08:00','--out',str(stats)],
                  ['prepare-review','--input',str(ROOT/'examples/demo.csv'),'--analysis',str(stats/'analysis.json'),
                   '--events','E000007','E000030','--include-content','--out',str(context)],
                  ['review-workbench','--packet',str(context/'context_packet.json'),'--out',str(desk)]]
        with redirect_stdout(io.StringIO()) as output:
            for command in commands:self.assertEqual(main(command),0)
        packet=json.loads((context/'context_packet.json').read_text(encoding='utf-8'))
        reviews=json.loads((ROOT/'examples/demo-reviews.json').read_text(encoding='utf-8'))
        reviews['reviews']=[r for r in reviews['reviews'] if r['event_id'] in ('E000007','E000030')]
        (self.path/'reviews.json').write_text(json.dumps(reviews),encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['apply-review','--packet',str(context/'context_packet.json'),
                '--reviews',str(self.path/'reviews.json'),'--out',str(report)]),0)
        self.assertEqual(len(packet['cases']),2)
        self.assertTrue((report/'report.html').is_file())
        self.assertNotIn('会场预约',output.getvalue())


if __name__=='__main__':unittest.main()
