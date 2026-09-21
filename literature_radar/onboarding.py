"""Shared, workspace-persisted guided tour for every product page."""
import json
from pathlib import Path

def inject(content, config):
    web = config.get('web', {})
    step = web.get('tutorial_step', 0)
    if type(step) is not int or not 0 <= step <= 7:
        step = 0
    state = {'active': bool(web.get('show_onboarding', False)), 'step': step,
             'zh': web.get('language', 'zh-CN') == 'zh-CN'}
    assets = Path(__file__).with_name('assets')
    css = (assets/'onboarding.css').read_text(encoding='utf-8')
    js = (assets/'onboarding.js').read_text(encoding='utf-8')
    content = content.replace('</head>', '<style>'+css+'</style></head>', 1)
    return content.replace('</body>', '<script>window.orbitTourState='+json.dumps(state)+';</script><script>'+js+'</script></body>', 1)
