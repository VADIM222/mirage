from copy import deepcopy
from dataclasses import replace

import pytest
from PySide6.QtCore import QModelIndex, Qt

from mirage.model import RESEARCH_TYPES, ResearchOptions, research_default_order
from mirage.research import candidate, research_goal, research_workflow
from mirage.research_priority_ui import PriorityModel, ResearchPriorityEditor
from mirage.workflows import Cancelled, Engine
from test_research import Route, state


def multiple_technologies():
    s=state();base=s.values['research_plan']['rows']['103']
    for kind in (101,102,201,202,203):
        cfg=deepcopy(base);cfg.update(ID=kind*100+1,Type=kind)
        s.values['research_plan']['rows'][str(kind)]=cfg
    return s


def test_branch_modes_include_the_entire_correct_tree_and_custom_contains_both():
    economy=ResearchOptions.from_settings({'priority_mode':'economy'})
    military=ResearchOptions.from_settings({'priority_mode':'military'})
    custom=ResearchOptions.from_settings({'priority_mode':'custom'})
    assert len(economy.types)==28 and all(k<200 for k in economy.types)
    assert len(military.types)==43 and all(k>=200 for k in military.types)
    assert set(custom.types)==set(RESEARCH_TYPES) and len(custom.types)==71
    assert economy.auto_prerequisites and military.auto_prerequisites
    assert ResearchOptions.from_settings({}).priority_mode=='economy'


def test_old_selection_migrates_to_custom_priority_without_losing_or_disabling_technologies():
    options=ResearchOptions.from_settings({'types':[103,101]})
    assert options.priority_mode=='custom' and options.types[:2]==(103,101)
    assert len(options.types)==71 and set(options.types)==set(RESEARCH_TYPES)
    assert ResearchOptions.from_settings({'types':[]}).priority_mode=='economy'


@pytest.mark.parametrize('fault',['duplicate','missing','foreign','wrong_branch','unknown_mode'])
def test_priority_tables_validate_membership_before_any_profile_write(fault):
    order=list(research_default_order('economy'));settings={'priority_mode':'economy','priority_orders':{'economy':order}}
    if fault=='duplicate':order[1]=order[0]
    elif fault=='missing':order.pop()
    elif fault=='foreign':order[0]=999
    elif fault=='wrong_branch':order[0]=201
    else:settings['priority_mode']='other'
    with pytest.raises(ValueError):ResearchOptions.from_settings(settings)


def test_priority_drives_real_candidate_and_keeps_native_prerequisites_ahead_of_its_goal():
    s=multiple_technologies();order=list(research_default_order('economy'));order.remove(103);order.insert(0,103)
    options=ResearchOptions.from_settings({'priority_mode':'economy','priority_orders':{'economy':order}})
    assert candidate(s,options)['Type']==103
    s.values['research_plan']['rows']['103'].update(PreType1=102,PreLevel1=1)
    assert research_goal(s,options)['Type']==102 and candidate(s,options)['Type']==102
    s.values['research_plan']['rows']['102']['Food']=100000
    assert candidate(s,options)['Type']==101  # An unavailable high priority does not block affordable work.


def test_balanced_switches_the_preferred_branch_and_falls_back_when_it_is_unavailable():
    s=multiple_technologies();options=ResearchOptions.from_settings({'priority_mode':'balanced'})
    assert candidate(s,options)['Type']==101
    assert candidate(s,replace(options,next_branch='military'))['Type']==201
    for kind in (201,202,203):s.values['research_plan']['rows'][str(kind)]['Food']=100000
    assert candidate(s,replace(options,next_branch='military'))['Type']==101


def test_balanced_recovers_the_next_branch_after_stop_immediately_after_server_commit():
    game=Route();game.stop=True
    def run():
        return Engine(game,game.observe,clock=lambda:game.now,resolution=(960,540)).execute(
            research_workflow({'priority_mode':'balanced','max_level':1},verified=True),game.cancelled,
            instance_id='one',pid=10,player_id=20)
    with pytest.raises(Cancelled):run()
    game.cancelled.clear();game.stop=False;after=run()
    assert after.values['research_next_branch']=='military'
    assert game.inputs.count((737,400))==1


def test_internal_drag_moves_one_row_without_duplicates_and_rejects_foreign_model(qapp):
    model=PriorityModel(research_default_order('economy'));before=tuple(model.order)
    mime=model.mimeData([model.index(5,c) for c in range(3)])
    assert model.dropMimeData(mime,Qt.DropAction.MoveAction,0,0,QModelIndex())
    assert model.order[0]==before[5] and len(model.order)==28 and set(model.order)==set(before)
    assert model.data(model.index(0,0))=='1' and model.data(model.index(1,0))=='2'
    other=PriorityModel(before)
    assert not other.dropMimeData(mime,Qt.DropAction.MoveAction,0,0,QModelIndex())
    assert not model.moveRows(QModelIndex(),0,1,QModelIndex(),1)
    assert not model.dropMimeData(mime,Qt.DropAction.CopyAction,0,0,QModelIndex())


def test_balanced_tables_are_branch_separated_and_reload_does_not_emit_saves(qtbot):
    widget=ResearchPriorityEditor();qtbot.addWidget(widget);changes=[]
    widget.orderChanged.connect(lambda *args:changes.append(args))
    widget.set_options(ResearchOptions.from_settings({'priority_mode':'balanced'}))
    assert widget.tables['balanced_economy'].model.rowCount()==28
    assert widget.tables['balanced_military'].model.rowCount()==43
    assert not changes
    table=widget.tables['balanced_military'];table.view.selectRow(4);table.up.click()
    mode,order=changes[0]
    assert mode=='balanced' and len(order)==71 and set(order)==set(RESEARCH_TYPES)
    assert [k for k in order if k>=200][:5]==[201,202,203,205,204]
