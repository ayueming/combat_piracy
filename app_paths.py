# app_paths.py
import os
import sys

def get_app_dir():
    """程序安装目录（打包后=exe所在目录；开发时=源码目录）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_user_data_dir():
    """用户数据目录（数据库、登录态、证据文件放这）"""
    # 打包后放在安装目录下的 data/ 里，最省事，也便于整体备份
    d = os.path.join(get_app_dir(), "data")
    os.makedirs(d, exist_ok=True)
    return d

def get_temp_dir():
    d = os.path.join(get_user_data_dir(), "temp")
    os.makedirs(d, exist_ok=True)
    return d

APP_DIR = get_app_dir()
DATA_DIR = get_user_data_dir()