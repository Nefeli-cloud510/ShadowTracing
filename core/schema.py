from pydantic import BaseModel, Field
from typing import Literal, Optional


class ExperimentConfig(BaseModel):
    """
    Qwen可以调整的实验参数。
    只包含原JSON中Qwen能动的字段。
    """
    window_size: int = Field(
        default=3,
        ge=1, le=196,
        description="滑动窗口天数"
    )
    use_lag_feature: bool = Field(
        default=False,
        description="是否使用时滞特征"
    )
    max_lag_day: int = Field(
        default=3,
        ge=0, le=10,
        description="最大时滞天数"
    )
    alpha: float = Field(
        default=0.5,
        ge=0.0, le=2.0,
        description="ElasticNet正则化强度"
    )
    l1_ratio: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="ElasticNet L1/L2混合比例"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Qwen的调整理由（仅供记录，不参与执行）"
    )