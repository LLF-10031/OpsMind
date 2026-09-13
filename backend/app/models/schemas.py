"""项目共享 DTO / schema（约定响应格式）。"""


def ok(data=None):
    return {"success": True, "data": data}


def fail(code: str, message: str):
    return {"success": False, "error": {"code": code, "message": message}}