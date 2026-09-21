"""Run discovery browser checks using illustrative fixtures, never the real library."""
from pathlib import Path
import os
import time
import json
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_library as fixtures
from literature_radar.models import Paper,PaperAnalysis
from literature_radar.workflows import TaskStore, collection_fingerprint


def main():
    candidates=[Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
                Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Google/Chrome/Application/chrome.exe']
    browser=next((p for p in candidates if p.exists()),None)
    if browser is None: raise SystemExit('Install Edge or Chrome to run browser checks.')
    output=Path(sys.argv[1] if len(sys.argv)>1 else 'tests/artifacts').resolve()
    output.mkdir(parents=True,exist_ok=True)
    fixture=fixtures.LibraryTest()
    titles=['A foundation model for cellular perturbation prediction','Mapping tissue architecture with spatial multi-omics',
            'Interpretable graph learning for cell interactions','Cross-tissue transfer learning for single-cell annotation',
            'Benchmarking reproducible workflows for RNA sequencing']
    summaries=['从细胞扰动出发，探索跨数据集的表征迁移与预测能力。','联合空间位置与分子表达，刻画组织中的细胞关系。',
               '通过可解释的图结构，寻找细胞互作中的关键线索。','评估跨组织迁移中的注释表现与适用边界。','比较常见分析流程的稳定性，为复现选择合适的起点。']
    try:
        fixture.setUp()
        fixture.config["web"]["show_onboarding"] = True
        for i in range(20):
            fixture.store.upsert_paper(Paper(source='pubmed',external_id='sample-'+str(i),title=titles[i%5]+' · '+str(i+1),
                abstract='Illustrative test fixture. <script>window.untrustedExecuted=true</script> Not a real publication.',
                url='https://example.org',journal='DEMO / TEST FIXTURE',
                analysis=PaperAnalysis(provider='deepseek',score=[29,25,20,12,6][i%5],summary=summaries[i%5],
                    tags=['single-cell','foundation model'] if i%2==0 else ['spatial omics','benchmark'],
                    why_read='测试数据：与当前研究方向相关，可进一步检查验证设置和可复现性。',
                    method_flow=['整理输入数据','建立模型并进行对照','检查泛化能力和局限'],follow_up_prompts=['验证是否覆盖独立数据？'])))
        TaskStore(fixture.store)
        with fixture.store._connect() as conn:
            conn.execute("INSERT INTO workflow_jobs(id,kind,status,options_json,result_json,started,heartbeat,finished) VALUES (?,?,?,?,?,?,?,?)",
                ('fixture-collection','collection','succeeded',json.dumps({'fingerprint':collection_fingerprint(fixture.config)}),
                 json.dumps(dict(added=20,matched=20,total=21)),time.time(),time.time(),time.time()))
        port=fixture.start_server()
        result=subprocess.run(['node',str(Path(__file__).with_name('browser_discovery.mjs')),f'http://127.0.0.1:{port}/',str(browser),str(output)],
                              timeout=90,creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True,text=True,encoding='utf-8')
        print(result.stdout)
        print(result.stderr)
        return result.returncode
    finally:
        fixture.doCleanups()


if __name__=='__main__':raise SystemExit(main())