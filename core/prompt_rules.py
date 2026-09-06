"""Shared constraints injected into scientific LLM role prompts."""

ELASTIC_NET_EXECUTION_RULE = (
    "本项目当前采用机器学习弹性回归（Elastic Net）开展实验，"
    "可调项包括 `alpha`、`l1_ratio`、特征组合、历史滞后窗口与预测超前窗口等。"
    "你生成的所有假设、质询、不确定性、候选实验与结果解释，"
    "必须只基于数据变量库中的真实物理量，"
    "并能被当前弹性回归流程实际执行、量化和比较（Pearson_r / RMSE）；"
    "必须符合物理规律，禁止发明变量、虚构数据来源或设计当前流程无法验证的机制。"
)
