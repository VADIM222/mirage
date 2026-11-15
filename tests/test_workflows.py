import threading

import pytest

from mirage.model import Snapshot
from mirage.workflows import AnyOf, CITY_HUD, Cancelled, Condition, Engine, Tap, Workflow, WorkflowError


def snapshot(value=1, *, instance="one", pid=10):
    return Snapshot(instance, pid, 20, 100, "1.1.12.20", {"help_count": value})


class FakeInput:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))


def flow(verified=True):
    return Workflow("alliance_help", "1.1.12.20", 960, 540,
                    (Tap(900, 400, Condition(("help_count",), "gt", 0),
                         Condition(("help_count",), "eq", 0), timeout=1),), verified)


def test_confirmed_transition_and_identity():
    values = iter([snapshot(), snapshot(), snapshot(0)])
    inputs = FakeInput()
    result = Engine(inputs, lambda: next(values), clock=lambda: 100).execute(
        flow(), threading.Event(), instance_id="one", pid=10, player_id=20)
    assert result.values["help_count"] == 0
    assert inputs.taps == [(900, 400)]


@pytest.mark.parametrize("observation", [snapshot(instance="other"), snapshot(pid=99)])
def test_changed_process_or_instance_blocks_input(observation):
    inputs = FakeInput()
    with pytest.raises(WorkflowError, match="изменился"):
        Engine(inputs, lambda: observation, clock=lambda: 100).execute(
            flow(), threading.Event(), instance_id="one", pid=10, player_id=20)
    assert not inputs.taps


def test_progress_callback_only_receives_validated_fresh_observations():
    progress = []
    values = iter([snapshot(),snapshot(),snapshot(0)])
    Engine(FakeInput(),lambda:next(values),clock=lambda:100,on_observed=progress.append).execute(
        flow(),threading.Event(),instance_id="one",pid=10,player_id=20)
    assert [state.values["help_count"] for state in progress] == [1,1,0]
    progress.clear()
    with pytest.raises(WorkflowError):
        Engine(FakeInput(),lambda:snapshot(pid=99),clock=lambda:100,on_observed=progress.append).execute(
            flow(),threading.Event(),instance_id="one",pid=10,player_id=20)
    assert not progress


def test_cancellation_prevents_input():
    cancelled = threading.Event()
    cancelled.set()
    inputs = FakeInput()
    with pytest.raises(Cancelled):
        Engine(inputs, snapshot, clock=lambda: 100).execute(
            flow(), cancelled, instance_id="one", pid=10, player_id=20)
    assert not inputs.taps


@pytest.mark.parametrize('mode',['clears','stuck','cancel','identity'])
def test_completion_animation_is_observed_until_removed_without_input(mode):
    from dataclasses import replace
    from mirage.workflows import NotReady
    inputs=FakeInput();cancelled=threading.Event();now=[100.];calls=[0]
    def observe():
        calls[0]+=1;now[0]+=.25
        state=replace(snapshot(),captured_at=now[0])
        if calls[0]<3 or mode=='stuck':state.values['views']={'PopupMissionComplete':True}
        if mode=='cancel':cancelled.set()
        if mode=='identity' and calls[0]==2:state=replace(state,pid=99)
        if calls[0]>=5:state.values['help_count']=0
        return state
    engine=Engine(inputs,observe,clock=lambda:now[0])
    if mode=='clears':
        engine.execute(flow(),cancelled,instance_id='one',pid=10,player_id=20)
        assert inputs.taps==[(900,400)]
    else:
        with pytest.raises({'stuck':NotReady,'cancel':Cancelled,'identity':WorkflowError}[mode]):
            engine.execute(flow(),cancelled,instance_id='one',pid=10,player_id=20)
        assert not inputs.taps


def test_unverified_scenario_is_not_success():
    with pytest.raises(WorkflowError, match="не подтверждён"):
        Engine(FakeInput(), snapshot).execute(flow(False), threading.Event(), instance_id="one", pid=10, player_id=20)


def test_unconfirmed_result_times_out_instead_of_claiming_success():
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return 100 + calls * 0.4

    with pytest.raises(WorkflowError, match="не подтверждён"):
        Engine(FakeInput(), snapshot, clock=clock).execute(
            flow(), threading.Event(), instance_id="one", pid=10, player_id=20)


def test_schedule_ends_during_observation_prevents_next_input():
    inputs = FakeInput()
    permitted = True
    count = 0
    def observe():
        nonlocal permitted, count
        count += 1
        if count == 2:
            permitted = False
        return snapshot()
    with pytest.raises(Cancelled):
        Engine(inputs, observe, clock=lambda: 100, allowed=lambda: permitted).execute(
            flow(), threading.Event(), instance_id="one", pid=10, player_id=20)
    assert not inputs.taps


def test_optional_reward_does_not_click_when_unavailable():
    inputs = FakeInput()
    workflow = Workflow("reward", "1.1.12.20", 960, 540,
                        (Tap(10, 10, Condition(("help_count",), "eq", 0),
                             Condition(("help_count",), "eq", 2), when=Condition(("help_count",), "gt", 0)),), True)
    Engine(inputs, lambda: snapshot(0), clock=lambda: 100).execute(
        workflow, threading.Event(), instance_id="one", pid=10, player_id=20)
    assert not inputs.taps


