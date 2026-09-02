import tempfile
import unittest
from pathlib import Path

from pydantic import BaseModel, Field

from core.llm_gateway import LLMGateway
from core.rag_service import RAGService
from core.runtime_config import (
    get_bailian_knowledge_agent_id,
    get_bailian_workspace_id,
    get_dasyscope_api_key,
    get_knowledge_search_endpoint,
    real_api_tests_enabled,
)


class SimpleStructuredResponse(BaseModel):
    answer: str = Field(min_length=1)


@unittest.skipUnless(real_api_tests_enabled(), "未启用真实 API 可选测试")
class RealAPIOptionalIntegrationTest(unittest.TestCase):
    def test_real_bailian_model_structured_output(self) -> None:
        if not get_dasyscope_api_key():
            self.skipTest("未配置 DASHSCOPE_API_KEY / BAILIAN_API_KEY")

        gateway = LLMGateway()
        self.assertTrue(gateway.is_available())
        response = gateway.generate_structured(
            system_prompt="你是一个只输出 JSON 的助手。",
            user_prompt='请严格输出 {"answer":"ok"}',
            response_model=SimpleStructuredResponse,
        )
        self.assertTrue(response.answer)

    def test_real_knowledge_base_search_if_configured(self) -> None:
        if not get_dasyscope_api_key():
            self.skipTest("未配置 DASHSCOPE_API_KEY / BAILIAN_API_KEY")
        if not get_bailian_knowledge_agent_id():
            self.skipTest("未配置 BAILIAN_KNOWLEDGE_AGENT_ID")
        if not (get_bailian_workspace_id() or get_knowledge_search_endpoint()):
            self.skipTest("未配置 BAILIAN_WORKSPACE_ID 或 BAILIAN_KNOWLEDGE_SEARCH_ENDPOINT")

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            rag_service = RAGService(project_root=project_root)
            results = rag_service.search_bailian_knowledge_base("DeltaDec Vsw By", max_results=2)
            self.assertIsInstance(results, list)
            self.assertLessEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
