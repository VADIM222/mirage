"""Observe fresh dispatch receipts, accounting separately for existing gem armies."""
import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import time

from mirage.emulators import CommandError, Discovery
from mirage.gather import FIELDS, own_troops, unit_ledger
from mirage.memory import MemoryError, Reader
from mirage.storage import Store


def city_units(state):
    rows=state.values.get('troops')
    if not isinstance(rows,dict) or not rows:raise RuntimeError('City units unavailable')
    result={}
    for row in rows.values():
        if (not isinstance(row,dict) or type(row.get('unitId')) is not int
                or type(row.get('unitCount')) is not int or row['unitCount']<0
                or type(row.get('hurt')) is not int or type(row.get('badHurt')) is not int
                or str(row['unitId']) in result):raise RuntimeError('Incomplete city unit ledger')
        result[str(row['unitId'])]=row
    return result


def resource_type(row):
    if row.get('state')==6:
        return (row.get('carrier') or {}).get('resType')
    return (row.get('target') or {}).get('resType')


class ReturnObservation:
    def __init__(self,before,expected,known_gems=None):
        self.before=deepcopy(before);self.expected=deepcopy(expected);self.initial=own_troops(self.before)
        if not expected or not set(expected)<=set(self.initial):
            raise RuntimeError('Every research army must still be present at baseline')
        self.baseline=city_units(self.before)
        self.armies={army:unit_ledger(row['troop']['units']) for army,row in self.initial.items()}
        if not all(self.armies.values()):raise RuntimeError('Incomplete healthy army ledger')
        self.minimum=Counter()
        for army,receipt in expected.items():
            row=self.initial[army]
            if (resource_type(row)!=receipt['resource'] or self.armies[army]!=receipt['units']
                    or row.get('collected')!=0):
                raise RuntimeError('Research baseline must precede collection and match its receipt')
            self.minimum[str(receipt['resource'])]+=receipt['minimum']
        self.unrelated=set(self.initial)-set(expected)
        self.stationary={}
        for army in self.unrelated:
            row=self.initial[army];goal=row.get('target') or {}
            if (row.get('state')==4 and row.get('charType')==1 and not goal
                    and type(row.get('collected')) is int and row['collected']>=0
                    and isinstance(row.get('pos'),dict) and set(row['pos'])=={'x','y'}):
                self.stationary[army]=deepcopy(row)
                continue
            identified_return=(row.get('state')==2 and goal.get('charType')==3
                and goal.get('charId')==before.values.get('gather_city_id')
                and (known_gems or {}).get(army)==self.armies[army] and row.get('collected',0)>0)
            if resource_type(row)!=5 and not identified_return:
                raise RuntimeError('Only identified gem marches may coexist with research')
        self.states={army:set() for army in self.initial}
        self.collected={army:0 for army in expected}
        self.last_time=before.values['server_time']
        self.last_resources={str(i):before.values['resources'][str(i)] for i in range(1,7)}
        self.jumps=[];self.missing_at={};self.credits={}
        if len({r['resource'] for r in expected.values()})!=len(expected):
            raise RuntimeError('Use separate sessions for overlapping same-resource returns')

    def sample(self,state):
        if (state.instance_id,state.pid,state.player_id)!=(self.before.instance_id,self.before.pid,self.before.player_id):
            raise RuntimeError('Game identity changed during return observation')
        if state.values['server_time']<self.last_time:raise RuntimeError('Server clock moved backwards')
        self.last_time=state.values['server_time']
        rows=own_troops(state)
        if not set(rows)<=set(self.initial):raise RuntimeError('Unexpected new army appeared')
        if set(rows)&set(self.missing_at):raise RuntimeError('A disappeared research army reappeared')
        for army,row in rows.items():
            self.states[army].add(row['state'])
            if unit_ledger(row['troop']['units'])!=self.armies[army]:raise RuntimeError('Army unit ledger changed')
            if army in self.expected:
                self.collected[army]=max(self.collected[army],row.get('collected',0))
        for army,initial in self.stationary.items():
            current=rows.get(army)
            if current is None or any(current.get(key)!=initial.get(key) for key in
                    ('state','charId','charType','pos','target','collected','troop')):
                raise RuntimeError('Stationary user army changed; return attribution stopped')
        returned=Counter()
        for army in set(self.initial)-set(rows):returned.update(self.armies[army])
        target_units={unit:{**row,'unitCount':row['unitCount']+returned.get(unit,0)}
                      for unit,row in self.baseline.items()}
        current=city_units(state)
        delta={str(i):state.values['resources'][str(i)]-self.before.values['resources'][str(i)] for i in range(1,7)}
        step={str(i):state.values['resources'][str(i)]-self.last_resources[str(i)] for i in range(1,7)}
        if any(amount<0 for amount in step.values()):raise RuntimeError('Resources spent during observation')
        for resource,amount in step.items():
            if amount:self.jumps.append({'time':self.last_time,'resource':resource,'amount':amount})
        self.last_resources={str(i):state.values['resources'][str(i)] for i in range(1,7)}
        # Only a credit adjacent to removal of the specific fully gathered army
        # qualifies. Earlier city/alliance income and existing gem marches are
        # recorded as background; total balance growth cannot prove a return.
        for army,receipt in self.expected.items():
            if army in rows:continue
            self.missing_at.setdefault(army,self.last_time)
            eligible=[jump for jump in self.jumps if jump['resource']==str(receipt['resource'])
                and abs(jump['time']-self.missing_at[army])<=20000 and jump['amount']>=receipt['minimum']]
            if len(eligible)==1:self.credits[army]=eligible[0]
            elif len(eligible)>1:raise RuntimeError('Ambiguous income at research return')
        completed=(not set(self.expected)&set(rows) and current==target_units
            and all(6 in self.states[army] and self.collected[army]>=receipt['minimum']
                    for army,receipt in self.expected.items())
            and set(self.credits)==set(self.expected))
        verified=[army for army,receipt in self.expected.items()
            if army not in rows and current==target_units and 6 in self.states[army]
            and self.collected[army]>=receipt['minimum'] and army in self.credits]
        research_income=Counter()
        for jump in self.credits.values():research_income[jump['resource']]+=jump['amount']
        return {'server_time':state.values['server_time'],'armies':rows,'units':current,
                'resource_delta':delta,'exact_healthy_units':current==target_units,
                'return_credits':dict(self.credits),'research_income':dict(research_income),
                'verified_armies':sorted(verified),'stationary_user_armies':sorted(self.stationary),
                'background_income':{k:amount-research_income.get(k,0) for k,amount in delta.items()},
                'research_returned':sorted(set(self.expected)-set(rows)),
                'unrelated_returned':sorted(self.unrelated-set(rows)),'complete':completed}


