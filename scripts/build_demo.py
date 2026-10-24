#!/usr/bin/env python3
"""Build reproducible, entirely invented examples. No private inputs or API calls."""
from __future__ import annotations
import argparse
import csv
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from audit_core import (analyze, load_phases, parse_zone, prepare_review, read_messages, review_template,
                        write_analysis, write_json, write_review_report)

ROOT = Path(__file__).resolve().parents[1]
DEMO = [
    ("01 09:00:00","A","text","演示用投影接好了吗？"),
    ("01 09:04:00","B","text","接好了，测试画面也正常。"),
    ("01 09:05:00","A","text","收到，准备开始。"),
    ("01 09:06:00","B","text","好，现场见。"),
    ("01 16:00:00","B","text","下周的演示封面选蓝色还是橙色？"),
    ("01 16:20:00","A","text","选蓝色吧。"),
    ("01 16:21:00","B","text","收到。"),
    ("02 09:00:00","A","text","今天的会场预约成功了吗？"),
    ("02 14:10:00","B","text","预约好了，刚才一直在培训，课间才看到。"),
    ("02 14:12:00","A","text","了解，我下午再准备材料。"),
    ("02 14:13:00","B","text","好的。"),
    ("02 22:30:00","A","text","我把明天演示稿发好了，你有空再看，今晚不用回。"),
    ("03 10:00:00","B","text","看过了，第二页可以再精简些。"),
    ("03 10:02:00","A","text","好，我改一下。"),
    ("03 10:03:00","B","text","谢谢。"),
    ("04 08:00:00","A","voice","[虚构语音占位，未转写]"),
    ("04 13:00:00","B","image","[虚构图片占位，未识别]"),
    ("04 13:10:00","A","text","这张演示海报的标题再大一点？"),
    ("04 13:20:00","B","text","好，我调整。"),
    ("04 13:22:00","A","text","收到。"),
    ("04 13:23:00","B","text","下午各自准备，晚些再沟通。"),
    ("05 09:00:00","A","text","展示时先播放音频还是先讲解？"),
    ("05 09:03:00","B","text","先播放音频。"),
    ("05 09:05:00","A","text","好。"),
    ("05 15:00:00","A","text","演示摘要控制在一页够吗？"),
    ("05 15:12:00","B","text","够，一页即可。"),
    ("05 15:13:00","A","text","收到，安排好了。"),
    ("05 15:14:00","B","text","那先各忙。"),
    ("06 10:00:00","A","text","这份演示代码你看懂了吗？"),
    ("06 14:00:00","B","text","基本看懂了。"),
    ("06 14:01:00","A","text","好，后面有问题再说。"),
    ("07 09:00:00","B","text","演示现场需要提前十分钟到吗？"),
    ("07 13:00:01","A","text","需要，提前到。刚结束排练。"),
    ("07 13:01:00","B","text","知道了。"),
]


