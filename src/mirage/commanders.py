"""Owned commander names and exact two-slot identities, independent of UI order."""
from copy import deepcopy


def hero_ids(value):
    if not isinstance(value,dict) or set(value) not in ({'1'},{'1','2'}):return None
    if any(type(item) is not int or not 1<=item<=1000000 for item in value.values()):return None
    if len(set(value.values()))!=len(value):return None
    return dict(value)


def troop_heroes(troop):
    rows=troop.get('heros') if isinstance(troop,dict) else None
    if not isinstance(rows,dict) or not 1<=len(rows)<=2:return None
    result={}
    for row in rows.values():
        if not isinstance(row,dict) or type(row.get('label')) is not int:return None
        key=str(row['label'])
        if key in result:return None
        result[key]=row.get('heroId')
    return hero_ids(result)


def selected_heroes(state):
    hero=state.values.get('barbarian_hero')
    if not isinstance(hero,dict):return None
    return hero_ids(hero.get('selectedHeroes',{'1':hero.get('Id')}))


def normalize_catalog(value,player=None):
    if (not isinstance(value,dict) or value.get('ready') is not True
            or type(value.get('player')) is not int or value['player']<=0
            or player is not None and value['player']!=player
            or not isinstance(value.get('heroes'),dict) or len(value['heroes'])>256):return None
    heroes={}
    for key,row in value['heroes'].items():
        if (not isinstance(row,dict) or type(row.get('id')) is not int or not 1<=row['id']<=1000000
                or str(row['id'])!=key or not isinstance(row.get('name'),str) or not 1<=len(row['name'])<=160
                or type(row.get('level')) is not int or not 1<=row['level']<=100
                or type(row.get('star')) is not int or not 1<=row['star']<=10):return None
        heroes[key]=deepcopy(row)
    return {'ready':True,'player':value['player'],'heroes':heroes}


def commander_catalog(store,instance_id,snapshot=None):
    key='commander-roster:'+instance_id
    if snapshot is not None:
        value=normalize_catalog(snapshot.values.get('player',{}).get('_commanders'),snapshot.player_id)
        if value is not None:
            if store.preference(key)!=value:store.set_preference(key,value)
            return value
    saved=store.preference(key)
    if snapshot is not None and isinstance(saved,dict) and saved.get('player')!=snapshot.player_id:
        store.set_preference(key,None);saved=None
    cached=normalize_catalog(saved,snapshot.player_id if snapshot is not None else None)
    return cached or {'ready':False,'player':None,'heroes':{}}


def commander_name(id,catalog):
    if not id:return 'Без второго командира'
    row=catalog.get('heroes',{}).get(str(id),{})
    return row.get('name') or ('Сунь-цзы' if id==3 else 'Командир №'+str(id))


def set_commander(settings,slot,id):
    if slot not in ('primary','deputy'):raise ValueError('Неизвестный слот командира')
    if type(id) is not int or not (1 if slot=='primary' else 0)<=id<=1000000:
        raise ValueError('Некорректный командир')
    if slot=='deputy' and id and id==settings.get('primary',3):
        raise ValueError('Основной и второй командиры должны различаться')
    settings[slot]=id
    if slot=='primary' and settings.get('deputy',0)==id:settings['deputy']=0
