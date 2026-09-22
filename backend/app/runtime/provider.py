from os import getenv

import httpx

from app.common.errors import ApiError


class NodeAgentClient:
    """Node Agent 的受控 RPC 适配器；不暴露 Docker 通用接口。"""

    def __init__(self, agent_url: str, token: str | None = None):
        self.agent_url = agent_url.rstrip("/")
        self.token = token or getenv("YUEKE_NODE_AGENT_TOKEN")

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise ApiError("RUNTIME.PROVIDER_UNAVAILABLE", "节点代理身份凭据未配置", 503)
        return {"Authorization": f"Bearer {self.token}"}

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            async with httpx.AsyncClient(base_url=self.agent_url, timeout=30) as client:
                response = await client.request(method, path, headers=self._headers(), **kwargs)
        except httpx.HTTPError as error:
            raise ApiError("RUNTIME.PROVIDER_UNAVAILABLE", "计算节点代理不可用", 503) from error
        if response.status_code >= 400:
            message = response.json().get("detail", "节点代理拒绝请求") if response.headers.get("content-type", "").startswith("application/json") else "节点代理拒绝请求"
            raise ApiError("RUNTIME.PROVIDER_REJECTED", message, 503, {"provider_status": response.status_code})
        return response.json()

    async def health(self) -> dict:
        return await self._request("GET", "/health")

    async def capacity(self) -> dict:
        return await self._request("GET", "/capacity")

    async def create_group(self, payload: dict) -> dict:
        # 节点代理创建阶段最多 120 秒，失败回滚另有 30 秒共享预算；客户端需覆盖完整边界。
        return await self._request("POST", "/runtime-groups", json=payload, timeout=160)

    async def group(self, provider_group_id: str) -> dict:
        return await self._request("GET", f"/runtime-groups/{provider_group_id}")

    async def destroy(self, provider_group_id: str) -> dict:
        return await self._request("POST", f"/runtime-groups/{provider_group_id}/destroy")

    async def exec(self, provider_group_id: str, payload: dict) -> dict:
        return await self._request("POST", f"/runtime-groups/{provider_group_id}/exec", json=payload)
