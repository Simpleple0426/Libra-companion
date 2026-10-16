"""Executable office rooms from the user-confirmed office inventory."""
from copy import deepcopy

ROOMS={'office':'左然办公室','reception':'前台与接待区','open_office':'公共办公区',
       'zhai_office':'翟星办公室','meeting':'会议室','consultation':'客户会谈室',
       'archive':'档案室','pantry':'茶水间','washroom':'卫生间'}
EQUIPMENT={'office':['办公桌','工作椅','访客椅','电脑','显示器','键盘','鼠标','台灯','电话','充电器',
    '待处理文件托盘','处理中文件托盘','已处理文件托盘','可上锁文件柜','书架','笔记本','笔','便签','文件夹','水杯','衣帽架','咖啡机','窗户','窗帘'],
    'pantry':['饮水机','电热水壶','冰箱','微波炉','咖啡机','茶具','橱柜','水槽','清洁用品','小桌','座椅','垃圾桶']}


def configured(base):
    config=deepcopy(base)
    source='docs/character/左然律所空间与物品清单.md; user-authorized office work skill'
    config['places'].setdefault('firm',{'name':'忒弥斯律所','parent':None,'status':'confirmed','source':source})
    edges=config['household_world']['edges'];existing={frozenset(x) for x in edges}
    for key,name in ROOMS.items():
        ident='firm.'+key
        config['places'].setdefault(ident,{'name':name,'parent':'firm','status':'confirmed','source':source})
        if frozenset(('firm',ident)) not in existing:edges.append(['firm',ident])
        config.setdefault('edge_seconds',{})['|'.join(sorted(('firm',ident)))]=30
    for room,names in EQUIPMENT.items():
        for i,name in enumerate(names):
            config['objects'].setdefault('firm-object:'+room+':'+str(i),
                {'name':name,'parent':'firm.'+room,'status':'confirmed','source':source})
    config['work_skill']={'version':1,'timing':'simulated indoor passage 30 seconds per edge',
                          'source':source,'network':'ThemisLaw-Office'}
    return config