def write_inputs(root):
    root.mkdir(parents=True,exist_ok=True)
    with (root/'demo.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f,lineterminator="\n");w.writerow(['timestamp','sender','kind','message_id','conversation_id','text'])
        for i,(when,who,kind,text) in enumerate(DEMO,1):
            w.writerow(['2030-01-'+when,who,kind,f'demo-{i:04}','synthetic-demo',text])
    write_json(root/'phases.json',[
        {'name':'虚构阶段一','start':'2030-01-01','end':'2030-01-05'},
        {'name':'虚构阶段二','start':'2030-01-05','end':'2030-01-08'}])


def annotations_for(packet):
    """Handwritten fixture answers, keyed to invented message refs, not a production classifier."""
    template=review_template(packet);template['review_source']='synthetic_fixture'
    scenarios={
        'M000004':('restart','M000005',['M000004','M000005','M000006'],'前面已说现场见；下午封面提问另起一轮，20分钟后答复。','新问题没有跨过4小时，上午收尾不构成持续等待。','not_applicable'),
        'M000008':('retained','M000008',['M000008','M000009'],'会场预约是明确问题，5小时10分后得到同事项回答。','对方明确解释在培训、课间才看见；延后回应不等于故意不回。','explained'),
        'M000010':('agreed_deferral',None,['M000012','M000013'],'当事人明确说有空再看、今晚不用回，次日反馈符合安排。','按明确约定延后，不用长间隔判定失礼。','explained'),
        'M000016':('uncertain',None,['M000016','M000017'],'语音和图片均未识别，无法确认是否存在待答事项及其对应关系。','保留未知，不猜测媒体内容。','insufficient'),
        'M000024':('restart','M000025',['M000024','M000025','M000026'],'上午确认音频安排已结束；下午摘要提问是新事项，12分钟后答复。','不能把上午的确认语作为下午等待起点。','not_applicable'),
        'M000032':('retained','M000032',['M000032','M000033'],'关于提前到场的明确问题，4小时01秒后得到答案，严格超过4小时。','对方说明刚结束排练；解释与是否存在延后回应分开。','explained'),
    }
    for review,case in zip(template['reviews'],packet['cases']):
        first=case['event']['first_ref']
        if first in scenarios:
            status,start,refs,reason,assessment,context=scenarios[first]
        else:
            status,start,refs='closed',None,[first]
            reason='此处为前一问答的确认或收尾；后面的新发言没有使它成为未解决问题。'
            assessment='未确认仍在等待答复，不把停聊时长当成迟答。';context='not_applicable'
        review.update(status=status,revised_start_ref=start,basis_refs=refs,reason=reason,
                      context_assessment=assessment,context_status=context)
    return template


def overview_svg(analysis,annotations):
    counts=Counter(r['status'] for r in annotations['reviews'])
    labels=[('retained','保留待回应'),('restart','新话题起点'),('closed','已收尾'),('agreed_deferral','允许延后'),('uncertain','证据不足')]
    bars=[]
    total=max(1,len(annotations['reviews']))
    for i,(key,label) in enumerate(labels):
        y=382+i*48;width=counts[key]/total*670
        bars.append(f'<text x="68" y="{y+21}" fill="#24434d" font-size="18">{label}</text><rect x="230" y="{y}" width="{width:.2f}" height="28" rx="7" fill="#2d8e7a"/><text x="{248+width:.2f}" y="{y+21}" fill="#24434d" font-size="18">{counts[key]}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="740" viewBox="0 0 1120 740" role="img" aria-labelledby="title desc">
<title id="title">Chat Reply Audit：完全虚构数据演示</title><desc id="desc">{len(DEMO)}条虚构消息，{len(analysis['candidates'])}个长间隔候选；示例审阅答案预先编写，没有调用API。</desc>
<rect width="1120" height="740" rx="24" fill="#f3f7f6"/><text x="58" y="64" font-family="Arial,sans-serif" font-size="17" letter-spacing="3" fill="#3e716b">CHAT REPLY AUDIT / SYNTHETIC DEMO</text>
<g font-family="system-ui,Microsoft YaHei,sans-serif"><text x="58" y="126" font-size="40" font-weight="700" fill="#183c43">把“我觉得”，变成可以核对的证据</text>
<text x="58" y="176" font-size="22" fill="#56717a">时间戳筛选候选 → 模型或人工读上下文 → 保留证据与不确定性</text>
<rect x="58" y="214" width="1004" height="110" rx="16" fill="#e1eeea"/>
<text x="88" y="254" font-size="19" fill="#46666a">虚构消息</text><text x="88" y="298" font-size="34" fill="#173f46">{len(DEMO)}</text>
<text x="365" y="254" font-size="19" fill="#46666a">严格超过4小时的候选</text><text x="365" y="298" font-size="34" fill="#173f46">{len(analysis['candidates'])}</text>
<text x="750" y="254" font-size="19" fill="#46666a">输入中的真实聊天</text><text x="750" y="298" font-size="34" fill="#173f46">0</text>
{''.join(bars)}<text x="58" y="683" font-size="17" fill="#5a737a">展示为预先编写的虚构审阅样例；不能用于评判任何人的关系或行为。</text>
<text x="58" y="713" font-size="15" fill="#5a737a">Python standard library · Optional API · Evidence references · No database decryption</text></g></svg>'''


def build(check=False):
    scratch=ROOT/'private-output';scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='demo-build-',dir=scratch) as td:
        stage=Path(td);examples=stage/'examples';write_inputs(examples)
        messages,audit=read_messages(examples/'demo.csv',parse_zone('+08:00'))
        result=analyze(messages,audit,phases=load_phases(examples/'phases.json',parse_zone('+08:00')),
                       as_of='2030-01-07T18:00:00+08:00')
        write_analysis(examples/'demo-report',result)
        full,check_audit=read_messages(examples/'demo.csv',parse_zone('+08:00'),content=True)
        packet=prepare_review(full,check_audit,result)
        annotations=annotations_for(packet)
        write_json(examples/'demo-context.json',packet);write_json(examples/'demo-reviews.json',annotations)
        write_review_report(examples/'demo-review',packet,annotations)
        assets=stage/'assets';assets.mkdir();(assets/'demo-overview.svg').write_text(overview_svg(result,annotations),encoding='utf-8', newline='\n')
        generated=[p for p in stage.rglob('*') if p.is_file()]
        for p in generated:
            dest=ROOT/p.relative_to(stage)
            if check:
                if not dest.exists() or dest.read_bytes()!=p.read_bytes():
                    raise ValueError('演示产物与生成器不一致：'+str(p.relative_to(stage)))
            else:
                dest.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(p,dest)
        print(f"{'核对' if check else '生成'}完成：{len(generated)}个虚构演示文件，{len(result['candidates'])}个候选；未调用API。")


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true')
    build(parser.parse_args().check)
