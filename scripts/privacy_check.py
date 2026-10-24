#!/usr/bin/env python3
"""Release allowlist + generic sensitive-pattern checks. Not a privacy guarantee."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE_FILES=(
    'README.md','SKILL.md','LICENSE','.gitignore','.gitattributes','.env.example',
    'agents/openai.yaml','references/input-format.md','references/review-guide.md',
    'docs/PRIVACY.md','docs/PUBLISHING.md','docs/HIGH_RISK_EXPORT.md','scripts/audit_core.py','scripts/reply_audit.py',
    'docs/DATA_PREPARATION.md','docs/WALKTHROUGH.md',
    'docs/RESULTS_AND_TROUBLESHOOTING.md','scripts/review_workbench.py','tests/test_workbench.py',
    'scripts/llm_review.py','scripts/build_demo.py','scripts/privacy_check.py','scripts/export_release.py',
    'tests/test_audit.py','tests/test_release.py','.github/workflows/check.yml',
    'examples/demo.csv','examples/phases.json','examples/demo-context.json','examples/demo-reviews.json',
    'assets/demo-overview.svg',
)
DEMO_FILES=tuple('examples/demo-report/'+name for name in (
    'analysis.json','events.csv','candidates.csv','boundary_events.csv','pending.csv','summary.csv','report.md','report.html'))
DEMO_FILES+=tuple('examples/demo-review/'+name for name in ('validated_reviews.json','review_summary.csv','report.html','report.md'))
PUBLIC_FILES=tuple(sorted(BASE_FILES+DEMO_FILES))
IGNORED_DIRS={'.git','__pycache__','.venv','private-input','private-output'}
PATTERNS={
    'chat account identifier':re.compile(r'\bwxid_[A-Za-z0-9]{6,}\b'),
    'absolute Windows path':re.compile(r'\b[A-Za-z]:[\\/][^\s"<>]+'),
    'personal home path':re.compile(r'/(?:home|Users)/[A-Za-z0-9_.-]+/'),
    'email address':re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
    'phone-like number':re.compile(r'\b1[3-9]\d{9}\b'),
    'private-key block':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'credential-like literal':re.compile(r'(?i)\b(?:api_key|enc_key|aeskey|password)\s*[:=]\s*[\"\x27][A-Za-z0-9/_+.-]{16,}'),
    'API token literal':re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
}


def file_digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    found=[];issues=[]
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in list(dirs):
            p=Path(parent)/name
            if p.is_symlink():
                issues.append({'file':p.relative_to(root).as_posix(),'rule':'symlink directory'});dirs.remove(name)
            elif name in IGNORED_DIRS:dirs.remove(name)
        for name in files:
            p=Path(parent)/name
            if p.is_symlink():issues.append({'file':p.relative_to(root).as_posix(),'rule':'symlink file'})
            else:found.append(p.relative_to(root).as_posix())
    return found,issues


def check(root=ROOT,verify_manifest=True):
    root=Path(root).resolve();found,issues=inventory(root)
    allowed=set(PUBLIC_FILES)|{'release-manifest.json'}
    for rel in found:
        if rel not in allowed:issues.append({'file':rel,'rule':'not in release allowlist'})
    for rel in PUBLIC_FILES:
        p=root/rel
        if not p.is_file():
            issues.append({'file':rel,'rule':'missing public file'});continue
        try:text=p.read_text(encoding='utf-8-sig')
        except UnicodeError:
            issues.append({'file':rel,'rule':'unexpected binary file'});continue
        for rule,pattern in PATTERNS.items():
            if pattern.search(text):issues.append({'file':rel,'rule':rule})
    if verify_manifest:
        p=root/'release-manifest.json'
        try:
            manifest=json.loads(p.read_text(encoding='utf-8'))
            if set(manifest['files'])!=set(PUBLIC_FILES):raise ValueError()
            for rel,expected in manifest['files'].items():
                if not (root/rel).is_file() or file_digest(root/rel)!=expected:
                    issues.append({'file':rel,'rule':'manifest digest mismatch'})
        except (OSError,KeyError,ValueError,TypeError):
            issues.append({'file':'release-manifest.json','rule':'missing or invalid manifest'})
    return {'ok':not issues,'allowlisted_file_count':len(PUBLIC_FILES),'issues':issues,
            'limits':'Checks the current allowlisted working tree, not Git history or all possible personal information. Ignored runtime folders are never release files.'}


def update_manifest(root=ROOT):
    root=Path(root)
    result=check(root,False)
    if not result['ok']:return result
    manifest={'schema_version':'1.0','scope':'Only listed source files, documentation and wholly invented demonstrations.',
              'files':{rel:file_digest(root/rel) for rel in PUBLIC_FILES}}
    (root/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8', newline='\n')
    return check(root)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--update-manifest',action='store_true')
    args=parser.parse_args();result=update_manifest() if args.update_manifest else check()
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['ok'] else 1)
