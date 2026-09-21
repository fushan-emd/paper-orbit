"""Full workflow browser verification with mocked publishers and model responses."""
from pathlib import Path
import copy
import json
import os
import subprocess
import sys
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_library as fixtures
from test_workbench import sample_result
from literature_radar.models import Paper,PaperAnalysis
from literature_radar.workflows import TaskStore


def main():
    browsers=[Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
              Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Google/Chrome/Application/chrome.exe']
    browser=next((p for p in browsers if p.exists()),None)
    if not browser:raise SystemExit('Edge or Chrome is required')
    output=Path(sys.argv[1] if len(sys.argv)>1 else 'tests/artifacts').resolve();output.mkdir(parents=True,exist_ok=True)
    fixture=fixtures.LibraryTest();counts={'fetch':0,'model':0}
    titles=['Cross-tissue transfer for cell perturbation models','Spatial context for interpretable cellular interactions',
            'Public-data benchmarks for single-cell foundation models','Graph representations for tissue microenvironments',
            'Reliable evaluation of cellular response prediction']
    def fetch(*args):
        counts['fetch']+=1;time.sleep(.25)
        return [Paper(source='pubmed',external_id='collected-'+str(i),title=titles[i%5]+f' · DEMO {i+1}',
                      abstract='Test fixture: The study measures cellular responses and evaluates transfer on held-out samples. <script>window.untrustedExecuted=true</script>',
                      journal='DEMO / TEST FIXTURE',url='https://example.org') for i in range(30)]
    def analyze(paper,config):
        i=int(paper.external_id.split('-')[-1])
        return PaperAnalysis(provider='deepseek',score=[29,25,20,12,8][i%5],tags=['single-cell','transfer learning'],
                             summary='测试文献：比较细胞表征的跨组织迁移与独立样本验证。',why_read='测试依据：可用于比较模型的泛化能力。')
    def model_request(*args,**kwargs):
        counts['model']+=1;time.sleep(.25)
        content=json.loads(kwargs['json']['messages'][1]['content']);sources=content['papers']
        assert 'PRIVATE_NOTE_DO_NOT_SEND' not in json.dumps(content)
        result=sample_result(sources);result['title']='测试想法：将空间上下文与细胞扰动表征相结合'
        idea=result['ideas'][0]
        idea.update(title='空间邻域是否能改善跨组织扰动预测？',question='在组织迁移时，空间邻域信息能否提供可泛化的额外信号？',
                    hypothesis='待验证假设：加入空间邻域表征可能改善留出组织上的预测表现，尚无实验结果支持。',
                    combination='结合两张卡提出的细胞表征与独立样本评价思路，设计跨组织的迁移对照。',
                    experiment='使用公开数据，比较无空间信息基线、随机邻域与真实邻域三组；按组织划分训练与测试集。',
                    evaluation='比较留出组织上的预测相关性与误差。如果真实邻域不优于随机邻域，则不能支持假设。',
                    risks='测试文献摘要不足以证明空间信号具有因果效应；需检查空间数据与扰动数据是否可对齐。',
                    novelty_checks='尚未检索新颖性。后续检索 spatial context、perturbation prediction、cross-tissue transfer，并核对已有基线。')
        return type('Response',(),{'json':lambda self:{'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}]}})()
    try:
        fixture.setUp()
        for source in fixture.config['sources'].values():source['enabled']=False
        fixture.config['sources']['pubmed']['enabled']=True
        fixture.config['run']['min_score']=0
        fixture.config['analysis']['deepseek']['enabled']=True
        port=fixture.start_server()
        with patch('literature_radar.collector.fetch_pubmed',side_effect=fetch),patch('literature_radar.collector.analyze_paper',side_effect=analyze), \
             patch('literature_radar.ideation.get_secret',return_value='test-key'),patch('literature_radar.usage.request',side_effect=model_request):
            result=subprocess.run(['node',str(Path(__file__).with_name('browser_workbench.mjs')),f'http://127.0.0.1:{port}/',str(browser),str(output)],
                                  timeout=90,creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True,text=True,encoding='utf-8')
            print(result.stdout);print(result.stderr)
            # Let an already-started background task settle before deleting the fixture database.
            deadline=time.monotonic()+8
            while any((j:=TaskStore(fixture.store).latest(k)) and j['status']=='running' for k in ['collection','ideas']) and time.monotonic()<deadline:
                time.sleep(.05)
        if result.returncode==0:
            assert counts=={'fetch':1,'model':1},counts
            print('PASS: exactly one publisher collection and one model invocation (both mocked).')
        return result.returncode
    finally:fixture.doCleanups()


if __name__=='__main__':raise SystemExit(main())