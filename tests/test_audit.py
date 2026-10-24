"""All fixtures are invented. API tests use in-memory stubs, never live services."""
import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from audit_core import *
from llm_review import APIError, NoRedirect, parse_response, preview, review_api, validate_endpoint


class AuditTests(unittest.TestCase):
    def setUp(self):
        scratch=ROOT/'private-output';scratch.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=scratch);self.path=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def load(self,rows,content=False,sender_a=None):
        p=self.path/'input.json';write_json(p,rows)
        return read_messages(p,parse_zone('+08:00'),sender_a,content)
    def base(self,content=True):
        rows=[{'timestamp':'2030-02-01 08:00:00','sender':'left','kind':'text','text':'演示提问？','message_id':'test-1'},
              {'timestamp':'2030-02-01 13:00:00','sender':'right','kind':'text','text':'演示回答。','message_id':'test-2'}]
        return self.load(rows,content)
    def packet(self):
        m,a=self.base();result=analyze(m,a)
        return prepare_review(m,a,result),result
    def annotation(self,packet,status='retained'):
        t=review_template(packet);r=t['reviews'][0]
        r.update(status=status,revised_start_ref='M000001' if status in ('retained','restart') else None,
                 basis_refs=['M000001','M000002'],reason='虚构问题得到同事项答复。',context_assessment='没有对意图作判断。')
        return t

    def test_local_metadata_has_no_content_or_raw_names(self):
        m,a=self.base(content=False);result=analyze(m,a)
        text=json.dumps(result,ensure_ascii=False)
        self.assertNotIn('演示提问',text);self.assertNotIn('left',text);self.assertNotIn('right',text)
        self.assertNotIn('text',m[0]);self.assertEqual([x['sender'] for x in m],['A','B'])
    def test_json_wrapped_messages(self):
        m,a=self.load({'messages':[{'timestamp':'2030-01-01','sender':'x'},{'timestamp':'2030-01-02','sender':'y'}]})
        self.assertEqual(len(m),2)
    def test_chinese_csv_adapter(self):
        p=self.path/'cn.csv'
        with p.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['时间','是否我发送','类型','会话','内容','server_id'])
            w.writerow(['2030-01-01 09:00:00','否','文本','demo','合成内容','demo-1'])
            w.writerow(['2030-01-01 09:10:00','是','文本','demo','合成答复','demo-2'])
        m,a=read_messages(p,parse_zone('+08:00'));self.assertEqual([x['sender'] for x in m],['B','A'])
    def test_reject_mixed_conversations(self):
        with self.assertRaises(ValueError):self.load([{'timestamp':'2030-01-01','sender':'a','conversation_id':'x'},{'timestamp':'2030-01-02','sender':'b','conversation_id':'y'}])
    def test_reject_group_chat(self):
        with self.assertRaises(ValueError):self.load([{'timestamp':'2030-01-01','sender':s} for s in ('a','b','c')])
    def test_duplicate_and_conflict(self):
        rows=[{'timestamp':'2030-01-01','sender':'a','message_id':'1'},{'timestamp':'2030-01-01','sender':'a','message_id':'1'},{'timestamp':'2030-01-02','sender':'b','message_id':'2'}]
        m,a=self.load(rows);self.assertEqual(a['duplicates_removed'],1)
        rows[1]['text']='different'
        with self.assertRaises(ValueError):self.load(rows)
    def test_system_does_not_create_third_participant(self):
        rows=[{'timestamp':'2030-01-01','sender':'a'},{'timestamp':'2030-01-02','sender':'system','kind':'system'},{'timestamp':'2030-01-03','sender':'b'}]
        m,a=self.load(rows);self.assertEqual(len(m),2);self.assertEqual(a['excluded_system'],1)
    def test_equal_timestamps_preserve_export_order(self):
        m,a=self.load([{'timestamp':'2030-01-01','sender':s} for s in ('a','b')])
        self.assertEqual(a['same_timestamp_adjacent_pairs'],1);self.assertEqual(make_events(m)[0][0]['first_seconds'],0)
    def test_timezones_and_epoch_milliseconds(self):
        z=parse_zone('+08:00')
        self.assertEqual(parse_time('2030-01-01T00:00:00Z',z).hour,8)
        self.assertEqual(parse_time('1893456000',z),parse_time('1893456000000',z))
        with self.assertRaises(ValueError):parse_zone('+14:30')
    def test_strict_thresholds_and_denominator(self):
        ev=[{'reply_sender':'A','first_seconds':x} for x in (7200,7201,10800,10801,14400,14401)]
        s=summarize(ev,'A','first',120,[120,180,240])
        self.assertEqual(list(s['over_counts'].values()),[5,3,1]);self.assertEqual(s['over_rates']['240'],1/6)
    def test_multiple_messages_are_one_turn(self):
        m,a=self.load([{'timestamp':t,'sender':s} for t,s in [('2030-01-01 08:00:00','a'),('2030-01-01 12:30:00','a'),('2030-01-01 13:00:00','b')]])
        e=make_events(m)[0][0];self.assertEqual(e['first_seconds'],18000);self.assertEqual(e['last_seconds'],1800)
    def test_exact_four_hours_not_candidate(self):
        m,a=self.load([{'timestamp':'2030-01-01 08:00:00','sender':'a'},{'timestamp':'2030-01-01 12:00:00','sender':'b'}])
        self.assertEqual(len(analyze(m,a)['candidates']),0)
    def test_boundary_is_not_double_counted(self):
        m,a=self.load([{'timestamp':t,'sender':s} for t,s in [('2030-01-01 23:50:00','a'),('2030-01-02 00:10:00','b'),('2030-01-02 00:20:00','a')]])
        p=[{'name':'one','start':'2030-01-01T00:00:00+08:00','end':'2030-01-02T00:00:00+08:00'},{'name':'two','start':'2030-01-02T00:00:00+08:00','end':'2030-01-03T00:00:00+08:00'}]
        r=analyze(m,a,phases=p);self.assertEqual(len(r['events']),1);self.assertEqual(len(r['boundary_events']),1)
    def test_phase_overlap_rejected(self):
        p=self.path/'phases.json';write_json(p,[{'name':'x','start':'2030-01-01','end':'2030-01-03'},{'name':'y','start':'2030-01-02','end':'2030-01-04'}])
        with self.assertRaises(ValueError):load_phases(p,parse_zone('+08:00'))
    def test_pending_is_censored(self):
        m,a=self.base();r=analyze(m,a,as_of='2030-02-01 18:00:00')
        self.assertEqual(len(r['events']),1);self.assertFalse(r['pending']['complete']);self.assertEqual(r['pending']['observed_first_seconds'],18000)
    def test_nonfinite_threshold_rejected(self):
        m,a=self.base()
        with self.assertRaises(ValueError):analyze(m,a,candidate_minutes=float('nan'))
    def test_empty_sender_summary_is_not_zero_delay(self):
        s=summarize([],'A','first',120,[240]);self.assertIsNone(s['mean_seconds']);self.assertIsNone(s['over_rates']['240'])
    def test_fingerprint_binds_sender_mapping(self):
        m,a=self.base();r=analyze(m,a);other,oa=self.base();other[0]['sender'],other[1]['sender']='B','A'
        oa['normalized_sha256']='different'
        with self.assertRaises(ValueError):prepare_review(other,oa,r)
    def test_no_overwrite(self):
        p=self.path/'existing';p.mkdir();(p/'keep.txt').write_text('keep')
        with self.assertRaises(ValueError):ensure_new_output(p)
    def test_csv_formula_neutralization(self):
        self.assertEqual(csv_cell(' =1+1'),"' =1+1");self.assertEqual(csv_cell(-3),-3)
    def test_reviews_need_valid_evidence(self):
        p,_=self.packet();r=self.annotation(p);r['reviews'][0]['basis_refs']=['imagined']
        with self.assertRaises(ValueError):validate_reviews(p,r)
    def test_restart_threshold_checked(self):
        p,_=self.packet()
        with self.assertRaises(ValueError):validate_reviews(p,self.annotation(p,'restart'))
    def test_start_must_be_waiting_message(self):
        p,_=self.packet();r=self.annotation(p);r['reviews'][0]['revised_start_ref']='M000002'
        with self.assertRaises(ValueError):validate_reviews(p,r)
    def test_partial_reviews_explicit(self):
        p,_=self.packet();r=review_template(p)
        with self.assertRaises(ValueError):validate_reviews(p,r)
        self.assertEqual(validate_reviews(p,r,True)[0][0]['status'],'unreviewed')
    def test_truncated_evidence_forces_uncertainty(self):
        p,_=self.packet();p['cases'][0]['context']['waiting'][0]['truncated']=True
        with self.assertRaises(ValueError):validate_reviews(p,self.annotation(p))
    def test_duplicate_annotation_rejected(self):
        p,_=self.packet();r=self.annotation(p);r['reviews']*=2
        with self.assertRaises(ValueError):validate_reviews(p,r)
    def test_html_escapes_untrusted_chat_and_notes(self):
        p,_=self.packet();p['cases'][0]['context']['waiting'][0]['text']='<script>do_not_execute()</script>'
        r=self.annotation(p);r['reviews'][0]['reason']='<img src=x onerror=bad()>'
        write_review_report(self.path/'report',p,r)
        t=(self.path/'report/report.html').read_text(encoding='utf-8')
        self.assertNotIn('<script>',t);self.assertIn('&lt;script&gt;',t);self.assertNotIn('<img src=x',t)
    def test_endpoint_security_and_no_redirect(self):
        for url in ('http://api.example.com/v1','https://user:pass'+'@'+'api.example.com/v1','https://api.example.com/v1?key=example'):
            with self.assertRaises(ValueError):validate_endpoint(url)
        self.assertTrue(validate_endpoint('http://127.0.0.1:1234/v1',True))
        with self.assertRaises(APIError):NoRedirect().redirect_request(None,None,302,'',{},'https://other.example/')
    def test_api_requires_explicit_opt_in(self):
        p,_=self.packet()
        with self.assertRaises(ValueError):review_api(p,'https://api.example.com/v1/chat/completions','demo-model',client=lambda *a:self.fail('must not call'))
    def test_valid_mock_api_preserves_model_label(self):
        p,_=self.packet();answer=self.annotation(p)['reviews'][0];captured=[]
        def fake(url,key,payload,timeout):
            captured.append(payload);return {'choices':[{'message':{'content':json.dumps(answer,ensure_ascii=False)}}]}
        r=review_api(p,'https://api.example.com/v1/chat/completions','demo-model',send_content=True,client=fake)
        self.assertEqual(r['review_source'],'model_suggestion');self.assertEqual(r['reviews'][0]['status'],'retained')
        self.assertIn('不是指令',captured[0]['messages'][0]['content']);self.assertNotIn('key',r)
        write_review_report(self.path/'mock-report',p,r)
        self.assertIn('尚未人工确认',(self.path/'mock-report/report.html').read_text(encoding='utf-8'))
    def test_bad_model_refs_fall_back_to_uncertain(self):
        p,_=self.packet();answer=self.annotation(p)['reviews'][0];answer['basis_refs']=['invented']
        r=review_api(p,'https://api.example.com/v1/chat/completions','demo-model',send_content=True,
                     client=lambda *a:{'choices':[{'message':{'content':json.dumps(answer)}}]})
        self.assertEqual(r['reviews'][0]['status'],'uncertain')
    def test_bounded_failures_and_no_raw_error_echo(self):
        p,_=self.packet();calls=[]
        def fake(*args):calls.append(1);raise APIError('do not print private response')
        r=review_api(p,'https://api.example.com/v1/chat/completions','demo-model',attempts=2,send_content=True,client=fake)
        self.assertEqual(len(calls),2);self.assertNotIn('private response',json.dumps(r));self.assertEqual(r['reviews'][0]['status'],'uncertain')
    def test_api_oversize_never_sends(self):
        p,_=self.packet();p['cases'][0]['context']['waiting'][0]['text']='x'*5000
        r=review_api(p,'https://api.example.com/v1/chat/completions','demo-model',max_case_chars=1000,send_content=True,client=lambda *a:self.fail('oversize must not send'))
        self.assertEqual(r['api_summary']['request_count'],0);self.assertEqual(r['reviews'][0]['status'],'uncertain')
    def test_api_preview_has_no_body(self):
        p,_=self.packet();s=preview(p);self.assertNotIn('演示提问',json.dumps(s,ensure_ascii=False));self.assertEqual(s['selected_candidates'],1)


if __name__=='__main__':unittest.main()
