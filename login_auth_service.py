def login(email: str, password: str, invite_code: str = "") -> dict:
    try:
        resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        return {"ok": False, "reason": f"登录失败：{e}"}

    device_id = get_machine_id()
    try:
        # 把邀请码传给 Edge Function
        r = supabase.functions.invoke(
            "verify-license",
            invoke_options={"body": {"device_id": device_id, "invite_code": invite_code}},
        )
        result = r
    except Exception as e:
        return {"ok": False, "reason": f"授权校验失败：{e}"}

    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "need_invite_code":
            return {"ok": False, "reason": "该账号未激活，请输入邀请码。", "need_code": True}
        elif reason == "invalid_code":
            return {"ok": False, "reason": "邀请码无效或已被使用，请检查后重试。", "need_code": True}
        # ... (其他拦截提示同前)

    return {"ok": True, "plan": result.get("plan")}