def test_multi_screen_workflow_waits_for_open_and_close_with_held_input():
    def state(page):
        return Snapshot("one", 10, 20, 100, "1.1.12.20", {"page":page})
    city = Condition(("page",), "eq", "city")
    panel = Condition(("page",), "eq", "panel")
    observations = iter([state("city"), state("city"), state("city"), state("panel"), state("panel"), state("city")])
    taps = []
    class HeldInput:
        def tap(self, x, y, *, hold_ms=0):
            taps.append((x, y, hold_ms))
    workflow = Workflow("reward", "1.1.12.20", 960, 540,
                        (Tap(10, 10, city, panel, hold_ms=100), Tap(20, 20, panel, city, hold_ms=100)), True,
                        precondition=AnyOf((city, panel)))
    result = Engine(HeldInput(), lambda: next(observations), clock=lambda: 100).execute(
        workflow, threading.Event(), instance_id="one", pid=10, player_id=20)
    assert result.values["page"] == "city"
    assert taps == [(10, 10, 100), (20, 20, 100)]


def test_no_available_rewards_returns_without_opening_panel():
    inputs = FakeInput()
    from dataclasses import replace
    workflow = replace(flow(), when=AnyOf((Condition(("help_count",), "gt", 2), Condition(("help_count",), "eq", 0))))
    result = Engine(inputs, snapshot, clock=lambda: 100).execute(
        workflow, threading.Event(), instance_id="one", pid=10, player_id=20)
    assert result.values["help_count"] == 1
    assert not inputs.taps


def test_transient_incomplete_data_is_reread_before_the_next_action():
    from dataclasses import replace
    observations = iter([snapshot(1),snapshot(-1),snapshot(1),snapshot(0)])
    inputs = FakeInput()
    workflow = replace(flow(),data_condition=Condition(("help_count",),"gt",-1))
    Engine(inputs,lambda:next(observations),clock=lambda:100).execute(
        workflow,threading.Event(),instance_id="one",pid=10,player_id=20)
    assert inputs.taps == [(900,400)]


def test_unavailable_data_has_a_bounded_wait_and_never_authorizes_input():
    from dataclasses import replace
    from mirage.workflows import NotReady
    instant = [100]
    def observe():
        instant[0] += .4
        return snapshot(-1)
    inputs = FakeInput()
    workflow = replace(flow(),data_condition=Condition(("help_count",),"gt",-1),data_timeout=1)
    with pytest.raises(NotReady):
        Engine(inputs,observe,clock=lambda:instant[0]).execute(
            workflow,threading.Event(),instance_id="one",pid=10,player_id=20)
    assert not inputs.taps and instant[0] < 102


@pytest.mark.parametrize("change",["cancel","identity"])
def test_waiting_for_data_keeps_cancellation_and_identity_checks_active(change):
    from dataclasses import replace
    cancelled = threading.Event()
    inputs = FakeInput()
    count = 0
    def observe():
        nonlocal count
        count += 1
        if count == 2 and change == "cancel":cancelled.set()
        return snapshot(-1,pid=99 if count == 2 and change == "identity" else 10)
    workflow = replace(flow(),data_condition=Condition(("help_count",),"gt",-1))
    with pytest.raises(Cancelled if change == "cancel" else WorkflowError):
        Engine(inputs,observe,clock=lambda:100).execute(
            workflow,cancelled,instance_id="one",pid=10,player_id=20)
    assert not inputs.taps and count == 2


@pytest.mark.parametrize("overlay", ["QuestSystemMainPage", "RoutineRewardsCollect", "UnknownPage"])
def test_observed_scene_huds_are_allowed_but_reward_windows_block_city_actions(overlay):
    values = {"hud_visible":True, "hud_menu":False, "in_city":True, "city_enabled":True, "player":{"AllianceID":10},
              "queue_panel":{"known":True,"visible":False},
              "city_selection_known":True,"city_selection":None,"vip_visible":False,
              "views":dict.fromkeys(("MapHudPanel", "MapUIDragMoveHandler", "AlliMarkElementHUD", "CityReflowUIContainerHud",
                                    "MapElementHud3D", "CityUIContainerHud", "MapElementHud"), True)}
    state = Snapshot("one", 10, 20, 100, "1.1.12.20", values)
    assert CITY_HUD.matches(state)
    values["views"][overlay] = True
    assert not CITY_HUD.matches(state)


def test_settle_observes_animation_and_cancellation_before_the_next_input():
    from dataclasses import replace
    cancelled = threading.Event()
    inputs = FakeInput()
    count = 0
    instant = 100
    def clock():
        nonlocal instant
        instant += 0.02
        return instant
    def observe():
        nonlocal count
        count += 1
        if count == 5:
            cancelled.set()
        return snapshot(1 if count <= 2 else 0)
    first = replace(flow().steps[0], settle=0.5)
    second = Tap(20, 20, Condition(("help_count",), "eq", 0), Condition(("help_count",), "eq", 2))
    workflow = replace(flow(), steps=(first, second))
    with pytest.raises(Cancelled):
        Engine(inputs, observe, clock=clock).execute(workflow, cancelled, instance_id="one", pid=10, player_id=20)
    assert inputs.taps == [(900, 400)]
    assert count == 5


@pytest.mark.parametrize("delay", [-0.1, 9, float("nan")])
def test_invalid_settle_blocks_input(delay):
    from dataclasses import replace
    inputs = FakeInput()
    workflow = replace(flow(), steps=(replace(flow().steps[0], settle=delay),))
    with pytest.raises(WorkflowError, match="ожидания"):
        Engine(inputs, snapshot, clock=lambda:100).execute(workflow, threading.Event(), instance_id="one", pid=10, player_id=20)
    assert inputs.taps == []
