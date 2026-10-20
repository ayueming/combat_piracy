import re


def get_platform_category(url):
    """
    根据链接自动识别平台分类。
    识别不到则返回空字符串。
    """
    url = url.lower()

    if "pan.baidu.com" in url:
        return "百度网盘"
    elif "zhidao.baidu.com" in url:
        return "百度知道"
    elif "tieba.baidu.com" in url:
        return "百度贴吧"
    elif "pan.quark.cn" in url:
        return "夸克网盘"
    elif "drive.uc.cn" in url:
        return "uc网盘"
    elif "aliyundrive.com" in url or "alipan.com" in url:
        return "阿里网盘"  # 如果你之后加了这个按钮
    elif "baidu.com" in url:
        return "百度搜索"
    elif "quark.cn" in url:
        return "夸克搜索"

    return ""


def extract_pure_feature(url):
    """
    智能提取纯净的特征码。
    """
    url = url.strip()

    if url.startswith("1http"):
        url = url[1:]
    elif url.startswith("1") and len(url) > 20 and not url.startswith("http"):
        url = url[1:]

    code = ""

    baidu_match = re.search(r'(?:pan\.baidu\.com/s/|surl=)([a-zA-Z0-9_-]+)', url)
    if baidu_match:
        code = baidu_match.group(1)
    else:
        quark_match = re.search(r'pan\.quark\.cn/s/([a-zA-Z0-9]+)', url)
        if quark_match:
            code = quark_match.group(1)
        else:
            zhidao_match = re.search(r'zhidao\.baidu\.com/question/(\d+)', url)
            if zhidao_match:
                code = zhidao_match.group(1)
            else:
                tieba_match = re.search(r'tieba\.baidu\.com/p/(\d+)', url)
                if tieba_match:
                    code = tieba_match.group(1)
                else:
                    uc_match = re.search(r'drive\.uc\.cn/s/([a-zA-Z0-9]+)', url)
                    if uc_match:
                        code = uc_match.group(1)
                    else:
                        code = url

    if code.startswith('1') and len(code) >= 20:
        code = code[1:]

    return code