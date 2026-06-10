"""
修复现有数据文件中的错误 URL
- GDGPO: articleDetail?noticeId= → noticeGd?id=
- 执行: python scripts/fix_data_urls.py
"""
import json
import os
import re
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

def fix_gdgpo_url(url: str) -> str:
    """修复 GDGPO 详情 URL: articleDetail?noticeId= → noticeGd?id="""
    if not url or 'gdgpo.czt.gd.gov.cn' not in url:
        return url
    # 旧格式: /maincms-web/articleDetail?noticeId=xxx
    # 新格式: /maincms-web/noticeGd?id=xxx
    old_pattern = r'/maincms-web/articleDetail\?noticeId='
    new_url = re.sub(old_pattern, '/maincms-web/noticeGd?id=', url)
    if new_url != url:
        return new_url
    return url

def fix_procurements():
    """修复 procurements.json"""
    path = os.path.join(DATA_DIR, 'procurements.json')
    if not os.path.exists(path):
        print(f"[跳过] {path} 不存在")
        return

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    fixed_count = 0
    for item in data:
        old_url = item.get('url', '')
        new_url = fix_gdgpo_url(old_url)
        if new_url != old_url:
            item['url'] = new_url
            fixed_count += 1

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[procurements.json] 共 {len(data)} 条, 修复 URL {fixed_count} 条")

def fix_search_index():
    """修复 search-index.json"""
    path = os.path.join(DATA_DIR, 'search-index.json')
    if not os.path.exists(path):
        print(f"[跳过] {path} 不存在")
        return

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    fixed_count = 0
    for item in data:
        old_url = item.get('url', '')
        new_url = fix_gdgpo_url(old_url)
        if new_url != old_url:
            item['url'] = new_url
            fixed_count += 1

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[search-index.json] 共 {len(data)} 条, 修复 URL {fixed_count} 条")

if __name__ == '__main__':
    print(f"=== 数据 URL 修复工具 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据目录: {os.path.abspath(DATA_DIR)}")
    print()
    fix_procurements()
    fix_search_index()
    print("\n完成!")
