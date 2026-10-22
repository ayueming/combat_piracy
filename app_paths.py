# app_paths.py
import os
import sys


def get_app_dir():
    """程序安装目录（打包后=exe所在目录；开发时=源码目录）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_data_root():
    r"""
    获取数据根目录。
    1. 开发环境（PyCharm运行）：项目目录下的 data 文件夹。
    2. 打包后的生产环境：C:\Users\用户名\AppData\Local\CombatPiracy，避免 Program Files 无写入权限的问题。
    """
    if getattr(sys, 'frozen', False):
        # 打包后：使用系统的 LocalAppData 目录
        base_dir = os.getenv('LOCALAPPDATA') or os.path.expanduser('~')
        d = os.path.join(base_dir, "CombatPiracy")
    else:
        # 开发时：使用当前项目目录下的 data 文件夹
        d = os.path.join(get_app_dir(), "data")

    os.makedirs(d, exist_ok=True)
    return d


def get_user_dir(user_id):
    """
    获取指定用户的专属数据目录。
    会自动创建该用户的所有子文件夹（evidences, logs, temp）。
    """
    if not user_id:
        raise ValueError("user_id 不能为空")

    user_dir = os.path.join(get_data_root(), "users", str(user_id))

    # 确保用户的子文件夹都存在
    os.makedirs(os.path.join(user_dir, "evidences"), exist_ok=True)
    os.makedirs(os.path.join(user_dir, "logs"), exist_ok=True)
    os.makedirs(os.path.join(user_dir, "temp"), exist_ok=True)

    return user_dir


def get_session_path():
    """获取当前登录会话（指针）的文件路径"""
    return os.path.join(get_data_root(), "session.json")


# ================= 兼容旧代码的变量和函数 =================
# 提示：这些是过渡期的兼容代码，后续我们会把调用它们的地方改掉。

def get_temp_dir():
    """【兼容旧代码】获取全局临时目录（后续需改为按用户隔离）"""
    d = os.path.join(get_data_root(), "temp")
    os.makedirs(d, exist_ok=True)
    return d


# 注意：这里的 DATA_DIR 现在代表的是“全局数据根目录”，不再是某个用户的业务数据目录！
APP_DIR = get_app_dir()
DATA_DIR = get_data_root()