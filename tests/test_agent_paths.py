"""Exercise Lua's int32 versus double-key ABI without a live game process."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_owned_commander_projection_never_publishes_a_partial_or_other_account_catalog():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
let stack=[],player={PlayerID:7},heroes={3:{Id:3,Level:20,Star:3},37:{Id:37,Level:60,Star:6}},missing=false,fail=false;
const value=i=>stack[i<0?stack.length+i:i-1];
const context={readPath:()=>({...player}),rawPath:()=>{stack.push(heroes);return stack.length;},
 fieldValue:(L,i,k)=>value(i)[k]??null,scalar:(L,i)=>value(i),
 commanderConfig:(L,id)=>{if(fail)throw Error('native lookup failed');return {LC_N:'LC_HERO_NAME_'+id,Rare:4,Tag:'1,7,11'};},
 commanderText:(L,key)=>missing&&key.endsWith('_37')?null:'Name '+key,
 api:{gettop:()=>stack.length,settop:(L,n)=>stack.length=n,gettype:(L,i)=>value(i)&&typeof value(i)==='object'?5:0,
 pushnil:()=>stack.push(null),next:(L,i)=>{const table=value(i),previous=stack.pop(),keys=Object.keys(table).map(Number),n=previous===null?0:keys.indexOf(previous)+1;
  if(n>=keys.length)return 0;stack.push(keys[n],table[keys[n]]);return 1;}}};
vm.createContext(context);vm.runInContext(source.slice(source.indexOf('function playerWithCommanders('),source.indexOf('function commanderText(')),context);
stack=Array(10).fill(null);
let out=context.playerWithCommanders(null,3,{left:1800});assert.equal(out._commanders.player,7);
assert.equal(out._commanders.ready,true);assert.equal(Object.keys(out._commanders.heroes).length,2);assert.equal(stack.length,10);
missing=true;out=context.playerWithCommanders(null,3,{left:1800});assert.equal(out._commanders.ready,false);
assert.equal(Object.keys(out._commanders.heroes).length,0);assert.equal(stack.length,10);
missing=false;heroes[37].Star=0;assert.equal(context.playerWithCommanders(null,3,{})._commanders.ready,false);
heroes[37].Star=6;fail=true;assert.throws(()=>context.playerWithCommanders(null,3,{}));assert.equal(stack.length,10);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_commander_text_calls_only_whitelisted_native_string_lookup_and_restores_stack():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');let stack=[],calls=0,allowed=true;
const value=i=>stack[i<0?stack.length+i:i-1],context={Memory:{allocUtf8String:s=>s},scalar:(L,i)=>value(i),
 rawPath:(L,path)=>{assert.equal(path.join('.'),'eng.rawGetGameText');calls++;stack.push(key=>'Sun Tzu');return stack.length;},
 dataReader:()=>allowed,api:{gettop:()=>stack.length,settop:(L,n)=>stack.length=n,
 gettype:(L,i)=>typeof value(i)==='string'?4:0,pushlstring:(L,s,n)=>{assert.equal(s.length,n);stack.push(s);},
 pcall:(L,n,r)=>{assert.equal(n,1);assert.equal(r,1);const key=stack.pop(),fn=stack.pop();stack.push(fn(key));return 0;}}};
vm.createContext(context);vm.runInContext(source.slice(source.indexOf('function commanderText('),source.indexOf('function commanderConfig(')),context);
stack=Array(10).fill(null);assert.equal(context.commanderText(null,'LC_HERO_NAME_3'),'Sun Tzu');assert.equal(calls,1);assert.equal(stack.length,10);
assert.equal(context.commanderText(null,'UIHelper.SetText'),null);assert.equal(calls,1);assert.equal(stack.length,10);
allowed=false;assert.equal(context.commanderText(null,'LC_HERO_NAME_37'),null);assert.equal(stack.length,10);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_selected_troop_identity_projects_only_scalars_and_preserves_numeric_lua_keys():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
let stack=[],row={troopId:1338361,charId:14169210100,state:2,APR:0};
const global={UIObjectManager:{MapUISelectTroops:{ListData:{1:{troopInfo:row}}}},huge:{9000000001:{troopInfo:row}}};
const value=i=>i===-10002?global:stack[i-1];
const context={api:{gettop:()=>stack.length,settop:(L,n)=>stack.length=n,
 gettype:(L,i)=>value(i)&&typeof value(i)==='object'?5:0,
 pushnumber:(L,k)=>stack.push(k),rawget:(L,i)=>{const table=value(i),key=stack.pop();stack.push(table?.[key]??null);}},
 pushField:(L,i,k)=>{assert.equal(typeof k,'string');stack.push(value(i)?.[k]??null);return stack.length;},
 fieldValue:(L,i,k,depth)=>{assert.equal(depth,0);assert.ok(['troopId','charId','state','APR'].includes(k));return value(i)?.[k]??null;}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function rawPath('),source.indexOf('function itemCounts('))+
 source.slice(source.indexOf('function barbarianTroopIdentity('),source.indexOf('function barbarianDispatchUi(')),context);
stack=Array(10).fill(null);
let result=context.barbarianTroopIdentity(null,['UIObjectManager','MapUISelectTroops','ListData',1,'troopInfo']);
assert.equal(result.charId,14169210100);assert.equal(Object.keys(result).length,4);assert.equal(stack.length,10);
assert.equal(context.barbarianTroopIdentity(null,['huge',9000000001,'troopInfo']).troopId,1338361);
assert.equal(stack.length,10);row.charId=null;
assert.equal(context.barbarianTroopIdentity(null,['huge',9000000001,'troopInfo']),null);assert.equal(stack.length,10);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_pve_talent_reader_uses_native_config_nodes_and_restores_stack():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('function barbarianPveTalent('),source.indexOf('function barbarianReports('));
let stack=[],fail=false;
const value=i=>stack[i-1],configs={804:{ID:804,Node:64,Condition:{1:802}},1007:{ID:1007,Node:84}},
 levels={64:{1:{ID:64,Lv:1,Param1:3}},84:{1:{ID:84,Lv:1,Param1:3}}};
const context={rawPath:(L,path)=>{stack.push(path.at(-1));return stack.length;},
 capturedData:(L,i,pos,count)=>{assert.equal(pos,1);assert.equal(count,1);
  stack.push(value(i)==='GetTalentConfig'?configs:levels);return {index:stack.length};},
 configScalarField:(L,i,k)=>{if(fail)throw Error('native read failed');return value(i)?.[k]??null;},
 nativeScalarRow:(L,i)=>value(i),api:{gettop:()=>stack.length,settop:(L,n)=>stack.length=n,
  gettype:(L,i)=>typeof value(i)==='object'&&value(i)!==null?5:0,
  rawgeti:(L,i,key)=>stack.push(value(i)?.[key]??null)}};
vm.createContext(context);vm.runInContext(fn,context);stack=Array(10).fill(null);
const hero={CurrentPage:0,TalentPage:{0:{TalentMap:{1101:1,1102:3}}}};
let result=context.barbarianPveTalent(null,hero);assert.equal(result.cost,0);assert.equal(result.nodes['804'].node,64);
assert.equal(stack.length,10);hero.TalentPage[0].TalentMap[804]=1;
assert.equal(context.barbarianPveTalent(null,hero).cost,3);assert.equal(stack.length,10);
hero.TalentPage[0].TalentMap.$truncated=true;assert.equal(context.barbarianPveTalent(null,hero),null);
assert.equal(stack.length,10);delete hero.TalentPage[0].TalentMap.$truncated;
fail=true;assert.throws(()=>context.barbarianPveTalent(null,hero));assert.equal(stack.length,10);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_barbarian_config_is_matched_by_native_id_not_the_row_index_and_restores_stack():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('const barbarianConfigCache='),source.indexOf('function discoveredPlaceTarget('));
let stack=[],rows=[],calls=0,bad=false,fail=false;
const value=i=>stack[i<0?stack.length+i:i-1];
const iterator=(state,key)=>{calls++;if(fail)throw Error('iterator failed');
 const index=key===null?0:key+1;return index>=rows.length?[null,null]:[index,rows[index]];};
const configs={type:7,address:'config-a'},meta={__pairs:()=>[iterator,null,null]};
const context={rawPath:(L,path)=>{assert.equal(path.join('.'),'GameDatas.barbarian_Barbarian');stack.push(configs);return stack.length;},
 pushField:(L,index,key)=>{stack.push(value(index)[key]);return stack.length;},dataReader:(L,index)=>!bad&&typeof value(index)==='function',
 configScalarField:(L,index,key)=>value(index)?.[key]??null,
 nativeScalarRow:(L,index)=>value(index),api:{gettop:()=>stack.length,settop:(L,n)=>stack.length=n,
 gettype:(L,i)=>value(i)?.type??(typeof value(i)==='function'?6:value(i)===null?0:5),
 touserdata:(L,i)=>({toString:()=>value(i).address}),getmetatable:()=>{stack.push(meta);return 1;},
 pushvalue:(L,i)=>stack.push(value(i)),replace:(L,i)=>{const v=stack.pop();stack[i-1]=v;},
 pcall:(L,n,r)=>{const args=stack.splice(stack.length-n,n),fn=stack.pop();const result=fn(...args);stack.push(...result);return 0;}}};
vm.createContext(context);vm.runInContext(fn,context);
rows=[{ID:1688,Type:92},{ID:641,Type:1},{ID:901,Type:1}];stack=Array(10).fill(null);
assert.equal(context.barbarianConfig(null,641).ID,641);assert.equal(calls,2);assert.equal(stack.length,10);
assert.equal(context.barbarianConfig(null,641).ID,641);assert.equal(calls,2);assert.equal(stack.length,10);
assert.equal(context.barbarianConfig(null,901).ID,901);assert.equal(stack.length,10);
assert.equal(context.barbarianConfig(null,12345),null);assert.equal(stack.length,10);
bad=true;assert.equal(context.barbarianConfig(null,12345),null);assert.equal(stack.length,10);
bad=false;fail=true;assert.throws(()=>context.barbarianConfig(null,12345));assert.equal(stack.length,10);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_barbarian_hold_uses_the_measured_two_capture_closure_and_restores_stack():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('function readPath('),source.indexOf('function pushField('));
let top=10,hold=0,missing=false,fail=false;
const context={rawPath:(L,path)=>{assert.equal(path.join('.'),'WorldMapHandler.SetStayAfterBattle');return ++top;},
 capturedData:(L,index,position,count)=>{assert.equal(position,1);assert.equal(count,2);
  if(fail)throw Error('read failed');return missing?null:{index:++top};},fieldValue:(L,index,key)=>{
  assert.equal(key,'stayAfterBattle');return hold;},
 api:{gettop:()=>top,settop:(L,n)=>top=n,gettype:()=>5}};
vm.createContext(context);vm.runInContext(fn,context);
for(const value of [0,1]){hold=value;assert.equal(context.readPath(null,['@barbarian_hold'],0,{}),value);assert.equal(top,10);}
missing=true;assert.equal(context.readPath(null,['@barbarian_hold'],0,{}),null);assert.equal(top,10);
fail=true;assert.throws(()=>context.readPath(null,['@barbarian_hold'],0,{}));assert.equal(top,10);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_barbarian_target_uses_active_form_split_identity_and_restores_stack():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('function barbarianTarget('),source.indexOf('const barbarianConfigCache='));
let stack=[],root={},active=new Set(),fail=false;
const lookup=path=>path.reduce((v,key)=>v?.[key],root)??null;
const context={rawPath:(L,path)=>{assert(path.every(k=>typeof k==='string'));const v=lookup(path);
 if(v===null)return null;stack.push(v);return stack.length;},readPath:(L,path)=>lookup(path),
  barbarianConfig:(L,id)=>({ID:id}),viewActive:(L,index,name)=>active.has(name),fieldValue:(L,index,key)=>{
  if(fail)throw Error('native failure');return stack[index-1]?.[key]??null;},
 api:{gettop:()=>stack.length,settop:(L,n)=>stack.length=n,
  gettype:(L,i)=>stack[i-1]!==null&&typeof stack[i-1]==='object'?5:0,
  pushnumber:(L,n)=>{assert(Number.isSafeInteger(n));stack.push(n);},
  rawget:(L,i)=>{const key=stack.pop();assert.equal(key,15975210100);stack.push(stack[i-1]?.[key]??null);}}};
vm.createContext(context);vm.runInContext(fn,context);
function run(names,options={}){
 stack=Array(8).fill(null);active=new Set(names);fail=!!options.fail;
 root={UIObjectManager:{SendTroopsMain:{DstCharId:options.formID??159752101},
  MapUISelectTroops:{CurTargetId:15975210100},MapUIBarbarianPopUp:{TargetId:15975210100}},
  MapData:{chars:{15975210100:{id:15975210100,charType:1,playerId:-2,npcInfo:{npcType:641,npcLevel:1},
   troop:{units:{'1':{unitId:1,unitCount:750,maxCount:750}}},square:{hp:750,hpMax:750}}}},
  WorldMgr:{allObjs:{15975210100:{playerId:-2}}}};
 if(options.noTarget)root.MapData.chars={};
 try{return context.barbarianTarget(null);}finally{assert.equal(stack.length,8);}
}
for(const name of ['SendTroopsMain','MapUISelectTroops','MapUIBarbarianPopUp']){
 const target=run([name]);assert.equal(target.id,15975210100);assert.equal(target.owner,-2);
 assert.equal(target.npcInfo.npcType,641);assert.equal(target.hp,750);
}
assert.equal(run([]),null);
assert.equal(run(['SendTroopsMain','MapUIBarbarianPopUp'],{formID:0}),null);
assert.equal(run(['SendTroopsMain'],{formID:Number.MAX_SAFE_INTEGER}),null);
assert.equal(run(['MapUIBarbarianPopUp'],{noTarget:true}),null);
assert.throws(()=>run(['MapUIBarbarianPopUp'],{fail:true}));
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_large_map_ids_use_double_keys_without_overflowing_lua_rawgeti():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('function readPath('),source.indexOf('function pushField('));
const calls=[];
const context={Memory:{allocUtf8String:key=>key},scalar:()=>null,readTable:()=>({read:true}),
 api:{gettop:()=>10,settop:(L,value)=>calls.push(['restore',value]),gettype:()=>5,
 pushlstring:()=>{},rawget:()=>calls.push(['rawget']),pushnumber:(L,value)=>calls.push(['number',value]),
 rawgeti:(L,index,value)=>{assert(value>=-2147483648&&value<=2147483647);calls.push(['int32',value]);}}};
vm.createContext(context);vm.runInContext(fn,context);
for(const id of [119670600,2147483647,-2147483648,3435360600,10213890100,-2147483649]){
 calls.length=0;context.readPath(null,['MapData','chars',id],3,{left:256});
 const kind=id>=-2147483648&&id<=2147483647?'int32':'number';
 assert(calls.some(call=>call[0]===kind&&call[1]===id));
 assert.deepEqual(calls.at(-1),['restore',10]);
}
calls.length=0;
assert.equal(context.readPath(null,['MapData','chars',Number.MAX_SAFE_INTEGER+1],3,{left:256}),null);
assert(!calls.some(call=>call[0]==='int32'||call[0]==='number'));
assert.deepEqual(calls.at(-1),['restore',10]);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_city_production_alias_is_deduplicated_but_conflicting_objects_fail_closed():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('function cityResources('),source.indexOf('function dataReader('));
let rows=[],pos=-1,top=10,fail=false;
const context={rawPath:()=>12,fieldValue:(L,index,key)=>{if(fail)throw Error('read failed');return rows[pos][key];},
 api:{gettop:()=>top,settop:(L,n)=>{top=n;},gettype:()=>5,pushnil:()=>top++,
 topointer:()=>({toString:()=>rows[pos].address}),next:()=>{pos++;if(pos>=rows.length){top--;return 0;}top+=2;return 1;}}};
vm.createContext(context);vm.runInContext(fn,context);
function read(input){rows=input;pos=-1;top=10;return context.cityResources(null);}
const farm={id:'55',type:2,rssType:1,rssValue:4000,address:'same'};
assert.equal(Object.keys(read([farm,farm])).length,1);assert.equal(top,10);
assert.equal(read([farm,{...farm,address:'different'}]),null);assert.equal(top,10);
fail=true;assert.throws(()=>read([farm]));assert.equal(top,10);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_inventory_ledger_rejects_partial_invalid_and_duplicate_rows_and_restores_stack():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('function itemCounts('),source.indexOf('function queuePanel('));
let rows=[],position=-1,top=10,ready=true,list=true,fail=false;
const context={readPath:()=>ready,rawPath:()=>list?12:null,
 fieldValue:(L,index,key)=>{if(fail)throw Error('read failed');return rows[position][key];},
 api:{gettop:()=>top,settop:(L,n)=>{top=n;},pushnil:()=>{top++;},
 gettype:(L,index)=>index===12||typeof rows[position]==='object'?5:0,
 next:()=>{position++;if(position>=rows.length){top--;return 0;}top+=2;return 1;}}};
vm.createContext(context);vm.runInContext(fn,context);
function read(input){rows=input;position=-1;top=10;return JSON.parse(JSON.stringify(context.itemCounts(null)));}
assert.deepEqual(read([{itemId:7001,itemCount:145},{itemId:141,itemCount:5},{itemId:9,itemCount:0}]),
 {ready:true,items:{'7001':145,'141':5}});assert.equal(top,10);
for(const input of [
 [{itemId:1,itemCount:-1}],[{itemId:1,itemCount:true}],[{itemId:1.5,itemCount:1}],
 [{itemId:1,itemCount:0},{itemId:1,itemCount:2}],[{itemId:1,itemCount:2},{itemId:1,itemCount:3}],
 [false],Array.from({length:2049},(_,i)=>({itemId:i+1,itemCount:1}))]){
 assert.deepEqual(read(input),{ready:false,items:{}});assert.equal(top,10);
}
ready=false;assert.deepEqual(read([]),{ready:false,items:{}});assert.equal(top,10);ready=true;
list=false;assert.deepEqual(read([]),{ready:false,items:{}});assert.equal(top,10);list=true;
fail=true;assert.throws(()=>read([{itemId:1,itemCount:1}]));assert.equal(top,10);
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)


def test_place_target_uses_the_active_identity_or_exact_camera_and_restores_lua_stack():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is needed for the isolated JS adapter check')
    source=Path(__file__).parents[1]/'src'/'mirage'/'agents'/'state_reader.js'
    check=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('function discoveredPlaceTarget('),source.indexOf('function tutorialStepConfig('));
let stack=[],root={},active=false,fail=false,scanned=0;
const value=index=>stack[index-1];
const lookup=path=>path.reduce((v,key)=>v?.[key],root)??null;
const context={rawPath:(L,path)=>{const v=lookup(path);if(v===null)return null;stack.push(v);return stack.length;},
 readPath:(L,path)=>lookup(path),viewActive:()=>active,
 fieldValue:(L,index,key)=>{if(fail)throw Error('native read failed');return value(index)?.[key]??null;},
 pushField:(L,index,key)=>{stack.push(value(index)?.[key]??null);return stack.length;},
 readTable:(L,index)=>value(index),
 api:{gettop:()=>stack.length,settop:(L,n)=>{stack.length=n;},
 gettype:(L,index)=>value(index)!==null&&typeof value(index)==='object'?5:0,
 pushnil:()=>stack.push(null),next:(L,index)=>{
  scanned++;const table=value(index),key=stack.pop(),keys=Object.keys(table);
  const next=key===null?0:keys.indexOf(String(key))+1;
  if(next>=keys.length)return 0;stack.push(keys[next],table[keys[next]]);return 1;
 }}};
vm.createContext(context);vm.runInContext(fn,context);
function run(chars,options={}){
 stack=Array(10).fill(null);active=!!options.active;fail=!!options.fail;scanned=0;
 root={UIObjectManager:{MapUnkownCityPopUp:{targetId:options.id??5401100},
  CityUIScoutsManagement:{ListDatas:{'1':{type:11,caviId:30215,pos:{x:2619.3,y:6296.6}},
    '2':{type:11,caviId:40174,pos:{x:2350.6,y:6405.1}}}},
  MapHudPanel:{CurViewX:9550.6,CurViewY:6405.1}},FogMgr:{m_kingdomOffsetX:7200,m_kingdomOffsetY:0},MapData:{chars}};
 if(options.offCenter)root.UIObjectManager.MapHudPanel.CurViewX+=1;
 try{return context.discoveredPlaceTarget(null);}finally{assert.equal(stack.length,10);}
}
const target={id:5401100,charType:11,village:{caviId:40174},pos:{x:9550.6,y:6405.1}};
const other={id:5791100,charType:11,village:{caviId:30215}};
assert.equal(run({'5791100':other,'5401100':target}),target);
assert.equal(run({'5401100':target},{offCenter:true}),null);
assert.equal(run({'5401100':target},{active:true,offCenter:true}),target);
assert.equal(scanned,0);
assert.equal(run({'5401100':target},{active:true,id:-9999900}),null);
assert.equal(run({'5401100':{...target,charType:10}}),null);
assert.equal(run(Object.fromEntries(Array.from({length:2049},(_,i)=>[i+1,{charType:1}]))),null);
assert(scanned<=2052);
assert.throws(()=>run({'5401100':target},{fail:true}));
"""
    subprocess.run([node,'-e',check,str(source)],check=True,capture_output=True,text=True,timeout=10)
