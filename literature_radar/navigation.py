"""One navigation structure across discovery, library, settings and management."""
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

def inject(content, path, lang):
    zh = lang == 'zh-CN'
    url = urlsplit(path)
    discovery = url.path == '/discover'
    settings = url.path == '/' and 'settings' in parse_qs(url.query)
    current = 'discover' if discovery else 'manage' if url.path.startswith('/manage') else 'settings' if settings else 'library'
    names = ['灵感抽卡','卡牌仓库','科研想法','文献库','数据与任务'] if zh else ['Discover','Warehouse','Idea lab','Library','Data & tasks']
    tabs = [('discover','/discover'),('warehouse','/discover#warehouse'),('lab','/discover#lab'),('library','/#library'),('manage','/manage')]
    links = ''.join('<a href="'+href+'" data-nav="'+key+'"'+(' class="active" aria-current="page"' if current==key else '')+'>'+label+'</a>' for (key,href),label in zip(tabs,names))
    theme_id = 'theme-switch' if discovery else 'theme-toggle'
    theme_click = '' if discovery else " onclick=\"const t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;this.setAttribute('aria-pressed',String(t==='light'));try{localStorage.setItem('literature-radar-theme',t)}catch(e){}\""
    header = '<header class="orbit-global-header"><a class="orbit-global-brand" href="/discover"><span aria-hidden="true">✧</span><span>PAPER <b>ORBIT</b><small>'+('你的本地科研工作区' if zh else 'YOUR LOCAL RESEARCH WORKSPACE')+'</small></span></a><div class="orbit-global-tools"><button type="button" id="open-tutorial" title="'+('新手教程' if zh else 'Getting started')+'" aria-label="'+('新手教程' if zh else 'Getting started')+'">?</button><button type="button" id="'+theme_id+'" aria-label="'+('切换主题' if zh else 'Switch theme')+'" aria-pressed="false"'+theme_click+'>◐</button><a href="/?settings=1"'+(' aria-current="page"' if settings else '')+'>'+('设置' if zh else 'Settings')+'</a></div><nav class="orbit-global-nav main-nav orbit-nav" aria-label="'+('主导航' if zh else 'Main navigation')+'">'+links+'</nav></header>'
    content = re.sub(r'<header class="(?:masthead|workspace-header)">.*?</header>', lambda _:header, content, count=1, flags=re.S)
    css = (Path(__file__).with_name('assets')/'navigation.css').read_text(encoding='utf-8')
    return content.replace('</head>','<style>'+css+'</style></head>',1)
