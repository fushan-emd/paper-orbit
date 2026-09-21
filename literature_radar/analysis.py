from __future__ import annotations

import re

from literature_radar.models import Paper, PaperAnalysis
from literature_radar.text import clean_text, first_sentence
from literature_radar.deepseek import enrich_with_deepseek


METHOD_PATTERNS = [
    "foundation model",
    "large language model",
    "transformer",
    "graph neural network",
    "variational autoencoder",
    "diffusion",
    "contrastive learning",
    "deep learning",
    "machine learning",
    "benchmark",
    "software",
    "tool",
    "pipeline",
    "package",
]

DATA_TASK_PATTERNS = [
    "single-cell",
    "single cell",
    "scrna-seq",
    "snrna-seq",
    "spatial transcriptomics",
    "spatial omics",
    "cell type annotation",
    "trajectory inference",
    "batch correction",
    "integration",
    "perturbation",
    "gene regulatory network",
    "multi-omics",
    "atlas",
]


def analyze_paper(paper: Paper, config: dict) -> PaperAnalysis:
    text = f"{paper.title}\n{paper.abstract}".lower()
    exclude_keywords = [item.lower() for item in config["profile"].get("exclude_keywords", [])]
    if any(keyword in text for keyword in exclude_keywords):
        return PaperAnalysis(score=0, tags=["excluded"], summary="Filtered by exclusion keyword.")

    weights = {key.lower(): int(value) for key, value in config.get("weights", {}).items()}
    core_keywords = {key.lower() for key in config["profile"].get("core_keywords", [])}
    core_matched = {keyword for keyword in core_keywords if keyword in text}
    tags = []
    score = 0
    for keyword, weight in weights.items():
        if keyword not in core_keywords and not core_matched:
            continue
        if keyword in text:
            tags.append(keyword)
            score += weight

    title_bonus = _title_bonus(paper.title, weights, core_keywords, core_matched)
    score += title_bonus

    method_clues = _collect_patterns(text, METHOD_PATTERNS)
    data_task_clues = _collect_patterns(text, DATA_TASK_PATTERNS)
    summary = first_sentence(paper.abstract) or first_sentence(paper.title)
    detailed_summary = _detailed_summary(paper)
    method_flow = _method_flow(method_clues, data_task_clues)
    follow_up_prompts = _follow_up_prompts(tags, method_clues, data_task_clues)

    if score >= 18:
        why_read = "High priority: closely matches the single-cell/spatial/virtual-cell/model/tool profile."
        evaluation = "A 级：优先精读。它很可能包含与你方向直接相关的数据、任务或方法，可以进入文献笔记库。"
    elif score >= 10:
        why_read = "Worth scanning: several profile keywords matched and may contain useful methods or datasets."
        evaluation = "B 级：建议快速读摘要、图 1 和方法部分。如果方法可复用，再做精读。"
    elif score > 0:
        why_read = "Low-to-medium priority: relevant keyword match, but likely needs manual triage."
        evaluation = "C 级：先略读。除非与你当前课题或数据集直接相关，否则不必投入太多时间。"
    else:
        why_read = "No strong profile match."
        evaluation = "D 级：当前配置下相关性较弱。"

    analysis = PaperAnalysis(
        score=score,
        tags=sorted(set(tags)),
        summary=summary,
        detailed_summary=detailed_summary,
        method_clues=method_clues,
        data_task_clues=data_task_clues,
        method_flow=method_flow,
        follow_up_prompts=follow_up_prompts,
        evaluation=evaluation,
        why_read=why_read,
    )
    if config.get("analysis", {}).get("mode") == "deepseek":
        return enrich_with_deepseek(paper, analysis, config)
    return analysis


def _title_bonus(
    title: str,
    weights: dict[str, int],
    core_keywords: set[str],
    core_matched: set[str],
) -> int:
    lowered = title.lower()
    bonus = 0
    for keyword, weight in weights.items():
        if keyword not in core_keywords and not core_matched:
            continue
        if keyword in lowered:
            bonus += max(1, weight // 2)
    return bonus


def _collect_patterns(text: str, patterns: list[str]) -> list[str]:
    found = []
    for pattern in patterns:
        normalized = pattern.lower()
        if re.search(rf"\b{re.escape(normalized)}\b", text):
            found.append(pattern)
    return sorted(set(found))


def _detailed_summary(paper: Paper) -> str:
    abstract = clean_text(paper.abstract)
    if not abstract:
        return "没有可用摘要，建议打开原文页面确认研究问题、数据类型和方法细节。"
    if len(abstract) <= 900:
        return abstract
    return abstract[:897].rstrip() + "..."


def _method_flow(method_clues: list[str], data_task_clues: list[str]) -> list[str]:
    flow = []
    if data_task_clues:
        flow.append(f"输入/对象：关注 {', '.join(data_task_clues[:5])} 相关数据或任务。")
    else:
        flow.append("输入/对象：从标题和摘要中暂未识别到明确的数据类型，需要看全文确认。")

    if method_clues:
        flow.append(f"核心方法：摘要中出现 {', '.join(method_clues[:5])} 等方法或工具线索。")
    else:
        flow.append("核心方法：摘要中未出现明显模型名或工具名，建议优先检查 Methods 和 GitHub/Software availability。")

    flow.append("验证方式：重点看 benchmark、消融实验、跨数据集泛化、与现有工具对比以及生物学可解释性。")
    flow.append("可复用性：确认代码、模型权重、数据下载链接、输入格式和运行成本。")
    return flow


def _follow_up_prompts(tags: list[str], method_clues: list[str], data_task_clues: list[str]) -> list[str]:
    prompts = [
        "这篇文章解决的问题是否是单细胞/空间组学分析中的真实痛点，还是只是在常见数据集上做增量改进？",
        "如果要复现，最小输入数据、依赖环境、训练/推理成本分别是什么？",
        "它相比 Seurat、Scanpy、cell2location、Tangram、scVI/scANVI、现有 foundation model 或同类工具的优势在哪里？",
    ]
    if any("spatial" in item for item in tags + data_task_clues):
        prompts.append("空间信息是如何建模的：邻域图、坐标、图神经网络、图像特征，还是纯表达矩阵？")
    if any("foundation model" in item or "transformer" in item for item in tags + method_clues):
        prompts.append("模型是否有跨组织、跨物种、跨平台泛化能力，预训练语料和 token 设计是否合理？")
    if any("single" in item or "scrna" in item for item in tags + data_task_clues):
        prompts.append("单细胞分析部分是否处理了 batch effect、稀疏性、细胞类型标注和亚群解释问题？")
    return prompts[:6]