def dispatch_receipts(directories):
    expected={};identity=None
    for directory in directories:
        result=json.loads((directory/'result.json').read_text())
        current=(result['pid'],result['player_id'])
        if identity is not None and current!=identity:raise RuntimeError('Dispatch identities differ')
        identity=current
        army_id,=result['new_army_ids'];row=result['armies'][army_id]
        if army_id in expected:raise RuntimeError('Duplicate dispatch receipt')
        resource=result['resource']
        trace=json.loads((directory/'trace.json').read_text())
        form=next(state for state in reversed(trace)
            if state.get('gather_view_SendTroopsMain') is True and state.get('gather_form_CollectResType')==resource)
        rss=form['gather_target']['rss']
        if resource not in (1,2,3,4) or rss['resType']!=resource:raise RuntimeError('Wrong dispatch resource')
        expected[army_id]={'resource':resource,'minimum':rss['remain'],
            'units':unit_ledger(row['troop']['units']),'source':str(directory)}
    return expected,identity


def known_gem_ledger(directories,player_id):
    result={}
    for directory in directories:
        before=json.loads((directory/'before.json').read_text())
        for army,row in before.get('gather_troops',{}).items():
            if resource_type(row)==5 and row.get('troop',{}).get('playerId')==player_id:
                units=unit_ledger(row['troop'].get('units'))
                if units:result[army]=units
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    parser.add_argument('--dispatch',type=Path,action='append',required=True)
    parser.add_argument('--seconds',type=int,default=7200)
    parser.add_argument('--wait-background-return',type=int,default=0)
    args=parser.parse_args()
    root=Path(r'C:\Users\Dirvi\AppData\Local\Temp\opencode');key='ld:a00ebeaccc:1'
    def guard():
        paths=[Path(os.environ['LOCALAPPDATA'])/'Mirage'/'mirage.sqlite3',
            *root.glob('mirage-packaged-*/mirage.sqlite3'),*root.glob('mirage-controller-*/mirage.sqlite3')]
        if any(not p.manual_pause and(p.manual_run or p.schedule_enabled) for p in (Store(path).profile(key) for path in paths)):
            raise RuntimeError('Automation resumed during exact return observation')
    guard();args.directory.mkdir(exist_ok=False)
    expected,identity=dispatch_receipts(args.dispatch)
    reader=Reader(next(i for i in Discovery().discover() if i.id==key))
    samples=(args.directory/'samples.jsonl').open('w',encoding='utf8')
    def observe():
        for attempt in range(4):
            guard()
            try:
                if reader.script is None:reader.connect()
                return reader.snapshot(FIELDS)
            except (MemoryError,CommandError):
                reader.close()
                if attempt==3:raise
                threading.Event().wait((attempt+1)*5)
    try:
        before=observe()
        if (before.pid,before.player_id)!=identity:raise RuntimeError('Dispatch game identity changed')
        # An unidentified cargo must finish before the research baseline, so
        # none of its income can be mistaken for the new resource deliveries.
        pending=set(own_troops(before))-set(expected)
        if pending and args.wait_background_return:
            deadline=time.monotonic()+args.wait_background_return
            with (args.directory/'background-wait.jsonl').open('w',encoding='utf8') as waiting:
                while pending:
                    rows=own_troops(before)
                    if not set(expected)<=set(rows):raise RuntimeError('Research returned before fresh baseline')
                    for army in pending:
                        row=rows[army];goal=row.get('target') or {}
                        if (row.get('state')!=2 or goal.get('charType')!=3
                                or goal.get('charId')!=before.values.get('gather_city_id')):
                            raise RuntimeError('Background army is not returning to own city')
                    waiting.write(json.dumps({'time':before.values['server_time'],'pending':sorted(pending)})+'\n');waiting.flush()
                    if time.monotonic()>deadline:raise RuntimeError('Background return deadline exceeded')
                    threading.Event().wait(5);before=observe()
                    if (before.pid,before.player_id)!=identity:raise RuntimeError('Dispatch game identity changed')
                    current=set(own_troops(before))-set(expected)
                    if not current<=pending:raise RuntimeError('Unexpected new background army')
                    pending=current
        observation=ReturnObservation(before,expected,known_gem_ledger(args.dispatch,before.player_id))
        (args.directory/'before.json').write_text(json.dumps(before.values,indent=2),encoding='utf8')
        (args.directory/'receipts.json').write_text(json.dumps(expected,indent=2),encoding='utf8')
        deadline=time.monotonic()+args.seconds
        while True:
            guard();state=observe()
            sample=observation.sample(state)
            samples.write(json.dumps(sample,ensure_ascii=True)+'\n');samples.flush()
            # Preserve individual completed cycles even if another long-running
            # resource is later interrupted by the user's stop command.
            progress={'pid':state.pid,'player_id':state.player_id,'server_time':sample['server_time'],
                'overall_complete':sample['complete'],'verified_armies':sample['verified_armies'],
                'return_credits':sample['return_credits'],'collected':observation.collected,
                'resource_delta':sample['resource_delta'],'exact_healthy_units':sample['exact_healthy_units']}
            temporary=args.directory/'progress.tmp'
            temporary.write_text(json.dumps(progress,indent=2),encoding='utf8')
            temporary.replace(args.directory/'progress.json')
            for army in sample['verified_armies']:
                evidence=args.directory/f'army-{army}-return.json'
                if not evidence.exists():
                    evidence.write_text(json.dumps({'pid':state.pid,'player_id':state.player_id,
                        'army_id':army,'receipt':expected[army],'credit':sample['return_credits'][army],
                        'full_collected':observation.collected[army],'exact_healthy_units':True,
                        'verified_at':sample['server_time'],'overall_complete':sample['complete']},indent=2),encoding='utf8')
            if sample['complete']:
                result={'pid':state.pid,'player_id':state.player_id,'resource_delta':sample['resource_delta'],
                    'minimum_expected':dict(observation.minimum),'all_research_armies_returned':True,
                    'research_returned':sample['research_returned'],'unrelated_returned':sample['unrelated_returned'],
                    'research_income':sample['research_income'],'background_income':sample['background_income'],
                    'return_credits':sample['return_credits'],
                    'remaining_marches':len(sample['armies']),'exact_healthy_units':True,
                    'research_units':{army:observation.armies[army] for army in expected},
                    'collected':observation.collected,
                    'states':{key:sorted(value) for key,value in observation.states.items()}}
                (args.directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
                print(json.dumps(result));break
            if time.monotonic()>deadline:raise RuntimeError('Natural resource return deadline exceeded')
            threading.Event().wait(5)
    except Exception as error:
        (args.directory/'failure.json').write_text(json.dumps({'error':str(error)},indent=2),encoding='utf8')
        raise
    finally:
        samples.close()
        try:
            if reader.script is not None:(args.directory/'screen.png').write_bytes(reader.adb.screenshot())
        finally:reader.close()


if __name__=='__main__':main()
