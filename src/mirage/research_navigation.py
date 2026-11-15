"""Bounded tree navigation; a native form's TypeID is the only arrival proof.

Node anchors observed from natural RectTransform reads on RoK1.1.12.20.
Scrolling is located again through a harmless node preview after every gesture;
GotoRate is deliberately not used as a live scroll offset (it stays zero).
"""
from .workflows import Cancelled, Condition, NotReady, Tap


ECONOMY='ReseachPage_Economy'
MILITARY='ReseachPage_Military'
SCALE=.648
ANCHORS={
    101:(153.4,-9.3),102:(525,87),103:(525,-100.1),104:(895.3,196.1),105:(895.3,-10),106:(895.3,-207.1),
    107:(1268.5,-10),108:(1637.7,196.1),109:(1637.7,-10),110:(1637.7,-207.1),
    111:(2008.9,-10),112:(2008.9,196.1),113:(2008.9,-207.1),114:(2381.2,139.1),
    115:(2743.4,-10),116:(3116.6,87),117:(3116.6,-100.1),118:(3486.9,196.1),
    119:(3486.9,-207.1),120:(3486.9,-10),121:(3860.1,-10),122:(4229.3,196.1),
    123:(4229.3,-207.1),124:(4600.6,196.1),125:(4600.6,-207.1),126:(4600.6,-10),
    127:(4972.8,139.1),128:(5351,-10),
    201:(155.6,-27),202:(528.95,173),203:(528.95,44),204:(528.95,-92),205:(528.95,-225),
    206:(899,173),207:(899,44),208:(899,-92),209:(899,-225),210:(1272,104),211:(1272,-160),
    212:(1641,173),213:(1641,44),214:(1641,-92),215:(1641,-225),216:(2012,173),
    217:(2012,44),218:(2012,-92),219:(2012,-225),220:(2384,-24),221:(2755,118),
    222:(2755,-24),223:(2755,-171),224:(3126,-24),225:(3496,173),226:(3496,44),
    227:(3496,-92),228:(3496,-225),229:(3867,173),230:(3867,44),231:(3867,-92),
    232:(3867,-225),233:(4239,173),234:(4239,44),235:(4239,-92),236:(4239,-225),
    237:(4608,-24),238:(4980,115),239:(4980,-173),240:(5349,173),241:(5349,44),
    242:(5349,-92),243:(5349,-225),
}


def tree_for(kind):
    if kind not in ANCHORS:raise NotReady('Исследования: неизвестный узел обычного дерева')
    return ECONOMY if kind<200 else MILITARY


def open_node(kind,device,observe,execute,permit,tree_condition,panel_condition,cancelled):
    tree=tree_for(kind);state=observe()
    def change(name):
        nonlocal state
        state=execute((Tap(50,130 if name==ECONOMY else 229,tree_condition,
            Condition(('research_ui','tree'),'eq',name),hold_ms=100,settle=.4),))
    # Tabs recreate their viewport at the start; no stale scroll offset is trusted.
    current=state.values.get('research_ui',{}).get('tree')
    if current==tree:change(MILITARY if tree==ECONOMY else ECONOMY)
    change(tree)
    anchor_x,anchor_y=ANCHORS[kind];y=round((287 if tree==ECONOMY else 274)-SCALE*anchor_y)
    class Preview:
        def matches(self,s):return panel_condition.matches(s) or tree_condition.matches(s)
    def preview(x,row_y=y):
        nonlocal state
        permit();state=observe()
        if not tree_condition.matches(state):raise NotReady('Исследования: перед просмотром нужен экран дерева')
        device.tap(round(x),row_y,hold_ms=100)
        if cancelled.wait(.35):raise Cancelled('Исследования отменены')
        permit();state=observe()
        if not Preview().matches(state):raise NotReady('Исследования: неизвестный экран после просмотра узла')
        form=state.values.get('research_form',{})
        if form.get('visible') is not True:return None
        actual=form.get('type')
        if actual==kind:return actual
        state=execute((Tap(818,62,panel_condition,tree_condition,hold_ms=100,settle=.3),))
        return actual
    predicted=54+SCALE*anchor_x;seen={}
    for page in range(18):
        permit()
        if 130<=predicted<=790:
            if preview(predicted)==kind:return state
        located=None
        columns=(394,634,153,224,294,364,434,504,574,644,714,784)
        probes=[(x,y) for x in columns]
        probes.extend((x,row_y) for row_y in (160,235,300,355,420) if abs(row_y-y)>30
            for x in columns)
        for x,row_y in probes:
            actual=preview(x,row_y)
            if actual==kind:return state
            if actual in ANCHORS and tree_for(actual)==tree:
                predicted=x+SCALE*(anchor_x-ANCHORS[actual][0]);located=actual
                if 130<=predicted<=790 and preview(predicted)==kind:return state
                break
        if located is None:raise NotReady('Исследования: положение прокрученного дерева не определено')
        signature=(located,round(predicted/10))
        seen[signature]=seen.get(signature,0)+1
        if seen[signature]>2:raise NotReady('Исследования: прокрутка не продвигается к выбранному узлу')
        delta=max(-500,min(500,round(394-predicted)))
        if abs(delta)<100:delta=-180 if predicted>394 else 180
        start=760 if delta<0 else 200
        permit();device.drag(start,480,start+delta,480)
        if cancelled.wait(.5):
            raise Cancelled('Исследования отменены')
        # The next preview re-locates the viewport; gesture distance is never proof.
        state=observe()
        if not tree_condition.matches(state):raise NotReady('Исследования: дерево изменилось при прокрутке')
        predicted=-1
    raise NotReady('Исследования: исчерпан ограниченный поиск узла')
