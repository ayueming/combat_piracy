## 本地开发

本项目包含一套 Supabase 登录/授权系统，**仅用于发布的 exe**。

源码运行时，只要在 `config_local.py` 里设置 `DEV_MODE = True`，
即可跳过登录，直接进入主界面，方便开发和调试。

打包 exe 时，登录校验会自动强制开启（无法通过配置绕过）。

如果你需要测试登录流程，请自行创建一个 Supabase 项目，
并参考 docs/supabase_setup.md 完成配置。