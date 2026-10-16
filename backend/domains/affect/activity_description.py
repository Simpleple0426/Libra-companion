"""Use a stable subject in event descriptions without rewriting timeline rows."""


def activity_description(description, nickname=''):
    text = str(description).strip()
    names = sorted({nickname.strip(), 'simple', '我', '用户'} - {''}, key=len, reverse=True)
    for name in names:
        if text.startswith(name):
            text = '用户' + text[len(name):]
            break
    else:
        if text.startswith(('开始学习', '结束学习', '正在', '离开了', '手机开始充电',
                            '手机结束充电', '完成了打卡', '添加了待办', '完成了待办')):
            text = '用户' + text
    return '用户生活动态报告：' + text
