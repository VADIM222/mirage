from types import SimpleNamespace
import threading

import pytest

from mirage.research import ResearchPanel, ResearchTree
from mirage.research_navigation import ANCHORS, ECONOMY, MILITARY, SCALE, open_node, tree_for
from mirage.workflows import Cancelled, NotReady


class Stop(threading.Event):
    def wait(self,timeout=None):return self.is_set()


class TreeGame:
    def __init__(self):
        self.tree=ECONOMY;self.offset=1900;self.form=None;self.inputs=[];self.stop=Stop()

    def observe(self):
        return SimpleNamespace(values={'in_city':True,'views':{self.tree:True},
            'research_ui':{'tree':self.tree,'offset':0},
            'research_form':{'visible':self.form is not None,'type':self.form}})

    def execute(self,steps):
        for step in steps:
            self.permit();self.inputs.append((step.x,step.y))
            if step.x==50:
                self.tree=ECONOMY if step.y==130 else MILITARY;self.offset=0
            elif (step.x,step.y)==(818,62):self.form=None
            else:
                assert self.form is None, 'A preview must be closed before another tree input'
                for kind,(x,y) in ANCHORS.items():
                    if tree_for(kind)!=self.tree:continue
                    sy=(287 if self.tree==ECONOMY else 274)-SCALE*y
                    if abs(step.x-(54+SCALE*x-self.offset))<43 and abs(step.y-sy)<30:
                        self.form=kind;break
        return self.observe()

    def drag(self,x,y,ex,ey):
        assert self.form is None
        self.inputs.append(('drag',x,y,ex,ey))
        # The game does not move by the requested distance; overshoot varies.
        self.offset=max(0,min(2850,self.offset+(x-ex)*1.31))

    def tap(self,x,y,**kwargs):
        self.execute((SimpleNamespace(x=x,y=y),))

    def permit(self):
        if self.stop.is_set():raise Cancelled('stop')

    def run(self,kind):
        return open_node(kind,self,self.observe,self.execute,self.permit,ResearchTree(),ResearchPanel(),self.stop)


@pytest.mark.parametrize('kind',[101,107,128,201,224,243])
def test_native_preview_relocates_after_nonuniform_scroll_and_finds_exact_node(kind):
    game=TreeGame();state=game.run(kind)
    assert state.values['research_form']['type']==kind
    assert (737,400) not in game.inputs
    assert len(game.inputs)<100


def test_stop_prevents_next_scroll_or_preview_and_resume_restarts_viewport():
    game=TreeGame();game.stop.set()
    with pytest.raises(Cancelled):game.run(243)
    assert game.inputs==[]
    game.stop.clear();assert game.run(243).values['research_form']['type']==243


def test_unknown_technology_is_rejected_before_any_input():
    game=TreeGame()
    with pytest.raises(NotReady):game.run(9999)
    assert not game.inputs
