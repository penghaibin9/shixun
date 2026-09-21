from os import getenv

import httpx

from app.common.errors import ApiError


class LabCatalogClient:
    """只通过 C 线冻结接口读取不可变版本，禁止跨域 SQL。"""

    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = base_url or getenv("YUEKE_LAB_CATALOG_URL")
        self.token = token or getenv("YUEKE_LAB_CATALOG_TOKEN")

    async def frozen_version(self, version_id: str, course_id: str | None = None) -> dict:
        if not self.base_url or not self.token:
            raise ApiError("RUNTIME.CATALOG_UNAVAILABLE", "实验定义服务未配置，运行请求保持待处理", 503)
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=5) as client:
                response = await client.get(
                    f"/api/v1/lab-versions/{version_id}/export.json",
                    headers={
                        "Authorization": f"Bearer {self.token}", "X-Service-Name": "lab-runtime",
                        "X-User-Id": "service_lab_runtime", "X-Role": "admin", "X-Permissions": "labs.read",
                        "X-Course-Ids": course_id or "",
                    },
                )
        except httpx.HTTPError as error:
            raise ApiError("RUNTIME.CATALOG_UNAVAILABLE", "实验定义服务暂时不可用", 503) from error
        if response.status_code != 200:
            raise ApiError("RUNTIME.LAB_VERSION_UNAVAILABLE", "实验版本不存在或尚未发布", 422, {"status_code": response.status_code})
        return response.json()
