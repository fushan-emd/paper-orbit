"""Local maintenance page, served through the same protected session."""
from html import escape
from pathlib import Path
from literature_radar.backup import list_backups
from literature_radar.usage import usage_summary
from literature_radar.workflows import TaskStore

def page(root,config,store,message=''):
    options=''.join('<option>'+escape(item['name'])+'</option>' for item in list_backups(root/'backups'))
    jobs=TaskStore(store).history('collection',5)+TaskStore(store).history('ideas',10)
    rows=''
    for job in sorted(jobs,key=lambda j:j['started'],reverse=True):
        rows+='<tr><td>'+escape(job['kind'])+'</td><td>'+escape(job['status'])+(' · 取消已请求' if job.get('cancel_requested') else '')+'</td><td>'+escape((job['log'] or [''])[ -1])+'</td><td>'
        if job['status']=='running':rows+='<form method="post" action="/manage/cancel"><input type="hidden" name="id" value="'+escape(job['id'])+'"><button>取消任务</button></form>'
        rows+='</td></tr>'
    css=(Path(__file__).with_name('assets')/'library.css').read_text(encoding='utf-8')
    usage=usage_summary({**config,'_workspace_root':str(root)})
    counts=''.join('<tr>'+''.join('<td>'+escape(str(row[k]))+'</td>' for k in ['day','calls','input_tokens','output_tokens','uncertain_calls'])+'</tr>' for row in usage)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Paper Orbit · 数据与任务</title><style>{css}table{{width:100%;text-align:left;font-size:12px;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}}.manage-panel{{margin:20px 0}}.manage-actions{{display:flex;gap:12px;flex-wrap:wrap}}.manage-panel form{{margin:15px 0}}.manage-panel p{{margin:12px 0}}.manage-panel select,.manage-panel input{{max-width:600px}}.table-scroll{{overflow:auto}}</style></head><body><main class="shell">
    <header class="workspace-header"><a class="orbit-brand" href="/discover">✧ PAPER ORBIT</a><nav class="orbit-nav"><a href="/discover">抽卡</a><a href="/">文献库</a><a class="active" href="/manage">数据与任务</a></nav></header>
    <section class="panel manage-panel"><h1>数据与任务</h1><p role="status">{escape(message)}</p><p class="muted">数据目录：{escape(str(root))}</p><p>备份包含文献、私人笔记、仓库和想法。请妥善保管。密钥不包含在备份与导出中。</p><div class="manage-actions"><form method="post" action="/manage/backup"><button>创建数据库备份</button></form><a class="button ghost" href="/api/export">导出全部文献与笔记 JSON</a></div>
    <form method="post" action="/manage/restore"><label>选择本机备份</label><select name="backup">{options}</select><p>恢复会替换当前数据库；恢复前会再备份当前数据。请先完成或取消所有任务。配置与 API 密钥不变。</p><label>输入 RESTORE 确认恢复</label><input name="confirmation" required pattern="RESTORE" autocomplete="off"><button>恢复所选备份</button></form></section>
    <section class="panel manage-panel"><h2>任务状态</h2><p class="muted">取消会在当前网络请求结束后生效；已入库文献保留。已发送的 AI 请求可能仍计费。关闭软件不会自动续跑任务。</p><div class="table-scroll"><table><thead><tr><th>任务</th><th>状态</th><th>最近进度</th><th>操作</th></tr></thead><tbody>{rows}</tbody></table></div><p><a href="/manage">刷新状态</a></p></section>
    <section class="panel manage-panel"><h2>AI 用量与上限</h2><p>当前每日上限：{int(config.get('budget',{}).get('daily_call_limit',100))} 次请求 / {int(config.get('budget',{}).get('daily_token_limit',500000))} tokens。失败且用量未知的请求按预留额度计入预算，不代表已经产生同等费用。实际费用以服务商账单为准。</p><div class="table-scroll"><table><thead><tr><th>日期</th><th>请求数</th><th>输入 tokens</th><th>输出 tokens</th><th>用量未确认</th></tr></thead><tbody>{counts}</tbody></table></div></section>
    <section class="panel manage-panel"><h2>隐私与内容边界</h2><p>配置 AI 后，分析会发送文献标题与摘要；组合生成还会发送你输入的研究问题。私人笔记不发送。高评级仅表示阅读优先级，AI 想法需要实验与查新验证。</p><p><a href="/policy/privacy">隐私说明</a> · <a href="/policy/license">MIT 许可证</a> · <a href="/policy/notices">第三方许可</a></p></section>
    </main><script>try{{document.documentElement.dataset.theme=localStorage.getItem('literature-radar-theme')||'dark'}}catch(e){{}}</script></body></html>'''
